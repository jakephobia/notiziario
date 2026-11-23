from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from notiziario import tts as modulo_tts
from notiziario.audio import info_audio
from notiziario.config import carica_impostazioni


LOGGER = logging.getLogger("test-tts-edge")


def _mp3_tono(percorso: Path, secondi: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=24000:duration={secondi:.3f}",
            "-ar",
            "24000",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "48k",
            str(percorso),
        ],
        check=True,
    )


def _edge_con(monkeypatch, tmp_path, durata_blocco: float, sezioni):
    mp3 = tmp_path / "noto.mp3"
    _mp3_tono(mp3, durata_blocco)

    async def finto_salva(
        testo, voce, rate, pitch, percorso, tentativi, indice, logger
    ):
        percorso.write_bytes(mp3.read_bytes())

    monkeypatch.setattr(modulo_tts, "_salva_blocco", finto_salva)
    visti: list[Path] = []
    concatena_originale = modulo_tts.concatena_wav

    def spia_concatena(percorsi, uscita):
        visti.extend(Path(percorso) for percorso in percorsi)
        concatena_originale(percorsi, uscita)

    monkeypatch.setattr(modulo_tts, "concatena_wav", spia_concatena)
    uscita = tmp_path / "edge.mp3"
    info = modulo_tts._sintetizza_edge(
        sezioni,
        uscita,
        carica_impostazioni(),
        LOGGER,
        voce="it-IT-IsabellaNeural",
        velocita=1.0,
    )
    return info, visti


def test_edge_concatena_wav_con_durate_esatte(monkeypatch, tmp_path):
    sezioni = [("A.", 0.0), ("B.", 0.3), ("C.", 0.0)]
    info, visti = _edge_con(monkeypatch, tmp_path, 1.0, sezioni)

    assert info["motore"] == "edge"
    assert info["voce"] == "it-IT-IsabellaNeural"
    assert info["velocita"] == 1.0
    assert len(info["durate_sezioni"]) == 3
    assert all(
        abs(avuta - attesa) <= 0.02
        for avuta, attesa in zip(info["durate_sezioni"], [1.0, 1.3, 1.0])
    )
    atteso = 3.3 + 1.0
    assert abs(info["durata"] - atteso) <= 0.05
    assert info_audio(tmp_path / "edge.mp3")["codec"] == "mp3"
    # Il fix usa WAV intermedi, senza padding MP3 che falserebbe i confini.
    assert visti
    assert all(percorso.suffix.lower() == ".wav" for percorso in visti)


def test_edge_senza_pause_e_blocchi_corti(monkeypatch, tmp_path):
    sezioni = [("A.", 0.0), ("B.", 0.0), ("C.", 0.0)]
    info, _ = _edge_con(monkeypatch, tmp_path, 0.05, sezioni)

    assert len(info["durate_sezioni"]) == 3
    assert all(durata > 0 for durata in info["durate_sezioni"])
    atteso = sum(info["durate_sezioni"]) + 1.0
    assert abs(info["durata"] - atteso) <= 0.05
    assert info_audio(tmp_path / "edge.mp3")["codec"] == "mp3"


def test_edge_senza_sezioni_errore_chiaro(tmp_path):
    with pytest.raises(modulo_tts.TTSError, match="Nessun blocco"):
        modulo_tts._sintetizza_edge(
            [],
            tmp_path / "vuoto.mp3",
            carica_impostazioni(),
            LOGGER,
            voce="it-IT-IsabellaNeural",
            velocita=1.0,
        )
