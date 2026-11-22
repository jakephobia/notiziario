from __future__ import annotations

import base64
import logging
import wave

import pytest

from notiziario import tts as modulo_tts
from notiziario import tts_gemini
from notiziario.audio import applica_atempo, info_audio
from notiziario.config import carica_impostazioni
from notiziario.tts_gemini import (
    GeminiTTSError,
    _chiama_gemini_tts,
    chunk_testo,
    sintetizza_sezioni_gemini,
)


LOGGER = logging.getLogger("test-tts-gemini")


def pcm_secondi(secondi: float) -> bytes:
    return b"\x10\x00" * int(24000 * secondi)


class Risposta:
    def __init__(self, pcm: bytes):
        self.status_code = 200
        self._pcm = pcm

    def json(self):
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": "audio/L16;codec=pcm;rate=24000",
                                    "data": base64.b64encode(self._pcm).decode("ascii"),
                                }
                            }
                        ]
                    }
                }
            ]
        }


def test_chunking_limite():
    testo = " ".join(["Questa è una frase di prova."] * 400)
    chunks = chunk_testo(testo, 300)
    assert len(chunks) > 1
    assert all(len(c) <= 300 for c in chunks)
    assert "".join(chunks).replace(" ", "") != ""


def test_header_x_goog_api_key(monkeypatch):
    catturato = {}

    def finto_post(url, json=None, headers=None, timeout=None):
        catturato["url"] = url
        catturato["headers"] = headers
        catturato["json"] = json
        return Risposta(pcm_secondi(0.5))

    monkeypatch.setattr(tts_gemini.requests, "post", finto_post)
    pcm, rate = _chiama_gemini_tts(
        "Ciao", "Kore", carica_impostazioni(), "chiave-test", LOGGER
    )
    assert rate == 24000
    assert len(pcm) == 24000
    assert catturato["headers"]["x-goog-api-key"] == "chiave-test"
    assert "key" not in catturato["url"]
    assert catturato["json"]["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert (
        catturato["json"]["generationConfig"]["speechConfig"]["voiceConfig"][
            "prebuiltVoiceConfig"
        ]["voiceName"]
        == "Kore"
    )


