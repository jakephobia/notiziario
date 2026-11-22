"""Controllo di stile del copione: avvisi, mai blocchi."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import Counter
from pathlib import Path

from .testi import conta_parole, estrai_frasi


PATTERN_VIETATI: tuple[str, ...] = (
    "in un mondo in cui",
    "non solo",
    "ma anche",
    "è importante sottolineare",
    "in conclusione",
    "ecco cosa",
    "nel panorama",
    "un mix di",
    "questo evidenzia",
    "in questo contesto",
    "al giorno d'oggi",
    "al giorno d’oggi",
    "senza dubbio",
    "in sostanza",
)

MAX_PAROLE_FRASE = 35

_SOSTITUZIONI_SLOP: tuple[tuple[str, str], ...] = (
    (r"\bin un mondo in cui\b", "mentre"),
    (r"\bnon solo\b", ""),
    (r"\bma anche\b", "e"),
    (r"\bè importante sottolineare che\b", "va detto che"),
    (r"\bè importante sottolineare\b", "va detto"),
    (r"\bin conclusione\b", "per chiudere"),
    (r"\becco cosa\b", "questo è"),
    (r"\bnel panorama\b", "nel settore"),
    (r"\bun mix di\b", "una combinazione di"),
    (r"\bquesto evidenzia\b", "questo mostra"),
    (r"\bin questo contesto\b", "qui"),
    (r"\bal giorno d['’]oggi\b", "oggi"),
    (r"\bsenza dubbio\b", "certamente"),
    (r"\bin sostanza\b", "in breve"),
)


def semplifica_slop(testo: str) -> str:
    """Sostituisce le formule più vietate senza cambiare i fatti."""
    risultato = testo or ""
    for schema, sostituto in _SOSTITUZIONI_SLOP:
        risultato = re.sub(schema, sostituto, risultato, flags=re.IGNORECASE)
    risultato = re.sub(r"[ \t]+", " ", risultato)
    risultato = re.sub(r"\s+([,.;:!?])", r"\1", risultato)
    risultato = re.sub(r"([,.;:!?])(?=[A-Za-zÀ-ÖØ-öø-ÿ])", r"\1 ", risultato)
    risultato = re.sub(r"\.{2,}", ".", risultato)
    risultato = re.sub(
        r"(^|[.!?]\s+)([a-zà-öø-ÿ])",
        lambda m: m.group(1) + m.group(2).upper(),
        risultato,
    )
    return risultato.strip()


def _normalizza_frase(frase: str) -> str:
    return re.sub(r"\s+", " ", frase.casefold()).strip(" .,;:!?\"'")


def analizza(testo: str) -> list[str]:
    """Restituisce un elenco di avvisi leggibili; lista vuota = nessun problema."""
    testo = testo or ""
    avvisi: list[str] = []
    basso = testo.casefold()

    for pattern in PATTERN_VIETATI:
        quante = basso.count(pattern.casefold())
        if quante:
            avvisi.append(
                f'Espressione da evitare: "{pattern}" (trovata {quante} volta/e).'
            )

    frasi = estrai_frasi(testo)
    for frase in frasi:
        parole = conta_parole(frase)
        if parole > MAX_PAROLE_FRASE:
            inizio = frase[:70].rstrip()
            avvisi.append(f"Frase troppo lunga ({parole} parole): {inizio}...")

    if "(" in testo or ")" in testo:
        avvisi.append("Il copione contiene parentesi: meglio una pausa o una frase.")
    if re.search(r"[*_#`]", testo):
        avvisi.append("Il copione contiene markdown (*, _, # o backtick).")
    if re.search(r"^\s*[-–—•]\s+", testo, re.MULTILINE):
        avvisi.append("Il copione contiene un elenco puntato.")
    if re.search(r"<[^>]+>", testo):
        avvisi.append("Il copione contiene tag HTML.")
    if re.search(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", testo):
        avvisi.append("Il copione contiene emoji o simboli grafici.")

    # Attacchi di frase ripetuti.
    attacchi = []
    for frase in frasi:
        parole = re.findall(r"[\wÀ-ÖØ-öø-ÿ]+", frase)
        if parole:
            attacchi.append(parole[0].casefold())
    if len(frasi) >= 5:
        conteggi = Counter(attacchi)
        parola, quante = conteggi.most_common(1)[0]
        soglia = max(4, int(len(frasi) * 0.3))
        if quante >= soglia:
            avvisi.append(
                f'Ripetizione di attacco frase: "{parola}" apre {quante} frasi '
                f"su {len(frasi)}."
            )

    # Frasi intere ripetute.
    normalizzate = [_normalizza_frase(f) for f in frasi if len(f.split()) >= 5]
    for frase, quante in Counter(normalizzate).items():
        if frase and quante > 1:
            avvisi.append(f"Frase ripetuta {quante} volte: {frase[:70]}...")

    return avvisi


def registra_avvisi(
    testo: str, logger: logging.Logger | None = None
) -> list[str]:
    logger = logger or logging.getLogger("notiziario")
    avvisi = analizza(testo)
    if not avvisi:
        logger.info("Stile: nessun avviso.")
        return []
    for avviso in avvisi:
        logger.warning("Stile: %s", avviso)
    return avvisi


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Controlla lo stile di uno o più copioni del Notiziario."
    )
    parser.add_argument("file", nargs="+", help="Percorso del copione .txt o .md")
    args = parser.parse_args(argv)

    codice = 0
    for nome in args.file:
        percorso = Path(nome)
        if not percorso.exists():
            print(f"File non trovato: {percorso}", file=sys.stderr)
            codice = 2
            continue
        testo = percorso.read_text(encoding="utf-8")
        avvisi = analizza(testo)
        print(f"\n{percorso}: {len(avvisi)} avviso/i")
        if not avvisi:
            print("  Nessun avviso di stile.")
        for avviso in avvisi:
            print(f"  - {avviso}")
    return codice


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
