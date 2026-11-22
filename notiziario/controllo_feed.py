"""Controllo anti-block dei feed RSS: testo utile, paywall, inattività, podcast."""

from __future__ import annotations

import argparse
import calendar
import concurrent.futures
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feedparser
import requests

from .config import Fonte, carica_fonti_tutte
from .fetch import HEADERS, MAX_FEED_BYTES, normalizza_url
from .sicurezza import FetchHttpError, UrlRifiutato, fetch_con_limite
from .fonti_io import sostituisci_fonte, scrivi_fonti_yaml
from .tempo import adesso_roma, iso_roma
from .testi import pulisci_testo, pulisci_titolo


PAYWALL_MARKERS = (
    "abbonati",
    "abbonamento",
    "riservato agli abbonati",
    "continua a leggere",
    "leggi l'articolo completo",
    "leggi l’articolo completo",
    "solo per abbonati",
    "subscribe",
    "sign in to continue",
    "accedi per continuare",
)

_CTA = (
    "iscriviti alla newsletter",
    "iscriviti",
    "seguici",
    "condividi",
    "commenta",
    "clicca qui",
    "scopri di più",
    "vai all'articolo",
    "leggi tutto",
)


@dataclass
class EsitoControllo:
    fonte: str
    url: str
    categoria: str
    attivo: bool
    stato: str
    http: int | None = None
    item_totali: int = 0
    item_valutati: int = 0
    item_con_testo: int = 0
    item_con_testo_presente: int = 0
    percentuale_testo: float = 0.0
    percentuale_presente: float = 0.0
    percentuale_paywall: float = 0.0
    ultima_data: str | None = None
    giorni_inattivita: int | None = None
    podcast: bool = False
    data_assente: bool = False
    testo_breve: bool = False
    testo_medio: float = 0.0
    motivo: str = ""


def _data_entry(entry) -> datetime | None:
    for chiave in ("published_parsed", "updated_parsed"):
        strutturata = entry.get(chiave)
        if strutturata:
            try:
                return datetime.fromtimestamp(
                    calendar.timegm(strutturata), tz=timezone.utc
                )
            except (OverflowError, ValueError, TypeError):
                continue
    return None


def _testo_entry(entry) -> tuple[str, bool]:
    """Testo utile pulito e flag paywall (solo su testi corti)."""
    grezzo = entry.get("summary") or entry.get("description") or ""
    contenuto = ""
    if entry.get("content"):
        pezzi = []
        for voce in entry["content"]:
            valore = voce.get("value") if hasattr(voce, "get") else None
            if valore:
                pezzi.append(str(valore))
        contenuto = " ".join(pezzi)
    if len(contenuto) > max(500, len(grezzo) * 2):
        grezzo = contenuto
    testo = pulisci_testo(grezzo)
    titolo = pulisci_titolo(entry.get("title"))
    if titolo and testo.casefold().startswith(titolo.casefold()):
        testo = testo[len(titolo) :].lstrip(" .:-–—")
    for cta in _CTA:
        testo = testo.replace(cta, " ")
        testo = testo.replace(cta.capitalize(), " ")
    testo = " ".join(testo.split()).strip()
    paywall = any(marker in testo.casefold() for marker in PAYWALL_MARKERS)
    if paywall and len(testo) >= 160:
        # Un articolo lungo che parla di abbonamenti non è un paywall.
        paywall = False
    return testo, paywall


