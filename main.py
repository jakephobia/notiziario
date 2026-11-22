"""Entrypoint CLI del Notiziario."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from notiziario.categorie import (
    CATEGORIE_IDS,
    CategorieError,
    label_categoria,
    leggi_issue,
    parse_issue_body,
)
from notiziario.clustering import clusterizza
from notiziario.config import (
    ConfigError,
    carica_fonti,
    carica_fonti_tutte,
    carica_impostazioni,
    numero_issue_categorie,
    repository_github,
)
from notiziario.arricchisci import arricchisci_selezioni
from notiziario.traduzione import TraduzioneError, prepara_selezioni_italiane
from notiziario.audio import AudioError, info_audio as leggi_info_audio, inserisci_suoni
from notiziario.copione import (
    blocchi_per_tts,
    genera_copione,
    prova_llm,
    sezioni_tts_strutturate,
)
from notiziario.controllo_feed import (
    aggiorna_fonti_con_controllo,
    controlla_tutte,
    salva_report,
    stampa_tabella,
)
from notiziario.feed import (
    Episodio,
    aggiorna_docs,
    fonti_pubbliche,
    normalizza_sito_url,
    scrivi_impostazioni_pubbliche,
)
from notiziario.fetch import fetch_all
from notiziario.fonti_io import scrivi_fonti_yaml
from notiziario.importa_feed import elenco_fonti, importa_feed, stampa_report
from notiziario.modelli import test_modelli
from notiziario.outro import (
    applica_outro,
    leggi_modello_outro,
    risolvi_outro,
    scegli_modello as scegli_modello_outro,
)
from notiziario.incipit import (
    aggiungi_incipit,
    leggi_modello_incipit,
    risolvi_incipit,
    scegli_modello,
)
from notiziario.positivita import filtra_buone_notizie
from notiziario.selezione import NotiziaSelezionata, seleziona
from notiziario.stile import registra_avvisi
from notiziario.tempo import adesso_roma, data_iso_roma
from notiziario.testi import (
    conta_parole,
    data_in_italiano,
    durata_umana,
    elenco_naturale,
)
from notiziario.tts import (
    TTSError,
    genera_provini,
    sintetizza_anteprima,
    sintetizza_sezioni,
)
from notiziario.visti import Visti
from notiziario.voce import VoceScelta, risolvi_voce


BASE = Path(__file__).resolve().parent


def _percorso_fonti(args: argparse.Namespace) -> Path:
    if args.fonti == "__ELENCA__":
        return BASE / "config" / "fonti.yaml"
    return Path(args.fonti)


def _percorso_base(valore: str | None, default: str) -> Path:
    path = Path(valore or default)
    return path if path.is_absolute() else BASE / path


class ErroreBloccante(Exception):
    """Errore che impedisce di produrre un episodio valido."""


def _intero_positivo(valore: str) -> int:
    try:
        numero = int(valore)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("deve essere un numero intero") from exc
    if numero < 1:
        raise argparse.ArgumentTypeError("deve essere maggiore di zero")
    return numero


def costruisci_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notiziario",
        description=(
            "Scarica le notizie RSS, crea il copione italiano e genera il podcast mp3."
        ),
    )
    parser.add_argument(
        "--durata",
        choices=("svelto", "standard", "completo"),
        help="Durata dell'episodio (default dal file impostazioni.json).",
    )
    parser.add_argument(
        "--ore",
        type=_intero_positivo,
        help="Finestra delle notizie in ore (default 24).",
    )
    parser.add_argument(
        "--notizie",
        type=_intero_positivo,
        help="Numero massimo di notizie nell'episodio.",
    )
    parser.add_argument(
        "--senza-audio",
        action="store_true",
        help="Crea solo copione e stato, senza TTS.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch e copione sì; niente TTS, feed o pubblicazione.",
    )
    parser.add_argument(
        "--test-llm",
        action="store_true",
        help="Prova la chiave GEMINI_API_KEY con una richiesta minima.",
    )
    parser.add_argument(
        "--test-modelli",
        action="store_true",
        help="Elenca i modelli e prova una chiamata minima sui candidati.",
    )
    parser.add_argument(
        "--provini",
        action="store_true",
        help="Genera i due provini edge-tts storici.",
    )
    parser.add_argument(
        "--anteprima-voce",
        nargs="?",
        const="",
        default=None,
        metavar="FRASE",
        help=(
            "Genera solo un mp3 breve di anteprima voce; frase opzionale. "
            "Non fa fetch, copione o episodio."
        ),
    )
    parser.add_argument("--voce", help="Voce Gemini (Kore, Leda, Charon, Puck, Orus).")
    parser.add_argument(
        "--anteprima-suono",
        nargs="?",
        const="",
        choices=("", "ding", "chime", "whoosh"),
        help="Copia i suoni di transizione in output/anteprima (senza nome: tutti).",
    )
    parser.add_argument(
        "--velocita",
        type=float,
        help="Velocità TTS tra 0.75 e 1.25, step 0.05 (default 1.1).",
    )
    parser.add_argument(
        "--tts-motore",
        choices=("gemini", "edge"),
        help="Forza il motore TTS.",
    )
    parser.add_argument(
        "--config",
        default=str(BASE / "config" / "impostazioni.json"),
        help="Percorso del file impostazioni.json.",
    )
    parser.add_argument(
        "--fonti",
        nargs="?",
        const="__ELENCA__",
        default=str(BASE / "config" / "fonti.yaml"),
        help=(
            "Percorso di fonti.yaml. Usato da solo, stampa l'elenco numerato "
            "delle fonti e termina."
        ),
    )
    parser.add_argument(
        "--elenca-fonti",
        action="store_true",
        help="Stampa l'elenco numerato delle fonti e termina.",
    )
    parser.add_argument(
        "--importa-feed",
        metavar="PERCORSO",
        help="Importa OPML, TXT, CSV o JSON di feed RSS.",
    )
    parser.add_argument(
        "--attiva-tutte",
        action="store_true",
        help="Attiva le nuove fonti importate che superano il controllo.",
    )
    parser.add_argument(
        "--attiva-fonti",
        metavar="1,3,5",
        help="Attiva le nuove fonti agli indici dell'elenco stampato.",
    )
    parser.add_argument(
        "--categoria",
        help="Categoria da applicare alle nuove fonti senza categoria.",
    )
    parser.add_argument(
        "--controlla-feed",
        action="store_true",
        help="Controlla testo, paywall, podcast e inattività dei feed.",
    )
    parser.add_argument(
        "--disattiva-non-ok",
        action="store_true",
        help="Con il controllo feed, spegne anche le fonti esistenti non OK.",
    )
    parser.add_argument(
        "--incipit",
        help="Percorso alternativo di config/incipit.txt.",
    )
    parser.add_argument(
        "--stato-visti",
        help="Percorso alternativo di state/visti.json.",
    )
    parser.add_argument(
        "--output",
        default=str(BASE / "output"),
        help="Cartella degli artefatti locali (default output).",
    )
    parser.add_argument(
        "--docs",
        default=str(BASE / "docs"),
        help="Cartella del sito e del feed (default docs).",
    )
    parser.add_argument(
        "--feed-base-url",
        help="Override di feed.base_url (utile nel workflow GitHub).",
    )
    parser.add_argument(
        "--feed-site-url",
        help="Override di feed.sito_url (in cloud: https://owner.github.io/repo/).",
    )
    parser.add_argument(
        "--no-feed",
        action="store_true",
        help="Non aggiornare docs/ (utile per prove locali).",
    )
    return parser


def configura_logging(cartella_log: Path, data_iso: str) -> logging.Logger:
    cartella_log.mkdir(parents=True, exist_ok=True)
    percorso = cartella_log / f"run-{data_iso}.log"
    logger = logging.getLogger("notiziario")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    file_handler = logging.FileHandler(percorso, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(file_handler)
    logger.addHandler(console)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logger.info("Log di questa esecuzione: %s", percorso)
    return logger


def _corpo_issue(
    impostazioni: dict[str, Any], logger: logging.Logger
) -> tuple[str | None, list[str]]:
    """Legge una sola volta la issue usata per categorie e incipit."""
    try:
        numero = numero_issue_categorie(impostazioni)
    except ConfigError as exc:
        logger.warning("Issue: %s", exc)
        return None, [str(exc)]
    if numero is None:
        return None, []
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = repository_github()
    if not token or not repo:
        messaggio = (
            f"Issue #{numero} configurata, ma manca GITHUB_TOKEN o "
            "GITHUB_REPOSITORY. Uso configurazione locale."
        )
        logger.warning(messaggio)
        return None, [messaggio]
    try:
        return leggi_issue(token, repo, numero), []
    except CategorieError as exc:
        messaggio = f"Non leggo la issue #{numero}: {exc} Uso configurazione locale."
        logger.warning(messaggio)
        return None, [messaggio]


def _categorie_attive(
    impostazioni: dict[str, Any],
    logger: logging.Logger,
    corpo_issue: str | None = None,
) -> tuple[list[str], list[str]]:
    default = [c for c in CATEGORIE_IDS if c in set(impostazioni["categorie_default"])]
    if corpo_issue is None:
        logger.info("Categorie: uso i default di config/impostazioni.json.")
        return default, []
    attive, avvisi_issue = parse_issue_body(corpo_issue, default)
    for avviso in avvisi_issue:
        logger.warning("Categorie: %s", avviso)
    return attive, avvisi_issue


def _scrivi_copione_md(
    percorso: Path,
    copione: dict[str, Any],
    selezioni: list[NotiziaSelezionata],
    data_riferimento: datetime,
    preset_nome: str,
    preset: dict[str, Any],
    categorie_attive: list[str],
    durata_audio: float | None,
) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    modalita = "Gemini" if copione["modalita"] == "llm" else "Fallback locale"
    righe = [
        f"# {copione['titolo_episodio']}",
        "",
        f"- Data: {data_in_italiano(data_riferimento)}",
        f"- Target indicativo: circa {preset['minuti']} minuti ({preset_nome})",
        f"- Modalità di scrittura: {modalita}",
        f"- Categorie attive: {', '.join(label_categoria(c) for c in categorie_attive) or 'nessuna'}",
        f"- Parole del copione: {conta_parole(copione['testo'])}",
        f"- Descrizione breve: {copione.get('descrizione_breve', '')}",
    ]
    if durata_audio:
        righe.append(f"- Durata audio: {durata_umana(durata_audio)}")
    if copione.get("motivo_fallback"):
        righe.append(f"- Motivo del fallback: {copione['motivo_fallback']}")
    righe.extend(["", "## Copione", "", copione["testo"], "", "## Notizie incluse", ""])

    for selezione in selezioni:
        tipo = "Copertina" if selezione.copertina else "Secondaria"
        righe.append(
            f"### {selezione.ordine}. {selezione.titolo} — {tipo}"
        )
        righe.append(
            f"- Categoria: {label_categoria(selezione.categoria)}"
        )
        righe.append(f"- Fonti: {elenco_naturale(selezione.fonti)}")
        for articolo in selezione.cluster.ordina_articoli():
            righe.append(
                f"- {articolo.fonte}: [{articolo.titolo}]({articolo.link})"
            )
        righe.append("")
    percorso.write_text("\n".join(righe).rstrip() + "\n", encoding="utf-8", newline="\n")


def _solo_senza_novita(risultato) -> bool:
    return not risultato.articoli and risultato.senza_novita > 0

def _indici_transizioni(sezioni: int) -> list[int]:
    """Esclude sempre l'ultimo confine, quello prima dell'outro."""
    return list(range(max(0, sezioni - 2)))

def _prepara_blocchi_tts(
    copione: dict[str, Any], impostazioni: dict[str, Any]
) -> tuple[list[tuple[str, float]], list[int]]:
    """Usa i confini strutturati; fallback al vecchio chunking per copioni legacy."""
    sezioni, indici = sezioni_tts_strutturate(copione)
    if sezioni:
        parole_strutturate = sum(conta_parole(testo) for testo, _ in sezioni)
        parole_corpo = conta_parole(str(copione.get("testo", "")))
        if not parole_corpo or parole_strutturate >= parole_corpo * 0.85:
            return sezioni, indici
    # Copione legacy o confini incompleti: non indovinare i confini.
    sezioni = _prepara_sezioni_tts(str(copione.get("testo", "")), impostazioni)
    return sezioni, []


def _deve_salvare_visti(
    dry_run: bool, senza_audio: bool, info_audio: dict[str, Any] | None
) -> bool:
    return (not dry_run) and (info_audio is not None or senza_audio)


def _prepara_sezioni_tts(
    copione_testo: str, impostazioni: dict[str, Any]
) -> list[tuple[str, float]]:
    blocchi = blocchi_per_tts(copione_testo)
    if not blocchi:
        return []
    pausa_sezione = float(impostazioni.get("tts", {}).get("pausa_sezione", 0.8))
    pausa_notizia = float(impostazioni.get("tts", {}).get("pausa_notizia", 0.5))
    ultimo = len(blocchi) - 1
    sezioni: list[tuple[str, float]] = []
    for indice, blocco in enumerate(blocchi):
        if indice == ultimo:
            pausa = 0.0
        elif indice == 0 or indice == ultimo - 1:
            pausa = pausa_sezione
        else:
            pausa = pausa_notizia
        sezioni.append((blocco, pausa))
    return sezioni


def _stato(
    *,
    data_iso: str,
    copione: dict[str, Any],
    selezioni: list[NotiziaSelezionata],
    preset_nome: str,
    categorie_attive: list[str],
    categorie_default: list[str],
    ore: int,
    fonti_totali: int,
    risultato_fetch,
    clusters,
    avvisi_stile: list[str],
    errori_non_bloccanti: list[str],
    info_audio: dict[str, Any] | None,
    mp3_path: Path,
    copione_md: Path,
    copione_txt: Path,
    docs_info: dict[str, str] | None,
    impostazioni: dict[str, Any],
    dry_run: bool,
    senza_audio: bool,
    incipit: str = "",
    incipit_fonte: str = "file",
    esito_buone=None,
    visti_path: str | None = None,
    voce_scelta: VoceScelta | None = None,
    riepilogo_arricchimento: dict[str, Any] | None = None,
    sito_url: str | None = None,
) -> dict[str, Any]:
    fonti_ok = sorted({e.fonte for e in risultato_fetch.esiti if e.stato == "ok"})
    fonti_ko = [
        {"fonte": e.fonte, "url": e.url, "errore": e.errore}
        for e in risultato_fetch.esiti
        if e.stato != "ok"
    ]
    notizie = []
    for selezione in selezioni:
        notizie.append(
            {
                "titolo": selezione.titolo,
                "categoria": selezione.categoria,
                "categoria_label": label_categoria(selezione.categoria),
                "copertina": selezione.copertina,
                "fonti": selezione.fonti,
                "parole_target": selezione.parole_target,
                "articoli": [
                    {
                        "fonte": articolo.fonte,
                        "titolo": articolo.titolo,
                        "link": articolo.link,
                        "pubblicato": articolo.pubblicato.isoformat(),
                        "data_stimata": articolo.data_stimata,
                        "prima_vista": (
                            articolo.prima_vista.isoformat()
                            if articolo.prima_vista
                            else None
                        ),
                        "sommario": articolo.sommario,
                    }
                    for articolo in selezione.cluster.ordina_articoli()
                ],
            }
        )
    return {
        "data": data_iso,
        "titolo": copione["titolo_episodio"],
        "descrizione": copione["descrizione"],
        "descrizione_breve": copione.get("descrizione_breve", ""),
        "incipit": incipit,
        "incipit_fonte": incipit_fonte,
        "durata_preset": preset_nome,
        "categorie_attive": categorie_attive,
        "categorie_default": categorie_default,
        "modalita": copione["modalita"],
        "llm": {
            "modello": impostazioni["llm"]["modello"],
            "modello_riserva": impostazioni.get("llm_modello_riserva"),
            "modello_usato": copione.get("modello_usato"),
            "motivo_modello": copione.get("motivo_modello"),
            "usato": copione["modalita"] == "llm",
            "motivo": copione.get("motivo_fallback"),
        },
        "finestra_ore": ore,
        "fonti_totali": fonti_totali,
        "feed_ok": risultato_fetch.ok,
        "feed_ko": risultato_fetch.ko,
        "fonti_ok": fonti_ok,
        "fonti_ko": fonti_ko,
        "fonti_usate": sorted({fonte for n in notizie for fonte in n["fonti"]}),
        "articoli_fetch": len(risultato_fetch.articoli),
        "cluster": len(clusters),
        "cluster_multifonte": sum(1 for c in clusters if c.multi_fonte),
        "notizie": notizie,
        "buone_notizie": {
            "notizie": sum(1 for n in notizie if n["categoria"] == "buone-notizie"),
            "usato_ai": bool(esito_buone.usato_ai) if esito_buone else False,
            "motivo": (
                f"{sum(1 for n in notizie if n['categoria'] == 'buone-notizie')} "
                f"in scaletta; {esito_buone.motivo}"
                if esito_buone
                else "categoria non attiva"
            ),
            "candidati": esito_buone.candidati if esito_buone else 0,
            "scartate_negative": (
                esito_buone.scartate_negative if esito_buone else 0
            ),
        },
        "tts": {
            "motore_richiesto": voce_scelta.motore if voce_scelta else None,
            "motore_usato": info_audio.get("motore") if info_audio else None,
            "voce": (
                info_audio.get("voce")
                if info_audio
                else (voce_scelta.nome if voce_scelta else None)
            ),
            "voce_etichetta": (
                voce_scelta.etichetta
                if info_audio and info_audio.get("motore") == "gemini"
                else (
                    f"{info_audio.get('voce')} (edge-tts)"
                    if info_audio
                    else (voce_scelta.etichetta if voce_scelta else None)
                )
            ),
            "velocita": (
                info_audio.get("velocita")
                if info_audio
                else (voce_scelta.velocita if voce_scelta else None)
            ),
            "motivo_fallback": (
                info_audio.get("motivo_fallback") if info_audio else None
            ),
        },
        "arricchimento": riepilogo_arricchimento or {},
        "sito_url": sito_url,
        "parole_copione": conta_parole(copione["testo"]),
        "target_parole": copione.get("target_parole"),
        "divario_parole": copione.get("divario_parole"),
        "durata_secondi": round(float(info_audio["durata"]), 2)
        if info_audio
        else None,
        "dimensione_mp3": info_audio["dimensione"] if info_audio else None,
        "mp3": str(mp3_path) if info_audio else None,
        "copione_md": str(copione_md),
        "copione_txt": str(copione_txt),
        "avvisi_stile": avvisi_stile,
        "errori_non_bloccanti": errori_non_bloccanti,
        "feed": docs_info["feed"] if docs_info else None,
        "index": docs_info["index"] if docs_info else None,
        "visti": visti_path,
        "dry_run": dry_run,
        "senza_audio": senza_audio,
    }


def esegui(
    args: argparse.Namespace,
    impostazioni: dict[str, Any],
    data_riferimento: datetime,
    logger: logging.Logger,
) -> int:
    data_iso = data_iso_roma(data_riferimento)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    errori_non_bloccanti: list[str] = []

    fonti = carica_fonti(_percorso_fonti(args))
    logger.info(
        "Avvio del %s: %d fonti attive, preset %s.",
        data_in_italiano(data_riferimento),
        len(fonti),
        args.durata or impostazioni["durata_default"],
    )

    corpo_issue, avvisi_issue = _corpo_issue(impostazioni, logger)
    errori_non_bloccanti.extend(avvisi_issue)
    categorie_attive, avvisi_categorie = _categorie_attive(
        impostazioni, logger, corpo_issue
    )
    errori_non_bloccanti.extend(avvisi_categorie)
    logger.info(
        "Categorie attive: %s",
        ", ".join(label_categoria(c) for c in categorie_attive) or "nessuna",
    )

    percorso_incipit = _percorso_base(
        args.incipit or impostazioni.get("incipit", {}).get("file"),
        "config/incipit.txt",
    )
    modello_file, avvisi_incipit_file = leggi_modello_incipit(percorso_incipit)
    modello_incipit, fonte_incipit = scegli_modello(corpo_issue, modello_file)

    percorso_outro = _percorso_base(
        impostazioni.get("outro", {}).get("file"), "config/outro.txt"
    )
    modello_outro_file, avvisi_outro_file = leggi_modello_outro(percorso_outro)
    modello_outro, fonte_outro = scegli_modello_outro(
        corpo_issue, modello_outro_file
    )
    outro, avvisi_outro = risolvi_outro(
        modello_outro,
        str(impostazioni.get("nome_utente", "")),
        data_riferimento,
        logger,
    )
    errori_non_bloccanti.extend(avvisi_outro_file + avvisi_outro)
    logger.info("Outro (%s): %s", fonte_outro, outro)
    incipit, avvisi_incipit = risolvi_incipit(
        modello_incipit,
        str(impostazioni.get("nome_utente", "")),
        data_riferimento,
        logger,
    )
    errori_non_bloccanti.extend(avvisi_incipit_file + avvisi_incipit)
    logger.info("Incipit (%s): %s", fonte_incipit, incipit or "(vuoto)")

    voce_scelta = risolvi_voce(
        impostazioni,
        corpo_issue=corpo_issue,
        voce_cli=args.voce,
        velocita_cli=args.velocita,
        motore_cli=args.tts_motore,
    )
    for avviso in voce_scelta.avvisi:
        logger.warning("Voce: %s", avviso)
    errori_non_bloccanti.extend(voce_scelta.avvisi)
    logger.info(
        "Voce TTS: %s (%s), velocità %.2f, motore richiesto %s (fonte %s).",
        voce_scelta.nome,
        voce_scelta.etichetta,
        voce_scelta.velocita,
        voce_scelta.motore,
        voce_scelta.fonte,
    )

    ore = args.ore or int(impostazioni["fetch"]["ore_default"])
    configurazione_fetch = impostazioni["fetch"]
    percorso_visti = _percorso_base(
        args.stato_visti or impostazioni.get("stato", {}).get("visti"),
        "state/visti.json",
    )
    visti = Visti(
        percorso_visti,
        giorni_pruning=int(impostazioni.get("stato", {}).get("giorni_pruning", 60)),
        logger=logger,
        adesso=data_riferimento,
    )
    logger.info("Scarico %d feed RSS (ultime %d ore).", len(fonti), ore)
    risultato_fetch = fetch_all(
        fonti,
        ore=ore,
        timeout=int(configurazione_fetch["timeout"]),
        retry=int(configurazione_fetch["retry"]),
        max_workers=int(configurazione_fetch["max_workers"]),
        logger=logger,
        adesso=data_riferimento,
        visti=visti,
    )
    if not risultato_fetch.articoli:
        if _solo_senza_novita(risultato_fetch):
            print(
                "Nessuna novità: i feed senza date hanno solo articoli già in rubrica. "
                f"{risultato_fetch.ko} feed senza articoli validi. Nessun episodio creato."
            )
            logger.info(
                "Nessuna novità: %d feed senza date senza nuovi articoli; %d feed KO.",
                risultato_fetch.senza_novita,
                risultato_fetch.ko,
            )
            return 0
        raise ErroreBloccante(
            "Nessun articolo valido scaricato. Controlla i feed o la connessione."
        )

    clusters = clusterizza(
        risultato_fetch.articoli,
        soglia=float(impostazioni["clustering"]["soglia"]),
        logger=logger,
        max_per_feed=int(impostazioni["clustering"].get("max_per_feed", 30)),
        max_totale=int(impostazioni["clustering"].get("max_totale", 3000)),
    )
    if not clusters:
        raise ErroreBloccante("Il clustering non ha prodotto notizie.")

    esito_buone = filtra_buone_notizie(
        clusters,
        categorie_attive,
        impostazioni,
        logger=logger,
    )
    preset_nome = args.durata or impostazioni["durata_default"]
    preset = impostazioni["preset"][preset_nome]
    selezioni = seleziona(
        clusters,
        preset=preset,
        categorie_attive=categorie_attive,
        max_notizie=args.notizie,
        logger=logger,
        buone_notizie=esito_buone.notizie,
    )
    if not selezioni:
        raise ErroreBloccante(
            "Nessuna notizia selezionabile con le categorie attive. "
            "Controlla la issue delle categorie o config/impostazioni.json."
        )

    riepilogo_arricchimento = arricchisci_selezioni(
        selezioni,
        impostazioni,
        logger=logger,
        adesso=data_riferimento,
    )
    try:
        selezioni, avvisi_traduzione = prepara_selezioni_italiane(
            selezioni, impostazioni, logger=logger
        )
    except TraduzioneError as exc:
        raise ErroreBloccante(str(exc)) from exc
    for avviso in avvisi_traduzione:
        logger.warning(avviso)

    copione = genera_copione(
        selezioni,
        impostazioni,
        data_riferimento,
        logger=logger,
    )
    applica_outro(copione, outro)
    aggiungi_incipit(copione, incipit)
    avvisi_stile = registra_avvisi(copione["testo"], logger)
    logger.info(
        "Copione pronto: %d parole, modalità %s, target %s, divario %s.",
        conta_parole(copione["testo"]),
        copione["modalita"],
        copione.get("target_parole"),
        copione.get("divario_parole"),
    )
    if args.dry_run:
        print(f"Incipit risolto: {incipit}")

    copione_md = output / f"copione-{data_iso}.md"
    copione_txt = output / f"copione-{data_iso}.txt"
    _scrivi_copione_md(
        copione_md,
        copione,
        selezioni,
        data_riferimento,
        preset_nome,
        preset,
        categorie_attive,
        None,
    )
    copione_txt.write_text(copione["testo"] + "\n", encoding="utf-8", newline="\n")
    logger.info("Copione scritto: %s e %s.", copione_md, copione_txt)

    mp3_path = output / f"notiziario-{data_iso}.mp3"
    info_audio = None
    if args.dry_run or args.senza_audio:
        motivo = "dry-run" if args.dry_run else "--senza-audio"
        logger.info("Audio non generato (%s).", motivo)
    else:
        sezioni, indici_transizioni = _prepara_blocchi_tts(copione, impostazioni)
        if not sezioni:
            raise ErroreBloccante("Copione vuoto: impossibile generare l'audio.")
        logger.info(
            "Genero l'audio con %d blocchi e %d transizioni...",
            len(sezioni),
            len(indici_transizioni),
        )
        try:
            suono = str(impostazioni.get("suono_transizione", "ding"))
            if suono == "nessuno":
                info_audio = sintetizza_sezioni(
                    sezioni,
                    mp3_path,
                    impostazioni,
                    logger=logger,
                    voce=voce_scelta.nome,
                    velocita=voce_scelta.velocita,
                    motore=voce_scelta.motore,
                )
            else:
                percorso_suono = BASE / "docs" / "suoni" / f"{suono}.mp3"
                if not percorso_suono.exists():
                    raise ErroreBloccante(f"Suono di transizione mancante: {percorso_suono}")
                voce_temp = output / f".voce-{data_iso}.mp3"
                try:
                    info_voce = sintetizza_sezioni(
                        sezioni,
                        voce_temp,
                        impostazioni,
                        logger=logger,
                        voce=voce_scelta.nome,
                        velocita=voce_scelta.velocita,
                        motore=voce_scelta.motore,
                    )
                    durate = info_voce.get("durate_sezioni", [])
                    risultato_suoni = inserisci_suoni(
                        voce_temp,
                        percorso_suono,
                        mp3_path,
                        durate,
                        impostazioni,
                        indici_transizioni,
                    )
                    info_audio = dict(info_voce)
                    info_audio["durata"] = risultato_suoni["durata"]
                    info_audio["dimensione"] = mp3_path.stat().st_size
                    info_audio["transizioni"] = risultato_suoni["transizioni"]
                    info_audio["suono"] = suono
                finally:
                    voce_temp.unlink(missing_ok=True)
        except (TTSError, AudioError) as exc:
            # Salvo comunque lo stato per diagnostica, poi esco con errore.
            stato = _stato(
                data_iso=data_iso,
                copione=copione,
                selezioni=selezioni,
                preset_nome=preset_nome,
                categorie_attive=categorie_attive,
                categorie_default=impostazioni["categorie_default"],
                ore=ore,
                fonti_totali=len(fonti),
                risultato_fetch=risultato_fetch,
                clusters=clusters,
                avvisi_stile=avvisi_stile,
                errori_non_bloccanti=errori_non_bloccanti + [f"Audio: {exc}"],
                info_audio=None,
                mp3_path=mp3_path,
                copione_md=copione_md,
                copione_txt=copione_txt,
                docs_info=None,
                impostazioni=impostazioni,
                dry_run=args.dry_run,
                senza_audio=args.senza_audio,
                incipit=incipit,
                incipit_fonte=fonte_incipit,
                esito_buone=esito_buone,
                visti_path=str(percorso_visti),
                voce_scelta=voce_scelta,
                riepilogo_arricchimento=riepilogo_arricchimento,
                sito_url=_sito_url(args, impostazioni),
            )
            (output / f"stato-{data_iso}.json").write_text(
                json.dumps(stato, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            raise ErroreBloccante(f"Audio non generato: {exc}") from exc

        # Riscrivo il copione leggibile con la durata reale dell'audio.
        _scrivi_copione_md(
            copione_md,
            copione,
            selezioni,
            data_riferimento,
            preset_nome,
            preset,
            categorie_attive,
            float(info_audio["durata"]),
        )

    if _deve_salvare_visti(args.dry_run, args.senza_audio, info_audio) and visti.modificato:
        visti.salva()
        logger.info("Rubrica first_seen salvata: %s", percorso_visti)

    voce_pub = str(info_audio.get("voce", voce_scelta.nome)) if info_audio else voce_scelta.nome
    voce_label_pub = (
        voce_scelta.etichetta
        if info_audio and info_audio.get("motore") == "gemini"
        else (f"{voce_pub} (edge-tts)" if info_audio else voce_scelta.etichetta)
    )
    motore_pub = str(info_audio.get("motore", voce_scelta.motore)) if info_audio else voce_scelta.motore
    velocita_pub = float(info_audio.get("velocita", voce_scelta.velocita)) if info_audio else voce_scelta.velocita
    tutte_fonti = fonti
    try:
        tutte_fonti = carica_fonti_tutte(_percorso_fonti(args))
        fonti_totali = len(tutte_fonti)
        fonti_attive = sum(1 for f in tutte_fonti if f.attivo)
    except Exception:
        fonti_totali = len(fonti)
        fonti_attive = len(fonti)
    impostazioni_pubbliche = {
        "categorie_attive": categorie_attive,
        "incipit_template": modello_incipit,
        "incipit_risolto": incipit,
        "voce": voce_pub,
        "voce_label": voce_label_pub,
        "voce_configurata": str(impostazioni.get("voce", {}).get("nome", "")),
        "durata_default": str(impostazioni.get("durata_default", "standard")),
        "orario_generazione": str(impostazioni.get("orario_generazione", "07:00")),
        "velocita": velocita_pub,
        "motore": motore_pub,
        "motore_richiesto": voce_scelta.motore,
        "motore_configurato": str(impostazioni.get("tts_motore", voce_scelta.motore)),
        "outro": outro,
        "data": data_iso,
        "nome_utente": str(impostazioni.get("nome_utente", "")),
        "fonti_totali": fonti_totali,
        "fonti_attive": fonti_attive,
        "fonti": fonti_pubbliche(tutte_fonti),
        "issue_url": _issue_url(impostazioni),
        "repo_url": _repo_url(impostazioni),
    }

    docs_info = None
    if info_audio and not args.dry_run and not args.no_feed:
        episodio = Episodio(
            data=data_iso,
            titolo=copione["titolo_episodio"],
            descrizione=copione["descrizione"],
            descrizione_breve=copione.get("descrizione_breve", ""),
            filename=mp3_path.name,
            durata_secondi=float(info_audio["durata"]),
            dimensione=int(info_audio["dimensione"]),
            modalita=copione["modalita"],
            categorie=categorie_attive,
            voce=str(info_audio.get("voce", voce_scelta.nome)),
            voce_label=(
                voce_scelta.etichetta
                if info_audio.get("motore") == "gemini"
                else f"{info_audio.get('voce', voce_scelta.nome)} (edge-tts)"
            ),
            velocita=float(info_audio.get("velocita", voce_scelta.velocita)),
            tts_motore=str(info_audio.get("motore", voce_scelta.motore)),
            pubblicato=datetime.now(timezone.utc).isoformat(),
        )
        try:
            docs_info = aggiorna_docs(
                episodio,
                impostazioni,
                args.docs,
                base_url=args.feed_base_url,
                sito_url=_sito_url(args, impostazioni),
                impostazioni_pubbliche=impostazioni_pubbliche,
                logger=logger,
            )
        except Exception as exc:
            messaggio = f"Feed/sito non aggiornati: {type(exc).__name__}: {exc}"
            logger.warning(messaggio)
            errori_non_bloccanti.append(messaggio)

    stato = _stato(
        data_iso=data_iso,
        copione=copione,
        selezioni=selezioni,
        preset_nome=preset_nome,
        categorie_attive=categorie_attive,
        categorie_default=impostazioni["categorie_default"],
        ore=ore,
        fonti_totali=len(fonti),
        risultato_fetch=risultato_fetch,
        clusters=clusters,
        avvisi_stile=avvisi_stile,
        errori_non_bloccanti=errori_non_bloccanti,
        info_audio=info_audio,
        mp3_path=mp3_path,
        copione_md=copione_md,
        copione_txt=copione_txt,
        docs_info=docs_info,
        impostazioni=impostazioni,
        dry_run=args.dry_run,
        senza_audio=args.senza_audio,
        incipit=incipit,
        incipit_fonte=fonte_incipit,
        esito_buone=esito_buone,
        visti_path=str(percorso_visti),
        voce_scelta=voce_scelta,
        riepilogo_arricchimento=riepilogo_arricchimento,
        sito_url=_sito_url(args, impostazioni),
    )
    stato_path = output / f"stato-{data_iso}.json"
    stato_path.write_text(
        json.dumps(stato, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # Riepilogo per l'utente.
    print("")
    print("Notiziario completato.")
    print(f"Data: {data_in_italiano(data_riferimento)}")
    modalita = "Gemini" if copione["modalita"] == "llm" else "fallback locale"
    print(f"Modalità: {modalita}")
    print(
        f"Modello testo: {copione.get('modello_usato') or 'fallback'} "
        f"({copione.get('motivo_modello') or 'n/d'})"
    )
    if copione.get("motivo_fallback"):
        print(f"Motivo fallback: {copione['motivo_fallback']}")
    print(
        f"Fonti: {risultato_fetch.ok} OK, {risultato_fetch.ko} KO; "
        f"{len(risultato_fetch.articoli)} articoli; "
        f"{len(clusters)} notizie raggruppate "
        f"({sum(1 for c in clusters if c.multi_fonte)} con più fonti)."
    )
    print(
        f"Scaletta: {len(selezioni)} notizie "
        f"({sum(1 for s in selezioni if s.copertina)} copertine)."
    )
    print(
        f"Copione: {conta_parole(copione['testo'])} parole "
        f"(target {copione.get('target_parole')}, "
        f"divario {copione.get('divario_parole')})."
    )
    positive_count = sum(1 for s in selezioni if s.blocco == "buone-notizie")
    print(
        f"Buone notizie: {positive_count} in scaletta "
        f"({esito_buone.motivo})."
    )
    print(
        f"Arricchimento: {riepilogo_arricchimento.get('arricchiti', 0)}/"
        f"{riepilogo_arricchimento.get('articoli', 0)} articoli, "
        f"{riepilogo_arricchimento.get('parziali', 0)} parziali."
    )
    if info_audio:
        print(
            f"Audio: {mp3_path} ({durata_umana(info_audio['durata'])}, "
            f"{info_audio['dimensione']} byte)."
        )
        print(
            f"TTS: {info_audio.get('motore')} · voce {info_audio.get('voce')} "
            f"· velocità {info_audio.get('velocita')}."
        )
        if info_audio.get("motivo_fallback"):
            print(f"Fallback TTS: {info_audio['motivo_fallback']}")
    elif args.dry_run:
        print("Dry-run: niente audio, feed o pubblicazione.")
    else:
        print("Audio saltato.")
    if docs_info:
        print(f"Feed: {docs_info['feed']}")
        print(f"Player: {docs_info['index']}")
    if avvisi_stile:
        print(f"Avvisi di stile: {len(avvisi_stile)} (dettagli nel log).")
    else:
        print("Avvisi di stile: nessuno.")
    if errori_non_bloccanti:
        print(f"Avvisi non bloccanti: {len(errori_non_bloccanti)} (dettagli nel log).")
    print(f"Stato: {stato_path}")
    return 0


def comando_provini(
    args: argparse.Namespace,
    impostazioni: dict[str, Any],
    logger: logging.Logger,
) -> int:
    try:
        risultati = genera_provini(
            Path(args.output) / "provini",
            impostazioni,
            logger=logger,
        )
    except TTSError as exc:
        print(f"Provini non generati: {exc}", file=sys.stderr)
        return 1
    print("Provini vocali generati:")
    for voce in risultati:
        print(
            f"- {voce['voce']}: {voce['file']} "
            f"({voce['durata_secondi']:.1f} s, {voce['dimensione']} byte)"
        )
    return 0


def comando_test_llm(
    impostazioni: dict[str, Any], logger: logging.Logger
) -> int:
    ok, messaggio = prova_llm(impostazioni, logger)
    print(messaggio)
    return 0 if ok else 1


def _sito_url(args: argparse.Namespace, impostazioni: dict[str, Any]) -> str:
    if args.feed_site_url:
        return normalizza_sito_url(str(args.feed_site_url))
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo and "/" in repo:
        owner, nome = repo.split("/", 1)
        if nome.casefold() == f"{owner}.github.io".casefold():
            return f"https://{owner}.github.io/"
        return f"https://{owner}.github.io/{nome}/"
    return normalizza_sito_url(str(impostazioni["feed"]["sito_url"]))


def comando_anteprima(
    args: argparse.Namespace,
    impostazioni: dict[str, Any],
    logger: logging.Logger,
) -> int:
    scelta = risolvi_voce(
        impostazioni,
        corpo_issue=None,
        voce_cli=args.voce,
        velocita_cli=args.velocita,
        motore_cli=args.tts_motore,
    )
    for avviso in scelta.avvisi:
        logger.warning("Voce: %s", avviso)
    data = adesso_roma()
    frase = args.anteprima_voce or (
        f"Ciao Jacopo, oggi è il {data_in_italiano(data, con_giorno=False)}. "
        "Il 3 per cento delle risorse andrà alla scuola. "
        "Le temperature sono salite a 25 gradi. "
        "Questa è una prova della voce del Notiziario."
    )
    cartella = Path(args.output) / "anteprima"
    cartella.mkdir(parents=True, exist_ok=True)
    nome_voce = "".join(
        c for c in scelta.nome if c.isalnum() or c in {"-", "_"}
    ) or "voce"
    velocita_nome = f"{scelta.velocita:g}"
    uscita = cartella / f"anteprima-{nome_voce}-{velocita_nome}.mp3"
    print(f"Voce: {scelta.nome} ({scelta.etichetta}) · velocità {scelta.velocita}")
    try:
        info = sintetizza_anteprima(
            frase,
            uscita,
            impostazioni,
            logger=logger,
            voce=scelta.nome,
            velocita=scelta.velocita,
            motore=scelta.motore,
        )
    except TTSError as exc:
        print(f"Anteprima non generata: {exc}", file=sys.stderr)
        return 1
    print(f"File: {uscita}")
    print(f"Durata: {durata_umana(info['durata'])} · motore: {info['motore']}")
    print(f"Voce usata: {info['voce']} · velocità: {info['velocita']}")
    if info.get("motivo_fallback"):
        print(f"Fallback: {info['motivo_fallback']}")
    return 0


def _repo_url(impostazioni: dict[str, Any]) -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo:
        return f"https://github.com/{repo}"
    return str(impostazioni.get("github", {}).get("repo_url", "")).rstrip("/")

def _issue_url(impostazioni: dict[str, Any]) -> str | None:
    try:
        numero = numero_issue_categorie(impostazioni)
    except ConfigError:
        return None
    repo = _repo_url(impostazioni)
    if numero and repo:
        return f"{repo}/issues/{numero}"
    return None

def comando_anteprima_suono(args: argparse.Namespace) -> int:
    nomi = (
        ["ding", "chime", "whoosh"]
        if not args.anteprima_suono
        else [args.anteprima_suono]
    )
    origine = BASE / "docs" / "suoni"
    destinazione = Path(args.output) / "anteprima"
    destinazione.mkdir(parents=True, exist_ok=True)
    for nome in nomi:
        sorgente = origine / f"{nome}.mp3"
        if not sorgente.exists():
            print(f"Suono mancante: {sorgente}", file=sys.stderr)
            return 1
        uscita = destinazione / f"suono-{nome}.mp3"
        uscita.write_bytes(sorgente.read_bytes())
        try:
            info = leggi_info_audio(uscita)
        except Exception:
            info = {}
        print(f"{uscita} ({float(info.get('durata', 0)):.2f} s)")
    return 0


def comando_elenco_fonti(args: argparse.Namespace) -> int:
    fonti = carica_fonti_tutte(_percorso_fonti(args))
    elenco_fonti(fonti)
    return 0


def comando_importa(
    args: argparse.Namespace,
    impostazioni: dict[str, Any],
    logger: logging.Logger,
) -> int:
    report = importa_feed(
        args.importa_feed,
        _percorso_fonti(args),
        categoria=args.categoria,
        attiva_tutte=args.attiva_tutte,
        attiva_fonti=args.attiva_fonti,
        impostazioni=impostazioni,
        logger=logger,
        output=args.output,
    )
    stampa_report(report)
    return 0


def comando_controllo(
    args: argparse.Namespace,
    impostazioni: dict[str, Any],
    logger: logging.Logger,
    data_riferimento: datetime,
) -> int:
    percorso_fonti = _percorso_fonti(args)
    fonti = carica_fonti_tutte(percorso_fonti)
    percorso_visti = _percorso_base(
        args.stato_visti or impostazioni.get("stato", {}).get("visti"),
        "state/visti.json",
    )
    visti = Visti(
        percorso_visti,
        giorni_pruning=int(impostazioni.get("stato", {}).get("giorni_pruning", 60)),
        logger=logger,
        adesso=data_riferimento,
    )
    esiti = controlla_tutte(
        fonti,
        impostazioni,
        adesso=data_riferimento,
        visti=visti,
        logger=logger,
        max_workers=int(impostazioni["fetch"]["max_workers"]),
    )
    stampa_tabella(esiti)
    data_iso = data_iso_roma(data_riferimento)
    report_path = Path(args.output) / f"controllo-feed-{data_iso}.json"
    salva_report(report_path, esiti, impostazioni, adesso=data_riferimento)
    aggiornate = aggiorna_fonti_con_controllo(
        fonti, esiti, args.disattiva_non_ok, adesso=data_riferimento
    )
    scrivi_fonti_yaml(percorso_fonti, aggiornate)
    non_ok = [e for e in esiti if e.stato != "ok"]
    print(
        f"\nControllo feed: {len(esiti)} fonti, {len(esiti) - len(non_ok)} OK, "
        f"{len(non_ok)} da controllare."
    )
    print(f"Report: {report_path}")
    print(
        "Fonti esistenti disattivate: "
        + (
            "sì (--disattiva-non-ok)"
            if args.disattiva_non_ok
            else "no (aggiornato solo il campo controllo)"
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = costruisci_parser()
    args = parser.parse_args(argv)

    try:
        impostazioni = carica_impostazioni(args.config)
    except ConfigError as exc:
        print(f"Configurazione non valida: {exc}", file=sys.stderr)
        return 1

    data_riferimento = adesso_roma()
    logger = configura_logging(BASE / "logs", data_iso_roma(data_riferimento))
    logger.info("================ Notiziario ================")

    try:
        if args.anteprima_suono is not None:
            return comando_anteprima_suono(args)
        if args.anteprima_voce is not None:
            return comando_anteprima(args, impostazioni, logger)
        if args.importa_feed:
            return comando_importa(args, impostazioni, logger)
        if args.controlla_feed or args.disattiva_non_ok:
            return comando_controllo(
                args, impostazioni, logger, data_riferimento
            )
        if args.elenca_fonti or args.fonti == "__ELENCA__":
            return comando_elenco_fonti(args)
        if args.attiva_fonti or args.attiva_tutte or args.categoria:
            print(
                "Le opzioni --attiva-tutte, --attiva-fonti e --categoria "
                "richiedono --importa-feed.",
                file=sys.stderr,
            )
            return 1
        if args.test_modelli:
            return 0 if test_modelli(impostazioni, logger) == 0 else 1
        if args.test_llm:
            return comando_test_llm(impostazioni, logger)
        if args.provini:
            return comando_provini(args, impostazioni, logger)
        return esegui(args, impostazioni, data_riferimento, logger)
    except KeyboardInterrupt:
        logger.warning("Interrotto dall'utente.")
        return 130
    except (ErroreBloccante, ConfigError) as exc:
        logger.error("Errore bloccante: %s", exc)
        print(f"\nErrore: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - ultima difesa
        logger.exception("Errore imprevisto: %s", type(exc).__name__)
        print(
            f"Errore imprevisto ({type(exc).__name__}). Dettagli nel log.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
