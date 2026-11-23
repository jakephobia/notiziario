"""Controllo dell'orario di generazione del notiziario in Europe/Rome."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .config import ConfigError, carica_impostazioni
from .tempo import ROMA, adesso_roma

_ORARIO_RE = re.compile(r"(?:[01]\d|2[0-3]):00")


def orario_valido(valore: Any) -> bool:
    return isinstance(valore, str) and bool(_ORARIO_RE.fullmatch(valore.strip()))


def ora_roma(adesso: datetime | None = None) -> str:
    data = adesso or adesso_roma()
    if data.tzinfo is None:
        data = data.replace(tzinfo=ROMA)
    return data.astimezone(ROMA).strftime("%H:%M")


def _minuti(ora: str) -> int:
    ore, minuti = ora.split(":", 1)
    return int(ore) * 60 + int(minuti)


def _data_roma(adesso: datetime | None = None) -> str:
    data = adesso or adesso_roma()
    if data.tzinfo is None:
        data = data.replace(tzinfo=ROMA)
    return data.astimezone(ROMA).date().isoformat()


def _episodio_da_storico(percorso: Path, oggi: str) -> bool:
    if not percorso.exists():
        return False
    try:
        dati = json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    episodi = dati.get("episodi") if isinstance(dati, dict) else None
    if not isinstance(episodi, list):
        return False
    for episodio in episodi:
        if not isinstance(episodio, dict):
            continue
        if str(episodio.get("data", "")) == oggi:
            return True
        if str(episodio.get("guid", "")).endswith(oggi):
            return True
    return False


def _episodio_da_feed(percorso: Path, oggi: str) -> bool:
    if not percorso.exists():
        return False
    try:
        radice = ET.parse(percorso).getroot()
    except (OSError, ET.ParseError):
        return False
    for item in radice.findall(".//item"):
        pub = item.findtext("pubDate") or ""
        if not pub:
            continue
        try:
            data = parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            continue
        if data.tzinfo is None:
            data = data.replace(tzinfo=ROMA)
        if data.astimezone(ROMA).date().isoformat() == oggi:
            return True
    return False


def episodio_oggi(
    storico_path: str | Path = "docs/storico.json",
    feed_path: str | Path = "docs/feed.xml",
    adesso: datetime | None = None,
) -> bool:
    """True se esiste già un episodio con la data odierna Europe/Rome."""
    oggi = _data_roma(adesso)
    return _episodio_da_storico(Path(storico_path), oggi) or _episodio_da_feed(
        Path(feed_path), oggi
    )


def controlla(
    impostazioni: dict[str, Any] | None = None,
    adesso: datetime | None = None,
    storico_path: str | Path = "docs/storico.json",
    feed_path: str | Path = "docs/feed.xml",
) -> bool:
    """Recupera la generazione mancante nella giornata dopo l'orario configurato."""
    dati = impostazioni or carica_impostazioni()
    orario = str(dati.get("orario_generazione", "07:00")).strip()
    adesso_rm = adesso or adesso_roma()
    ora = ora_roma(adesso_rm)
    presente = episodio_oggi(storico_path, feed_path, adesso_rm)
    esito = _minuti(ora) >= _minuti(orario) and not presente
    print(
        f"orario: ora={ora} orario={orario} episodio_oggi={str(presente).lower()}",
        file=sys.stderr,
    )
    return esito


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Controlla l'orario di generazione.")
    parser.add_argument(
        "--controlla",
        action="store_true",
        help="Stampa true se l'ora corrente (Europe/Rome) ha superato l'orario e manca l'episodio.",
    )
    args = parser.parse_args(argv)
    if not args.controlla:
        parser.print_help()
        return 0
    try:
        esito = controlla()
    except (ConfigError, OSError) as exc:
        print(f"Errore configurazione orario: {exc}", file=sys.stderr)
        return 1
    print("true" if esito else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
