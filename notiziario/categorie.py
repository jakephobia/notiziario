"""Categorie fisse e lettura delle checkbox da una issue GitHub."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class Categoria:
    id: str
    label: str


CATEGORIE: tuple[Categoria, ...] = (
    Categoria("italia", "Italia"),
    Categoria("mondo", "Mondo"),
    Categoria("economia", "Economia"),
    Categoria("tecnologia", "Tecnologia"),
    Categoria("scienza-salute", "Scienza e salute"),
    Categoria("cultura", "Cultura"),
    Categoria("sport", "Sport"),
    Categoria("ambiente", "Ambiente"),
    Categoria("buone-notizie", "Buone notizie"),
)

CATEGORIE_IDS: tuple[str, ...] = tuple(c.id for c in CATEGORIE)
CATEGORIE_PER_ID: dict[str, Categoria] = {c.id: c for c in CATEGORIE}
CATEGORIA_DA_ASSEGNARE = "da-assegnare"


class CategorieError(Exception):
    """Errore non bloccante nella lettura della issue delle categorie."""


def label_categoria(categoria_id: str) -> str:
    categoria = CATEGORIE_PER_ID.get(categoria_id)
    return categoria.label if categoria else categoria_id


def normalizza_testo(testo: str) -> str:
    """Minuscole, senza accenti, solo lettere/numeri separati da spazi."""
    testo = unicodedata.normalize("NFKD", testo or "")
    testo = "".join(ch for ch in testo if not unicodedata.combining(ch))
    testo = testo.casefold()
    testo = re.sub(r"[^a-z0-9]+", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()


def trova_categoria(testo: str) -> str | None:
    """Riconosce id o etichetta di una categoria dentro una riga, senza ambiguità."""
    normale = normalizza_testo(testo)
    if not normale:
        return None
    trovati: list[tuple[int, str]] = []
    imbottito = f" {normale} "
    for categoria in CATEGORIE:
        for chiave in (categoria.id, categoria.label):
            chiave_norm = normalizza_testo(chiave)
            posizione = imbottito.find(f" {chiave_norm} ")
            if posizione >= 0:
                trovati.append((posizione, categoria.id))
    if not trovati:
        return None
    trovati.sort()
    return trovati[0][1]


_RIGA_CHECKBOX = re.compile(
    r"^\s*[-*+]\s*\[\s*([xX ])\s*\]\s*(.+?)\s*$", re.MULTILINE
)


def _pulisci_riga(testo: str) -> str:
    testo = re.sub(r"[*_`~]+", "", testo)
    testo = re.sub(r"^\s*#+\s*", "", testo)
    return testo.strip()


def parse_issue_body(
    corpo: str | None, categorie_default: list[str]
) -> tuple[list[str], list[str]]:
    """Legge le checkbox della issue.

    Regole:
    - ``- [x] italia`` attiva la categoria;
    - ``- [ ] italia`` la disattiva;
    - una categoria non citata mantiene il default;
    - il match è case-insensitive e accetta id oppure etichetta.

    Restituisce (categorie_attive_in_ordine, avvisi).
    """
    default = [c for c in CATEGORIE_IDS if c in set(categorie_default)]
    if not default:
        default = [c.id for c in CATEGORIE if c.id != "sport"]

    avvisi: list[str] = []
    if not corpo or not corpo.strip():
        avvisi.append(
            "Issue categorie vuota o non disponibile: uso le categorie predefinite."
        )
        return default, avvisi

    sezione = re.search(
        r"(?ims)^##\s*Categorie\b[^\n]*\n(.*?)(?=^##\s|\Z)", corpo
    )
    if sezione is None:
        avvisi.append(
            "Sezione '## Categorie' assente: uso le categorie predefinite."
        )
        return default, avvisi
    contenuto = sezione.group(1)

    menzioni: dict[str, list[bool]] = {c.id: [] for c in CATEGORIE}
    righe_trovate = 0
    for match in _RIGA_CHECKBOX.finditer(contenuto):
        righe_trovate += 1
        selezionata = match.group(1).lower() == "x"
        testo = _pulisci_riga(match.group(2))
        categoria_id = trova_categoria(testo)
        if categoria_id is None:
            if selezionata:
                avvisi.append(
                    f"Riga della issue non riconosciuta come categoria: {testo!r}"
                )
            continue
        menzioni[categoria_id].append(selezionata)

    if righe_trovate == 0:
        avvisi.append(
            "Nessuna checkbox trovata nella issue: uso le categorie predefinite."
        )
        return default, avvisi

    attive: list[str] = []
    for categoria in CATEGORIE:
        valori = menzioni[categoria.id]
        if not valori:
            if categoria.id in default:
                attive.append(categoria.id)
            continue
        if all(valori) or any(valori):
            attive.append(categoria.id)
            if any(valori) and not all(valori):
                avvisi.append(
                    f"La issue indica {categoria.label} sia selezionata sia no; "
                    "la considero attiva."
                )
    return attive, avvisi


def leggi_issue(
    token: str, repository: str, numero: int, timeout: int = 15
) -> str:
    """Scarica il corpo di una issue GitHub. Non logga mai il token."""
    if not token:
        raise CategorieError("GITHUB_TOKEN assente: non posso leggere la issue.")
    if not repository or "/" not in repository:
        raise CategorieError("GITHUB_REPOSITORY assente o non valido.")
    url = f"https://api.github.com/repos/{repository}/issues/{numero}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Notiziario/0.1",
    }
    try:
        risposta = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise CategorieError(
            f"Errore di rete leggendo la issue {numero}: {type(exc).__name__}"
        ) from exc
    if risposta.status_code == 404:
        raise CategorieError(
            f"Issue {numero} non trovata in {repository}. Controlla il numero."
        )
    if risposta.status_code == 401:
        raise CategorieError(
            "GitHub ha rifiutato il token leggendo la issue (401). "
            "Controlla i permessi issues: read."
        )
    if risposta.status_code >= 400:
        raise CategorieError(
            f"GitHub ha risposto {risposta.status_code} leggendo la issue {numero}."
        )
    try:
        dati = risposta.json()
    except ValueError as exc:
        raise CategorieError("Risposta GitHub non JSON leggendo la issue.") from exc
    return str(dati.get("body") or "")
