"""Lettura/scrittura YAML delle fonti e merge per l'import."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .config import Fonte
from .fetch import normalizza_url


def salva_fonti(percorso: str | Path, fonti: Iterable[Fonte]) -> None:
    """API stabile per salvare le fonti (delega a scrivi_fonti_yaml)."""
    scrivi_fonti_yaml(percorso, fonti)


def scrivi_fonti_yaml(percorso: str | Path, fonti: Iterable[Fonte]) -> None:
    """Scrive un YAML leggibile. I commenti vengono rigenerati."""
    path = Path(percorso)
    path.parent.mkdir(parents=True, exist_ok=True)
    righe = [
        "# Fonti RSS del Notiziario.",
        "# Campi: nome, url, categoria, attivo, controllo, ultimo_controllo, note.",
        "# Categorie valide: italia, mondo, economia, tecnologia, scienza-salute,",
        "# cultura, sport, ambiente, buone-notizie. 'da-assegnare' esclude la fonte.",
        "# Dopo una modifica: python -m notiziario.verifica_fonti",
        "",
        "fonti:",
    ]
    for fonte in fonti:
        righe.append(f"  - nome: {json.dumps(fonte.nome, ensure_ascii=False)}")
        righe.append(f"    url: {json.dumps(fonte.url, ensure_ascii=False)}")
        righe.append(
            f"    categoria: {json.dumps(fonte.categoria, ensure_ascii=False)}"
        )
        if not fonte.attivo:
            righe.append("    attivo: false")
        if fonte.controllo:
            righe.append(
                f"    controllo: {json.dumps(fonte.controllo, ensure_ascii=False)}"
            )
        if fonte.ultimo_controllo:
            righe.append(
                "    ultimo_controllo: "
                + json.dumps(fonte.ultimo_controllo, ensure_ascii=False)
            )
        if fonte.note:
            righe.append(f"    note: {json.dumps(fonte.note, ensure_ascii=False)}")
        righe.append("")
    path.write_text("\n".join(righe).rstrip() + "\n", encoding="utf-8", newline="\n")


def merge_fonti(
    esistenti: list[Fonte], nuove: list[Fonte]
) -> tuple[list[Fonte], list[Fonte]]:
    """Aggiunge le nuove senza duplicare URL; le esistenti non vengono toccate."""
    visti = {normalizza_url(f.url) for f in esistenti}
    merged = list(esistenti)
    duplicate: list[Fonte] = []
    for fonte in nuove:
        chiave = normalizza_url(fonte.url)
        if chiave in visti:
            duplicate.append(fonte)
            continue
        visti.add(chiave)
        merged.append(fonte)
    return merged, duplicate


def sostituisci_fonte(fonti: list[Fonte], url: str, **campi) -> list[Fonte]:
    risultato = []
    for fonte in fonti:
        if normalizza_url(fonte.url) == normalizza_url(url):
            risultato.append(replace(fonte, **campi))
        else:
            risultato.append(fonte)
    return risultato
