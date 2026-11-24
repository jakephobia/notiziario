from __future__ import annotations

import base64
import io
import logging
import wave

import pytest

from notiziario import tts_google
from notiziario.audio import info_audio
from notiziario.config import carica_impostazioni
from notiziario.tts_google import (
    GoogleTTSError,
    _chiama_google_tts,
    sintetizza_sezioni_google,
)


LOGGER = logging.getLogger("test-tts-google")


def wav_secondi(secondi: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x10\x00" * int(24000 * secondi))
    return buffer.getvalue()


class Risposta:
    def __init__(self, audio: bytes | None, status_code: int = 200):
        self.status_code = status_code
        self._audio = audio

    def json(self):
        if self._audio is None:
            return {}
        return {
            "audioContent": base64.b64encode(self._audio).decode("ascii"),
        }


class Errore:
    def __init__(self, status_code: int, messaggio: str = "errore"):
        self.status_code = status_code
        self._messaggio = messaggio

    def json(self):
        return {"error": {"message": self._messaggio}}


def test_sintesi_google_produce_mp3(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_CLOUD_TTS_API_KEY", "chiave-test")
    catturato = {}

    def finto_post(url, json=None, headers=None, timeout=None):
        catturato["url"] = url
        catturato["headers"] = headers
        catturato["json"] = json
        return Risposta(wav_secondi(2.0))

    monkeypatch.setattr(tts_google.requests, "post", finto_post)
    uscita = tmp_path / "google.mp3"
    info = sintetizza_sezioni_google(
        [("Ciao Jacopo, questa Ã¨ una prova.", 0.0)],
        uscita,
        carica_impostazioni(),
        LOGGER,
    )
    assert uscita.exists()
    assert info["motore"] == "google"
    assert info["voce"] == "it-IT-Chirp3-HD-Kore"
    assert info["durata"] > 1
    assert info["chiamate"] == 1
    assert info["limite_chunk_usato"] == 3000
    assert len(info["durate_sezioni"]) == 1
    assert info_audio(uscita)["codec"] == "mp3"
    assert catturato["headers"]["X-Goog-Api-Key"] == "chiave-test"
    assert catturato["json"]["voice"]["name"] == "it-IT-Chirp3-HD-Kore"
    assert catturato["json"]["audioConfig"]["audioEncoding"] == "LINEAR16"
    assert "key" not in catturato["url"]


def test_chiave_mancante_solleva(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_CLOUD_TTS_API_KEY", raising=False)
    with pytest.raises(GoogleTTSError):
        sintetizza_sezioni_google(
            [("Ciao", 0.0)],
            tmp_path / "manca.mp3",
            carica_impostazioni(),
            LOGGER,
        )


def test_retry_429_poi_successo(monkeypatch):
    chiamate = {"n": 0}

    def finto_post(*args, **kwargs):
        chiamate["n"] += 1
        if chiamate["n"] < 3:
            return Errore(429, "quota exceeded")
        return Risposta(wav_secondi(0.5))

    monkeypatch.setattr(tts_google.requests, "post", finto_post)
    monkeypatch.setattr(tts_google.time, "sleep", lambda *_: None)
    audio = _chiama_google_tts(
        "Ciao", "it-IT-Chirp3-HD-Kore", carica_impostazioni(), "chiave", LOGGER
    )
    assert chiamate["n"] == 3
    assert audio[:4] == b"RIFF"


def test_risposta_senza_audio_content(monkeypatch):
    monkeypatch.setattr(
        tts_google.requests, "post", lambda *a, **k: Risposta(None)
    )
    with pytest.raises(GoogleTTSError) as exc:
        _chiama_google_tts(
            "Ciao", "voce", carica_impostazioni(), "chiave", LOGGER
        )
    assert "audioContent" in str(exc.value)

def test_dispatcher_google_usa_voce_google(monkeypatch, tmp_path):
    from notiziario import tts as modulo_tts

    catturato = {}

    def finto_google(sezioni, uscita, impostazioni, logger, voce=None, velocita=1.0):
        catturato["voce"] = voce
        uscita.write_bytes(b"ID3finto")
        return {
            "durata": 5.0,
            "dimensione": 8,
            "motore": "google",
            "voce": voce,
            "velocita": velocita,
            "motivo_fallback": None,
        }

    monkeypatch.setattr(modulo_tts, "sintetizza_sezioni_google", finto_google)
    info = modulo_tts.sintetizza_sezioni(
        [("Ciao", 0.0)],
        tmp_path / "google.mp3",
        carica_impostazioni(),
        logger=LOGGER,
        motore="google",
    )
    assert info["motore"] == "google"
    assert catturato["voce"] == "it-IT-Chirp3-HD-Kore"


def test_fallback_google_a_edge_non_usa_voce_google(monkeypatch, tmp_path):
    from notiziario import tts as modulo_tts

    def errore(*args, **kwargs):
        raise GoogleTTSError("HTTP 500: errore interno")

    catturato = {}

    def finto_edge(sezioni, uscita, impostazioni, logger, voce=None, velocita=1.1):
        catturato["voce"] = voce
        return {
            "durata": 5.0,
            "dimensione": 8,
            "motore": "edge",
            "voce": "it-IT-IsabellaNeural",
            "velocita": velocita,
            "motivo_fallback": None,
        }

    monkeypatch.setattr(modulo_tts, "sintetizza_sezioni_google", errore)
    monkeypatch.setattr(modulo_tts, "_sintetizza_edge", finto_edge)
    info = modulo_tts.sintetizza_sezioni(
        [("Ciao", 0.0)],
        tmp_path / "edge.mp3",
        carica_impostazioni(),
        logger=LOGGER,
        motore="google",
    )
    assert info["motore"] == "edge"
    assert "500" in info["motivo_fallback"]
    assert catturato["voce"] is None

