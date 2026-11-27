from __future__ import annotations

import copy

import pytest

from notiziario import modelli
from notiziario.config import carica_impostazioni


class Risposta:
    def __init__(self, status=200, dati=None):
        self.status_code = status
        self._dati = dati or {}

    def json(self):
        return self._dati


def _disponibili() -> dict:
    return {
        "models": [
            {"name": "models/gemini-3.1-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-flash-preview-tts", "supportedGenerationMethods": ["generateContent"]},
        ]
    }


def test_candidati_testo_sono_la_catena_configurata(monkeypatch):
    monkeypatch.setattr(modelli.requests, "get", lambda *a, **k: Risposta(200, _disponibili()))
    disponibili = modelli.elenca_modelli("chiave")
    testo, tts = modelli._candidati(disponibili, carica_impostazioni())
    assert testo == [
        "gemini-3.1-flash-lite",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3-flash",
    ]
    assert "gemini-2.5-flash" not in testo
    # Con Chirp 3 HD (motore google) i TTS Gemini non vanno testati.
    assert tts == []

    impostazioni = copy.deepcopy(carica_impostazioni())
    impostazioni["tts_motore"] = "gemini"
    testo, tts = modelli._candidati(disponibili, impostazioni)
    assert "gemini-2.5-flash-preview-tts" in tts


def test_test_modelli_google_non_prova_tts(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-test")
    monkeypatch.setattr(modelli.requests, "get", lambda *a, **k: Risposta(200, _disponibili()))
    testo_chiamati: list[str] = []

    def finto_testo(modello, chiave, timeout):
        testo_chiamati.append(modello)
        return 200, 0.01, "OK"

    def finto_tts(*args, **kwargs):
        pytest.fail("TTS Gemini non deve essere testato con motore google")

    monkeypatch.setattr(modelli, "_prova_testo", finto_testo)
    monkeypatch.setattr(modelli, "_prova_tts", finto_tts)
    monkeypatch.setattr(modelli.time, "sleep", lambda *_: None)

    assert modelli.test_modelli(carica_impostazioni()) == 0
    assert testo_chiamati == [
        "gemini-3.1-flash-lite",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3-flash",
    ]
    uscita = capsys.readouterr().out
    assert "TTS Gemini non testato: motore google" in uscita
    assert "TIPO" in uscita


def test_test_modelli_gemini_prova_tts(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-test")
    monkeypatch.setattr(modelli.requests, "get", lambda *a, **k: Risposta(200, _disponibili()))
    testo_chiamati: list[str] = []
    tts_chiamati: list[str] = []

    def finto_testo(modello, chiave, timeout):
        testo_chiamati.append(modello)
        return 200, 0.01, "OK"

    def finto_tts(modello, chiave, timeout):
        tts_chiamati.append(modello)
        return 200, 0.01, "audio audio/L16"

    monkeypatch.setattr(modelli, "_prova_testo", finto_testo)
    monkeypatch.setattr(modelli, "_prova_tts", finto_tts)
    monkeypatch.setattr(modelli.time, "sleep", lambda *_: None)

    impostazioni = copy.deepcopy(carica_impostazioni())
    impostazioni["tts_motore"] = "gemini"
    assert modelli.test_modelli(impostazioni) == 0
    assert len(testo_chiamati) == 4
    assert tts_chiamati == ["gemini-2.5-flash-preview-tts"]
