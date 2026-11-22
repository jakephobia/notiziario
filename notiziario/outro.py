"""Outro configurabile, con override dalla issue e marker dell'incipit."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .incipit import estrai_sezione_issue, risolvi_incipit


OUTRO_DEFAULT = (
    "Queste erano le notizie di oggi. "
    "A domani con i principali eventi della giornata!"
)


def leggi_modello_outro(percorso: str | Path | None) -> tuple[str, list[str]]:
    avvisi: list[str] = []
    if percorso:
        path = Path(percorso)
        if path.exists():
            try:
                testo = path.read_text(encoding="utf-8-sig").strip()
                if testo:
                    return testo, avvisi
            except OSError:
                avvisi.append(f"Non riesco a leggere {path}: uso l'outro predefinito.")
        else:
            avvisi.append(f"File outro non trovato ({path}): uso il default.")
    return OUTRO_DEFAULT, avvisi


def estrai_outro_issue(corpo: str | None) -> str | None:
    return estrai_sezione_issue(corpo, "Outro")


def scegli_modello(corpo_issue: str | None, modello_file: str) -> tuple[str, str]:
    modello_issue = estrai_outro_issue(corpo_issue)
    if modello_issue:
        return modello_issue, "issue"
    return modello_file, "file"


def risolvi_outro(
    modello: str,
    nome_utente: str,
    data_riferimento: datetime,
    logger=None,
) -> tuple[str, list[str]]:
    testo, avvisi = risolvi_incipit(modello, nome_utente, data_riferimento, logger)
    if not testo:
        testo = OUTRO_DEFAULT
        avvisi.append("Outro vuoto: uso il testo predefinito.")
    return testo, avvisi


def applica_outro(copione: dict[str, Any], outro: str) -> dict[str, Any]:
    """Rimuove qualsiasi chiusura e appende l'outro configurato una sola volta."""
    from .copione import _CHIUSURA_RE, _CHIUSURA_DEFAULT

    testo = outro.strip() or _CHIUSURA_DEFAULT
    paragrafi = [
        p.strip()
        for p in re.split(r"\n\s*\n", str(copione.get("testo", "")))
        if p.strip()
    ]
    filtrati = []
    for paragrafo in paragrafi:
        if len(paragrafo.split()) <= 45 and _CHIUSURA_RE.match(paragrafo):
            continue
        if paragrafo == testo:
            continue
        filtrati.append(paragrafo)
    copione["testo"] = "\n\n".join(filtrati + [testo])
    copione["outro"] = testo
    target = copione.get("target_parole")
    if isinstance(target, int) and target > 0:
        from .testi import conta_parole

        copione["divario_parole"] = max(0, target - conta_parole(copione["testo"]))
    return copione
