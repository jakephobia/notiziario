"""Caricamento e validazione della configurazione e delle fonti RSS."""

from __future__ import annotations

import copy
import json
import re
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .categorie import CATEGORIA_DA_ASSEGNARE, CATEGORIE_IDS


ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


class ConfigError(Exception):
    """Errore di configurazione leggibile dall'utente."""


@dataclass(frozen=True)
class Fonte:
    nome: str
    url: str
    categoria: str
    attivo: bool = True
    controllo: str | None = None
    ultimo_controllo: str | None = None
    note: str | None = None


DEFAULT_SETTINGS: dict[str, Any] = {
    "versione": 2,
    "orario_generazione": "07:00",
    "durata_default": "standard",
    "nome_utente": "Jacopo",
    "tts_motore": "gemini",
    "suono_transizione": "ding",
    "suono_gain_db": 0,
    "outro": {"file": "config/outro.txt"},
    "silenzio_iniziale_ms": 1000,
    "tts_chunk_max_caratteri": 4500,
    "llm_modello_riserva": "gemini-3.1-flash-lite",
    "preset": {
        "svelto": {
            "minuti": 4,
            "copertine": 1,
            "secondarie": 4,
            "max_notizie": 6,
            "buone_notizie": 2,
            "parole_copertina": 240,
            "parole_secondaria": 95,
            "parole_buona_notizia": 100,
        },
        "standard": {
            "minuti": 7,
            "copertine": 2,
            "secondarie": 6,
            "max_notizie": 10,
            "buone_notizie": 2,
            "parole_copertina": 240,
            "parole_secondaria": 100,
            "parole_buona_notizia": 100,
        },
        "completo": {
            "minuti": 12,
            "copertine": 3,
            "secondarie": 8,
            "max_notizie": 14,
            "buone_notizie": 3,
            "parole_copertina": 260,
            "parole_secondaria": 110,
            "parole_buona_notizia": 100,
        },
    },
    "parole_per_minuto": 145,
    "intervallo_copertina": [220, 300],
    "intervallo_secondaria": [90, 130],
    "intervallo_buona_notizia": [90, 130],
    "categorie_default": [
        "italia",
        "mondo",
        "economia",
        "tecnologia",
        "scienza-salute",
        "cultura",
        "ambiente",
        "buone-notizie",
    ],
    "incipit": {"file": "config/incipit.txt"},
    "github": {"issue_categorie": 1, "repo_url": "https://github.com/jakephobia/notiziario"},
    "voce": {
        "nome": "Kore",
        "velocita": 1.1,
        "voci": [
            {"nome": "Kore", "genere": "F", "label": "Kore — femminile, calda"},
            {"nome": "Leda", "genere": "F", "label": "Leda — femminile, luminosa"},
            {"nome": "Charon", "genere": "M", "label": "Charon — maschile, profonda"},
            {"nome": "Puck", "genere": "M", "label": "Puck — maschile, vivace"},
            {"nome": "Orus", "genere": "M", "label": "Orus — maschile, riserva"},
        ],
        "edge": {"nome": "it-IT-IsabellaNeural", "alternativa": "it-IT-ElsaNeural"},
        "google": {
            "nome": "it-IT-Chirp3-HD-Achernar",
            "label": "Google Chirp 3 HD — Achernar",
            "genere": "",
        },
    },
    "tts_gemini": {
        "modello": "gemini-2.5-flash-preview-tts",
        "endpoint": (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "{modello}:generateContent"
        ),
        "timeout": 60,
        "max_caratteri_chunk": 4500,
        "direzione": (
            "Read aloud in a warm, lively, natural Italian female radio host "
            "voice, with varied pacing and clear pronunciation. Read only the "
            "Italian text below, not this instruction."
        ),
    },
    "tts_google": {
        "lingua": "it-IT",
        "endpoint": "https://texttospeech.googleapis.com/v1/text:synthesize",
        "max_caratteri_chunk": 3000,
        "timeout": 90,
    },
    "tts": {
        "pausa_sezione": 0.8,
        "pausa_notizia": 0.5,
        "tentativi": 2,
        "pausa_chiamate": 3.0,
        "max_retry_429": 2,
        "backoff_429": [5, 15, 30],
    },
    "audio": {
        "loudnorm": "loudnorm=I=-16:TP=-1.5:LRA=11",
        "sample_rate": 44100,
        "canali": 1,
        "bitrate": "96k",
        "musica": {
            "attivo": True,
            "file": "assets/musica-sottofondo.mp3",
            "volume_db": -18.0,
            "ducking": True,
            "ducking_threshold": 0.05,
            "ducking_ratio": 4.0,
            "fade_out_secondi": 3.0,
            "silenzio_finale_secondi": 3.0,
            "bitrate": "128k",
        },
    },
    "llm": {
        "modello": "gemini-2.5-flash",
        "temperatura": 0.6,
        "endpoint": (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "{modello}:generateContent"
        ),
        "timeout": 60,
        "max_output_tokens": 16384,
    },
    "arricchimento": {
        "attivo": True,
        "max_articoli": 20,
        "max_per_cluster": 3,
        "timeout": 15,
        "max_bytes": 2000000,
        "max_caratteri_articolo": 6000,
        "min_caratteri_estratto": 300,
        "rispetta_robots": True,
        "cache_dir": "cache/articoli",
        "ttl_ore": 24,
        "max_redirect": 3,
    },
    "clustering": {"soglia": 0.58, "max_per_feed": 30, "max_totale": 3000},
    "fetch": {"timeout": 15, "retry": 2, "max_workers": 8, "ore_default": 24},
    "buone_notizie": {"max_candidati": 30},
    "controllo_feed": {
        "min_caratteri_testo": 40,
        "min_percentuale_con_testo": 50,
        "max_percentuale_paywall": 25,
        "min_item_valutati": 5,
        "giorni_inattivita": 180,
        "max_item_valutati": 30,
    },
    "importa_feed": {"max_feed": 200, "max_file_mb": 5},
    "stato": {"visti": "state/visti.json", "giorni_pruning": 60},
    "feed": {
        "titolo": "Il notiziario di Jacopo",
        "descrizione": (
            "Le notizie del giorno scelte da Jacopo, lette in italiano. "
            "Un riassunto quotidiano delle notizie italiane e internazionali."
        ),
        "autore": "Notiziario",
        "lingua": "it-it",
        "sito_url": "https://jakephobia.github.io/notiziario/",
        "base_url": "https://github.com/jakephobia/notiziario/releases/download",
        "copertina": "copertina.png",
        "max_episodi": 60,
    },
}


