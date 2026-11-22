from __future__ import annotations

import wave
from pathlib import Path

from notiziario.audio import (
    info_audio,
    masterizza,
    verifica_silenzio_iniziale,
)
from notiziario.config import carica_impostazioni


def _tono_wav(percorso: Path, secondi: float = 2.0) -> None:
    with wave.open(str(percorso), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x10\x00" * int(24000 * secondi))


def test_mastering_aggiunge_un_secondo_di_silenzio(tmp_path):
    ingresso = tmp_path / "tono.wav"
    _tono_wav(ingresso, 2.0)
    uscita = tmp_path / "tono.mp3"
    masterizza(ingresso, uscita, carica_impostazioni())
    info = info_audio(uscita)
    assert 2.9 <= info["durata"] <= 3.2
    silenzioso, massimo, _ = verifica_silenzio_iniziale(uscita)
    assert silenzioso is True
    assert massimo is not None and massimo <= -60


def test_mastering_blocca_silenzio_non_valido(monkeypatch, tmp_path):
    from notiziario import audio

    ingresso = tmp_path / "tono.wav"
    _tono_wav(ingresso, 1.0)
    monkeypatch.setattr(
        audio,
        "verifica_silenzio_iniziale",
        lambda *a, **k: (False, -20.0, "finto"),
    )
    with __import__("pytest").raises(audio.AudioError):
        audio.masterizza(ingresso, tmp_path / "uscita.mp3", carica_impostazioni())
