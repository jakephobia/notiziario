"""Incipit configurabile, con override dalla issue GitHub e marker parlati."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .tempo import ROMA
from .testi import GIORNI, MESI, conta_parole


INCIPIT_DEFAULT = (
    "Ciao [NOME UTENTE], ecco le tue notizie del giorno. Oggi è il [DATA]."
)


def leggi_modello_incipit(percorso: str | Path | None) -> tuple[str, list[str]]:
    """Legge il file incipit; se manca usa il default senza bloccare."""
    avvisi: list[str] = []
    if percorso:
        path = Path(percorso)
        if path.exists():
            try:
                testo = path.read_text(encoding="utf-8-sig").strip()
                if testo:
                    return testo, avvisi
            except OSError:
                avvisi.append(f"Non riesco a leggere {path}: uso l'incipit predefinito.")
        else:
            avvisi.append(f"File incipit non trovato ({path}): uso il default.")
    return INCIPIT_DEFAULT, avvisi


def estrai_incipit_issue(corpo: str | None) -> str | None:
    """Estrae la sezione '## Incipit' fino al prossimo heading '##'."""
    if not corpo:
        return None
    match = re.search(
        r"(?ims)^##\s*Incipit\b[^\n]*\n(.*?)(?=^##\s|\Z)",
        corpo,
    )
    if not match:
        return None
    blocco = match.group(1).strip()
    if not blocco:
        return None

    # Blocco di codice: usa il suo contenuto, non i backtick.
    fence = re.search(r"```(?:[A-Za-z0-9_-]+)?\s*\n(.*?)```", blocco, re.DOTALL)
    if fence:
        blocco = fence.group(1)
    else:
        blocco = re.sub(r"^\s*```.*$", "", blocco, flags=re.MULTILINE)
        blocco = re.sub(r"^\s*```\s*$", "", blocco, flags=re.MULTILINE)

    righe = []
    for riga in blocco.splitlines():
        riga = riga.strip()
        if not riga or riga.startswith(">"):
            continue
        righe.append(riga)
    testo = " ".join(righe)
    testo = re.sub(r"[*_`]+", "", testo)
    testo = re.sub(r"\s+", " ", testo).strip()
    return testo or None


def scegli_modello(
    corpo_issue: str | None, modello_file: str
) -> tuple[str, str]:
    """Priorità: sezione Incipit della issue, poi config/incipit.txt."""
    modello_issue = estrai_incipit_issue(corpo_issue)
    if modello_issue:
        return modello_issue, "issue"
    return modello_file, "file"


def estrai_sezione_issue(corpo: str | None, nome: str) -> str | None:
    """Estrae una sezione testuale/codice fino al prossimo heading ##."""
    if not corpo:
        return None
    match = re.search(
        rf"(?ims)^##\s*{re.escape(nome)}\b[^\n]*\n(.*?)(?=^##\s|\Z)",
        corpo,
    )
    if not match:
        return None
    blocco = match.group(1).strip()
    if not blocco:
        return None
    fence = re.search(r"```(?:[A-Za-z0-9_-]+)?\s*\n(.*?)```", blocco, re.DOTALL)
    if fence:
        blocco = fence.group(1)
    else:
        blocco = re.sub(r"^\s*```.*$", "", blocco, flags=re.MULTILINE)
        blocco = re.sub(r"^\s*```\s*$", "", blocco, flags=re.MULTILINE)
    righe = [
        riga.strip() for riga in blocco.splitlines()
        if riga.strip() and not riga.strip().startswith(">")
    ]
    testo = " ".join(righe)
    testo = re.sub(r"[*_`]+", "", testo)
    testo = re.sub(r"\s+", " ", testo).strip()
    return testo or None

def _data_marker(data: datetime) -> tuple[str, str, str]:
    data = data.astimezone(ROMA)
    giorno = GIORNI[data.weekday()]
    mese = MESI[data.month - 1]
    parziale = f"{data.day} {mese}"
    completa = f"{giorno} {parziale} {data.year}"
    return parziale, giorno, completa


def _pulisci_dopo_marker(testo: str) -> str:
    testo = re.sub(r"[ \t]+", " ", testo)
    testo = re.sub(r"\s+([,.;:!?])", r"\1", testo)
    testo = re.sub(r"([,.;:!?])(?=[A-Za-zÀ-ÖØ-öø-ÿ])", r"\1 ", testo)
    testo = re.sub(r"\.{2,}", ".", testo)
    return testo.strip()


def risolvi_incipit(
    modello: str,
    nome_utente: str,
    data_riferimento: datetime,
    logger=None,
) -> tuple[str, list[str]]:
    """Sostituisce i marker e rimuove quelli sconosciuti.

    Restituisce (testo_risolto, avvisi). Non lascia mai '[' o ']' nel testo.
    """
    avvisi: list[str] = []
    parziale, giorno, completa = _data_marker(data_riferimento)
    testo = modello or ""

    sostituzioni = [
        (r"\[\s*DATA\s+COMPLETA\s*\]", completa),
        (r"\[\s*NOME\s+UTENTE\s*\]", nome_utente.strip()),
        (r"\[\s*NOME\s*\]", nome_utente.strip()),
        (r"\[\s*DATA\s*\]", parziale),
        (r"\[\s*GIORNO\s*\]", giorno),
    ]
    for schema, valore in sostituzioni:
        if re.search(schema, testo, flags=re.IGNORECASE):
            if not valore and "NOME" in schema:
                avvisi.append(
                    "nome_utente vuoto: rimuovo il marker del nome dall'incipit."
                )
            testo = re.sub(schema, valore, testo, flags=re.IGNORECASE)

    for marker in re.findall(r"\[[^\[\]]{1,100}\]", testo):
        avvisi.append(f"Marker incipit sconosciuto rimosso: {marker}")
        testo = testo.replace(marker, " ")

    if "[" in testo or "]" in testo:
        avvisi.append("Parentesi quadre residue nell'incipit: rimosse.")
        testo = testo.replace("[", " ").replace("]", " ")

    testo = _pulisci_dopo_marker(testo)
    if not testo:
        avvisi.append("L'incipit è vuoto dopo la risoluzione dei marker.")
    if logger:
        for avviso in avvisi:
            logger.warning("Incipit: %s", avviso)
    return testo, avvisi


def aggiungi_incipit(copione: dict[str, Any], incipit: str) -> dict[str, Any]:
    """Aggiunge l'incipit in testa al corpo già scritto, senza toccare le notizie."""
    corpo = str(copione.get("testo", "")).lstrip()
    if incipit:
        copione["testo"] = incipit + ("\n\n" + corpo if corpo else "")
    copione["incipit"] = incipit
    target = copione.get("target_parole")
    if isinstance(target, int) and target > 0:
        copione["divario_parole"] = max(0, target - conta_parole(copione["testo"]))
    return copione