def _podcast(entries: list) -> bool:
    audio = 0
    for entry in entries:
        for enclosure in entry.get("enclosures") or []:
            tipo = str(enclosure.get("type", "")).lower()
            href = str(enclosure.get("href", "")).lower()
            if tipo.startswith("audio/") or href.endswith(
                (".mp3", ".m4a", ".aac", ".ogg")
            ):
                audio += 1
                break
    return audio > 0 and audio >= max(1, len(entries) // 2)


def controlla_feed(
    fonte: Fonte,
    impostazioni: dict[str, Any],
    adesso: datetime | None = None,
    visti=None,
    logger: logging.Logger | None = None,
    timeout: int = 15,
) -> EsitoControllo:
    logger = logger or logging.getLogger("notiziario")
    adesso = (adesso or adesso_roma()).astimezone(adesso_roma().tzinfo)
    conf = impostazioni.get("controllo_feed", {})
    min_caratteri = int(conf.get("min_caratteri_testo", 80))
    min_percentuale = float(conf.get("min_percentuale_con_testo", 50))
    max_paywall = float(conf.get("max_percentuale_paywall", 25))
    min_item = int(conf.get("min_item_valutati", 5))
    giorni_inattivo = int(conf.get("giorni_inattivita", 180))
    max_item = int(conf.get("max_item_valutati", 30))

    esito = EsitoControllo(
        fonte=fonte.nome,
        url=fonte.url,
        categoria=fonte.categoria,
        attivo=fonte.attivo,
        stato="errore",
    )
    try:
        contenuto, _, status = fetch_con_limite(
            fonte.url,
            timeout=timeout,
            max_bytes=MAX_FEED_BYTES,
            max_redirect=3,
            headers=HEADERS,
        )
        esito.http = status
        parsed = feedparser.parse(contenuto)
    except FetchHttpError as exc:
        esito.http = exc.status
        esito.motivo = f"HTTP {exc.status}"
        return esito
    except UrlRifiutato as exc:
        esito.motivo = f"URL non pubblico: {exc}"
        return esito
    except requests.RequestException as exc:
        esito.motivo = f"errore di rete ({type(exc).__name__})"
        return esito
    except Exception as exc:  # pragma: no cover - difesa
        esito.motivo = f"errore imprevisto ({type(exc).__name__})"
        return esito

    entries = list(parsed.entries or [])
    esito.item_totali = len(entries)
    if not entries:
        if getattr(parsed, "bozo", 0):
            esito.stato = "errore"
            esito.motivo = "XML malformato o non leggibile"
        else:
            esito.stato = "vuoto"
            esito.motivo = "nessun articolo nel feed"
        return esito

    esito.podcast = _podcast(entries)
    if esito.podcast:
        esito.stato = "podcast"
        esito.motivo = "il feed contiene enclosure audio"
        return esito

    date = [_data_entry(entry) for entry in entries]
    date = [d for d in date if d]
    ultima = max(date) if date else None
    esito.ultima_data = iso_roma(ultima) if ultima else None
    if ultima:
        esito.giorni_inattivita = max(0, (adesso - ultima.astimezone(adesso.tzinfo)).days)
    else:
        esito.data_assente = True
        if visti is not None:
            ultimo_visto = visti.ultimo_first_seen_feed(
                fonte.url
            ) or visti.ultimo_first_seen_feed(fonte.nome)
            if ultimo_visto:
                esito.giorni_inattivita = max(
                    0, (adesso - ultimo_visto.astimezone(adesso.tzinfo)).days
                )

    if esito.giorni_inattivita is not None and esito.giorni_inattivita > giorni_inattivo:
        esito.stato = "inattivo"
        esito.motivo = f"ultima attività {esito.giorni_inattivita} giorni fa"
        return esito
    if esito.data_assente and visti is not None:
        if not (
            visti.ha_visti_feed(fonte.url) or visti.ha_visti_feed(fonte.nome)
        ):
            esito.stato = "data-assente"
            esito.motivo = "feed senza date e senza first_seen"
            return esito
        # Con first_seen recente il feed è valutabile sul testo; se è vecchio
        # il blocco inattivo qui sopra lo ha già intercettato.

    valutati = entries[:max_item]
    testi: list[str] = []
    presenti = 0
    paywall_count = 0
    for entry in valutati:
        testo, paywall = _testo_entry(entry)
        if paywall:
            paywall_count += 1
        if testo:
            presenti += 1
        if len(testo) >= min_caratteri:
            testi.append(testo)

    esito.item_valutati = len(valutati)
    esito.item_con_testo = len(testi)
    esito.item_con_testo_presente = presenti
    esito.percentuale_testo = (
        round(100 * esito.item_con_testo / esito.item_valutati, 1)
        if esito.item_valutati
        else 0.0
    )
    esito.percentuale_presente = (
        round(100 * presenti / esito.item_valutati, 1)
        if esito.item_valutati
        else 0.0
    )
    esito.percentuale_paywall = (
        round(100 * paywall_count / esito.item_valutati, 1)
        if esito.item_valutati
        else 0.0
    )
    esito.testo_medio = (
        round(sum(len(t) for t in testi) / len(testi), 1) if testi else 0.0
    )

    if esito.item_valutati < min_item:
        esito.stato = "campione-insufficiente"
        esito.motivo = f"solo {esito.item_valutati} item valutabili (minimo {min_item})"
    elif esito.percentuale_paywall > max_paywall:
        esito.stato = "paywall"
        esito.motivo = f"paywall sul {esito.percentuale_paywall:.1f}% degli item"
    elif esito.percentuale_testo < min_percentuale:
        if esito.percentuale_presente >= min_percentuale:
            esito.stato = "testo-breve"
            esito.testo_breve = True
            esito.motivo = (
                f"testo presente ma sotto {min_caratteri} caratteri "
                f"sul {esito.percentuale_testo:.1f}% degli item"
            )
        else:
            esito.stato = "solo-titoli"
            esito.motivo = (
                f"testo utile sul {esito.percentuale_testo:.1f}% degli item "
                f"(minimo {min_percentuale:.0f}%)"
            )
    elif esito.testo_medio < 80:
        esito.stato = "testo-breve"
        esito.testo_breve = True
        esito.motivo = (
            f"summary brevi ma reali (media {esito.testo_medio:.0f} caratteri); "
            "non disattivare"
        )
    else:
        esito.stato = "ok"
        esito.motivo = f"testo utile sul {esito.percentuale_testo:.1f}% degli item"
    return esito


def controlla_tutte(
    fonti: list[Fonte],
    impostazioni: dict[str, Any],
    adesso: datetime | None = None,
    visti=None,
    logger: logging.Logger | None = None,
    max_workers: int = 8,
    timeout: int = 15,
) -> list[EsitoControllo]:
    logger = logger or logging.getLogger("notiziario")
    adesso = adesso or adesso_roma()

    def uno(fonte: Fonte) -> EsitoControllo:
        esito = controlla_feed(
            fonte, impostazioni, adesso, visti, logger, timeout=timeout
        )
        logger.info(
            "Controllo feed: %-22s %-24s %s",
            fonte.nome,
            esito.stato,
            esito.motivo,
        )
        return esito

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, min(max_workers, len(fonti)))
    ) as pool:
        esiti = list(pool.map(uno, fonti))
    return esiti


