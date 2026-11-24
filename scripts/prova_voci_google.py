"""Una tantum: elenca le voci italiane Chirp 3 HD e genera 4 campioni audio.

Uso locale:
    set GOOGLE_CLOUD_TTS_API_KEY=...
    python scripts/prova_voci_google.py

Lo script non pubblica nulla: scrive in ``output/voci-google.json`` e in
``output/prove-voci/`` (mp3 + index.html). La chiave non viene mai stampata.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests


LINGUA = "it-IT"
VOCI_URL = "https://texttospeech.googleapis.com/v1/voices"
SINTESI_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
PROVE_DIR = OUTPUT_DIR / "prove-voci"
TEMPO_LIMITE = 60

# Voci preferite, se presenti nell'elenco italiano.
PREFERITE = [
    "it-IT-Chirp3-HD-Achernar",
    "it-IT-Chirp3-HD-Aoede",
    "it-IT-Chirp3-HD-Charon",
    "it-IT-Chirp3-HD-Puck",
    "it-IT-Chirp3-HD-Kore",
]

TESTO_PROVA = (
    "Buongiorno, questa è una prova delle voci del Notiziario. "
    "Il governo ha approvato il nuovo piano per la scuola e per i trasporti, "
    "secondo quanto riportano ANSA e Repubblica. "
    "Il 3 per cento delle risorse sarà dedicato alla ricerca, mentre le regioni "
    "chiedono più tempo per organizzare i servizi. "
    "La notizia è stata confermata anche da Il Post. "
    "Ascolta con attenzione il ritmo e la chiarezza: scegli tu la voce migliore."
)


class ErroreProva(Exception):
    """Errore con messaggio leggibile per l'utente."""


def _chiave() -> str:
    chiave = os.environ.get("GOOGLE_CLOUD_TTS_API_KEY", "").strip()
    if not chiave:
        raise ErroreProva(
            "GOOGLE_CLOUD_TTS_API_KEY non impostata: esportala nell'ambiente "
            "o configura il secret nel workflow."
        )
    return chiave


