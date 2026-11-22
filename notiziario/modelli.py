"""Diagnostica modelli Gemini disponibili e quota, con chiamate minime."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

from .copione import _redigi


BASE = "https://generativelanguage.googleapis.com/v1beta"


def _headers(chiave: str) -> dict[str, str]:
    return {
        "x-goog-api-key": chiave,
        "Content-Type": "application/json",
        "User-Agent": "Notiziario/0.4",
    }


def elenca_modelli(chiave: str, timeout: int = 30) -> dict[str, list[str]]:
    risposta = requests.get(
        f"{BASE}/models",
        headers=_headers(chiave),
        params={"pageSize": 1000},
        timeout=timeout,
    )
    if risposta.status_code >= 400:
        raise RuntimeError(f"HTTP {risposta.status_code} su models.list")
    dati = risposta.json()
    modelli: dict[str, list[str]] = {}
    for voce in dati.get("models", []) or []:
        nome = str(voce.get("name", "")).removeprefix("models/")
        if nome:
            modelli[nome] = list(voce.get("supportedGenerationMethods") or [])
    return modelli


def _candidati(
    disponibili: dict[str, list[str]], impostazioni: dict[str, Any]
) -> tuple[list[str], list[str]]:
    primario = str(impostazioni["llm"]["modello"])
    riserva = str(impostazioni.get("llm_modello_riserva", "")).strip()
    testo_preferiti = [
        primario,
        riserva,
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite",
    ]
    testo: list[str] = []
    for nome in testo_preferiti:
        if nome and nome not in testo:
            testo.append(nome)
    testo = testo[:4]
    tts_preferiti = [
        "gemini-2.5-flash-preview-tts",
        "gemini-2.5-pro-preview-tts",
        "gemini-2.5-flash-tts",
    ]
    tts = [n for n in tts_preferiti if n in disponibili][:3]
    if not tts:
        tts = [n for n in disponibili if "tts" in n.lower()][:3]
    return testo, tts


def _prova_testo(
    modello: str, chiave: str, timeout: int
) -> tuple[int | None, float, str]:
    inizio = time.perf_counter()
    try:
        risposta = requests.post(
            f"{BASE}/models/{modello}:generateContent",
            headers=_headers(chiave),
            json={
                "contents": [{"parts": [{"text": "Rispondi solo con OK."}]}],
                "generationConfig": {"maxOutputTokens": 16, "temperature": 0},
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return None, time.perf_counter() - inizio, f"rete: {type(exc).__name__}"
    latenza = time.perf_counter() - inizio
    dettaglio = ""
    try:
        corpo = risposta.json()
        if risposta.status_code >= 400:
            dettaglio = str(corpo.get("error", {}).get("message", ""))
        else:
            candidates = corpo.get("candidates") or []
            if candidates:
                parti = candidates[0].get("content", {}).get("parts", [])
                dettaglio = "".join(
                    str(p.get("text", "")) for p in parti if isinstance(p, dict)
                )[:80]
            else:
                dettaglio = "risposta senza candidati"
    except ValueError:
        dettaglio = "risposta non JSON"
    return risposta.status_code, latenza, _redigi(dettaglio)


def _prova_tts(
    modello: str, chiave: str, timeout: int
) -> tuple[int | None, float, str]:
    inizio = time.perf_counter()
    try:
        risposta = requests.post(
            f"{BASE}/models/{modello}:generateContent",
            headers=_headers(chiave),
            json={
                "contents": [{"parts": [{"text": "Ciao."}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {"voiceName": "Kore"}
                        }
                    },
                },
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return None, time.perf_counter() - inizio, f"rete: {type(exc).__name__}"
    latenza = time.perf_counter() - inizio
    dettaglio = ""
    try:
        corpo = risposta.json()
        if risposta.status_code >= 400:
            dettaglio = str(corpo.get("error", {}).get("message", ""))
        else:
            candidates = corpo.get("candidates") or []
            inline = (
                candidates[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("inlineData")
                if candidates
                else None
            )
            dettaglio = (
                f"audio {inline.get('mimeType')}"
                if inline
                else "risposta senza audio"
            )
    except ValueError:
        dettaglio = "risposta non JSON"
    return risposta.status_code, latenza, _redigi(dettaglio)


def test_modelli(
    impostazioni: dict[str, Any], logger: logging.Logger | None = None
) -> int:
    logger = logger or logging.getLogger("notiziario")
    chiave = os.environ.get("GEMINI_API_KEY", "").strip()
    if not chiave:
        print("GEMINI_API_KEY non impostata.")
        return 1
    timeout = int(impostazioni.get("llm", {}).get("timeout", 60))
    pausa = float(impostazioni.get("tts", {}).get("pausa_chiamate", 3.0))
    try:
        disponibili = elenca_modelli(chiave, timeout)
    except Exception as exc:
        print(f"models.list non riuscito: {_redigi(exc)}")
        return 1

    print(f"Modelli disponibili: {len(disponibili)}")
    testo, tts = _candidati(disponibili, impostazioni)
    righe: list[tuple[str, str, str, str, str]] = []
    for modello in testo:
        if modello not in disponibili:
            righe.append(("testo", modello, "non disponibile", "-", "assente da models.list"))
            continue
        stato, latenza, dettaglio = _prova_testo(modello, chiave, timeout)
        esito = "ok" if stato == 200 else (f"HTTP {stato}" if stato else "errore")
        righe.append(("testo", modello, esito, f"{latenza:.2f}s", dettaglio))
        if pausa > 0:
            time.sleep(pausa)
    for modello in tts:
        stato, latenza, dettaglio = _prova_tts(modello, chiave, timeout)
        esito = "ok" if stato == 200 else (f"HTTP {stato}" if stato else "errore")
        righe.append(("tts", modello, esito, f"{latenza:.2f}s", dettaglio))
        if pausa > 0:
            time.sleep(pausa)

    print(f"\n{'TIPO':6} {'MODELLO':34} {'ESITO':16} {'LATENZA':9} DETTAGLIO")
    for tipo, modello, esito, latenza, dettaglio in righe:
        print(f"{tipo:6} {modello[:34]:34} {esito:16} {latenza:9} {dettaglio[:90]}")
    return 0
