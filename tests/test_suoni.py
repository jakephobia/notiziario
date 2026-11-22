from __future__ import annotations

import re
import subprocess
import wave
from pathlib import Path

from notiziario import audio
from notiziario.config import carica_impostazioni


def _tono(path: Path, secondi: float = 4.0, rate: int = 44100) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x10\x00" * int(rate * secondi))


def _volume(path: Path) -> tuple[float, float]:
    risultato = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "NUL"],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    testo = risultato.stderr
    mean = float(re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)", testo).group(1))
    massimo = float(re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)", testo).group(1))
    return mean, massimo


def test_suoni_generati_validi():
    attesi = {"ding": 2.2, "chime": 0.8, "whoosh": 0.6}
    for nome, durata in attesi.items():
        percorso = Path("docs/suoni") / f"{nome}.mp3"
        info = audio.info_audio(percorso)
        assert info["codec"] == "mp3"
        assert info["sample_rate"] == 44100
        assert info["canali"] == 1
        assert abs(info["durata"] - durata) < 0.05
        media, massimo = _volume(percorso)
        assert -30 <= media <= -15
        assert massimo <= -8


def test_inserimento_suoni_conta_e_aumenta_durata(tmp_path):
    voce = tmp_path / "voce.mp3"
    _tono(tmp_path / "voce.wav", 4.0)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp_path / "voce.wav"), "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "96k", str(voce)],
        check=True,
    )
    uscita = tmp_path / "episodio.mp3"
    risultato = audio.inserisci_suoni(
        voce,
        Path("docs/suoni/ding.mp3"),
        uscita,
        [1.0, 1.0, 1.0],
        carica_impostazioni(),
        [0, 1],
    )
    assert risultato["transizioni"] == 2
    durata = audio.info_audio(uscita)["durata"]
    durata_suono = audio.info_audio(Path("docs/suoni/ding.mp3"))["durata"]
    atteso = 4.0 + 2 * (0.3 + durata_suono + 0.3)
    assert abs(durata - atteso) < 0.6
