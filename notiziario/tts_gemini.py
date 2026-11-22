"""TTS con Gemini 2.5 Flash Preview TTS (PCM L16 24 kHz mono)."""

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
    masterizza,
    verifica_mp3,
)
from .testi import conta_parole, estrai_frasi


class GeminiTTSError(Exception):
    """Errore TTS Gemini: il chiamante può passare a edge-tts."""


def _redigi(messaggio: Any) -> str:
    testo = str(messaggio or "")
    testo = re.sub(r"AIza[0-9A-Za-z_\-]{10,}", "***", testo)
    testo = re.sub(r"(key=)[^&\s]+", r"\1***", testo, flags=re.I)
    return testo[:300]


def chunk_testo(testo: str, massimo: int = 2500) -> list[str]:
    """Divide in blocchi <= massimo caratteri, rispettando frasi e paragrafi."""
    testo = (testo or "").strip()
    if not testo:
        return []
    if len(testo) <= massimo:
        return [testo]
    blocchi: list[str] = []
    paragrafi = [p.strip() for p in re.split(r"\n\s*\n", testo) if p.strip()]
    corrente = ""
    for paragrafo in paragrafi:
        candidate = (corrente + "\n\n" + paragrafo).strip() if corrente else paragrafo
        if len(candidate) <= massimo:
            corrente = candidate
            continue
        if corrente:
            blocchi.append(corrente)
            corrente = ""
        if len(paragrafo) <= massimo:
            corrente = paragrafo
            continue
        # Paragrafo troppo lungo: spezza sulle frasi.
        for frase in estrai_frasi(paragrafo):
            if len(frase) > massimo:
                parole = frase.split()
                pezzo = ""
                for parola in parole:
                    tentativo = (pezzo + " " + parola).strip()
                    if len(tentativo) > massimo and pezzo:
                        blocchi.append(pezzo)
                        pezzo = parola
                    else:
                        pezzo = tentativo
                if pezzo:
                    if len(pezzo) <= massimo:
                        if corrente and len(corrente) + len(pezzo) + 1 <= massimo:
                            corrente = (corrente + " " + pezzo).strip()
                        else:
                            if corrente:
                                blocchi.append(corrente)
                            corrente = pezzo
                    else:
                        blocchi.append(pezzo[:massimo])
                        corrente = pezzo[massimo:]
                continue
            tentativo = (corrente + " " + frase).strip() if corrente else frase
            if len(tentativo) <= massimo:
                corrente = tentativo
            else:
                if corrente:
                    blocchi.append(corrente)
                corrente = frase
    if corrente:
        blocchi.append(corrente)
    # Difesa: nessun blocco vuoto o oltre il limite.
    risultato = []
    for blocco in blocchi:
        blocco = blocco.strip()
        while len(blocco) > massimo:
            taglio = blocco.rfind(" ", 0, massimo)
            if taglio <= 0:
                taglio = massimo
            risultato.append(blocco[:taglio].strip())
            blocco = blocco[taglio:].strip()
        if blocco:
            risultato.append(blocco)
    return risultato


def _estrai_pcm(dati: dict[str, Any]) -> tuple[bytes, int]:
    candidates = dati.get("candidates") or []
    if not candidates:
        blocco = dati.get("promptFeedback", {}).get("blockReason")
        raise GeminiTTSError(f"nessun candidato audio (blockReason={blocco})")
    parti = candidates[0].get("content", {}).get("parts", [])
    pezzi: list[bytes] = []
    rate = 24000
    for parte in parti:
        inline = parte.get("inlineData") if isinstance(parte, dict) else None
        if not inline or not inline.get("data"):
            continue
        mime = str(inline.get("mimeType", ""))
        trovato = re.search(r"rate=(\d+)", mime)
        if trovato:
            rate = int(trovato.group(1))
        try:
            pezzi.append(base64.b64decode(inline["data"], validate=True))
        except Exception as exc:
            raise GeminiTTSError("audio Gemini non decodificabile") from exc
    if not pezzi:
        motivo = candidates[0].get("finishReason", "sconosciuto")
        raise GeminiTTSError(f"risposta senza inlineData audio (finishReason={motivo})")
    pcm = b"".join(pezzi)
    if len(pcm) % 2:
        pcm = pcm[:-1]
    if not pcm:
        raise GeminiTTSError("PCM vuoto")
    return pcm, rate


