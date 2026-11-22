"""Controllo rapido delle fonti RSS configurate (utile dopo una modifica)."""

from __future__ import annotations

import argparse
import calendar
import sys
from datetime import datetime, timezone

import feedparser
import requests

from .config import carica_fonti
from .fetch import HEADERS


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


def verifica(percorso: str | None = None, timeout: int = 15) -> int:
    fonti = carica_fonti(percorso)
    adesso = datetime.now(timezone.utc)
    errori = 0
    print(f"Controllo {len(fonti)} fonti RSS...\n")
    for fonte in fonti:
        try:
            risposta = requests.get(fonte.url, headers=HEADERS, timeout=timeout)
            if risposta.status_code >= 400:
                raise RuntimeError(f"HTTP {risposta.status_code}")
            parsed = feedparser.parse(risposta.content)
            if not parsed.entries:
                raise RuntimeError("nessun articolo nel feed")
            date = [d for d in (_data_entry(e) for e in parsed.entries) if d]
            recenti = sum(
                1 for d in date if (adesso - d).total_seconds() <= 24 * 3600
            )
            ultima = max(date).isoformat() if date else "nessuna data"
            stato = "OK " if recenti else "ATT"
            print(
                f"{stato} {fonte.nome:16} {fonte.categoria:14} "
                f"entry={len(parsed.entries):3} recenti24h={recenti:3} "
                f"ultima={ultima}"
            )
            print(f"     {fonte.url}")
            if not recenti:
                errori += 1
        except Exception as exc:
            errori += 1
            print(f"KO  {fonte.nome:16} {fonte.categoria:14} {type(exc).__name__}: {exc}")
            print(f"     {fonte.url}")
    print(
        f"\nRiepilogo: {len(fonti) - errori} fonti con articoli recenti, "
        f"{errori} da controllare."
    )
    return 1 if errori else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verifica che i feed di config/fonti.yaml rispondano e abbiano date."
    )
    parser.add_argument("--fonti", help="Percorso alternativo del file YAML")
    parser.add_argument("--strict", action="store_true", help="Esce con errore se una fonte è KO o ferma")
    args = parser.parse_args(argv)
    codice = verifica(args.fonti)
    return codice if args.strict else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
