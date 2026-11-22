"""Notifica di un nuovo episodio: commento GitHub o email SMTP opzionale."""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from .config import carica_impostazioni
from .feed import costruisci_url_audio, normalizza_sito_url
from .tempo import data_iso_roma
from .testi import durata_umana


def messaggio_episodio(
    titolo: str,
    data: str,
    durata: str | float | int,
    descrizione: str,
    player_url: str,
    feed_url: str,
    mp3_url: str,
) -> str:
    """Markdown breve e leggibile per commento issue o email."""
    durata_testo = (
        durata
        if isinstance(durata, str)
        else durata_umana(float(durata))
    )
    descrizione = " ".join(str(descrizione or "").split())
    if len(descrizione) > 300:
        taglio = descrizione[:297].rsplit(" ", 1)[0].rstrip(" ,;:-")
        descrizione = taglio + "..."
    righe = [
        "## Nuovo episodio",
        "",
        f"**{titolo}**",
        "",
        f"- Data: {data}",
        f"- Durata: {durata_testo}",
    ]
    if descrizione:
        righe += ["", descrizione]
    righe += [
        "",
        f"- [Apri il player]({player_url})",
        f"- [Apri il feed RSS]({feed_url})",
        f"- [Scarica l'MP3]({mp3_url})",
    ]
    return "\n".join(righe).strip() + "\n"


def _config_email(env: dict[str, str]) -> tuple[list[str], str, int, str, str] | None:
    destinatari = [x.strip() for x in env.get("MAIL_TO", "").split(",") if x.strip()]
    host = env.get("SMTP_HOST", "").strip()
    utente = env.get("SMTP_USER", "").strip()
    password = env.get("SMTP_PASSWORD", "").strip()
    if not destinatari or not host or not utente or not password:
        return None
    try:
        porta = int(env.get("SMTP_PORT", "587") or "587")
    except ValueError:
        return None
    return destinatari, host, porta, utente, password


def invia_email(
    messaggio: str,
    *,
    oggetto: str = "Nuovo episodio del notiziario",
    env: dict[str, str] | None = None,
    smtp_factory: Callable[..., Any] | None = None,
    timeout: float = 20,
) -> bool | None:
    """Invia l'email. Restituisce None se non configurata, False su errore."""
    ambiente = env if env is not None else dict(os.environ)
    config = _config_email(ambiente)
    if config is None:
        print("email non configurata")
        return None
    destinatari, host, porta, utente, password = config
    factory = smtp_factory or smtplib.SMTP
    client = None
    try:
        client = factory(host, porta, timeout=timeout)
        client.ehlo()
        client.starttls()
        client.ehlo()
        client.login(utente, password)
        email = MIMEText(messaggio, "plain", "utf-8")
        email["Subject"] = oggetto
        email["From"] = utente
        email["To"] = ", ".join(destinatari)
        client.sendmail(utente, destinatari, email.as_string())
        print("email inviata")
        return True
    except Exception as exc:
        # Non stampare mai password, payload o dettagli del server.
        print(f"invio email non riuscito: {type(exc).__name__}", file=sys.stderr)
        return False
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:
                pass


def _carica_stato(data: str) -> dict[str, Any]:
    percorso = Path("output") / f"stato-{data}.json"
    if not percorso.exists():
        raise FileNotFoundError(f"Stato episodio non trovato: {percorso}")
    dati = json.loads(percorso.read_text(encoding="utf-8"))
    if not isinstance(dati, dict):
        raise ValueError("Stato episodio non valido.")
    return dati


def messaggio_da_stato(
    stato: dict[str, Any],
    data: str,
    impostazioni: dict[str, Any],
    *,
    player_url: str | None = None,
    feed_url: str | None = None,
    mp3_url: str | None = None,
) -> str:
    sito = normalizza_sito_url(
        str(impostazioni.get("feed", {}).get("sito_url") or "https://jakephobia.github.io/notiziario/")
    )
    base_url = str(impostazioni.get("feed", {}).get("base_url") or "")
    titolo = str(stato.get("titolo") or f"Notiziario del {data}")
    descrizione = str(stato.get("descrizione") or "")
    durata = stato.get("durata_secondi")
    if durata is None:
        durata = stato.get("durata_preset", "")
    mp3 = mp3_url or (
        costruisci_url_audio(base_url, data, f"notiziario-{data}.mp3")
        if base_url
        else ""
    )
    return messaggio_episodio(
        titolo=titolo,
        data=data,
        durata=durata,
        descrizione=descrizione,
        player_url=player_url or sito,
        feed_url=feed_url or urljoin(sito, "feed.xml"),
        mp3_url=mp3,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stampa il messaggio di un nuovo episodio e, se richiesto, invia l'email."
    )
    parser.add_argument(
        "--email",
        action="store_true",
        help="Invia il messaggio via SMTP se i secret sono configurati.",
    )
    parser.add_argument(
        "--data",
        help="Data episodio YYYY-MM-DD (default: oggi Europe/Rome).",
    )
    parser.add_argument("--player-url", help="Override URL del player.")
    parser.add_argument("--feed-url", help="Override URL del feed.")
    parser.add_argument("--mp3-url", help="Override URL dell'MP3.")
    args = parser.parse_args(argv)
    data = (args.data or data_iso_roma()).strip()
    try:
        stato = _carica_stato(data)
        messaggio = messaggio_da_stato(
            stato,
            data,
            carica_impostazioni(),
            player_url=args.player_url,
            feed_url=args.feed_url,
            mp3_url=args.mp3_url,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Notifica non disponibile: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.email:
        esito = invia_email(messaggio)
        return 0 if esito is not False else 1
    print(messaggio, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