def _chiama_gemini_tts(
    testo: str,
    voce: str,
    impostazioni: dict[str, Any],
    chiave: str,
    logger,
) -> tuple[bytes, int]:
    conf = impostazioni.get("tts_gemini", {})
    modello = conf.get("modello", "gemini-2.5-flash-preview-tts")
    endpoint = conf.get("endpoint", "").format(modello=modello)
    direzione = conf.get(
        "direzione",
        "Read aloud in a warm, lively, natural Italian female radio host "
        "voice, with varied pacing. Read only the text below.",
    )
    prompt = f"{direzione}\n\n{testo}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voce}}
            },
        },
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": chiave,
        "User-Agent": "Notiziario/0.3",
    }
    timeout = int(conf.get("timeout", 60))
    tts_conf = impostazioni.get("tts", {})
    max_retry = int(tts_conf.get("max_retry_429", 2))
    backoff = list(tts_conf.get("backoff_429", [5, 15, 30]))
    for tentativo in range(max_retry + 1):
        try:
            risposta = requests.post(
                endpoint, json=payload, headers=headers, timeout=timeout
            )
        except requests.RequestException as exc:
            if tentativo < max_retry:
                attesa = float(backoff[min(tentativo, len(backoff) - 1)])
                logger.warning(
                    "Gemini TTS: errore di rete, attendo %.0f secondi.", attesa
                )
                time.sleep(attesa)
                continue
            raise GeminiTTSError(
                f"errore di rete TTS ({type(exc).__name__})"
            ) from exc
        if risposta.status_code == 429:
            if tentativo < max_retry:
                attesa = float(backoff[min(tentativo, len(backoff) - 1)])
                logger.warning(
                    "Gemini TTS 429: attendo %.0f secondi e riprovo (%d/%d).",
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
            raise GeminiTTSError(messaggio)
        if risposta.status_code in (500, 502, 503, 504) and tentativo < max_retry:
            attesa = float(backoff[min(tentativo, len(backoff) - 1)])
            logger.warning(
                "Gemini TTS HTTP %s: attendo %.0f secondi.",
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
            raise GeminiTTSError(messaggio)
        try:
            dati = risposta.json()
        except ValueError as exc:
            raise GeminiTTSError("risposta TTS Gemini non JSON") from exc
        return _estrai_pcm(dati)
    raise GeminiTTSError("TTS Gemini non riuscito")


def _pcm_a_wav(pcm: bytes, percorso: Path, rate: int = 24000) -> None:
    with wave.open(str(percorso), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)


def sintetizza_sezioni_gemini(
    sezioni: list[tuple[str, float]],
    percorso_uscita: str | Path,
    impostazioni: dict[str, Any],
    logger,
    voce: str = "Kore",
    velocita: float = 1.1,
) -> dict[str, Any]:
    """Sintetizza con Gemini, applica atempo ai chunk e poi le pause."""
    chiave = os.environ.get("GEMINI_API_KEY", "").strip()
    if not chiave:
        raise GeminiTTSError("GEMINI_API_KEY non impostata")
    if not 0.75 <= float(velocita) <= 1.25:
        raise GeminiTTSError("velocità fuori dall'intervallo 0.75-1.25")
    sezioni = [(t.strip(), float(p)) for t, p in sezioni if t and t.strip()]
    if not sezioni:
        raise GeminiTTSError("Nessun testo da sintetizzare.")

    uscita = Path(percorso_uscita)
    uscita.parent.mkdir(parents=True, exist_ok=True)
    massimo = int(
        impostazioni.get(
            "tts_chunk_max_caratteri",
            impostazioni.get("tts_gemini", {}).get("max_caratteri_chunk", 4500),
        )
    )
    limite_usato = massimo
    pausa_chiamate = float(impostazioni.get("tts", {}).get("pausa_chiamate", 3.0))
    cartella = Path(
        tempfile.mkdtemp(prefix="notiziario-gemini-tts-", dir=str(uscita.parent))
    )
    try:
        pezzi: list[Path] = []
        pause: dict[float, Path] = {}
        indice = 0
        chiamate = 0
        for testo_sezione, pausa_sezione in sezioni:
            limite = massimo
            while True:
                chunks = chunk_testo(testo_sezione, limite)
                locali: list[Path] = []
                try:
                    for posizione, chunk in enumerate(chunks):
                        if chiamate > 0 and pausa_chiamate > 0:
                            time.sleep(pausa_chiamate)
                        chiamate += 1
                        indice += 1
                        pcm, rate = _chiama_gemini_tts(
                            chunk, voce, impostazioni, chiave, logger
                        )
                        grezzo = cartella / f"grezzo-{indice:03d}.wav"
                        _pcm_a_wav(pcm, grezzo, rate)
                        parlato = cartella / f"parlato-{indice:03d}.wav"
                        applica_atempo(grezzo, parlato, velocita)
                        locali.append(parlato)
                        pausa = pausa_sezione if posizione == len(chunks) - 1 else 0.5
                        if pausa > 0:
                            if pausa not in pause:
                                silenzio = cartella / f"pausa-{pausa:.2f}.wav"
                                genera_silenzio_wav(pausa, silenzio)
                                pause[pausa] = silenzio
                            locali.append(pause[pausa])
                        logger.info(
                            "Gemini TTS chunk %d: %d parole, %d byte PCM.",
                            indice,
                            conta_parole(chunk),
                            len(pcm),
                        )
                    pezzi.extend(locali)
                    break
                except GeminiTTSError as exc:
                    if (
                        "HTTP 400" in str(exc)
                        and limite > 900
                        and len(testo_sezione) > 900
                    ):
                        nuovo = max(800, min(limite - 500, len(testo_sezione) // 2))
                        logger.warning(
                            "Gemini TTS ha rifiutato %d caratteri con HTTP 400: "
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
                "motore": "gemini",
                "voce": voce,
                "velocita": float(velocita),
                "motivo_fallback": None,
                "limite_chunk_usato": limite_usato,
                "chiamate": chiamate,
            }
        )
        logger.info(
            "Audio Gemini finale: %s (%.1f s, %d byte, %d chiamate).",
            uscita,
            info["durata"],
            info["dimensione"],
            chiamate,
        )
        return info
    except AudioError as exc:
        raise GeminiTTSError(f"Errore audio Gemini: {exc}") from exc
    finally:
        shutil.rmtree(cartella, ignore_errors=True)