"""Data e ora di riferimento: sempre Europe/Rome, mai UTC per i testi."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


ROMA = ZoneInfo("Europe/Rome")


def adesso_roma() -> datetime:
    return datetime.now(timezone.utc).astimezone(ROMA)


def data_iso_roma(data: datetime | None = None) -> str:
    return (data or adesso_roma()).astimezone(ROMA).date().isoformat()


def iso_roma(data: datetime) -> str:
    return data.astimezone(ROMA).isoformat()


def parse_iso(testo: str) -> datetime | None:
    try:
        valore = datetime.fromisoformat(str(testo).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if valore.tzinfo is None:
        valore = valore.replace(tzinfo=ROMA)
    return valore
