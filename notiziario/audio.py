"""Operazioni ffmpeg: silenzi, concatenazione, mastering e verifiche."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


class AudioError(Exception):
    """Errore di ffmpeg/ffprobe con messaggio utile all'utente."""


def _strumento(nome: str) -> str:
    percorso = shutil.which(nome)
    if not percorso:
        raise AudioError(
            f"{nome} non trovato nel PATH. Installa ffmpeg e riapri il terminale."
        )
    return percorso


def _esegui(comando: list[str]) -> None:
    try:
        risultato = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise AudioError(f"Programma non trovato: {comando[0]}") from exc
    if risultato.returncode != 0:
        dettaglio = (risultato.stderr or risultato.stdout or "").strip()
        if len(dettaglio) > 800:
            dettaglio = dettaglio[-800:]
        raise AudioError(f"ffmpeg ha fallito: {dettaglio}")


def info_audio(percorso: str | Path) -> dict[str, Any]:
    path = Path(percorso)
    if not path.exists():
        raise AudioError(f"File audio non trovato: {path}")
    ffprobe = _strumento("ffprobe")
    comando = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,sample_rate,channels",
        "-show_entries",
        "format=duration,size,format_name",
        "-of",
        "json",
        str(path),
    ]
    risultato = subprocess.run(
        comando,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if risultato.returncode != 0:
        raise AudioError(f"ffprobe non riesce a leggere {path}.")
    try:
        dati = json.loads(risultato.stdout)
    except json.JSONDecodeError as exc:
        raise AudioError(f"ffprobe ha restituito un output non valido per {path}.") from exc
    streams = dati.get("streams") or []
    if not streams:
        raise AudioError(f"Nessuna traccia audio in {path}.")
    formato = dati.get("format") or {}
    stream = streams[0]
    return {
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream.get("sample_rate", 0) or 0),
        "canali": int(stream.get("channels", 0) or 0),
        "durata": float(formato.get("duration", 0) or 0),
        "dimensione": int(formato.get("size", path.stat().st_size) or 0),
        "formato": formato.get("format_name"),
    }


def durata_mp3(percorso: str | Path) -> float:
    return float(info_audio(percorso)["durata"])


def applica_atempo(
    ingresso: str | Path,
    uscita: str | Path,
    velocita: float,
    bitrate: str = "96k",
) -> None:
    """Applica atempo al solo parlato, prima di aggiungere le pause."""
    ffmpeg = _strumento("ffmpeg")
    fattore = max(0.5, min(2.0, float(velocita)))
    codec = (
        ["-c:a", "pcm_s16le"]
        if Path(uscita).suffix.lower() == ".wav"
        else ["-c:a", "libmp3lame", "-b:a", bitrate]
    )
    _esegui(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(ingresso),
            "-filter:a",
            f"atempo={fattore:.4f}",
            "-ar",
            "24000",
            "-ac",
            "1",
            *codec,
            str(uscita),
        ]
    )


def genera_silenzio_wav(secondi: float, percorso: str | Path) -> None:
    if secondi <= 0:
        return
    ffmpeg = _strumento("ffmpeg")
    _esegui(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            f"{secondi:.3f}",
            "-c:a",
            "pcm_s16le",
            str(percorso),
        ]
    )


def concatena_wav(percorsi: list[Path], uscita: str | Path) -> None:
    if not percorsi:
        raise AudioError("Nessun blocco WAV da concatenare.")
    ffmpeg = _strumento("ffmpeg")
    lista = Path(uscita).with_suffix(".concat.txt")
    righe = []
    for percorso in percorsi:
        assoluto = Path(percorso).resolve().as_posix().replace("'", "'\\''")
        righe.append(f"file '{assoluto}'")
    lista.write_text("\n".join(righe) + "\n", encoding="utf-8")
    try:
        _esegui(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(lista),
                "-c",
                "copy",
                str(uscita),
            ]
        )
    finally:
        lista.unlink(missing_ok=True)