def _slug(nome: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", nome.casefold()).strip("-")
    return slug or "voce"


def _genere_etichetta(valore: Any) -> str:
    testo = str(valore or "").strip().upper()
    if testo == "FEMALE":
        return "femminile"
    if testo == "MALE":
        return "maschile"
    return ""


def elenca_voci(chiave: str) -> list[dict[str, Any]]:
    try:
        risposta = requests.get(
            VOCI_URL,
            params={"languageCode": LINGUA},
            headers={"X-Goog-Api-Key": chiave},
            timeout=TEMPO_LIMITE,
        )
    except requests.RequestException as exc:
        raise ErroreProva(
            f"Errore di rete nel recupero delle voci ({type(exc).__name__})."
        ) from exc
    if risposta.status_code >= 400:
        dettaglio = ""
        try:
            corpo = risposta.json()
            dettaglio = str(corpo.get("error", {}).get("message", ""))
        except ValueError:
            pass
        messaggio = f"HTTP {risposta.status_code} nel recupero delle voci"
        if dettaglio:
            messaggio += f": {dettaglio}"
        raise ErroreProva(messaggio)
    try:
        dati = risposta.json()
    except ValueError as exc:
        raise ErroreProva("Risposta del servizio voci non JSON.") from exc
    voci = dati.get("voices") if isinstance(dati, dict) else None
    if not isinstance(voci, list):
        raise ErroreProva("Risposta del servizio voci senza elenco 'voices'.")
    filtrate = [
        v
        for v in voci
        if isinstance(v, dict) and "Chirp3-HD" in str(v.get("name", ""))
    ]
    if not filtrate:
        raise ErroreProva("Nessuna voce italiana Chirp 3 HD trovata.")
    return filtrate


def scegli_quattro(voci: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mescola femminile e maschile, preferendo le voci note."""
    per_nome = {str(v.get("name")): v for v in voci}
    femmine = [v for v in voci if _genere_etichetta(v.get("ssmlGender")) == "femminile"]
    maschi = [v for v in voci if _genere_etichetta(v.get("ssmlGender")) == "maschile"]

    def ordina(lista: list[dict[str, Any]]) -> list[dict[str, Any]]:
        preferite = [per_nome[n] for n in PREFERITE if n in per_nome and per_nome[n] in lista]
        resto = [v for v in lista if v not in preferite]
        return preferite + resto

    scelte: list[dict[str, Any]] = []
    for lista in (femmine, maschi):
        prese = 0
        for voce in ordina(lista):
            if prese >= 2 or len(scelte) >= 4:
                break
            if voce not in scelte:
                scelte.append(voce)
                prese += 1
    # Completa fino a 4 con le voci rimanenti (generi mancanti o elenco corto).
    for voce in ordina(list(voci)):
        if len(scelte) >= 4:
            break
        if voce not in scelte:
            scelte.append(voce)
    return scelte[:4]


def sintetizza(chiave: str, voce: str) -> bytes:
    payload = {
        "input": {"text": TESTO_PROVA},
        "voice": {"languageCode": LINGUA, "name": voce},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.0},
    }
    try:
        risposta = requests.post(
            SINTESI_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": chiave,
            },
            timeout=TEMPO_LIMITE,
        )
    except requests.RequestException as exc:
        raise ErroreProva(
            f"Errore di rete nella sintesi di {voce} ({type(exc).__name__})."
        ) from exc
    if risposta.status_code >= 400:
        dettaglio = ""
        try:
            corpo = risposta.json()
            dettaglio = str(corpo.get("error", {}).get("message", ""))
        except ValueError:
            pass
        messaggio = f"HTTP {risposta.status_code} nella sintesi di {voce}"
        if dettaglio:
            messaggio += f": {dettaglio}"
        raise ErroreProva(messaggio)
    try:
        dati = risposta.json()
    except ValueError as exc:
        raise ErroreProva(f"Risposta di sintesi non JSON per {voce}.") from exc
    contenuto = dati.get("audioContent") if isinstance(dati, dict) else None
    if not contenuto:
        raise ErroreProva(f"Risposta senza audioContent per {voce}.")
    try:
        return base64.b64decode(contenuto, validate=True)
    except Exception as exc:
        raise ErroreProva(f"Audio non decodificabile per {voce}.") from exc


def scrivi_indice(campioni: list[dict[str, str]]) -> None:
    righe = []
    for campione in campioni:
        etichetta = campione["etichetta"]
        righe.append(
            "    <section class=\"voce\">\n"
            f"      <h2>{html.escape(etichetta)}</h2>\n"
            f"      <audio controls preload=\"none\" "
            f"src=\"{html.escape(campione['file'])}\"></audio>\n"
            f"      <p>{html.escape(campione['nome'])}</p>\n"
            "    </section>"
        )
    documento = (
        "<!doctype html>\n"
        "<html lang=\"it\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "  <title>Prove voci Google Chirp 3 HD</title>\n"
        "  <style>\n"
        "    body { font-family: system-ui, sans-serif; margin: 2rem; background: #111; color: #eee; }\n"
        "    h1 { font-size: 1.4rem; }\n"
        "    .voce { background: #1c1c1c; border-radius: 12px; padding: 1rem; margin: 1rem 0; }\n"
        "    .voce h2 { font-size: 1.1rem; margin: 0 0 .5rem; }\n"
        "    .voce p { color: #aaa; margin: .5rem 0 0; font-size: .85rem; }\n"
        "    audio { width: 100%; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <h1>Prove voci Google Chirp 3 HD (it-IT)</h1>\n"
        "  <p>Stesso testo di prova, speakingRate 1.0.</p>\n"
        + "\n".join(righe)
        + "\n</body>\n</html>\n"
    )
    (PROVE_DIR / "index.html").write_text(documento, encoding="utf-8", newline="\n")


def main() -> int:
    try:
        chiave = _chiave()
        voci = elenca_voci(chiave)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        PROVE_DIR.mkdir(parents=True, exist_ok=True)

        elenco = [
            {
                "nome": str(v.get("name", "")),
                "genere": str(v.get("ssmlGender", "")),
                "lingue": v.get("languageCodes", []),
            }
            for v in voci
        ]
        (OUTPUT_DIR / "voci-google.json").write_text(
            json.dumps(elenco, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"Voci italiane Chirp 3 HD: {len(elenco)}")
        for voce in elenco:
            print(f"- {voce['nome']} ({voce['genere'] or 'genere sconosciuto'})")

        scelte = scegli_quattro(voci)
        if not scelte:
            raise ErroreProva("Nessuna voce selezionabile per i campioni.")

        campioni: list[dict[str, str]] = []
        for voce in scelte:
            nome = str(voce.get("name"))
            genere = _genere_etichetta(voce.get("ssmlGender"))
            file_name = f"{_slug(nome)}.mp3"
            print(f"Sintetizzo {nome}...")
            audio = sintetizza(chiave, nome)
            (PROVE_DIR / file_name).write_bytes(audio)
            campioni.append(
                {
                    "nome": nome,
                    "file": file_name,
                    "etichetta": f"{nome} — {genere}" if genere else nome,
                }
            )

        scrivi_indice(campioni)
        print(f"Campioni salvati in {PROVE_DIR}")
        return 0
    except ErroreProva as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
