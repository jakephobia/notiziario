"""Confronta il fetch HTTP dei feed con un'apertura browser-like."""

from __future__ import annotations

import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit

import feedparser
import requests

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from notiziario.config import carica_fonti_tutte  # noqa: E402
from notiziario.fetch import HEADERS  # noqa: E402

USCITA = BASE / "output" / "diagnostica-feed.json"
UA_BROWSER = HEADERS["User-Agent"]
HEADERS_BROWSER = {
    "User-Agent": UA_BROWSER,
    "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.6",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


def _entrate(contenuto: bytes) -> int:
    try:
        feed = feedparser.parse(contenuto)
        return len(feed.entries)
    except Exception:
        return 0


def _prova(fonte) -> dict:
    risultato = {
        "nome": fonte.nome,
        "url": fonte.url,
        "categoria": fonte.categoria,
        "attivo": bool(fonte.attivo),
        "richieste": {"ok": False, "stato": None, "errore": "", "entrate": 0},
        "browser": {"ok": False, "stato": None, "errore": "", "entrate": 0},
    }
    try:
        r = requests.get(fonte.url, headers=HEADERS_BROWSER, timeout=20)
        risultato["richieste"]["stato"] = r.status_code
        risultato["richieste"]["entrate"] = _entrate(r.content)
        risultato["richieste"]["ok"] = (
            r.status_code < 400 and risultato["richieste"]["entrate"] > 0
        )
        if not risultato["richieste"]["ok"]:
            risultato["richieste"]["errore"] = f"HTTP {r.status_code}, {len(r.content)} byte"
    except Exception as exc:
        risultato["richieste"]["errore"] = f"{type(exc).__name__}: {exc}"[:200]
    return risultato


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    fonti = {f.url: f for f in carica_fonti_tutte()}
    risultati = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_prova, fonte): fonte for fonte in fonti.values()}
        for future in as_completed(futures):
            risultati.append(future.result())
    risultati.sort(key=lambda voce: (not voce["richieste"]["ok"], voce["nome"]))
    USCITA.parent.mkdir(parents=True, exist_ok=True)
    USCITA.write_text(
        json.dumps(risultati, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fallite = [voce for voce in risultati if not voce["richieste"]["ok"]]
    print(f"Feed totali: {len(risultati)}; falliti: {len(fallite)}")
    for voce in fallite:
        print(
            voce["nome"],
            "|",
            voce["url"],
            "|",
            voce["richieste"]["stato"],
            "|",
            voce["richieste"]["errore"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