def _unisci(base: Any, sopra: Any) -> Any:
    """Unisce ricorsivamente due strutture; i valori di ``sopra`` vincono."""
    if isinstance(base, dict) and isinstance(sopra, dict):
        risultato = copy.deepcopy(base)
        for chiave, valore in sopra.items():
            if chiave in risultato:
                risultato[chiave] = _unisci(risultato[chiave], valore)
            else:
                risultato[chiave] = copy.deepcopy(valore)
        return risultato
    return copy.deepcopy(sopra)


def carica_impostazioni(percorso: str | Path | None = None) -> dict[str, Any]:
    """Legge config/impostazioni.json e completa i valori mancanti."""
    path = Path(percorso) if percorso else CONFIG_DIR / "impostazioni.json"
    if not path.exists():
        raise ConfigError(f"File di impostazioni non trovato: {path}")
    try:
        dati = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"JSON non valido in {path}: {exc}") from exc
    if not isinstance(dati, dict):
        raise ConfigError(f"Il file {path} deve contenere un oggetto JSON.")
    impostazioni = _unisci(DEFAULT_SETTINGS, dati)
    valida_impostazioni(impostazioni)
    return impostazioni


def valida_impostazioni(impostazioni: dict[str, Any]) -> None:
    """Controlla i valori che, se sbagliati, romperebbero la pipeline."""
    preset = impostazioni.get("preset")
    if not isinstance(preset, dict) or not preset:
        raise ConfigError("La sezione 'preset' è mancante o vuota.")
    durata_default = impostazioni.get("durata_default")
    if durata_default not in preset:
        raise ConfigError(
            f"durata_default '{durata_default}' non è tra i preset: "
            f"{', '.join(preset)}"
        )
    orario = impostazioni.get("orario_generazione", "07:00")
    if not isinstance(orario, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):00", orario):
        raise ConfigError("orario_generazione deve essere un'ora intera HH:00 tra 00:00 e 23:00.")

    for nome, valori in preset.items():
        if not isinstance(valori, dict):
            raise ConfigError(f"Il preset '{nome}' deve essere un oggetto.")
        for chiave in (
            "minuti",
            "copertine",
            "secondarie",
            "max_notizie",
            "buone_notizie",
            "parole_copertina",
            "parole_secondaria",
            "parole_buona_notizia",
        ):
            valore = valori.get(chiave)
            if not isinstance(valore, int) or valore < 1:
                raise ConfigError(
                    f"Nel preset '{nome}' la voce '{chiave}' deve essere un intero positivo."
                )
        if valori["max_notizie"] < valori["copertine"]:
            raise ConfigError(
                f"Nel preset '{nome}' max_notizie non può essere minore di copertine."
            )
        if valori["buone_notizie"] > valori["max_notizie"]:
            raise ConfigError(
                f"Nel preset '{nome}' buone_notizie non può superare max_notizie."
            )

    categorie = impostazioni.get("categorie_default")
    if not isinstance(categorie, list) or not categorie:
        raise ConfigError("'categorie_default' deve essere una lista non vuota.")
    for categoria in categorie:
        if categoria not in CATEGORIE_IDS:
            raise ConfigError(
                f"Categoria sconosciuta in categorie_default: '{categoria}'. "
                f"Valide: {', '.join(CATEGORIE_IDS)}"
            )

    if not isinstance(impostazioni.get("nome_utente", ""), str):
        raise ConfigError("'nome_utente' deve essere una stringa.")
    if not isinstance(impostazioni.get("incipit", {}), dict):
        raise ConfigError("'incipit' deve essere un oggetto.")
    if not isinstance(impostazioni.get("github", {}).get("repo_url", ""), str):
        raise ConfigError("github.repo_url deve essere una stringa.")

    motore = impostazioni.get("tts_motore", "gemini")
    if motore not in {"gemini", "edge", "google"}:
        raise ConfigError("tts_motore deve essere 'gemini', 'edge' oppure 'google'.")

    suono = impostazioni.get("suono_transizione", "ding")
    if suono not in {"ding", "chime", "whoosh", "nessuno"}:
        raise ConfigError("suono_transizione deve essere ding, chime, whoosh o nessuno.")
    gain = impostazioni.get("suono_gain_db", 0)
    if not isinstance(gain, (int, float)) or not -30 <= float(gain) <= 12:
        raise ConfigError("suono_gain_db deve essere tra -30 e 12 dB.")
    if not isinstance(impostazioni.get("outro", {}), dict) or not impostazioni["outro"].get("file"):
        raise ConfigError("outro.file è mancante.")
    silenzio = impostazioni.get("silenzio_iniziale_ms")
    if not isinstance(silenzio, int) or not 0 <= silenzio <= 5000:
        raise ConfigError("silenzio_iniziale_ms deve essere un intero tra 0 e 5000.")
    musica = impostazioni.get("audio", {}).get("musica", {})
    if not isinstance(musica, dict):
        raise ConfigError("audio.musica deve essere un oggetto.")
    if musica.get("attivo"):
        if not str(musica.get("file", "")).strip():
            raise ConfigError("audio.musica.file è mancante.")
        volume = musica.get("volume_db")
        if not isinstance(volume, (int, float)) or not -40 <= float(volume) <= 0:
            raise ConfigError("audio.musica.volume_db deve essere tra -40 e 0 dB.")
        if not isinstance(musica.get("ducking"), bool):
            raise ConfigError("audio.musica.ducking deve essere true o false.")
        for chiave in ("fade_out_secondi", "silenzio_finale_secondi"):
            valore = musica.get(chiave)
            if not isinstance(valore, (int, float)) or not 0 <= float(valore) <= 15:
                raise ConfigError(
                    f"audio.musica.{chiave} deve essere un numero tra 0 e 15."
                )
        if not str(musica.get("bitrate", "")).strip():
            raise ConfigError("audio.musica.bitrate è mancante.")
    chunk_max = impostazioni.get("tts_chunk_max_caratteri")
    if not isinstance(chunk_max, int) or not 500 <= chunk_max <= 20000:
        raise ConfigError(
            "tts_chunk_max_caratteri deve essere un intero tra 500 e 20000."
        )
    riserva = impostazioni.get("llm_modello_riserva")
    if not isinstance(riserva, str):
        raise ConfigError("llm_modello_riserva deve essere una stringa.")

    voce = impostazioni.get("voce", {})
    if not isinstance(voce, dict) or not voce.get("nome"):
        raise ConfigError("La voce TTS 'voce.nome' è mancante.")
    voci = voce.get("voci")
    if not isinstance(voci, list) or not voci:
        raise ConfigError("voce.voci deve essere una lista non vuota.")
    nomi_voci = set()
    for elemento in voci:
        if not isinstance(elemento, dict) or not elemento.get("nome"):
            raise ConfigError("Ogni voce deve avere un 'nome'.")
        nomi_voci.add(str(elemento["nome"]).strip())
    if str(voce["nome"]).strip() not in nomi_voci:
        raise ConfigError(
            f"voce.nome '{voce['nome']}' non è tra le voci configurate: "
            f"{', '.join(sorted(nomi_voci))}"
        )
    velocita = voce.get("velocita")
    if not isinstance(velocita, (int, float)) or not 0.75 <= float(velocita) <= 1.25:
        raise ConfigError("voce.velocita deve essere un numero tra 0.75 e 1.25.")
    if not isinstance(voce.get("edge", {}), dict):
        raise ConfigError("voce.edge deve essere un oggetto.")
    if not isinstance(voce.get("google", {}), dict):
        raise ConfigError("voce.google deve essere un oggetto.")

    tts = impostazioni.get("tts", {})
    for chiave in ("pausa_chiamate",):
        valore = tts.get(chiave)
        if not isinstance(valore, (int, float)) or float(valore) < 0:
            raise ConfigError(f"tts.{chiave} deve essere un numero non negativo.")
    for chiave in ("max_retry_429",):
        valore = tts.get(chiave)
        if not isinstance(valore, int) or valore < 0:
            raise ConfigError(f"tts.{chiave} deve essere un intero non negativo.")
    backoff = tts.get("backoff_429")
    if not isinstance(backoff, list) or not all(
        isinstance(x, (int, float)) and x >= 0 for x in backoff
    ):
        raise ConfigError("tts.backoff_429 deve essere una lista di numeri.")

    tts_gemini = impostazioni.get("tts_gemini", {})
    if not isinstance(tts_gemini.get("modello"), str) or not tts_gemini["modello"]:
        raise ConfigError("tts_gemini.modello è mancante.")
    for chiave in ("timeout", "max_caratteri_chunk"):
        valore = tts_gemini.get(chiave)
        if not isinstance(valore, int) or valore < 1:
            raise ConfigError(f"tts_gemini.{chiave} deve essere un intero positivo.")

    tts_google = impostazioni.get("tts_google", {})
    if not isinstance(tts_google, dict):
        raise ConfigError("tts_google deve essere un oggetto.")
    if not isinstance(tts_google.get("lingua"), str) or not tts_google["lingua"].strip():
        raise ConfigError("tts_google.lingua deve essere una stringa non vuota.")
    endpoint_google = tts_google.get("endpoint")
    if not isinstance(endpoint_google, str) or not endpoint_google.startswith(
        ("http://", "https://")
    ):
        raise ConfigError("tts_google.endpoint deve essere un URL http(s).")
    chunk_google = tts_google.get("max_caratteri_chunk")
    if not isinstance(chunk_google, int) or not 500 <= chunk_google <= 5000:
        raise ConfigError(
            "tts_google.max_caratteri_chunk deve essere un intero tra 500 e 5000."
        )
    timeout_google = tts_google.get("timeout")
    if not isinstance(timeout_google, int) or not 10 <= timeout_google <= 300:
        raise ConfigError("tts_google.timeout deve essere un intero tra 10 e 300.")

    arricchimento = impostazioni.get("arricchimento", {})
    if not isinstance(arricchimento.get("attivo"), bool):
        raise ConfigError("arricchimento.attivo deve essere true/false.")
    for chiave in (
        "max_articoli",
        "max_per_cluster",
        "timeout",
        "max_bytes",
        "max_caratteri_articolo",
        "min_caratteri_estratto",
        "ttl_ore",
        "max_redirect",
    ):
        valore = arricchimento.get(chiave)
        if not isinstance(valore, int) or valore < 1:
            raise ConfigError(f"arricchimento.{chiave} deve essere un intero positivo.")
    if not isinstance(arricchimento.get("rispetta_robots"), bool):
        raise ConfigError("arricchimento.rispetta_robots deve essere true/false.")
    if not isinstance(arricchimento.get("cache_dir"), str):
        raise ConfigError("arricchimento.cache_dir deve essere un percorso.")

    clustering = impostazioni.get("clustering", {})
    soglia = clustering.get("soglia")
    if not isinstance(soglia, (int, float)) or not 0 <= soglia <= 1:
        raise ConfigError("clustering.soglia deve essere un numero tra 0 e 1.")
    for chiave in ("max_per_feed", "max_totale"):
        valore = clustering.get(chiave)
        if not isinstance(valore, int) or valore < 1:
            raise ConfigError(f"clustering.{chiave} deve essere un intero positivo.")

    fetch = impostazioni.get("fetch", {})
    for chiave in ("timeout", "retry", "max_workers", "ore_default"):
        valore = fetch.get(chiave)
        if not isinstance(valore, int) or valore < 1:
            raise ConfigError(f"fetch.{chiave} deve essere un intero positivo.")

    controllo = impostazioni.get("controllo_feed", {})
    for chiave in (
        "min_caratteri_testo",
        "min_percentuale_con_testo",
        "max_percentuale_paywall",
        "min_item_valutati",
        "giorni_inattivita",
        "max_item_valutati",
    ):
        valore = controllo.get(chiave)
        if not isinstance(valore, int) or valore < 1:
            raise ConfigError(f"controllo_feed.{chiave} deve essere un intero positivo.")
    if controllo["min_percentuale_con_testo"] > 100:
        raise ConfigError("controllo_feed.min_percentuale_con_testo non può superare 100.")
    if controllo["max_percentuale_paywall"] > 100:
        raise ConfigError("controllo_feed.max_percentuale_paywall non può superare 100.")

    importa = impostazioni.get("importa_feed", {})
    for chiave in ("max_feed", "max_file_mb"):
        valore = importa.get(chiave)
        if not isinstance(valore, int) or valore < 1:
            raise ConfigError(f"importa_feed.{chiave} deve essere un intero positivo.")

    stato = impostazioni.get("stato", {})
    if not isinstance(stato.get("visti"), str) or not stato["visti"]:
        raise ConfigError("stato.visti deve essere un percorso.")
    if not isinstance(stato.get("giorni_pruning"), int) or stato["giorni_pruning"] < 1:
        raise ConfigError("stato.giorni_pruning deve essere un intero positivo.")

    feed = impostazioni.get("feed", {})
    if not isinstance(feed, dict) or not feed.get("base_url"):
        raise ConfigError("feed.base_url è mancante.")
    if not isinstance(feed.get("sito_url"), str) or not feed["sito_url"]:
        raise ConfigError("feed.sito_url è mancante.")
    if not isinstance(feed.get("copertina"), str) or not feed["copertina"]:
        raise ConfigError("feed.copertina è mancante.")
    if not isinstance(feed.get("max_episodi"), int) or feed["max_episodi"] < 1:
        raise ConfigError("feed.max_episodi deve essere un intero positivo.")


