"""Dati per l'anteprima delle fonti RSS nel sito statico.

Il file prodotto (``docs/anteprime-fonti.json``) è pensato per la UI: contiene
tutte le fonti configurate, anche quelle senza articoli recenti, e per ognuna
al massimo ``limite`` articoli puliti.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import Fonte
from .fetch import Article
from .testi import pulisci_testo, pulisci_titolo, tronca_a_frase


LIMITE_ANTEPRIME = 5
LUNGHEZZA_SOMMARIO = 260


def _data_ordinamento(articolo: Article) -> datetime:
    data = getattr(articolo, "pubblicato", None)
    if not isinstance(data, datetime):
        return datetime.min.replace(tzinfo=timezone.utc)
    if data.tzinfo is None:
        data = data.replace(tzinfo=timezone.utc)
    return data


def _data_iso(data: Any) -> str:
    if not isinstance(data, datetime):
        return ""
    if data.tzinfo is None:
        data = data.replace(tzinfo=timezone.utc)
    return data.isoformat()


def _chiave_dedup(articolo: Article) -> str:
    link = str(getattr(articolo, "link", "") or "").strip()
    if link:
        return link
    titolo = str(getattr(articolo, "titolo", "") or "").strip()
    fonte = str(getattr(articolo, "fonte", "") or "").strip()
    return f"{titolo}|{fonte}"


def _anteprima_articolo(articolo: Article) -> dict[str, str]:
    return {
        "titolo": pulisci_titolo(getattr(articolo, "titolo", "")),
        "sommario": tronca_a_frase(
            pulisci_testo(getattr(articolo, "sommario", "")),
            LUNGHEZZA_SOMMARIO,
        ),
        "link": str(getattr(articolo, "link", "") or "").strip(),
        "pubblicato": _data_iso(getattr(articolo, "pubblicato", None)),
    }


def costruisci_anteprime(
    articoli: list[Article], fonti: list[Fonte], limite: int = LIMITE_ANTEPRIME
) -> dict[str, Any]:
    """Raggruppa gli articoli per fonte e restituisce i dati dell'anteprima."""
    limite = max(0, int(limite))
    per_url: dict[str, list[Article]] = {}
    per_fonte: dict[str, list[Article]] = {}
    for articolo in articoli or []:
        feed_url = str(getattr(articolo, "feed_url", "") or "").strip()
        nome = str(getattr(articolo, "fonte", "") or "").strip()
        if feed_url:
            per_url.setdefault(feed_url, []).append(articolo)
        elif nome:
            per_fonte.setdefault(nome, []).append(articolo)

    risultato: dict[str, Any] = {}
    for fonte in fonti or []:
        try:
            candidati = list(per_url.get(fonte.url, [])) + list(
                per_fonte.get(fonte.nome, [])
            )
            visti: set[str] = set()
            selezionati: list[dict[str, str]] = []
            if limite > 0:
                for articolo in sorted(
                    candidati, key=_data_ordinamento, reverse=True
                ):
                    chiave = _chiave_dedup(articolo)
                    if chiave in visti:
                        continue
                    visti.add(chiave)
                    try:
                        selezionati.append(_anteprima_articolo(articolo))
                    except Exception:
                        continue
                    if len(selezionati) >= limite:
                        break
            voce = {
                "nome": fonte.nome,
                "url": fonte.url,
                "attivo": bool(fonte.attivo),
                "articoli": selezionati,
            }
        except Exception:
            # Una singola fonte malformata non deve fermare il file.
            voce = {
                "nome": fonte.nome,
                "url": fonte.url,
                "attivo": bool(fonte.attivo),
                "articoli": [],
            }
        risultato[fonte.url] = voce

    return {
        "generato": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "fonti": risultato,
    }