def test_sintesi_gemini_produce_mp3(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-test")
    monkeypatch.setattr(
        tts_gemini,
        "_chiama_gemini_tts",
        lambda *a, **k: (pcm_secondi(2.0), 24000),
    )
    uscita = tmp_path / "test.mp3"
    info = sintetizza_sezioni_gemini(
        [("Ciao Jacopo, questa è una prova.", 0.0)],
        uscita,
        carica_impostazioni(),
        LOGGER,
        voce="Kore",
        velocita=1.0,
    )
    assert uscita.exists()
    assert info["motore"] == "gemini"
    assert info["voce"] == "Kore"
    assert info["durata"] > 1
    assert info_audio(uscita)["codec"] == "mp3"


def test_atempo_non_tocca_le_pause(tmp_path):
    wav = tmp_path / "due.wav"
    with wave.open(str(wav), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(pcm_secondi(2.0))
    uscita = tmp_path / "veloce.wav"
    applica_atempo(wav, uscita, 1.2)
    durata = info_audio(uscita)["durata"]
    assert 1.5 < durata < 1.9


def test_fallback_su_errore_gemini(monkeypatch, tmp_path):
    def errore(*args, **kwargs):
        raise GeminiTTSError("HTTP 429: quota exceeded")

    def finto_edge(sezioni, uscita, impostazioni, logger, voce=None, velocita=1.1):
        uscita = uscita if hasattr(uscita, "parent") else tmp_path / "edge.mp3"
        uscita.parent.mkdir(parents=True, exist_ok=True)
        uscita.write_bytes(b"ID3finto")
        return {
            "durata": 10.0,
            "dimensione": 8,
            "codec": "mp3",
            "motore": "edge",
            "voce": "it-IT-IsabellaNeural",
            "velocita": velocita,
            "motivo_fallback": None,
        }

    monkeypatch.setattr(modulo_tts, "sintetizza_sezioni_gemini", errore)
    monkeypatch.setattr(modulo_tts, "_sintetizza_edge", finto_edge)
    info = modulo_tts.sintetizza_sezioni(
        [("Ciao", 0.0)],
        tmp_path / "edge.mp3",
        carica_impostazioni(),
        logger=LOGGER,
        voce="Kore",
        velocita=1.1,
        motore="gemini",
    )
    assert info["motore"] == "edge"
    assert "429" in info["motivo_fallback"]


def test_motore_edge_non_chiama_gemini(monkeypatch, tmp_path):
    chiamato = {"gemini": False}

    def errore(*args, **kwargs):
        chiamato["gemini"] = True
        raise AssertionError("non deve essere chiamato")

    monkeypatch.setattr(modulo_tts, "sintetizza_sezioni_gemini", errore)
    monkeypatch.setattr(
        modulo_tts,
        "_sintetizza_edge",
        lambda *a, **k: {
            "durata": 5.0,
            "dimensione": 8,
            "motore": "edge",
            "voce": "it-IT-IsabellaNeural",
            "velocita": 1.1,
            "motivo_fallback": None,
        },
    )
    info = modulo_tts.sintetizza_sezioni(
        [("Ciao", 0.0)],
        tmp_path / "edge.mp3",
        carica_impostazioni(),
        logger=LOGGER,
        motore="edge",
    )
    assert info["motore"] == "edge"
    assert chiamato["gemini"] is False


def test_backoff_429_due_retry_poi_successo(monkeypatch):
    chiamate = {"n": 0}

    class R429:
        status_code = 429

        def json(self):
            return {"error": {"message": "quota exceeded"}}

    class R200(Risposta):
        pass

    def finto_post(*args, **kwargs):
        chiamate["n"] += 1
        if chiamate["n"] < 3:
            return R429()
        return R200(pcm_secondi(0.5))

    monkeypatch.setattr(tts_gemini.requests, "post", finto_post)
    monkeypatch.setattr(tts_gemini.time, "sleep", lambda *_: None)
    pcm, rate = _chiama_gemini_tts(
        "Ciao", "Kore", carica_impostazioni(), "chiave-test", LOGGER
    )
    assert chiamate["n"] == 3
    assert len(pcm) == 24000


def test_backoff_429_persistente_errore_esatto(monkeypatch):
    chiamate = {"n": 0}

    class R429:
        status_code = 429

        def json(self):
            return {"error": {"message": "quota exceeded"}}

    def finto_post(*args, **kwargs):
        chiamate["n"] += 1
        return R429()

    monkeypatch.setattr(tts_gemini.requests, "post", finto_post)
    monkeypatch.setattr(tts_gemini.time, "sleep", lambda *_: None)
    with pytest.raises(GeminiTTSError) as exc:
        _chiama_gemini_tts(
            "Ciao", "Kore", carica_impostazioni(), "chiave-test", LOGGER
        )
    assert chiamate["n"] == 3
    assert "429" in str(exc.value)
    assert "quota exceeded" in str(exc.value)


def test_chunk_400_ridotto_automaticamente(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-test")
    monkeypatch.setattr(tts_gemini.time, "sleep", lambda *_: None)
    chiamate = {"n": 0}

    def finto_chiama(testo, *args, **kwargs):
        chiamate["n"] += 1
        if len(testo) > 1000:
            raise GeminiTTSError("HTTP 400: input too long")
        return pcm_secondi(1.0), 24000

    monkeypatch.setattr(tts_gemini, "_chiama_gemini_tts", finto_chiama)
    testo = ("Parola " * 300).strip()
    info = sintetizza_sezioni_gemini(
        [(testo, 0.0)],
        tmp_path / "adattivo.mp3",
        carica_impostazioni(),
        LOGGER,
        voce="Kore",
        velocita=1.1,
    )
    assert info["limite_chunk_usato"] <= 1000
    assert chiamate["n"] >= 3
    assert info["durata"] > 1
