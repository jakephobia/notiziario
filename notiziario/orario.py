"""Controllo dell'orario di generazione del notiziario in Europe/Rome."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from typing import Any

from .config import ConfigError, carica_impostazioni
from .tempo import ROMA, adesso_roma

_ORARIO_RE = re.compile(r"(?:[01]\d|2[0-3]):00")


def orario_valido(valore: Any) -> bool:
    return isinstance(valore, str) and bool(_ORARIO_RE.fullmatch(valore.strip()))


def ora_roma(adesso: datetime | None = None) -> str:
    data = adesso or adesso_roma()
    if data.tzinfo is None:
        data = data.replace(tzinfo=ROMA)
    return data.astimezone(ROMA).strftime("%H:00")


def controlla(
    impostazioni: dict[str, Any] | None = None,
    adesso: datetime | None = None,
) -> bool:
    dati = impostazioni or carica_impostazioni()
    orario = str(dati.get("orario_generazione", "07:00")).strip()
    return ora_roma(adesso) == orario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Controlla l'orario di generazione.")
    parser.add_argument(
        "--controlla",
        action="store_true",
        help="Stampa true se l'ora corrente (Europe/Rome) corrisponde.",
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
