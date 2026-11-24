"""Motore TTS: Gemini principale, Google Cloud TTS selezionabile, edge-tts fallback."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import edge_tts

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
from .tts_gemini import GeminiTTSError, sintetizza_sezioni_gemini
from .tts_google import GoogleTTSError, sintetizza_sezioni_google


class TTSError(Exception):
    """Errore della sintesi vocale."""


TESTO_PROVINI = (
    "Buongiorno. Questa è una prova della voce del Notiziario. "
    "Leggo qualche frase per farti sentire il ritmo e la chiarezza. "
    "Il 22 novembre 2026 apriamo con le notizie principali. "
    "Secondo ANSA e Repubblica, il governo ha approvato il nuovo piano. "
    "Il 3 per cento delle risorse sarà dedicato alla scuola. "
    "La notizia è riportata anche da Il Post. "
    "Scegli tu la voce che preferisci ascoltare. Buona giornata."
)


def _voce_edge(impostazioni: dict[str, Any], voce: str | None) -> str:
    if voce and str(voce).startswith("it-IT-"):
        return str(voce)
    edge = impostazioni.get("voce", {}).get("edge", {})
    return str(edge.get("nome", "it-IT-IsabellaNeural"))


async def _salva_blocco(
    testo: str,
    voce: str,
    rate: str,
    pitch: str,
    percorso: Path,
    tentativi: int,
    indice: int,
    logger: logging.Logger,
) -> None:
    ultimo: Exception | None = None
    for tentativo in range(1, tentativi + 1):
        try:
            comunicazione = edge_tts.Communicate(
                testo,
                voce,
                rate=rate,
                pitch=pitch,
            )
            await comunicazione.save(str(percorso))
            if percorso.exists() and percorso.stat().st_size > 1500:
                logger.info(
                    "edge-tts blocco %d: %d parole, %d byte.",
                    indice,
                    conta_parole(testo),
                    percorso.stat().st_size,
                )
                return
            raise TTSError("file audio vuoto o troppo piccolo")
        except Exception as exc:
            ultimo = exc
            if tentativo < tentativi:
                logger.warning(
                    "edge-tts blocco %d: tentativo %d fallito (%s), riprovo.",
                    indice,
                    tentativo,
                    type(exc).__name__,
                )
                await asyncio.sleep(2 * tentativo)
    raise TTSError(
        f"edge-tts non ha prodotto audio per il blocco {indice}: "
        f"{type(ultimo).__name__ if ultimo else 'errore sconosciuto'}. "
        "Controlla connessione, proxy o firewall e riprova."
    )


def _sintetizza_edge(
    sezioni: list[tuple[str, float]],
    percorso_uscita: Path,
    impostazioni: dict[str, Any],
    logger: logging.Logger,
    voce: str | None,
    velocita: float,
) -> dict[str, Any]:
    configurazione_voce = impostazioni.get("voce", {})
    voce_edge = _voce_edge(impostazioni, voce)
    pitch = str(configurazione_voce.get("pitch", "+0Hz"))
    tentativi = int(impostazioni.get("tts", {}).get("tentativi", 2))
    cartella = Path(
        tempfile.mkdtemp(prefix="notiziario-edge-tts-", dir=str(percorso_uscita.parent))
    )
    try:
        pezzi: list[Path] = []
        durate_sezioni: list[float] = []
        pause: dict[float, Path] = {}
        durate_pause: dict[float, float] = {}
        for pausa in sorted({p for _, p in sezioni if p > 0}):
            percorso_pausa = cartella / f"pausa-{pausa:.2f}.wav"
            genera_silenzio_wav(pausa, percorso_pausa)
            pause[pausa] = percorso_pausa
            durate_pause[pausa] = float(info_audio(percorso_pausa)["durata"])

        async def lavora() -> None:
            for indice, (testo, pausa) in enumerate(sezioni, start=1):
                durata_sezione = 0.0
                grezzo = cartella / f"blocco-{indice:02d}.mp3"
                await _salva_blocco(
                    testo,
                    voce_edge,
                    "+0%",
                    pitch,
                    grezzo,
                    tentativi,
                    indice,
                    logger,
                )
                # WAV senza padding MP3: le durate misurate restano esatte.
                parlato = cartella / f"parlato-{indice:02d}.wav"
                applica_atempo(grezzo, parlato, velocita)
                durata_sezione += float(info_audio(parlato)["durata"])
                pezzi.append(parlato)
                if pausa > 0:
                    pezzi.append(pause[pausa])
                    durata_sezione += durate_pause[pausa]
                durate_sezioni.append(durata_sezione)

        try:
            asyncio.run(lavora())
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(
                f"Errore imprevisto durante edge-tts: {type(exc).__name__}."
            ) from exc

        grezzo = cartella / "grezzo.wav"
        concatena_wav(pezzi, grezzo)
        masterizza(grezzo, percorso_uscita, impostazioni)
        info = verifica_mp3(percorso_uscita, min_durata=1.0)
        info.update(
            {
                "motore": "edge",
                "voce": voce_edge,
                "velocita": float(velocita),
                "motivo_fallback": None,
                "durate_sezioni": durate_sezioni,
            }
        )
        logger.info(
            "Audio edge finale: %s (%.1f s, %d byte).",
            percorso_uscita,
            info["durata"],
            info["dimensione"],
        )
        return info
    except AudioError as exc:
        raise TTSError(f"Errore audio edge: {exc}") from exc
    finally:
        shutil.rmtree(cartella, ignore_errors=True)


def sintetizza_sezioni(
    sezioni: list[tuple[str, float]],
    percorso_uscita: str | Path,
    impostazioni: dict[str, Any],
    logger: logging.Logger | None = None,
    voce: str | None = None,
    velocita: float | None = None,
    motore: str | None = None,
) -> dict[str, Any]:
    """Sintetizza con Gemini o Google Cloud TTS; su errore passa a edge-tts.

    ``sezioni`` contiene coppie (testo, pausa_dopo_in_secondi). Il motore
    ``edge`` salta del tutto Gemini e Google.
    """
    logger = logger or logging.getLogger("notiziario")
    sezioni = [(t.strip(), float(p)) for t, p in sezioni if t and t.strip()]
    if not sezioni:
        raise TTSError("Nessun testo da sintetizzare.")
    uscita = Path(percorso_uscita)
    uscita.parent.mkdir(parents=True, exist_ok=True)

    configurazione_voce = impostazioni.get("voce", {})
    motore = (motore or impostazioni.get("tts_motore", "gemini")).lower()
    voce_edge = voce
    if motore == "google":
        google = configurazione_voce.get("google", {})
        if not isinstance(google, dict):
            google = {}
        voce_google = str(google.get("nome") or "").strip() or (
            "it-IT-Chirp3-HD-Achernar"
        )
        if voce and str(voce).startswith("it-IT-"):
            voce = str(voce)
        else:
            voce = voce_google
        voce_edge = None
    else:
        voce = voce or str(configurazione_voce.get("nome", "Kore"))
    if velocita is None:
        velocita = float(configurazione_voce.get("velocita", 1.1))
    velocita = float(velocita)
    if not 0.75 <= velocita <= 1.25:
        raise TTSError("La velocità deve essere tra 0.75 e 1.25.")

    motivo_fallback = None
    if motore == "google":
        try:
            return sintetizza_sezioni_google(
                sezioni,
                uscita,
                impostazioni,
                logger,
                voce=voce,
                velocita=velocita,
            )
        except GoogleTTSError as exc:
            motivo_fallback = str(exc)
            logger.warning(
                "Google TTS non disponibile (%s). Passo a edge-tts.", motivo_fallback
            )
        except Exception as exc:  # pragma: no cover - difesa
            motivo_fallback = f"errore imprevisto ({type(exc).__name__})"
            logger.warning(
                "Google TTS non disponibile (%s). Passo a edge-tts.",
                motivo_fallback,
            )
    elif motore == "gemini":
        try:
            return sintetizza_sezioni_gemini(
                sezioni,
                uscita,
                impostazioni,
                logger,
                voce=voce,
                velocita=velocita,
            )
        except GeminiTTSError as exc:
            motivo_fallback = str(exc)
            logger.warning(
                "Gemini TTS non disponibile (%s). Passo a edge-tts.", motivo_fallback
            )
        except Exception as exc:  # pragma: no cover - difesa
            motivo_fallback = f"errore imprevisto ({type(exc).__name__})"
            logger.warning(
                "Gemini TTS non disponibile (%s). Passo a edge-tts.",
                motivo_fallback,
            )

    try:
        info = _sintetizza_edge(
            sezioni,
            uscita,
            impostazioni,
            logger,
            voce=voce_edge,
            velocita=velocita,
        )
        info["motivo_fallback"] = motivo_fallback
        return info
    except TTSError as exc:
        if motivo_fallback:
            raise TTSError(
                f"TTS principale: {motivo_fallback}; fallback edge fallito: {exc}"
            ) from exc
        raise


def sintetizza_anteprima(
    testo: str,
    percorso_uscita: str | Path,
    impostazioni: dict[str, Any],
    logger: logging.Logger | None = None,
    voce: str | None = None,
    velocita: float | None = None,
    motore: str | None = None,
) -> dict[str, Any]:
    """Anteprima breve: un solo blocco, senza pause finali."""
    return sintetizza_sezioni(
        [(testo, 0.0)],
        percorso_uscita,
        impostazioni,
        logger=logger,
        voce=voce,
        velocita=velocita,
        motore=motore,
    )


def genera_provini(
    cartella_uscita: str | Path,
    impostazioni: dict[str, Any],
    logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """Provini edge-tts storici (Isabella ed Elsa)."""
    logger = logger or logging.getLogger("notiziario")
    cartella = Path(cartella_uscita)
    cartella.mkdir(parents=True, exist_ok=True)
    edge = impostazioni.get("voce", {}).get("edge", {})
    voci = [
        ("isabella", str(edge.get("nome", "it-IT-IsabellaNeural"))),
        ("elsa", str(edge.get("alternativa", "it-IT-ElsaNeural"))),
    ]
    risultati = []
    pausa = float(impostazioni.get("tts", {}).get("pausa_chiamate", 3.0))
    for posizione, (nome_file, nome_voce) in enumerate(voci):
        if posizione > 0 and pausa > 0:
            time.sleep(pausa)
        uscita = cartella / f"provino-{nome_file}.mp3"
        logger.info("Genero il provino %s con %s.", nome_file, nome_voce)
        info = sintetizza_sezioni(
            [(TESTO_PROVINI, 0.0)],
            uscita,
            impostazioni,
            logger=logger,
            voce=nome_voce,
            velocita=1.0,
            motore="edge",
        )
        if not 20 <= info["durata"] <= 40:
            logger.warning(
                "Il provino %s dura %.1f s: fuori dall'intervallo 20-40 s.",
                nome_file,
                info["durata"],
            )
        risultati.append(
            {
                "voce": nome_voce,
                "file": str(uscita),
                "durata_secondi": round(float(info["durata"]), 2),
                "dimensione": info["dimensione"],
                "motore": info["motore"],
            }
        )
    return risultati
