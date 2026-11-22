"""Rubrica first_seen per i feed senza date, con pruning a 60 giorni."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .fetch import normalizza_url
from .tempo import ROMA, adesso_roma, parse_iso
from .testi import normalizza_titolo


class Visti:
    """Stato persistente: chiave -> {first_seen, fonte, titolo}."""

    def __init__(
        self,
        percorso: str | Path,
        giorni_pruning: int = 60,
        logger: logging.Logger | None = None,
        adesso: datetime | None = None,
    ) -> None:
        self.percorso = Path(percorso)
        self.giorni_pruning = giorni_pruning
        self.logger = logger or logging.getLogger("notiziario")
        self.adesso = (adesso or adesso_roma()).astimezone(ROMA)
        self.visti: dict[str, dict] = {}
        self.feed_last_seen: dict[str, str] = {}
        self.modificato = False
        self._carica()
        self._pruning()

    @staticmethod
    def chiave_entry(entry) -> str:
        guid = str(entry.get("id") or entry.get("guid") or "").strip()
        if guid:
            if guid.startswith(("http://", "https://")):
                return "url:" + normalizza_url(guid)
            return "guid:" + hashlib.sha1(guid.encode("utf-8")).hexdigest()
        link = str(entry.get("link") or "").strip()
        if link:
            return "url:" + normalizza_url(link)
        titolo = str(entry.get("title") or "")
        return "titolo:" + hashlib.sha1(
            normalizza_titolo(titolo).encode("utf-8")
        ).hexdigest()

    def _carica(self) -> None:
        if not self.percorso.exists():
            self.visti = {}
            return
        try:
            dati = json.loads(self.percorso.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning(
                "state/visti.json non leggibile (%s): riparto da una rubrica vuota.",
                type(exc).__name__,
            )
            self.visti = {}
            self.modificato = True
            return
        visti = dati.get("visti") if isinstance(dati, dict) else None
        if not isinstance(visti, dict):
            self.logger.warning("state/visti.json non ha la struttura attesa.")
            self.visti = {}
            self.modificato = True
            return
        for chiave, voce in visti.items():
            if isinstance(voce, dict) and parse_iso(voce.get("first_seen", "")):
                self.visti[str(chiave)] = voce
            else:
                self.modificato = True
        feed_last = dati.get("feed_last_seen")
        if isinstance(feed_last, dict):
            self.feed_last_seen = {
                str(k): str(v) for k, v in feed_last.items() if parse_iso(v)
            }
        for voce in self.visti.values():
            fonte = str(voce.get("feed_url") or voce.get("fonte", ""))
            data = parse_iso(voce.get("first_seen", ""))
            if fonte and data:
                precedente = parse_iso(self.feed_last_seen.get(fonte, ""))
                if not precedente or data > precedente:
                    self.feed_last_seen[fonte] = data.isoformat()

    def _pruning(self) -> None:
        limite = self.adesso - timedelta(days=self.giorni_pruning)
        da_rimuovere = []
        for chiave, voce in self.visti.items():
            data = parse_iso(voce.get("first_seen", ""))
            if not data or data < limite:
                da_rimuovere.append(chiave)
        if da_rimuovere:
            for chiave in da_rimuovere:
                self.visti.pop(chiave, None)
            self.modificato = True
            self.logger.info(
                "Rubrica: rimossi %d elementi più vecchi di %d giorni.",
                len(da_rimuovere),
                self.giorni_pruning,
            )

    def first_seen(self, chiave: str) -> datetime | None:
        voce = self.visti.get(chiave)
        if not voce:
            return None
        return parse_iso(voce.get("first_seen", ""))

    def registra(
        self,
        chiave: str,
        fonte: str,
        titolo: str,
        adesso: datetime | None = None,
        feed_url: str | None = None,
    ) -> datetime:
        esistente = self.first_seen(chiave)
        if esistente:
            return esistente
        quando = (adesso or self.adesso).astimezone(ROMA)
        identificatore = feed_url or fonte
        self.visti[chiave] = {
            "first_seen": quando.isoformat(),
            "fonte": fonte,
            "feed_url": identificatore,
            "titolo": titolo[:300],
        }
        self.feed_last_seen[identificatore] = quando.isoformat()
        self.modificato = True
        return quando

    def _corrisponde(self, voce: dict, chiave: str) -> bool:
        return voce.get("feed_url") == chiave or voce.get("fonte") == chiave

    def ha_visti_feed(self, fonte: str) -> bool:
        return any(self._corrisponde(v, fonte) for v in self.visti.values())

    def ultimo_first_seen_feed(self, fonte: str) -> datetime | None:
        memorizzato = parse_iso(self.feed_last_seen.get(fonte, ""))
        date = [
            parse_iso(v.get("first_seen", ""))
            for v in self.visti.values()
            if self._corrisponde(v, fonte)
        ]
        date = [d for d in date if d]
        if memorizzato:
            date.append(memorizzato)
        return max(date) if date else None

    def feed_visto_di_recente(self, fonte: str, giorni: int = 180) -> bool:
        ultimo = self.ultimo_first_seen_feed(fonte)
        if not ultimo:
            return False
        return ultimo >= self.adesso - timedelta(days=giorni)

    def salva(self) -> None:
        self.percorso.parent.mkdir(parents=True, exist_ok=True)
        self.percorso.write_text(
            json.dumps(
                {"visti": self.visti, "feed_last_seen": self.feed_last_seen},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        self.modificato = False
