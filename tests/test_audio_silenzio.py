from __future__ import annotations

import math
import struct
import subprocess
import wave
from pathlib import Path

from notiziario.audio import (
    _punto_in_silenzio,
    aggiungi_musica_sottofondo,
    concatena_wav,
    genera_silenzio_wav,
    info_audio,
    inserisci_suoni,
    masterizza,
    rileva_silenzi,
    verifica_silenzio_iniziale,
)
from notiziario.config import carica_impostazioni


def _tono_wav(percorso: Path, secondi: float = 2.0) -> None:
    with wave.open(str(percorso), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x10\x00" * int(24000 * secondi))


def _voce_sintetica(
    percorso: Path,
    parti: list[tuple[str, float]],
    rate: int = 24000,
) -> None:
    """WAV mono con parti ``("tono", secondi)`` e ``("silenzio", secondi)``."""
    frames = bytearray()
    fase = 0
    for tipo, secondi in parti:
        campioni = int(round(rate * secondi))
        for _ in range(campioni):
            if tipo == "silenzio":
                valore = 0
            else:
                valore = int(0.25 * 32767 * math.sin(2 * math.pi * 440 * fase / rate))
                fase += 1
            frames += struct.pack("<h", valore)
    with wave.open(str(percorso), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames))


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


def test_concatena_wav_durata_esatta(tmp_path):
    durate = [0.5, 0.25, 0.75]
    pezzi = []
    for indice, durata in enumerate(durate):
        percorso = tmp_path / f"pezzo-{indice}.wav"
        genera_silenzio_wav(durata, percorso)
        pezzi.append(percorso)
    uscita = tmp_path / "unito.wav"
    concatena_wav(pezzi, uscita)

    atteso = sum(durate)
    with wave.open(str(uscita), "rb") as wav:
        assert wav.getframerate() == 24000
        campioni = wav.getnframes()
    assert campioni == 36000
    assert abs(campioni / 24000 - atteso) <= 1 / 24000
    assert abs(info_audio(uscita)["durata"] - atteso) <= 1 / 24000


def test_punto_in_silenzio_dentro_e_fuori_finestra():
    dentro = _punto_in_silenzio(1.25, [(1.0, 1.3)])
    assert 1.0 <= dentro <= 1.3
    assert dentro == 1.25

    spostato = _punto_in_silenzio(1.6, [(1.0, 1.3)])
    assert 1.02 <= spostato <= 1.27

    assert _punto_in_silenzio(4.0, [(1.0, 1.3)]) == 4.0
    assert _punto_in_silenzio(4.0, []) == 4.0


def test_rileva_silenzi_trova_la_pausa(tmp_path):
    voce = tmp_path / "voce.wav"
    _voce_sintetica(
        voce,
        [("tono", 0.5), ("silenzio", 0.5), ("tono", 0.5)],
    )
    silenzi = rileva_silenzi(voce)
    assert silenzi
    inizio, fine = silenzi[0]
    assert abs(inizio - 0.5) <= 0.05
    assert abs(fine - 1.0) <= 0.05


def test_inserisci_suoni_sposta_il_taglio_nel_silenzio(tmp_path):
    voce = tmp_path / "voce.wav"
    _voce_sintetica(
        voce,
        [
            ("silenzio", 1.0),
            ("tono", 2.0),
            ("silenzio", 0.5),
            ("tono", 2.0),
        ],
    )
    # La pausa reale tra le sezioni è 3.0-3.5 s; la stima sbaglia di +0.15 s.
    uscita = tmp_path / "episodio.mp3"
    risultato = inserisci_suoni(
        voce,
        Path(__file__).resolve().parents[1] / "docs" / "suoni" / "ding.mp3",
        uscita,
        [2.65, 2.0],
        carica_impostazioni(),
        [0],
    )
    assert risultato["transizioni"] == 1
    punto = risultato["punti_regolati"][0]
    assert punto != 3.65
    assert 3.0 <= punto < 3.5
    assert info_audio(uscita)["durata"] > 5.5


def test_inserisci_suoni_senza_durate_copia_la_voce(tmp_path):
    voce = tmp_path / "voce.wav"
    _voce_sintetica(voce, [("tono", 1.0)])
    uscita = tmp_path / "copia.wav"
    risultato = inserisci_suoni(
        voce,
        Path(__file__).resolve().parents[1] / "docs" / "suoni" / "ding.mp3",
        uscita,
        [],
        carica_impostazioni(),
    )
    assert risultato["transizioni"] == 0
    assert risultato["punti_regolati"] == []
    assert uscita.read_bytes() == voce.read_bytes()


def test_inserisci_suoni_confini_collassati_non_creano_segmenti_negativi(
    monkeypatch, tmp_path
):
    voce = tmp_path / "voce.wav"
    _voce_sintetica(voce, [("tono", 5.0)])
    # Due confini stimati finiscono nello stesso silenzio iniziale.
    monkeypatch.setattr("notiziario.audio.rileva_silenzi", lambda *a, **k: [(0.0, 1.0)])
    uscita = tmp_path / "episodio.mp3"
    risultato = inserisci_suoni(
        voce,
        Path(__file__).resolve().parents[1] / "docs" / "suoni" / "ding.mp3",
        uscita,
        [0.5, 0.1, 3.0],
        carica_impostazioni(),
        [0, 1],
    )
    assert risultato["transizioni"] == 1
    assert len(risultato["punti_regolati"]) == 1
    assert 0.0 <= risultato["punti_regolati"][0] <= 1.0
    assert info_audio(uscita)["durata"] > info_audio(voce)["durata"]


def _mp3_tono(percorso: Path, secondi: float, frequenza: int) -> None:
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
            f"sine=frequency={frequenza}:duration={secondi}",
            "-ar",
            "44100",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "96k",
            str(percorso),
        ],
        check=True,
    )


def test_musica_sottofondo_dura_e_fa_fade(tmp_path):
    voce = tmp_path / "voce.mp3"
    musica = tmp_path / "musica.mp3"
    uscita = tmp_path / "episodio.mp3"
    _mp3_tono(voce, 3.0, 220)
    _mp3_tono(musica, 8.0, 440)

    impostazioni = carica_impostazioni()
    impostazioni["audio"]["musica"].update(
        {
            "attivo": True,
            "file": str(musica),
            "volume_db": -18,
            "ducking": True,
            "fade_out_secondi": 1.0,
            "silenzio_finale_secondi": 2.0,
            "bitrate": "96k",
        }
    )
    info = aggiungi_musica_sottofondo(voce, uscita, 1.0, impostazioni)
    assert uscita.exists()
    assert info["dimensione"] > 0
    assert info["inizio_musica"] == 1.0
    assert abs(info["durata"] - 5.0) < 0.25
    assert info_audio(uscita)["durata"] > info_audio(voce)["durata"] + 1.5
