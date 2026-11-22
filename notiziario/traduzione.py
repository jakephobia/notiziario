"""Pre-traduzione delle notizie selezionate verso l'italiano."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from typing import Any

from .copione import _chiama_gemini, _contiene_stopword_inglese, _estrai_json
from .selezione import NotiziaSelezionata


LIMITE_BATCH = 18_000
LIMITE_TESTO_NOTIZIA = 2_500


class TraduzioneError(Exception):
    """La pre-traduzione non è disponibile e restano troppe poche notizie italiane."""


def _testo_notizia(selezione: NotiziaSelezionata) -> str:
    pezzi = [selezione.cluster.titolo]
    for articolo in selezione.cluster.ordina_articoli()[:3]:
        testo = articolo.contenuto or articolo.sommario or ""
        if testo:
            pezzi.append(testo)
    return "\n".join(pezzi)[:LIMITE_TESTO_NOTIZIA]


def _non_italiana(selezione: NotiziaSelezionata) -> bool:
    testo = selezione.titolo + "\n" + (
        selezione.testo_tradotto or _testo_notizia(selezione)
    )
    return _contiene_stopword_inglese(testo)


def _payload_traduzione(
    selezioni: list[NotiziaSelezionata],
) -> tuple[list[dict[str, Any]], list[int]]:
    elementi: list[dict[str, Any]] = []
    ids: list[int] = []
    totale = 0
    for selezione in selezioni:
        if not _non_italiana(selezione):
            continue
        testo = _testo_notizia(selezione)
        elemento = {
            "id": selezione.ordine,
            "titolo": selezione.cluster.titolo,
            "testo": testo,
        }
        lunghezza = len(json.dumps(elemento, ensure_ascii=False))
        if elementi and totale + lunghezza > LIMITE_BATCH:
            break
        elementi.append(elemento)
        ids.append(selezione.ordine)
        totale += lunghezza
    return elementi, ids


def _traduzioni_da_risposta(risposta: str) -> dict[int, tuple[str, str]]:
    pulita = (risposta or "").strip().removeprefix("```json").removeprefix("```")
    pulita = pulita.removesuffix("```").strip()
    if pulita.startswith("["):
        dati = json.loads(pulita)
    else:
        dati = _estrai_json(risposta)
    if isinstance(dati, dict):
        dati = dati.get("traduzioni") or dati.get("notizie") or []
    if not isinstance(dati, list):
        return {}
    risultato: dict[int, tuple[str, str]] = {}
    for voce in dati:
        if not isinstance(voce, dict):
            continue
        try:
            identificativo = int(voce.get("id"))
        except (TypeError, ValueError):
            continue
        titolo = str(voce.get("titolo_it") or voce.get("titolo") or "").strip()
        testo = str(voce.get("testo_it") or voce.get("testo") or "").strip()
        if not titolo or not testo:
            continue
        if _contiene_stopword_inglese(titolo + " " + testo):
            continue
        risultato[identificativo] = (titolo, testo)
    return risultato


def traduci_selezioni(
    selezioni: list[NotiziaSelezionata],
    impostazioni: dict[str, Any],
    logger: logging.Logger | None = None,
) -> tuple[list[NotiziaSelezionata], bool, list[str]]:
    """Traduce in blocco le notizie non italiane; non solleva se Gemini fallisce."""
    logger = logger or logging.getLogger("notiziario")
    avvisi: list[str] = []
    elementi, _ = _payload_traduzione(selezioni)
    if not elementi:
        return selezioni, True, avvisi
    chiave = os.environ.get("GEMINI_API_KEY", "").strip()
    if not chiave:
        return selezioni, False, ["GEMINI_API_KEY assente: filtro le notizie non italiane."]

    prompt = (
        "Traduci in italiano titolo e testo delle notizie seguenti. "
        "Rispondi SOLO con un oggetto JSON con la chiave 'traduzioni', "
        "una lista di oggetti {id, titolo_it, testo_it}. "
        "Mantieni lo stesso id, non inventare fatti, non copiare testo inglese. "
        "Titoli e testi devono essere interamente in italiano.\n"
        + json.dumps(elementi, ensure_ascii=False, indent=2)
    )
    sistema = (
        "Sei un traduttore editoriale italiano. Rispondi solo con JSON valido, "
        "senza markdown e senza testo fuori dal JSON."
    )
    mappa: dict[int, tuple[str, str]] = {}
    for tentativo in (1, 2):
        try:
            risposta = _chiama_gemini(
                prompt,
                sistema,
                impostazioni,
                chiave,
                logger,
            )
            mappa = _traduzioni_da_risposta(risposta)
            if mappa:
                break
        except Exception as exc:
            logger.warning(
                "Pre-traduzione tentativo %d non riuscito: %s.",
                tentativo,
                type(exc).__name__,
            )
    if not mappa:
        avvisi.append("Pre-traduzione non disponibile: filtro le notizie non italiane.")
        return selezioni, False, avvisi

    tradotte: list[NotiziaSelezionata] = []
    for selezione in selezioni:
        if selezione.ordine in mappa:
            titolo, testo = mappa[selezione.ordine]
            tradotte.append(
                replace(
                    selezione,
                    titolo_tradotto=titolo,
                    testo_tradotto=testo,
                )
            )
        else:
            tradotte.append(selezione)
    return tradotte, True, avvisi


def prepara_selezioni_italiane(
    selezioni: list[NotiziaSelezionata],
    impostazioni: dict[str, Any],
    logger: logging.Logger | None = None,
) -> tuple[list[NotiziaSelezionata], list[str]]:
    """Traduce se possibile, poi tiene solo notizie italiane; minimo 3."""
    logger = logger or logging.getLogger("notiziario")
    tradotte, disponibile, avvisi = traduci_selezioni(selezioni, impostazioni, logger)
    italiane: list[NotiziaSelezionata] = []
    for selezione in tradotte:
        if selezione.titolo_tradotto and selezione.testo_tradotto:
            italiane.append(selezione)
        elif not _non_italiana(selezione):
            italiane.append(selezione)
    if len(italiane) < 3:
        raise TraduzioneError(
            "Non riesco a produrre un copione italiano: "
            f"restano {len(italiane)} notizie italiane su {len(selezioni)}. "
            "Serve la chiave Gemini/quota per tradurre le altre."
        )
    risultato: list[NotiziaSelezionata] = []
    for indice, selezione in enumerate(italiane, start=1):
        risultato.append(
            selezione if selezione.ordine == indice else replace(selezione, ordine=indice)
        )
    logger.info(
        "Notizie per il copione: %d italiane su %d selezionate "
        "(pre-traduzione %s).",
        len(risultato),
        len(selezioni),
        "disponibile" if disponibile else "non disponibile",
    )
    return risultato, avvisi