def _booleano(valore: Any, default: bool = True) -> bool:
    if valore is None:
        return default
    if isinstance(valore, bool):
        return valore
    if isinstance(valore, (int, float)):
        return bool(valore)
    testo = str(valore).strip().casefold()
    if testo in {"false", "no", "0", "off", "disattivo", "disattivata"}:
        return False
    if testo in {"true", "yes", "1", "on", "attivo", "attivata"}:
        return True
    return default


def carica_fonti(
    percorso: str | Path | None = None, solo_attive: bool = True
) -> list[Fonte]:
    """Legge config/fonti.yaml, valida le categorie e scarta URL duplicati.

    ``solo_attive=False`` serve a import, controllo e comandi di elenco.
    """
    path = Path(percorso) if percorso else CONFIG_DIR / "fonti.yaml"
    if not path.exists():
        raise ConfigError(f"File delle fonti non trovato: {path}")
    try:
        dati = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML non valido in {path}: {exc}") from exc

    if not isinstance(dati, dict) or not isinstance(dati.get("fonti"), list):
        raise ConfigError(f"Il file {path} deve contenere una lista sotto 'fonti:'.")

    fonti: list[Fonte] = []
    visti: set[str] = set()
    for indice, voce in enumerate(dati["fonti"], start=1):
        if not isinstance(voce, dict):
            raise ConfigError(f"Fonte numero {indice}: deve essere un oggetto YAML.")
        nome = str(voce.get("nome", "")).strip()
        url = str(voce.get("url", "")).strip()
        categoria = str(voce.get("categoria", "")).strip()
        attivo = _booleano(voce.get("attivo"), default=True)
        if not nome:
            raise ConfigError(f"Fonte numero {indice}: 'nome' mancante.")
        if not url.startswith(("http://", "https://")):
            raise ConfigError(f"Fonte '{nome}': URL non valido ({url!r}).")
        if categoria not in CATEGORIE_IDS and categoria != CATEGORIA_DA_ASSEGNARE:
            raise ConfigError(
                f"Fonte '{nome}': categoria sconosciuta '{categoria}'. "
                f"Valide: {', '.join(CATEGORIE_IDS)} oppure '{CATEGORIA_DA_ASSEGNARE}'."
            )
        if categoria == CATEGORIA_DA_ASSEGNARE:
            attivo = False
        if not attivo and solo_attive:
            continue
        if url in visti:
            continue
        visti.add(url)
        fonti.append(
            Fonte(
                nome=nome,
                url=url,
                categoria=categoria,
                attivo=attivo,
                controllo=(
                    str(voce.get("controllo")).strip()
                    if voce.get("controllo") is not None
                    else None
                ),
                ultimo_controllo=(
                    str(voce.get("ultimo_controllo")).strip()
                    if voce.get("ultimo_controllo") is not None
                    else None
                ),
                note=(
                    str(voce.get("note")).strip()
                    if voce.get("note") is not None
                    else None
                ),
            )
        )

    if not fonti:
        raise ConfigError(
            f"Nessuna fonte {'attiva ' if solo_attive else ''}valida in {path}."
        )
    return fonti


def carica_fonti_tutte(percorso: str | Path | None = None) -> list[Fonte]:
    """Tutte le fonti, comprese quelle spente e da assegnare."""
    return carica_fonti(percorso, solo_attive=False)


def numero_issue_categorie(impostazioni: dict[str, Any]) -> int | None:
    """Legge il numero della issue da env o config; None se non configurata."""
    grezzo = os.environ.get("GITHUB_ISSUE_CATEGORIE")
    if grezzo is None or str(grezzo).strip() == "":
        grezzo = impostazioni.get("github", {}).get("issue_categorie")
    if grezzo is None or str(grezzo).strip() == "":
        return None
    try:
        numero = int(str(grezzo).strip())
    except ValueError as exc:
        raise ConfigError(
            "GITHUB_ISSUE_CATEGORIE / github.issue_categorie deve essere un numero di issue."
        ) from exc
    if numero < 1:
        raise ConfigError("Il numero della issue deve essere positivo.")
    return numero


def repository_github() -> str | None:
    """Restituisce 'owner/repo' dall'ambiente GitHub Actions, se presente."""
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    return repo or None