def genera_silenzio(secondi: float, percorso: str | Path) -> None:
    if secondi <= 0:
        return
    ffmpeg = _strumento("ffmpeg")
    _esegui(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            f"{secondi:.3f}",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "48k",
            str(percorso),
        ]
    )


def concatena_mp3(percorsi: list[Path], uscita: str | Path) -> None:
    if not percorsi:
        raise AudioError("Nessun blocco audio da concatenare.")
    ffmpeg = _strumento("ffmpeg")
    lista = Path(uscita).with_suffix(".concat.txt")
    righe = []
    for percorso in percorsi:
        percorso_assoluto = Path(percorso).resolve().as_posix().replace("'", "'\\''")
        righe.append(f"file '{percorso_assoluto}'")
    lista.write_text("\n".join(righe) + "\n", encoding="utf-8")
    try:
        _esegui(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(lista),
                "-c",
                "copy",
                str(uscita),
            ]
        )
    except AudioError:
        # Se i blocchi non hanno esattamente lo stesso formato, ricodifico.
        _esegui(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(lista),
                "-ar",
                "24000",
                "-ac",
                "1",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "48k",
                str(uscita),
            ]
        )
    finally:
        lista.unlink(missing_ok=True)


def masterizza(
    ingresso: str | Path, uscita: str | Path, impostazioni: dict[str, Any]
) -> None:
    ffmpeg = _strumento("ffmpeg")
    audio = impostazioni.get("audio", {})
    loudnorm = audio.get("loudnorm", "loudnorm=I=-16:TP=-1.5:LRA=11")
    silenzio_ms = int(impostazioni.get("silenzio_iniziale_ms", 1000))
    if silenzio_ms > 0:
        loudnorm = f"{loudnorm},adelay={silenzio_ms}:all=1"
    sample_rate = int(audio.get("sample_rate", 44100))
    canali = int(audio.get("canali", 1))
    bitrate = str(audio.get("bitrate", "96k"))
    _esegui(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(ingresso),
            "-af",
            loudnorm,
            "-ar",
            str(sample_rate),
            "-ac",
            str(canali),
            "-b:a",
            bitrate,
            "-id3v2_version",
            "3",
            "-map_metadata",
            "-1",
            str(uscita),
        ]
    )
    if silenzio_ms > 0:
        silenzioso, massimo, dettaglio = verifica_silenzio_iniziale(uscita)
        if not silenzioso:
            raise AudioError(
                "Silenzio iniziale non valido dopo il mastering: "
                f"max_volume={massimo} dB. {dettaglio[:200]}"
            )


def verifica_mp3(
    percorso: str | Path, min_durata: float = 0.0
) -> dict[str, Any]:
    info = info_audio(percorso)
    if str(info.get("codec", "")).lower() != "mp3":
        raise AudioError(
            f"Il file {percorso} non è MP3 (codec: {info.get('codec')})."
        )
    if info["durata"] < min_durata:
        raise AudioError(
            f"Il file {percorso} dura {info['durata']:.1f}s, "
            f"meno del minimo richiesto ({min_durata:.1f}s)."
        )
    return info


def verifica_silenzio_iniziale(
    percorso: str | Path,
    durata_ms: int = 950,
    soglia_db: float = -60.0,
) -> tuple[bool, float | None, str]:
    """Controlla che i primi ``durata_ms`` siano sotto la soglia."""
    ffmpeg = _strumento("ffmpeg")
    secondi = max(0.01, durata_ms / 1000)
    risultato = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-ss",
            "0",
            "-t",
            f"{secondi:.3f}",
            "-i",
            str(percorso),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if risultato.returncode != 0:
        return False, None, (risultato.stderr or "").strip()[-500:]
    match = re.search(
        r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", risultato.stderr or ""
    )
    if not match:
        return False, None, "max_volume non trovato"
    massimo = float(match.group(1))
    return massimo <= soglia_db, massimo, risultato.stderr[-500:]


def ffmpeg_disponibile() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
