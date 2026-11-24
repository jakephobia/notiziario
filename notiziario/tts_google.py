"""TTS con Google Cloud Text-to-Speech (Chirp 3 HD, LINEAR16)."""

from __future__ import annotations

import base64
import os
import re
import shutil
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

import requests

from .audio import (
    AudioError,
    applica_atempo,
    concatena_wav,
    genera_silenzio_wav,
    info_audio,
    masterizza,
    verifica_mp3,
)
from .testi import conta_parole
from .tts_gemini import chunk_testo


ENDPOINT_DEFAULT = "https://texttospeech.googleapis.com/v1/text:synthesize"
VOCE_DEFAULT = "it-IT-Chirp3-HD-Achernar"
LINGUA_DEFAULT = "it-IT"


class GoogleTTSError(Exception):
    """Errore TTS Google: il chiamante può passare a edge-tts."""


def _redigi(messaggio: Any) -> str:
    testo = str(messaggio or "")
    testo = re.sub(r"AIza[0-9A-Za-z_\-]{10,}", "***", testo)
    testo = re.sub(r"(key=)[^&\s]+", r"\1***", testo, flags=re.I)
    testo = re.sub(r"(X-Goog-Api-Key\s*:\s*)\S+", r"\1***", testo, flags=re.I)
    return testo[:300]


def _voce_richiesta(
    impostazioni: dict[str, Any], voce: str | None
) -> str:
    nome = str(voce or "").strip()
    if nome:
        return nome
    configurazione = impostazioni.get("voce", {})
    google = configurazione.get("google", {}) if isinstance(configurazione, dict) else {}
    if isinstance(google, dict):
        nome = str(google.get("nome") or "").strip()
    return nome or VOCE_DEFAULT


def _audio_a_wav(audio: bytes, percorso: Path, rate: int = 24000) -> None:
    """Salva l'audio restituito da Google come WAV.

    Se è già un WAV (RIFF) lo scrive così com'è; altrimenti interpreta i byte
    come PCM L16 mono e costruisce l'intestazione WAV.
    """
    if not audio:
        raise GoogleTTSError("audio Google vuoto")
    if audio[:4] == b"RIFF":
        percorso.write_bytes(audio)
        return
    pcm = audio if len(audio) % 2 == 0 else audio[:-1]
    if not pcm:
        raise GoogleTTSError("PCM Google vuoto")
    with wave.open(str(percorso), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)


def _chiama_google_tts(
    testo: str,
    voce: str,
    impostazioni: dict[str, Any],
    chiave: str,
    logger,
) -> bytes:
    conf = impostazioni.get("tts_google", {})
    if not isinstance(conf, dict):
        conf = {}
    endpoint = str(conf.get("endpoint") or ENDPOINT_DEFAULT)
    lingua = str(conf.get("lingua") or LINGUA_DEFAULT)
    payload = {
        "input": {"text": testo},
        "voice": {"languageCode": lingua, "name": voce},
        "audioConfig": {"audioEncoding": "LINEAR16", "speakingRate": 1.0},
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": chiave,
        "User-Agent": "Notiziario/0.3",
    }
    timeout = int(conf.get("timeout", 90))
    tts_conf = impostazioni.get("tts", {})
    max_retry = int(tts_conf.get("max_retry_429", 2))
    backoff = list(tts_conf.get("backoff_429", [5, 15, 30])) or [5]
    for tentativo in range(max_retry + 1):
        try:
            risposta = requests.post(
                endpoint, json=payload, headers=headers, timeout=timeout
            )
        except requests.RequestException as exc:
            if tentativo < max_retry:
                attesa = float(backoff[min(tentativo, len(backoff) - 1)])
                logger.warning(
                    "Google TTS: errore di rete, attendo %.0f secondi.", attesa
                )
                time.sleep(attesa)
                continue
            raise GoogleTTSError(
                f"errore di rete TTS ({type(exc).__name__})"
            ) from exc
        if risposta.status_code == 429:
            if tentativo < max_retry:
                attesa = float(backoff[min(tentativo, len(backoff) - 1)])
                logger.warning(
                    "Google TTS 429: attendo %.0f secondi e riprovo (%d/%d).",
                    attesa,
                    tentativo + 1,
                    max_retry,
                )
                time.sleep(attesa)
                continue
            dettaglio = ""
            try:
                corpo = risposta.json()
                dettaglio = str(corpo.get("error", {}).get("message", ""))
            except ValueError:
                pass
            messaggio = f"HTTP 429 dopo {max_retry} retry"
            if dettaglio:
                messaggio += f": {_redigi(dettaglio)}"
            raise GoogleTTSError(messaggio)
        if risposta.status_code in (500, 502, 503, 504) and tentativo < max_retry:
            attesa = float(backoff[min(tentativo, len(backoff) - 1)])
            logger.warning(
                "Google TTS HTTP %s: attendo %.0f secondi.",
                risposta.status_code,
                attesa,
            )
            time.sleep(attesa)
            continue
        if risposta.status_code >= 400:
            dettaglio = ""
            try:
                corpo = risposta.json()
                dettaglio = str(corpo.get("error", {}).get("message", ""))
            except ValueError:
                pass
            messaggio = f"HTTP {risposta.status_code}"
            if dettaglio:
                messaggio += f": {_redigi(dettaglio)}"
            raise GoogleTTSError(messaggio)
        try:
            dati = risposta.json()
        except ValueError as exc:
            raise GoogleTTSError("risposta TTS Google non JSON") from exc
        contenuto = dati.get("audioContent") if isinstance(dati, dict) else None
        if not contenuto:
            raise GoogleTTSError("risposta senza audioContent")
        try:
            audio = base64.b64decode(contenuto, validate=True)
        except Exception as exc:
            raise GoogleTTSError("audio Google non decodificabile") from exc
        if not audio:
            raise GoogleTTSError("risposta senza audioContent")
        return audio
    raise GoogleTTSError("TTS Google non riuscito")


