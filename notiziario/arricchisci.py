"""Arricchimento degli articoli selezionati con il testo completo della pagina."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from .config import ROOT
from .controllo_feed import PAYWALL_MARKERS
from .fetch import Article
from .selezione import NotiziaSelezionata
from .sicurezza import (
    FetchHttpError,
    UrlRifiutato,
    fetch_con_limite,
    headers_browser,
    valida_url_pubblica,
)
from .tempo import adesso_roma, iso_roma, parse_iso
from .testi import (
    pulisci_testo,
    pulisci_titolo,
    rimuovi_elementi_pubblicitari,
    tronca_a_frase,
)

try:
    import trafilatura

    _HA_TRAFILATURA = True
except ImportError:  # pragma: no cover - fallback documentato
    trafilatura = None
    _HA_TRAFILATURA = False


USER_AGENT = "NotiziarioBot/0.3 (lettore RSS personale)"
_ROBOTS_CACHE: dict[str, tuple[RobotFileParser | None, str]] = {}


def _cache_dir(impostazioni: dict[str, Any]) -> Path:
    valore = Path(impostazioni.get("arricchimento", {}).get("cache_dir", "cache/articoli"))
    return valore if valore.is_absolute() else ROOT / valore


def _cache_path(url: str, impostazioni: dict[str, Any]) -> Path:
    nome = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32] + ".json"
    return _cache_dir(impostazioni) / nome


def leggi_cache(
    url: str, impostazioni: dict[str, Any], adesso: datetime | None = None
) -> dict[str, Any] | None:
    path = _cache_path(url, impostazioni)
    if not path.exists():
        return None
    try:
        dati = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if dati.get("url") != url:
        return None
    ttl = int(impostazioni.get("arricchimento", {}).get("ttl_ore", 24))
    salvato = parse_iso(dati.get("salvato", ""))
    if not salvato:
        return None
    if (adesso or adesso_roma()) - salvato > timedelta(hours=ttl):
        return None
    return dati


def scrivi_cache(
    url: str,
    impostazioni: dict[str, Any],
    testo: str | None,
    parziale: bool,
    motivo: str,
    adesso: datetime | None = None,
) -> None:
    path = _cache_path(url, impostazioni)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "url": url,
                "testo": testo,
                "parziale": bool(parziale),
                "motivo": motivo,
                "salvato": iso_roma(adesso or adesso_roma()),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _robots_url(url: str) -> str:
    parti = urlsplit(url)
    return f"{parti.scheme}://{parti.netloc}/robots.txt"


def robots_consenti(
    url: str,
    impostazioni: dict[str, Any],
    logger: logging.Logger | None = None,
) -> bool:
    logger = logger or logging.getLogger("notiziario")
    if not impostazioni.get("arricchimento", {}).get("rispetta_robots", True):
        return True
    chiave = urlsplit(url).netloc.casefold()
    if chiave in _ROBOTS_CACHE:
        parser, testo = _ROBOTS_CACHE[chiave]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)
    parser: RobotFileParser | None = None
    testo = ""
    try:
        contenuto, _, status = fetch_con_limite(
            _robots_url(url),
            timeout=int(impostazioni["arricchimento"]["timeout"]),
            max_bytes=100_000,
            max_redirect=2,
            headers=headers_browser(USER_AGENT),
        )
        testo = contenuto.decode("utf-8", errors="replace")
        parser = RobotFileParser()
        parser.parse(testo.splitlines())
    except (requests.RequestException, UrlRifiutato, FetchHttpError) as exc:
        logger.warning(
            "robots.txt non raggiungibile per %s (%s): consento il fetch per policy.",
            chiave,
            type(exc).__name__,
        )
        parser = None
    _ROBOTS_CACHE[chiave] = (parser, testo)
    consentito = True if parser is None else parser.can_fetch(USER_AGENT, url)
    if not consentito:
        logger.info("Robots.txt vieta %s: uso il summary.", url)
    return consentito


def _estrazione_bs4(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "aside", "form"]):
        tag.decompose()
    rimuovi_elementi_pubblicitari(soup)
    paragrafi = []
    for p in soup.find_all(["p", "h2", "h3", "li"]):
        testo = pulisci_testo(p.get_text(" "))
        if len(testo) >= 40:
            paragrafi.append(testo)
    return "\n\n".join(paragrafi)


def estrai_da_html(
    html: str,
    titolo: str,
    min_caratteri: int = 300,
) -> tuple[str | None, bool, str]:
    """Restituisce (testo, parziale, motivo). Testo None = usa il summary."""
    if not html:
        return None, True, "HTML vuoto"
    testo = ""
    if _HA_TRAFILATURA:
        try:
            testo = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
                favor_recall=True,
                output_format="txt",
            ) or ""
        except Exception:
            testo = ""
    if len(testo) < min_caratteri:
        testo = _estrazione_bs4(html)
    testo = pulisci_testo(testo)
    titre = pulisci_titolo(titolo)
    if titre and testo.casefold().startswith(titre.casefold()):
        testo = testo[len(titre) :].lstrip(" .:-–—")
    testo = " ".join(testo.split())
    basso = testo.casefold()
    paywall = any(marker in basso for marker in PAYWALL_MARKERS)
    if paywall and len(testo) < min_caratteri * 3:
        return None, True, "paywall"
    if len(testo) < min_caratteri:
        return None, True, "estratto troppo corto"
    return testo, False, "ok"


def arricchisci_articolo(
    articolo: Article,
    impostazioni: dict[str, Any],
    logger: logging.Logger | None = None,
    adesso: datetime | None = None,
) -> bool:
    """Arricchisce un Article; False se resta il summary."""
    logger = logger or logging.getLogger("notiziario")
    conf = impostazioni.get("arricchimento", {})
    if not conf.get("attivo", True):
        return False
    if articolo.contenuto:
        return True
    cache = leggi_cache(articolo.link, impostazioni, adesso)
    if cache is not None:
        if cache.get("testo") and not cache.get("parziale"):
            articolo.contenuto = pulisci_testo(str(cache["testo"]))
            articolo.arricchito = True
            articolo.contenuto_parziale = False
            return True
        articolo.contenuto_parziale = True
        return False

    if not robots_consenti(articolo.link, impostazioni, logger):
        articolo.contenuto_parziale = True
        scrivi_cache(
            articolo.link,
            impostazioni,
            None,
            True,
            "robots",
            adesso,
        )
        return False
    try:
        valida_url_pubblica(articolo.link, risolvi=True)
        html_bytes, _, _ = fetch_con_limite(
            articolo.link,
            timeout=int(conf.get("timeout", 15)),
            max_bytes=int(conf.get("max_bytes", 2_000_000)),
            max_redirect=int(conf.get("max_redirect", 3)),
            headers=headers_browser(USER_AGENT),
        )
        html = html_bytes.decode("utf-8", errors="replace")
    except (requests.RequestException, UrlRifiutato, FetchHttpError) as exc:
        motivo = f"fetch: {type(exc).__name__}"
        articolo.contenuto_parziale = True
        scrivi_cache(articolo.link, impostazioni, None, True, motivo, adesso)
        logger.info("Arricchimento saltato per %s (%s).", articolo.link, motivo)
        return False

    testo, parziale, motivo = estrai_da_html(
        html,
        articolo.titolo,
        int(conf.get("min_caratteri_estratto", 300)),
    )
    if testo:
        massimo = int(conf.get("max_caratteri_articolo", 6000))
        testo = tronca_a_frase(testo, massimo)
        articolo.contenuto = testo
        articolo.arricchito = True
        articolo.contenuto_parziale = parziale
    else:
        articolo.contenuto_parziale = True
    scrivi_cache(articolo.link, impostazioni, testo, parziale, motivo, adesso)
    return bool(testo)


def arricchisci_selezioni(
    selezioni: list[NotiziaSelezionata],
    impostazioni: dict[str, Any],
    logger: logging.Logger | None = None,
    adesso: datetime | None = None,
) -> dict[str, Any]:
    logger = logger or logging.getLogger("notiziario")
    conf = impostazioni.get("arricchimento", {})
    riepilogo = {
        "attivo": bool(conf.get("attivo", True)),
        "articoli": 0,
        "arricchiti": 0,
        "parziali": 0,
        "falliti": 0,
        "caratteri": 0,
    }
    if not riepilogo["attivo"]:
        return riepilogo
    massimo = int(conf.get("max_articoli", 20))
    per_cluster = int(conf.get("max_per_cluster", 3))
    for selezione in selezioni:
        if riepilogo["articoli"] >= massimo:
            break
        for articolo in selezione.cluster.ordina_articoli()[:per_cluster]:
            if riepilogo["articoli"] >= massimo:
                break
            riepilogo["articoli"] += 1
            if arricchisci_articolo(articolo, impostazioni, logger, adesso):
                riepilogo["arricchiti"] += 1
                riepilogo["caratteri"] += len(articolo.contenuto or "")
            elif articolo.contenuto_parziale:
                riepilogo["parziali"] += 1
            else:
                riepilogo["falliti"] += 1
    logger.info(
        "Arricchimento: %d articoli provati, %d arricchiti, %d parziali, "
        "%d falliti, %d caratteri.",
        riepilogo["articoli"],
        riepilogo["arricchiti"],
        riepilogo["parziali"],
        riepilogo["falliti"],
        riepilogo["caratteri"],
    )
    return riepilogo
