"""Scelta di voce, velocità e motore TTS, con override dalla issue."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


VELOCITA_PASSI = tuple(round(0.75 + 0.05 * i, 2) for i in range(11))
VELOCITA_DEFAULT = 1.10


@dataclass
class VoceScelta:
    nome: str
    velocita: float
    motore: str
    etichetta: str = ""
    genere: str = ""
    avvisi: list[str] = field(default_factory=list)
    fonte: str = "config"


def normalizza_velocita(
    valore: Any, default: float = VELOCITA_DEFAULT
) -> tuple[float, list[str]]:
    """Limita a 0.75-1.25 e aggancia allo step 0.05 più vicino."""
    avvisi: list[str] = []
    try:
        numero = float(str(valore).replace(",", "."))
    except (TypeError, ValueError):
        return round(float(default), 2), [
            f"Velocità {valore!r} non valida: uso {default:.2f}."
        ]
    limitato = min(1.25, max(0.75, numero))
    if abs(limitato - numero) > 1e-9:
        avvisi.append(
            f"Velocità {numero:g} fuori range: limitata a {limitato:.2f}."
        )
    agganciata = min(VELOCITA_PASSI, key=lambda x: abs(x - limitato))
    if abs(agganciata - limitato) > 1e-9:
        avvisi.append(
            f"Velocità {limitato:g} agganciata allo step {agganciata:.2f}."
        )
    return round(float(agganciata), 2), avvisi

def _voci(impostazioni: dict[str, Any]) -> list[dict[str, Any]]:
    voci = impostazioni.get("voce", {}).get("voci", [])
    return [v for v in voci if isinstance(v, dict) and v.get("nome")]


def _canonica(nome: str, voci: list[dict[str, Any]]) -> dict[str, Any] | None:
    cercato = str(nome).strip().casefold()
    for voce in voci:
        if str(voce.get("nome", "")).strip().casefold() == cercato:
            return voce
    return None


def _etichetta(voce: dict[str, Any]) -> str:
    return str(voce.get("label") or voce.get("nome", ""))


def sezione_voce(corpo: str | None) -> dict[str, str]:
    """Legge la sezione '## Voce' fino al prossimo heading ##."""
    if not corpo:
        return {}
    match = re.search(
        r"(?ims)^##\s*Voce\b[^\n]*\n(.*?)(?=^##\s|\Z)",
        corpo,
    )
    if not match:
        return {}
    valori: dict[str, str] = {}
    for riga in match.group(1).splitlines():
        riga = re.sub(r"^[\s>*_`-]+", "", riga).strip()
        riga = re.sub(r"[*_`]+", "", riga)
        trovato = re.match(r"(voce|velocita|motore)\s*:\s*(.+?)\s*$", riga, re.I)
        if trovato:
            valori[trovato.group(1).casefold()] = trovato.group(2).strip().strip("\"'")
    return valori