def sintetizza_sezioni_google(
    sezioni: list[tuple[str, float]],
    percorso_uscita: str | Path,
    impostazioni: dict[str, Any],
    logger,
    voce: str | None = None,
    velocita: float = 1.0,
) -> dict[str, Any]:
    """Sintetizza con Google Cloud TTS, applica atempo ai chunk e poi le pause."""
    chiave = os.environ.get("GOOGLE_CLOUD_TTS_API_KEY", "").strip()
    if not chiave:
        raise GoogleTTSError("GOOGLE_CLOUD_TTS_API_KEY non impostata")
    if not 0.75 <= float(velocita) <= 1.25:
        raise GoogleTTSError("velocità fuori dall'intervallo 0.75-1.25")
    sezioni = [(t.strip(), float(p)) for t, p in sezioni if t and t.strip()]
    if not sezioni:
        raise GoogleTTSError("Nessun testo da sintetizzare.")

    nome_voce = _voce_richiesta(impostazioni, voce)
    conf = impostazioni.get("tts_google", {})
    if not isinstance(conf, dict):
        conf = {}
    uscita = Path(percorso_uscita)
    uscita.parent.mkdir(parents=True, exist_ok=True)
    massimo = int(conf.get("max_caratteri_chunk", 3000))
    limite_usato = massimo
    cartella = Path(
        tempfile.mkdtemp(prefix="notiziario-google-tts-", dir=str(uscita.parent))
    )
    try:
        pezzi: list[Path] = []
        durate_sezioni: list[float] = []
        pause: dict[float, Path] = {}
        indice = 0
        chiamate = 0
        for testo_sezione, pausa_sezione in sezioni:
            limite = massimo
            while True:
                chunks = chunk_testo(testo_sezione, limite)
                locali: list[Path] = []
                durata_sezione = 0.0
                try:
                    for posizione, chunk in enumerate(chunks):
                        chiamate += 1
                        indice += 1
                        audio = _chiama_google_tts(
                            chunk, nome_voce, impostazioni, chiave, logger
                        )
                        grezzo = cartella / f"grezzo-{indice:03d}.wav"
                        _audio_a_wav(audio, grezzo)
                        parlato = cartella / f"parlato-{indice:03d}.wav"
                        applica_atempo(grezzo, parlato, velocita)
                        durata_sezione += float(info_audio(parlato)["durata"])
                        locali.append(parlato)
                        pausa = pausa_sezione if posizione == len(chunks) - 1 else 0.5
                        if pausa > 0:
                            if pausa not in pause:
                                silenzio = cartella / f"pausa-{pausa:.2f}.wav"
                                genera_silenzio_wav(pausa, silenzio)
                                pause[pausa] = silenzio
                            locali.append(pause[pausa])
                            durata_sezione += pausa
                        logger.info(
                            "Google TTS chunk %d: %d parole, %d byte WAV.",
                            indice,
                            conta_parole(chunk),
                            parlato.stat().st_size,
                        )
                    pezzi.extend(locali)
                    durate_sezioni.append(durata_sezione)
                    break
                except GoogleTTSError as exc:
                    if (
                        "HTTP 400" in str(exc)
                        and limite > 900
                        and len(testo_sezione) > 900
                    ):
                        nuovo = max(800, min(limite - 500, len(testo_sezione) // 2))
                        logger.warning(
                            "Google TTS ha rifiutato %d caratteri con HTTP 400: "
                            "riduco il chunk a %d caratteri.",
                            limite,
                            nuovo,
                        )
                        limite = nuovo
                        limite_usato = min(limite_usato, nuovo)
                        continue
                    raise
        unito = cartella / "unito.wav"
        concatena_wav(pezzi, unito)
        masterizza(unito, uscita, impostazioni)
        info = verifica_mp3(uscita, min_durata=1.0)
        info.update(
            {
                "motore": "google",
                "voce": nome_voce,
                "velocita": float(velocita),
                "motivo_fallback": None,
                "limite_chunk_usato": limite_usato,
                "chiamate": chiamate,
                "durate_sezioni": durate_sezioni,
            }
        )
        logger.info(
            "Audio Google finale: %s (%.1f s, %d byte, %d chiamate).",
            uscita,
            info["durata"],
            info["dimensione"],
            chiamate,
        )
        return info
    except AudioError as exc:
        raise GoogleTTSError(f"Errore audio Google: {exc}") from exc
    finally:
        shutil.rmtree(cartella, ignore_errors=True)
