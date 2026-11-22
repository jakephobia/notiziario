from __future__ import annotations

import copy

from notiziario import modelli
from notiziario.config import carica_impostazioni


class Risposta:
    def __init__(self, status=200, dati=None):
        self.status_code = status
        self._dati = dati or {}

    def json(self):
        return self._dati


def test_elenca_modelli_e_candidati(monkeypatch):
    dati = {
        "models": [
            {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.1-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-flash-preview-tts", "supportedGenerationMethods": ["generateContent"]},
        ]
    }
    monkeypatch.setattr(modelli.requests, "get", lambda *a, **k: Risposta(200, dati))
    disponibili = modelli.elenca_modelli("chiave")
    testo, tts = modelli._candidati(disponibili, carica_impostazioni())
    assert "gemini-2.5-flash" in testo
    assert "gemini-2.5-flash-lite" in testo
    assert "gemini-3.1-flash-lite" in testo
    assert "gemini-2.5-flash-preview-tts" in tts


def test_test_modelli_una_chiamata_per_modello(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-test")
    disponibili = {
        "models": [
            {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.1-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-flash-preview-tts", "supportedGenerationMethods": ["generateContent"]},
        ]
    }
    monkeypatch.setattr(modelli.requests, "get", lambda *a, **k: Risposta(200, disponibili))
    chiamate = []

    def post(url, **kwargs):
        chiamate.append(url)
        if "tts" in url:
            return Risposta(200, {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16"}}]}}]})
        return Risposta(200, {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]})

    monkeypatch.setattr(modelli.requests, "post", post)
    monkeypatch.setattr(modelli.time, "sleep", lambda *_: None)
    assert modelli.test_modelli(carica_impostazioni()) == 0
    # Tre modelli testo disponibili + un modello TTS.
    assert len(chiamate) == 4
    assert len(set(chiamate)) == 4
    uscita = capsys.readouterr().out
    assert "gemini-2.5-flash" in uscita
    assert "TIPO" in uscita
