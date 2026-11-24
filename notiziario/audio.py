"""Operazioni ffmpeg: silenzi, concatenazione, mastering e verifiche."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .config import ROOT


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


def genera_silenzio(
    secondi: float,
    percorso: str | Path,
    sample_rate: int = 24000,
    bitrate: str = "48k",
) -> None:
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
            f"anullsrc=r={sample_rate}:cl=mono",
            "-t",
            f"{secondi:.3f}",
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
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


def rileva_silenzi(
    percorso: str | Path,
    soglia_db: float = -35.0,
    durata_min: float = 0.12,
) -> list[tuple[float, float]]:
    """Elenca i silenzi reali ``(inizio, fine)`` con ``silencedetect``."""
    path = Path(percorso)
    if not path.exists():
        raise AudioError(f"File audio non trovato: {path}")
    ffmpeg = _strumento("ffmpeg")
    filtro = (
        f"silencedetect=noise={float(soglia_db):.1f}dB:"
        f"d={float(durata_min):.3f}"
    )
    risultato = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vn",
            "-af",
            filtro,
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
        dettaglio = (risultato.stderr or "").strip()[-500:]
        raise AudioError(f"silencedetect ha fallito su {path}: {dettaglio}")

    silenzi: list[tuple[float, float]] = []
    inizio: float | None = None
    for riga in (risultato.stderr or "").splitlines():
        avvio = re.search(r"silence_start:\s*(-?\d+(?:\.\d+)?)", riga)
        if avvio:
            inizio = max(0.0, float(avvio.group(1)))
            continue
        fine = re.search(r"silence_end:\s*(-?\d+(?:\.\d+)?)", riga)
        if fine and inizio is not None:
            finale = max(inizio, float(fine.group(1)))
            if finale > inizio:
                silenzi.append((inizio, finale))
            inizio = None
    if inizio is not None:
        # Il file può terminare dentro un silenzio: chiudo alla durata nota.
        finale = inizio
        try:
            finale = float(info_audio(path)["durata"])
        except AudioError:
            pass
        if finale > inizio:
            silenzi.append((inizio, finale))
    return silenzi


def _punto_in_silenzio(
    punto: float,
    silenzi: list[tuple[float, float]],
    finestra: float = 1.5,
) -> float:
    """Sposta ``punto`` dentro il silenzio più vicino entro ``finestra``.

    Se non c'è un silenzio abbastanza vicino restituisce il punto originale.
    Il margine evita di tagliare l'attacco o la coda di una parola.
    """
    punto = float(punto)
    migliore: tuple[float, float, float] | None = None
    for inizio, fine in silenzi:
        inizio = float(inizio)
        fine = float(fine)
        if fine <= inizio:
            continue
        if inizio <= punto <= fine:
            distanza = 0.0
        else:
            distanza = min(abs(punto - inizio), abs(punto - fine))
        if distanza <= finestra and (migliore is None or distanza < migliore[0]):
            migliore = (distanza, inizio, fine)
    if migliore is None:
        return punto
    _, inizio, fine = migliore
    minimo = inizio + 0.02
    massimo = fine - 0.03
    if massimo < minimo:
        return (inizio + fine) / 2
    return min(max(punto, minimo), massimo)


def inserisci_suoni(
    voce: str | Path,
    suono: str | Path,
    uscita: str | Path,
    durate_sezioni: list[float],
    impostazioni: dict[str, Any],
    indici_transizioni: list[int] | None = None,
) -> dict[str, Any]:
    """Inserisce 0.3s + suono + 0.3s tra le sezioni, dopo il mastering.

    Il suono non passa da loudnorm: viene solo applicato il gain configurato.
    I confini stimati vengono riallineati ai silenzi reali del file voce, così
    il taglio non cade mai dentro una parola se la stima è di poco sbagliata.
    """
    voce_path = Path(voce)
    suono_path = Path(suono)
    uscita_path = Path(uscita)
    if not voce_path.exists() or not suono_path.exists():
        raise AudioError("Voce o suono mancante per le transizioni.")
    durate = [max(0.0, float(x)) for x in durate_sezioni]
    if not durate:
        uscita_path.write_bytes(voce_path.read_bytes())
        return {
            "transizioni": 0,
            "durata": info_audio(voce_path)["durata"],
            "punti_regolati": [],
        }
    iniziale = int(impostazioni.get("silenzio_iniziale_ms", 1000)) / 1000
    confini: list[float] = []
    cumulato = iniziale
    for durata in durate:
        cumulato += durata
        confini.append(cumulato)
    if indici_transizioni is None:
        indici_transizioni = list(range(max(0, len(durate) - 1)))
    durata_voce = info_audio(voce_path)["durata"]
    punti = sorted(
        {
            confini[indice]
            for indice in indici_transizioni
            if 0 <= indice < len(confini) - 1
            and 0.05 < confini[indice] < durata_voce - 0.05
        }
    )
    if not punti:
        uscita_path.write_bytes(voce_path.read_bytes())
        return {"transizioni": 0, "durata": durata_voce, "punti_regolati": []}

    logger = logging.getLogger("notiziario")
    try:
        silenzi = rileva_silenzi(voce_path)
    except AudioError as exc:
        logger.warning(
            "Rilevamento silenzi non disponibile (%s): uso i confini stimati.",
            exc,
        )
        silenzi = []
    punti = sorted({_punto_in_silenzio(punto, silenzi) for punto in punti})
    punti_regolati = [round(punto, 3) for punto in punti]
    logger.info(
        "Transizioni: %d confini, %d silenzi rilevati, punti %s.",
        len(punti),
        len(silenzi),
        punti_regolati,
    )

    ffmpeg = _strumento("ffmpeg")
    cartella = Path(tempfile.mkdtemp(prefix="notiziario-suoni-", dir=str(uscita_path.parent)))
    try:
        gain = float(impostazioni.get("suono_gain_db", 0))
        suono_gain = cartella / "suono.mp3"
        _esegui(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(suono_path),
                "-af",
                f"volume={gain:.2f}dB",
                "-ar",
                "44100",
                "-ac",
                "1",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "96k",
                str(suono_gain),
            ]
        )
        silenzio = cartella / "pausa.mp3"
        genera_silenzio(0.3, silenzio, sample_rate=44100, bitrate="96k")

        inizi = [0.0] + punti
        fini = punti + [durata_voce]
        segmenti = []
        for indice, (inizio, fine) in enumerate(zip(inizi, fini)):
            if fine <= inizio:
                continue
            segmento = cartella / f"voce-{indice:02d}.mp3"
            _esegui(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{inizio:.3f}",
                    "-to",
                    f"{fine:.3f}",
                    "-i",
                    str(voce_path),
                    "-ar",
                    "44100",
                    "-ac",
                    "1",
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "96k",
                    str(segmento),
                ]
            )
            segmenti.append(segmento)

        pezzi: list[Path] = []
        for indice, segmento in enumerate(segmenti):
            pezzi.append(segmento)
            if indice < len(segmenti) - 1:
                pezzi.extend([silenzio, suono_gain, silenzio])
        concatena_mp3(pezzi, uscita_path)
        info = info_audio(uscita_path)
        return {
            "transizioni": len(punti),
            "durata": info["durata"],
            "punti_regolati": punti_regolati,
        }
    except AudioError:
        raise
    except Exception as exc:
        raise AudioError(f"Inserimento suoni fallito: {exc}") from exc
    finally:
        shutil.rmtree(cartella, ignore_errors=True)


def aggiungi_musica_sottofondo(
    voce: str | Path,
    uscita: str | Path,
    inizio_musica: float,
    impostazioni: dict[str, Any],
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Mix leggero con ducking: parte dalla prima notizia e chiude in fade-out.

    La voce viene allungata di ``silenzio_finale_secondi``; la musica parte da
    ``inizio_musica`` (dopo l'intro), resta sotto la voce e sfuma negli ultimi
    secondi. Il file musicale viene ripetuto se la puntata è più lunga.
    """
    logger = logger or logging.getLogger("notiziario")
    conf = impostazioni.get("audio", {}).get("musica", {})
    musica_path = Path(str(conf.get("file", "")))
    if not musica_path.is_absolute():
        musica_path = ROOT / musica_path
    if not musica_path.exists():
        raise AudioError(f"Musica di sottofondo mancante: {musica_path}")
    voce_path = Path(voce)
    uscita_path = Path(uscita)
    if not voce_path.exists():
        raise AudioError("Voce mancante per il sottofondo.")

    durata_voce = info_audio(voce_path)["durata"]
    inizio = max(0.0, min(float(inizio_musica), max(0.0, durata_voce - 0.1)))
    silenzio_finale = max(0.0, float(conf.get("silenzio_finale_secondi", 3.0)))
    fade = max(0.0, float(conf.get("fade_out_secondi", 3.0)))
    durata_finale = durata_voce + silenzio_finale
    durata_musica = max(0.1, durata_finale - inizio)
    fade = min(fade, durata_musica)
    fade_start = max(0.0, durata_musica - fade)
    volume_db = float(conf.get("volume_db", -18.0))
    bitrate = str(conf.get("bitrate", "128k"))
    sample_rate = int(impostazioni.get("audio", {}).get("sample_rate", 44100))
    ducking = bool(conf.get("ducking", True))
    soglia = float(conf.get("ducking_threshold", 0.05))
    ratio = float(conf.get("ducking_ratio", 4.0))

    pad = (
        f"apad=pad_dur={silenzio_finale:.3f},"
        if silenzio_finale > 0
        else ""
    )
    fade_filtro = (
        f",afade=t=out:st={fade_start:.3f}:d={fade:.3f}" if fade > 0 else ""
    )
    filtro = (
        f"[0:a]{pad}asplit=2[voce][side];"
        f"[1:a]atrim=start={inizio:.3f}:duration={durata_musica:.3f},"
        f"asetpts=PTS-STARTPTS,volume={volume_db:.2f}dB{fade_filtro}[musica];"
    )
    if ducking:
        filtro += (
            f"[musica][side]sidechaincompress=threshold={soglia:.4f}:"
            f"ratio={ratio:.2f}:attack=20:release=500[duck];"
            "[voce][duck]amix=inputs=2:duration=first:normalize=0[out]"
        )
    else:
        filtro += (
            "[voce][musica]amix=inputs=2:duration=first:normalize=0[out]"
        )

    ffmpeg = _strumento("ffmpeg")
    _esegui(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(voce_path),
            "-stream_loop",
            "-1",
            "-i",
            str(musica_path),
            "-filter_complex",
            filtro,
            "-map",
            "[out]",
            "-ar",
            str(sample_rate),
            "-ac",
            "2",
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-id3v2_version",
            "3",
            "-map_metadata",
            "-1",
            str(uscita_path),
        ]
    )
    info = info_audio(uscita_path)
    logger.info(
        "Musica sottofondo: da %.1fs a %.1fs, volume %.1f dB, ducking %s, "
        "fade %.1fs.",
        inizio,
        durata_finale,
        volume_db,
        "sì" if ducking else "no",
        fade,
    )
    return {
        "durata": info["durata"],
        "dimensione": uscita_path.stat().st_size,
        "inizio_musica": inizio,
        "volume_db": volume_db,
        "ducking": ducking,
        "fade_out_secondi": fade,
        "silenzio_finale_secondi": silenzio_finale,
    }


def ffmpeg_disponibile() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