def risolvi_voce(
    impostazioni: dict[str, Any],
    corpo_issue: str | None = None,
    voce_cli: str | None = None,
    velocita_cli: float | None = None,
    motore_cli: str | None = None,
) -> VoceScelta:
    voci = _voci(impostazioni)
    config_voce = impostazioni.get("voce", {})
    nome = str(config_voce.get("nome", "Kore")).strip()
    velocita, avvisi = normalizza_velocita(
        config_voce.get("velocita", VELOCITA_DEFAULT), VELOCITA_DEFAULT
    )
    motore = str(impostazioni.get("tts_motore", "gemini")).strip().lower()
    fonte = "config"

    issue = sezione_voce(corpo_issue)
    voce_issue: str | None = None
    if issue:
        fonte = "issue"
        if "voce" in issue:
            voce_issue = issue["voce"]
        if "velocita" in issue:
            velocita, avvisi_velocita = normalizza_velocita(
                issue["velocita"], velocita
            )
            avvisi.extend(avvisi_velocita)
        if "motore" in issue:
            valore = issue["motore"].casefold()
            if valore in {"gemini", "edge", "google"}:
                motore = valore
            else:
                avvisi.append(
                    f"Motore issue '{issue['motore']}' non valido: uso {motore}."
                )

    # I flag CLI servono soprattutto per l'anteprima; hanno precedenza.
    if voce_cli:
        fonte = "cli"
    if velocita_cli is not None:
        velocita, avvisi_velocita = normalizza_velocita(
            velocita_cli, velocita
        )
        avvisi.extend(avvisi_velocita)
        fonte = "cli"
    if motore_cli:
        if motore_cli in {"gemini", "edge", "google"}:
            motore = motore_cli
            fonte = "cli"
        else:
            avvisi.append(f"Motore CLI '{motore_cli}' non valido: uso {motore}.")

    if motore == "google":
        google = config_voce.get("google", {})
        if not isinstance(google, dict):
            google = {}
        mappa = google.get("voci")
        if not isinstance(mappa, dict):
            mappa = {}
        richiesta = (voce_cli or voce_issue or nome or "Kore").strip()
        if richiesta.startswith("it-IT-"):
            nome = richiesta
            etichetta = str(google.get("label") or nome)
            genere = str(google.get("genere", ""))
        else:
            voce_scelta = _canonica(richiesta, voci)
            if not voce_scelta:
                voce_scelta = _canonica("Kore", voci) or {
                    "nome": "Kore",
                    "genere": "F",
                    "label": "Kore",
                }
                if richiesta.casefold() != "kore":
                    avvisi.append(
                        f"Voce '{richiesta}' non valida per Google: uso Kore."
                    )
            chiave = str(voce_scelta["nome"])
            cloud = str(
                mappa.get(chiave) or google.get("nome") or ""
            ).strip()
            if not cloud:
                cloud = "it-IT-Chirp3-HD-Kore"
                avvisi.append("Voce Google non configurata: uso Kore.")
            nome = cloud
            etichetta = str(voce_scelta.get("label") or chiave)
            if "Google" not in etichetta:
                etichetta = f"{etichetta} (Google Chirp 3 HD)"
            genere = str(voce_scelta.get("genere", ""))
        return VoceScelta(
            nome=nome,
            velocita=round(float(velocita), 2),
            motore=motore,
            etichetta=etichetta,
            genere=genere,
            avvisi=avvisi,
            fonte=fonte,
        )

    if voce_issue:
        trovata = _canonica(voce_issue, voci)
        if trovata:
            nome = str(trovata["nome"])
        else:
            avvisi.append(f"Voce issue '{voce_issue}' non valida: uso {nome}.")
    if voce_cli:
        trovata = _canonica(voce_cli, voci)
        if trovata:
            nome = str(trovata["nome"])
            fonte = "cli"
        else:
            avvisi.append(f"Voce CLI '{voce_cli}' non valida: uso {nome}.")

    voce_scelta = _canonica(nome, voci)
    if not voce_scelta:
        voce_scelta = _canonica("Kore", voci) or {
            "nome": "Kore",
            "genere": "F",
            "label": "Kore",
        }
        nome = str(voce_scelta["nome"])
        avvisi.append(f"Voce '{nome}' non disponibile: uso Kore.")
    etichetta = _etichetta(voce_scelta)
    genere = str(voce_scelta.get("genere", ""))

    if motore == "edge":
        edge = config_voce.get("edge", {})
        edge_nome = str(edge.get("nome", "it-IT-IsabellaNeural"))
        if nome != edge_nome:
            avvisi.append(
                f"Motore edge: la voce {nome} non è disponibile; uso {edge_nome}."
            )
        nome = edge_nome
        etichetta = f"{edge_nome} (edge-tts)"

    return VoceScelta(
        nome=nome,
        velocita=round(float(velocita), 2),
        motore=motore,
        etichetta=etichetta,
        genere=genere,
        avvisi=avvisi,
        fonte=fonte,
    )