def salva_report(
    percorso: str | Path,
    esiti: list[EsitoControllo],
    impostazioni: dict[str, Any],
    adesso: datetime | None = None,
) -> None:
    path = Path(percorso)
    path.parent.mkdir(parents=True, exist_ok=True)
    dati = {
        "data": iso_roma(adesso or adesso_roma()),
        "soglie": impostazioni.get("controllo_feed", {}),
        "esiti": [asdict(e) for e in esiti],
    }
    path.write_text(
        json.dumps(dati, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def stampa_tabella(esiti: list[EsitoControllo]) -> None:
    print(
        f"{'STATO':24} {'FONTE':20} {'CAT':15} {'ITEM':>4} "
        f"{'TESTO%':>7} {'PAYWALL%':>9} {'ULTIMA':12} MOTIVO"
    )
    for e in esiti:
        print(
            f"{e.stato:24} {e.fonte[:20]:20} {e.categoria[:15]:15} "
            f"{e.item_valutati:4} {e.percentuale_testo:7.1f} "
            f"{e.percentuale_paywall:9.1f} "
            f"{(e.ultima_data or '-')[:10]:12} {e.motivo[:60]}"
        )


def aggiorna_fonti_con_controllo(
    fonti: list[Fonte],
    esiti: list[EsitoControllo],
    disattiva_non_ok: bool,
    adesso: datetime | None = None,
) -> list[Fonte]:
    per_url = {normalizza_url(e.url): e for e in esiti}
    risultato = list(fonti)
    for fonte in fonti:
        esito = per_url.get(normalizza_url(fonte.url))
        if not esito:
            continue
        campi = {
            "controllo": esito.stato,
            "ultimo_controllo": iso_roma(adesso or adesso_roma()),
        }
        if disattiva_non_ok and esito.stato not in {"ok", "testo-breve", "campione-insufficiente"}:
            campi["attivo"] = False
        risultato = sostituisci_fonte(risultato, fonte.url, **campi)
    return risultato


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Controlla i feed RSS: testo, paywall, podcast, inattività."
    )
    parser.add_argument("--fonti", required=True, help="File fonti.yaml")
    parser.add_argument("--output", default="output")
    parser.add_argument("--disattiva-non-ok", action="store_true")
    args = parser.parse_args(argv)

    logger = logging.getLogger("notiziario")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from .config import carica_impostazioni

    impostazioni = carica_impostazioni()
    fonti = carica_fonti_tutte(args.fonti)
    esiti = controlla_tutte(fonti, impostazioni, logger=logger)
    stampa_tabella(esiti)
    data_iso = adesso_roma().date().isoformat()
    salva_report(
        Path(args.output) / f"controllo-feed-{data_iso}.json",
        esiti,
        impostazioni,
    )
    if args.disattiva_non_ok:
        fonti = aggiorna_fonti_con_controllo(fonti, esiti, True)
    else:
        fonti = aggiorna_fonti_con_controllo(fonti, esiti, False)
    scrivi_fonti_yaml(args.fonti, fonti)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
