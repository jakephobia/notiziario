"""Dashboard del Notiziario: issue GitHub o payload JSON della pagina web."""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from .categorie import (
    CATEGORIA_DA_ASSEGNARE,
    CATEGORIE,
    CATEGORIE_IDS,
    label_categoria,
    leggi_issue,
    normalizza_testo,
    trova_categoria,
)
from .config import (
    Fonte,
    ROOT,
    carica_fonti,
    carica_fonti_tutte,
    carica_impostazioni,
    numero_issue_categorie,
    repository_github,
    valida_impostazioni,
)
from .controllo_feed import controlla_tutte
from .fetch import normalizza_url
from .fonti_io import merge_fonti, salva_fonti, scrivi_fonti_yaml, sostituisci_fonte
from .feed import fonti_pubbliche, scrivi_impostazioni_pubbliche
from .incipit import INCIPIT_DEFAULT
from .orario import orario_valido
from .voce import normalizza_velocita
from .importa_feed import ImportError_, _nome_fonte, _parse_opml
from .outro import OUTRO_DEFAULT, estrai_outro_issue
from .tempo import adesso_roma, iso_roma
from .visti import Visti


LIMITE_BODY = 60_000
LIMITE_PAYLOAD = 65_000
LIMITE_TESTO_PAYLOAD = 500
MOTORI_VALIDI = {"gemini", "edge"}
DURATE_VALIDE = {"svelto", "standard", "completo"}
CAMPI_PAYLOAD = {
    "nome",
    "categorie",
    "incipit",
    "outro",
    "voce",
    "velocita",
    "motore",
    "suono",
    "fonti",
    "durata",
    "orario",
}
_HEADING = re.compile(r"(?ims)^##\s*([^\n]+)\n(.*?)(?=^##\s|\Z)")


class DashboardError(Exception):
    """Errore bloccante della dashboard."""


def _sezione(corpo: str, nome: str) -> re.Match[str] | None:
    for match in _HEADING.finditer(corpo):
        if match.group(1).strip().casefold() == nome.casefold():
            return match
    return None


def _contenuto(corpo: str, nome: str) -> str | None:
    match = _sezione(corpo, nome)
    return match.group(2).strip() if match else None


def _sostituisci_sezione(corpo: str, nome: str, contenuto: str) -> str:
    match = _sezione(corpo, nome)
    corpo_nuovo = contenuto.strip()
    if match is None:
        return corpo.rstrip() + f"\n\n## {nome}\n\n{corpo_nuovo}\n"
    return corpo[: match.start(2)] + corpo_nuovo + "\n" + corpo[match.end(2) :]


SUONI_VALIDI = {"ding", "chime", "whoosh", "nessuno"}

def parse_suono(corpo: str) -> tuple[str | None, list[str]]:
    contenuto = _contenuto(corpo, "Suono")
    if contenuto is None:
        return None, []
    for riga in contenuto.splitlines():
        trovato = re.match(r"^\s*suono\s*:\s*(.*?)\s*$", riga, re.I)
        if trovato:
            valore = trovato.group(1).strip().casefold()
            if valore in SUONI_VALIDI:
                return valore, []
            return "ding", [
                f"Suono issue non valido ({valore}): uso ding."
            ]
    return "ding", ["Sezione Suono senza valore: uso ding."]

def parse_outro(corpo: str) -> tuple[str | None, list[str]]:
    if _sezione(corpo, "Outro") is None:
        return None, []
    contenuto = estrai_outro_issue(corpo) or ""
    testo = contenuto.strip()
    if not testo:
        return OUTRO_DEFAULT, ["Outro issue vuoto: uso il default."]
    return testo, []

def _righe_fonti(fonti: list[Fonte]) -> str:
    righe = []
    for fonte in fonti:
        segno = "x" if fonte.attivo else " "
        righe.append(
            f"- [{segno}] {fonte.nome} ({fonte.categoria}) — {fonte.url}"
        )
    return "\n".join(righe)


def parse_nome(corpo: str) -> tuple[str | None, list[str]]:
    contenuto = _contenuto(corpo, "Nome")
    if contenuto is None:
        return None, []
    valori = []
    for riga in contenuto.splitlines():
        trovato = re.match(r"^\s*nome\s*:\s*(.*?)\s*$", riga, re.I)
        if trovato:
            valori.append(trovato.group(1).strip())
    if not valori:
        return None, ["Sezione Nome senza riga 'nome:'; nessuna modifica."]
    if any(not valore for valore in valori):
        return None, ["Nome vuoto: mantengo il valore attuale."]
    if len(set(valori)) > 1:
        return None, ["Sezione Nome ambigua: mantengo il valore attuale."]
    nome = valori[0]
    if len(nome) > 80 or any(ord(c) < 32 for c in nome):
        return None, ["Nome non valido: mantengo il valore attuale."]
    return nome, []


def _categoria_da_testo(testo: str | None, attuale: str) -> tuple[str, str | None]:
    if not testo:
        return attuale, None
    pulito = testo.strip()
    if normalizza_testo(pulito) in {"da assegnare", "daassegnare"}:
        return attuale, None
    trovata = trova_categoria(pulito)
    if not trovata:
        return attuale, f"Categoria '{pulito}' non riconosciuta: lascio {attuale}."
    return trovata, None


def parse_fonti(corpo: str, fonti: list[Fonte]) -> tuple[list[Fonte], list[str]]:
    contenuto = _contenuto(corpo, "Fonti")
    if contenuto is None:
        return fonti, []
    by_url = {normalizza_url(f.url): f for f in fonti}
    by_nome: dict[str, list[Fonte]] = {}
    for fonte in fonti:
        by_nome.setdefault(normalizza_testo(fonte.nome), []).append(fonte)

    aggiornate = list(fonti)
    citate: set[str] = set()
    avvisi: list[str] = []
    righe = [r.strip() for r in contenuto.splitlines() if r.strip()]
    for riga in righe:
        if riga.startswith("#"):
            continue
        trovato = re.match(
            r"^[-*+]\s*\[\s*([xX ])\s*\]\s*(.+?)\s*\(([^()]+)\)\s*[—–-]\s*(https?://\S+)\s*$",
            riga,
        )
        if not trovato:
            return fonti, [
                f"Sezione Fonti malformata: riga non riconosciuta {riga!r}; blocco invariato."
            ]
        attivo = trovato.group(1).lower() == "x"
        nome = trovato.group(2).strip()
        categoria_testo = trovato.group(3).strip()
        url = trovato.group(4).strip()
        chiave_url = normalizza_url(url)
        fonte = by_url.get(chiave_url)
        if fonte is None:
            candidate = by_nome.get(normalizza_testo(nome), [])
            if len(candidate) == 1:
                fonte = candidate[0]
            elif len(candidate) > 1:
                return fonti, [
                    f"Fonte ambigua per nome '{nome}': aggiungi l'URL; blocco invariato."
                ]
        if fonte is None:
            avvisi.append(f"URL non presente in config, ignorato: {url}")
            continue
        if fonte.url in citate:
            return fonti, [
                f"Fonte duplicata nella sezione Fonti ({url}); blocco invariato."
            ]
        citate.add(fonte.url)
        nuova_categoria, avviso = _categoria_da_testo(
            categoria_testo, fonte.categoria
        )
        if avviso:
            avvisi.append(avviso)
        aggiornate = sostituisci_fonte(
            aggiornate,
            fonte.url,
            attivo=attivo,
            categoria=nuova_categoria,
        )
    return aggiornate, avvisi


def _url_import(contenuto: str) -> list[str]:
    urls: list[str] = []
    for riga in contenuto.splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#"):
            continue
        if riga.lower().startswith("incolla qui"):
            continue
        if not riga.startswith(("http://", "https://")):
            raise DashboardError(
                f"Sezione Import feed ambigua: riga non URL {riga!r}"
            )
        urls.append(riga)
    return urls


def parse_import(
    corpo: str,
    impostazioni: dict[str, Any],
    esistenti: list[Fonte],
    logger: logging.Logger | None = None,
    massimo: int = 20,
) -> tuple[list[Fonte], int, int, int, list[str], str | None]:
    """Restituisce fonti aggiornate, aggiunte, duplicate, scartate, avvisi, nuovo blocco."""
    logger = logger or logging.getLogger("notiziario")
    contenuto = _contenuto(corpo, "Import feed")
    if contenuto is None:
        return esistenti, 0, 0, 0, [], None
    if "import completato:" in contenuto.casefold():
        return esistenti, 0, 0, 0, [], contenuto
    avvisi: list[str] = []
    nuove: list[Fonte] = []
    try:
        if "<opml" in contenuto.casefold():
            nuove = _parse_opml(contenuto)
        else:
            for indice, url in enumerate(_url_import(contenuto), start=1):
                nuove.append(
                    Fonte(
                        nome=_nome_fonte("", url, indice),
                        url=url,
                        categoria=CATEGORIA_DA_ASSEGNARE,
                        attivo=False,
                        note="importato dalla dashboard",
                    )
                )
    except (DashboardError, ImportError_) as exc:
        return esistenti, 0, 0, 0, [f"Import feed malformato: {exc}"], None

    if not nuove:
        return esistenti, 0, 0, 0, avvisi, None
    if len(nuove) > massimo:
        avvisi.append(
            f"Import limitato a {massimo} feed: {len(nuove) - massimo} non processati."
        )
        nuove = nuove[:massimo]

    # Deduplica interna e rispetto alla config.
    viste: set[str] = set()
    uniche: list[Fonte] = []
    for fonte in nuove:
        chiave = normalizza_url(fonte.url)
        if chiave in viste:
            continue
        viste.add(chiave)
        uniche.append(fonte)
    esistenti_url = {normalizza_url(f.url) for f in esistenti}
    nuove_effettive = [
        f for f in uniche if normalizza_url(f.url) not in esistenti_url
    ]
    duplicate_count = len(uniche) - len(nuove_effettive)

    # Verifica solo le nuove, max 20, timeout 10, 8 worker.
    da_verificare = nuove_effettive
    percorsi_visti = Path(impostazioni.get("stato", {}).get("visti", "state/visti.json"))
    if not percorsi_visti.is_absolute():
        percorsi_visti = ROOT / percorsi_visti
    visti = Visti(
        percorsi_visti,
        giorni_pruning=int(impostazioni.get("stato", {}).get("giorni_pruning", 60)),
        logger=logger,
        adesso=adesso_roma(),
    )
    esiti = controlla_tutte(
        da_verificare,
        impostazioni,
        visti=visti,
        logger=logger,
        max_workers=8,
        timeout=10,
    ) if da_verificare else []
    per_url = {normalizza_url(e.url): e for e in esiti}
    aggiunte: list[Fonte] = []
    scartate = 0
    for fonte in nuove_effettive:
        esito = per_url.get(normalizza_url(fonte.url))
        stato = esito.stato if esito else "errore"
        if stato == "podcast":
            scartate += 1
            avvisi.append(f"Feed podcast scartato: {fonte.url}")
            continue
        controllata = replace(
            fonte,
            attivo=False,
            controllo=stato,
            ultimo_controllo=iso_roma(adesso_roma()),
        )
        aggiunte.append(controllata)
    merged, _ = merge_fonti(esistenti, aggiunte)
    blocco = (
        f"Import completato: {len(aggiunte)} aggiunte, {duplicate_count} duplicate, "
        f"{scartate} scartate."
    )
    return merged, len(aggiunte), duplicate_count, scartate, avvisi, blocco



def leggi_payload(
    payload_json: str | None = None,
    payload_file: str | Path | None = None,
) -> dict[str, Any]:
    """Legge il payload JSON da stringa o file, con limiti e messaggi chiari."""
    if (payload_json is None) == (payload_file is None):
        raise DashboardError("Indica esattamente uno tra --payload-json e --payload-file.")
    if payload_file is not None:
        percorso = Path(payload_file)
        if not percorso.exists():
            raise DashboardError(f"Payload non trovato: {percorso}")
        try:
            grezzo = percorso.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise DashboardError(f"Non riesco a leggere il payload: {exc}") from exc
    else:
        grezzo = str(payload_json or "")
    if not grezzo.strip():
        raise DashboardError("Payload vuoto.")
    if len(grezzo.encode("utf-8")) > LIMITE_PAYLOAD:
        raise DashboardError(
            f"Payload oltre {LIMITE_PAYLOAD} byte: riduci le fonti o i testi."
        )
    try:
        dati = json.loads(grezzo)
    except json.JSONDecodeError as exc:
        raise DashboardError(f"Payload JSON non valido: {exc}") from exc
    if not isinstance(dati, dict):
        raise DashboardError("Il payload deve essere un oggetto JSON.")
    return dati


def _testo_file(percorso: Path, default: str) -> str:
    try:
        testo = percorso.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return default
    return testo or default


def _booleano_payload(valore: Any, default: bool = False) -> bool:
    if isinstance(valore, bool):
        return valore
    if isinstance(valore, (int, float)):
        return bool(valore)
    testo = str(valore).strip().casefold()
    if testo in {"true", "1", "yes", "si", "attivo", "attiva"}:
        return True
    if testo in {"false", "0", "no", "off", "disattivo", "disattivata"}:
        return False
    return default


def _categoria_payload(
    valore: Any, contesto: str, avvisi: list[str]
) -> str | None:
    if valore is None:
        return None
    if not isinstance(valore, str):
        avvisi.append(f"{contesto}: categoria non testuale, ignorata.")
        return None
    testo = valore.strip()
    if not testo:
        return None
    if normalizza_testo(testo) in {"da assegnare", "daassegnare"}:
        return CATEGORIA_DA_ASSEGNARE
    trovata = trova_categoria(testo)
    if trovata:
        return trovata
    avvisi.append(f"{contesto}: categoria '{testo}' sconosciuta, uso da-assegnare.")
    return CATEGORIA_DA_ASSEGNARE


def _url_payload(valore: Any) -> str | None:
    if not isinstance(valore, str):
        return None
    url = valore.strip()
    if not url or len(url) > 2048:
        return None
    try:
        parti = urlsplit(url)
    except ValueError:
        return None
    if parti.scheme not in {"http", "https"} or not parti.netloc:
        return None
    if parti.username or parti.password:
        return None
    return url


def _nome_payload(valore: Any) -> str | None:
    if not isinstance(valore, str):
        return None
    nome = valore.strip()
    if not nome or len(nome) > 120 or any(ord(c) < 32 for c in nome):
        return None
    return nome


def _piano_payload(
    payload: dict[str, Any],
    impostazioni: dict[str, Any],
    base: Path,
) -> dict[str, Any]:
    candidato = copy.deepcopy(impostazioni)
    modifiche: list[str] = []
    avvisi: list[str] = []
    modifiche_impostazioni = False
    sconosciuti = sorted(set(payload) - CAMPI_PAYLOAD)
    if sconosciuti:
        avvisi.append("Campi payload ignorati: " + ", ".join(sconosciuti) + ".")

    if "nome" in payload:
        nome = _nome_payload(payload["nome"])
        if nome is None:
            raise DashboardError("Payload: 'nome' deve essere una stringa non vuota (max 120).")
        if nome != candidato.get("nome_utente"):
            modifiche.append(f"nome_utente: {candidato.get('nome_utente')} -> {nome}")
            candidato["nome_utente"] = nome
            modifiche_impostazioni = True

    if "categorie" in payload:
        valore = payload["categorie"]
        if not isinstance(valore, list):
            raise DashboardError("Payload: 'categorie' deve essere una lista.")
        categorie: list[str] = []
        for elemento in valore:
            if not isinstance(elemento, str):
                avvisi.append("Categoria non testuale scartata.")
                continue
            trovata = trova_categoria(elemento)
            if not trovata:
                avvisi.append(f"Categoria sconosciuta scartata: {elemento!r}.")
                continue
            if trovata not in categorie:
                categorie.append(trovata)
        if not categorie:
            raise DashboardError("Payload: nessuna categoria valida in 'categorie'.")
        if categorie != candidato.get("categorie_default"):
            modifiche.append("categorie_default aggiornate: " + ", ".join(categorie))
            candidato["categorie_default"] = categorie
            modifiche_impostazioni = True

    incipit_path = base / "config" / "incipit.txt"
    outro_path = base / "config" / "outro.txt"
    incipit = _testo_file(incipit_path, INCIPIT_DEFAULT)
    outro = _testo_file(outro_path, OUTRO_DEFAULT)
    incipit_modificato = False
    outro_modificato = False
    if "incipit" in payload:
        valore = payload["incipit"]
        if not isinstance(valore, str):
            raise DashboardError("Payload: 'incipit' deve essere una stringa.")
        nuovo = valore.strip()
        if not nuovo:
            raise DashboardError("Payload: 'incipit' non può essere vuoto.")
        if len(nuovo) > LIMITE_TESTO_PAYLOAD:
            raise DashboardError(
                f"Payload: 'incipit' oltre {LIMITE_TESTO_PAYLOAD} caratteri."
            )
        if nuovo != incipit:
            modifiche.append("incipit aggiornato")
            incipit = nuovo
            incipit_modificato = True
    if "outro" in payload:
        valore = payload["outro"]
        if not isinstance(valore, str):
            raise DashboardError("Payload: 'outro' deve essere una stringa.")
        nuovo = valore.strip() or OUTRO_DEFAULT
        if len(nuovo) > LIMITE_TESTO_PAYLOAD:
            raise DashboardError(
                f"Payload: 'outro' oltre {LIMITE_TESTO_PAYLOAD} caratteri."
            )
        if nuovo != outro:
            modifiche.append("outro aggiornato")
            outro = nuovo
            outro_modificato = True

    if "voce" in payload:
        valore = payload["voce"]
        if not isinstance(valore, str):
            raise DashboardError("Payload: 'voce' deve essere una stringa.")
        voci = {
            str(v.get("nome", "")).strip().casefold(): str(v.get("nome", "")).strip()
            for v in candidato.get("voce", {}).get("voci", [])
            if isinstance(v, dict) and v.get("nome")
        }
        canonica = voci.get(valore.strip().casefold())
        if not canonica:
            avvisi.append(f"Voce sconosciuta scartata: {valore!r}; mantengo {candidato['voce']['nome']}.")
        elif canonica != candidato["voce"]["nome"]:
            modifiche.append(f"voce.nome: {candidato['voce']['nome']} -> {canonica}")
            candidato["voce"]["nome"] = canonica
            modifiche_impostazioni = True

    if "velocita" in payload:
        velocita, avvisi_velocita = normalizza_velocita(payload["velocita"])
        avvisi.extend(avvisi_velocita)
        if abs(float(velocita) - float(candidato["voce"].get("velocita", 1.1))) > 1e-9:
            modifiche.append(
                f"voce.velocita: {candidato['voce'].get('velocita')} -> {velocita:g}"
            )
            candidato["voce"]["velocita"] = velocita
            modifiche_impostazioni = True

    if "motore" in payload:
        valore = payload["motore"]
        if not isinstance(valore, str):
            raise DashboardError("Payload: 'motore' deve essere una stringa.")
        motore = valore.strip().casefold()
        if motore not in MOTORI_VALIDI:
            avvisi.append(f"Motore non valido scartato: {valore!r}; mantengo {candidato.get('tts_motore')}.")
        elif motore != candidato.get("tts_motore"):
            modifiche.append(f"tts_motore: {candidato.get('tts_motore')} -> {motore}")
            candidato["tts_motore"] = motore
            modifiche_impostazioni = True

    if "suono" in payload:
        valore = payload["suono"]
        if not isinstance(valore, str):
            raise DashboardError("Payload: 'suono' deve essere una stringa.")
        suono = valore.strip().casefold()
        if suono not in SUONI_VALIDI:
            avvisi.append(f"Suono non valido scartato: {valore!r}; mantengo {candidato.get('suono_transizione')}.")
        elif suono != candidato.get("suono_transizione"):
            modifiche.append(
                f"suono_transizione: {candidato.get('suono_transizione')} -> {suono}"
            )
            candidato["suono_transizione"] = suono
            modifiche_impostazioni = True

    if "durata" in payload:
        valore = payload["durata"]
        if not isinstance(valore, str):
            raise DashboardError("Payload: 'durata' deve essere una stringa.")
        durata = valore.strip().casefold()
        if durata not in DURATE_VALIDE or durata not in candidato.get("preset", {}):
            avvisi.append(f"Durata non valida scartata: {valore!r}; mantengo {candidato.get('durata_default')}.")
        elif durata != candidato.get("durata_default"):
            modifiche.append(f"durata_default: {candidato.get('durata_default')} -> {durata}")
            candidato["durata_default"] = durata
            modifiche_impostazioni = True

    if "orario" in payload:
        valore = payload["orario"]
        if not isinstance(valore, str):
            raise DashboardError("Payload: 'orario' deve essere una stringa HH:00.")
        orario = valore.strip()
        if not orario_valido(orario):
            avvisi.append(
                f"Orario non valido scartato: {valore!r}; mantengo {candidato.get('orario_generazione')}."
            )
        elif orario != candidato.get("orario_generazione"):
            modifiche.append(
                f"orario_generazione: {candidato.get('orario_generazione')} -> {orario}"
            )
            candidato["orario_generazione"] = orario
            modifiche_impostazioni = True

    fonti = list(caricare_fonti_per_payload(base))
    aggiunte = 0
    aggiornate = 0
    if "fonti" in payload:
        valore = payload["fonti"]
        if not isinstance(valore, list):
            raise DashboardError("Payload: 'fonti' deve essere una lista.")
        if len(valore) > 200:
            raise DashboardError("Payload: massimo 200 fonti.")
        esistenti = {normalizza_url(f.url): f for f in fonti}
        aggiornamenti: dict[str, Fonte] = {}
        nuove: list[Fonte] = []
        viste: set[str] = set()
        for indice, elemento in enumerate(valore, start=1):
            contesto = f"Fonte {indice}"
            if not isinstance(elemento, dict):
                avvisi.append(f"{contesto}: non è un oggetto, scartata.")
                continue
            url = _url_payload(elemento.get("url"))
            if not url:
                avvisi.append(f"{contesto}: URL non valido, scartata.")
                continue
            chiave = normalizza_url(url)
            if chiave in viste:
                avvisi.append(f"{contesto}: URL duplicata, scartata.")
                continue
            viste.add(chiave)
            corrente = esistenti.get(chiave)
            nome = _nome_payload(elemento.get("nome"))
            if nome is None and corrente is None:
                avvisi.append(f"{contesto}: nome mancante, scartata.")
                continue
            categoria = _categoria_payload(
                elemento.get("categoria") if "categoria" in elemento else None,
                contesto,
                avvisi,
            )
            if "categoria" in elemento and categoria is None:
                avvisi.append(f"{contesto}: categoria non valida, scartata.")
                continue
            if corrente is not None:
                nuova_categoria = categoria or corrente.categoria
                nuovo_attivo = (
                    _booleano_payload(elemento["attivo"], corrente.attivo)
                    if "attivo" in elemento
                    else corrente.attivo
                )
                if nuova_categoria == CATEGORIA_DA_ASSEGNARE:
                    nuovo_attivo = False
                aggiornata = replace(
                    corrente,
                    nome=nome or corrente.nome,
                    categoria=nuova_categoria,
                    attivo=nuovo_attivo,
                )
                if aggiornata != corrente:
                    aggiornamenti[chiave] = aggiornata
                    aggiornate += 1
            else:
                nuova_categoria = categoria or CATEGORIA_DA_ASSEGNARE
                nuovo_attivo = _booleano_payload(elemento.get("attivo"), False)
                if nuova_categoria == CATEGORIA_DA_ASSEGNARE:
                    nuovo_attivo = False
                nuove.append(
                    Fonte(
                        nome=nome or "",
                        url=url,
                        categoria=nuova_categoria,
                        attivo=nuovo_attivo,
                        controllo="da-verificare",
                        note=None,
                    )
                )
                aggiunte += 1
        fonti = [
            aggiornamenti.get(normalizza_url(f.url), f)
            for f in fonti
        ] + nuove
        if len(fonti) > 200:
            raise DashboardError("Payload: la configurazione supererebbe 200 fonti.")
        if aggiunte or aggiornate:
            modifiche.append(f"fonti: {aggiunte} aggiunte, {aggiornate} aggiornate")
    else:
        fonti = list(fonti)

    candidato["voce"] = copy.deepcopy(candidato.get("voce", {}))
    candidato["voce"]["nome"] = candidato["voce"].get("nome", "Kore")
    if not isinstance(candidato.get("categorie_default"), list) or not candidato["categorie_default"]:
        raise DashboardError("Configurazione risultante senza categorie.")
    valida_impostazioni(candidato)

    return {
        "impostazioni": candidato,
        "incipit": incipit,
        "outro": outro,
        "fonti": fonti,
        "modifiche": modifiche,
        "avvisi": avvisi,
        "modifiche_impostazioni": modifiche_impostazioni,
        "incipit_modificato": incipit_modificato,
        "outro_modificato": outro_modificato,
        "aggiunte": aggiunte,
        "aggiornate": aggiornate,
    }


def caricare_fonti_per_payload(base: Path) -> list[Fonte]:
    percorso = base / "config" / "fonti.yaml"
    if not percorso.exists():
        raise DashboardError(f"File fonti non trovato: {percorso}")
    return carica_fonti_tutte(percorso)


def _rigenera_pubblico(
    radice: Path,
    impostazioni: dict[str, Any],
    fonti: list[Fonte],
    incipit: str,
    outro: str,
) -> None:
    percorso = radice / "docs" / "impostazioni.json"
    precedente: dict[str, Any] = {}
    if percorso.exists():
        try:
            dati = json.loads(percorso.read_text(encoding="utf-8-sig"))
            if isinstance(dati, dict):
                precedente = dati
        except (OSError, json.JSONDecodeError):
            precedente = {}
    voce = str(precedente.get("voce") or impostazioni["voce"]["nome"])
    scrivi_impostazioni_pubbliche(
        percorso,
        categorie_attive=list(impostazioni["categorie_default"]),
        incipit_template=incipit,
        incipit_risolto=str(precedente.get("incipit_risolto") or incipit),
        voce=voce,
        voce_label=str(precedente.get("voce_label") or voce),
        velocita=float(impostazioni["voce"]["velocita"]),
        motore=str(precedente.get("motore") or impostazioni["tts_motore"]),
        motore_richiesto=str(impostazioni["tts_motore"]),
        motore_configurato=str(impostazioni["tts_motore"]),
        data=str(precedente.get("data", "")),
        nome_utente=str(impostazioni.get("nome_utente", "")),
        suono=str(impostazioni.get("suono_transizione", "ding")),
        outro=outro,
        fonti_totali=len(fonti),
        fonti_attive=sum(1 for f in fonti if f.attivo),
        issue_url=precedente.get("issue_url"),
        repo_url=precedente.get("repo_url")
        or impostazioni.get("github", {}).get("repo_url"),
        voce_configurata=str(impostazioni["voce"]["nome"]),
        durata_default=str(impostazioni.get("durata_default", "standard")),
        orario_generazione=str(impostazioni.get("orario_generazione", "07:00")),
        fonti=fonti_pubbliche(fonti),
    )


def applica_payload(
    payload: dict[str, Any],
    *,
    dry_run: bool = False,
    base: str | Path | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Valida tutto, poi applica in modo idempotente; su errore non scrive nulla."""
    logger = logger or logging.getLogger("notiziario")
    radice = Path(base) if base is not None else ROOT
    config_dir = radice / "config"
    impostazioni_path = config_dir / "impostazioni.json"
    if not impostazioni_path.exists():
        raise DashboardError(f"File impostazioni non trovato: {impostazioni_path}")
    impostazioni = carica_impostazioni(impostazioni_path)
    try:
        grezze = json.loads(impostazioni_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DashboardError(f"Impostazioni illeggibili: {exc}") from exc
    piano = _piano_payload(payload, impostazioni, radice)
    candidate = piano["impostazioni"]
    candidate_fonti = piano["fonti"]

    if not dry_run:
        if piano["modifiche_impostazioni"]:
            grezze["nome_utente"] = candidate["nome_utente"]
            grezze["categorie_default"] = candidate["categorie_default"]
            grezze["tts_motore"] = candidate["tts_motore"]
            grezze["suono_transizione"] = candidate["suono_transizione"]
            grezze["durata_default"] = candidate["durata_default"]
            grezze["orario_generazione"] = candidate["orario_generazione"]
            grezze.setdefault("voce", {})
            if isinstance(grezze["voce"], dict):
                grezze["voce"]["nome"] = candidate["voce"]["nome"]
                grezze["voce"]["velocita"] = candidate["voce"]["velocita"]
            impostazioni_path.write_text(
                json.dumps(grezze, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            logger.info("Dashboard: impostazioni aggiornate.")
        if piano["incipit_modificato"]:
            (config_dir / "incipit.txt").write_text(
                piano["incipit"].strip() + "\n", encoding="utf-8", newline="\n"
            )
        if piano["outro_modificato"]:
            (config_dir / "outro.txt").write_text(
                piano["outro"].strip() + "\n", encoding="utf-8", newline="\n"
            )
        if candidate_fonti != list(caricare_fonti_per_payload(radice)):
            salva_fonti(config_dir / "fonti.yaml", candidate_fonti)
            logger.info("Dashboard: fonti aggiornate.")
        fonti_config = carica_fonti_tutte(config_dir / "fonti.yaml")
        _rigenera_pubblico(
            radice,
            candidate,
            fonti_config,
            piano["incipit"],
            piano["outro"],
        )

    return {
        "dry_run": dry_run,
        "modifiche": piano["modifiche"],
        "avvisi": piano["avvisi"],
        "aggiunte": piano["aggiunte"],
        "aggiornate": piano["aggiornate"],
        "fonti_totali": len(carica_fonti_tutte(config_dir / "fonti.yaml")),
    }


def genera_corpo(
    impostazioni: dict[str, Any],
    fonti: list[Fonte],
    modello_incipit: str,
    modello_outro: str = "",
) -> str:
    categorie_attive = set(impostazioni.get("categorie_default", []))
    righe = ["## Nome", f"nome: {impostazioni.get('nome_utente', '')}", "", "## Categorie"]
    for categoria in CATEGORIE:
        righe.append(f"- [{'x' if categoria.id in categorie_attive else ' '}] {categoria.label}")
    righe += ["", "## Incipit", modello_incipit.strip(), "", "## Voce"]
    voce = impostazioni.get("voce", {})
    righe += [
        f"voce: {voce.get('nome', 'Kore')}",
        f"velocita: {float(voce.get('velocita', 1.1)):g}",
        f"motore: {impostazioni.get('tts_motore', 'gemini')}",
        "",
        "## Suono",
        f"suono: {impostazioni.get('suono_transizione', 'ding')}",
        "",
        "## Outro",
        modello_outro.strip() or OUTRO_DEFAULT,
        "",
        "## Fonti",
        _righe_fonti(fonti),
        "",
        "## Import feed",
        "Incolla qui un OPML o una URL per riga. Le nuove fonti vengono importate spente.",
    ]
    corpo = "\n".join(righe).strip() + "\n"
    if len(corpo) > LIMITE_BODY:
        raise DashboardError(
            f"Corpo issue oltre {LIMITE_BODY} caratteri: usa l'import locale."
        )
    return corpo


def _aggiorna_issue(token: str, repo: str, numero: int, corpo: str) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Notiziario/0.5",
    }
    risposta = requests.patch(
        f"https://api.github.com/repos/{repo}/issues/{numero}",
        headers=headers,
        json={"body": corpo},
        timeout=30,
    )
    if risposta.status_code >= 400:
        raise DashboardError(f"GitHub ha rifiutato l'aggiornamento (HTTP {risposta.status_code}).")


def applica(
    dry_run: bool = False, logger: logging.Logger | None = None
) -> dict[str, Any]:
    logger = logger or logging.getLogger("notiziario")
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = repository_github()
    impostazioni = carica_impostazioni()
    numero = numero_issue_categorie(impostazioni)
    if not token or not repo or not numero:
        raise DashboardError(
            "Servono GITHUB_TOKEN, GITHUB_REPOSITORY e GITHUB_ISSUE_CATEGORIE."
        )
    try:
        corpo = leggi_issue(token, repo, numero)
    except Exception as exc:
        raise DashboardError(f"Issue non raggiungibile: {exc}") from exc
    if len(corpo) > LIMITE_BODY:
        raise DashboardError(
            f"Issue oltre {LIMITE_BODY} caratteri: usa l'import locale."
        )

    fonti = carica_fonti_tutte()
    nome, avvisi_nome = parse_nome(corpo)
    suono, avvisi_suono = parse_suono(corpo)
    outro_modello, avvisi_outro = parse_outro(corpo)
    fonti2, avvisi_fonti = parse_fonti(corpo, fonti)
    fonti3, aggiunte, duplicate, scartate, avvisi_import, blocco = parse_import(
        corpo, impostazioni, fonti2, logger=logger
    )
    avvisi = avvisi_nome + avvisi_fonti + avvisi_import + avvisi_suono + avvisi_outro
    fonti_sezione_valida = not any(
        "malformata" in a or "ambigua" in a or "duplicata" in a
        for a in avvisi_fonti
    )
    for avviso in avvisi:
        logger.warning("Dashboard: %s", avviso)

    modifiche = []
    config_modificato = False
    if nome is not None and nome != impostazioni.get("nome_utente"):
        modifiche.append(f"nome_utente: {impostazioni.get('nome_utente')} -> {nome}")
        impostazioni["nome_utente"] = nome
        config_modificato = True
    if suono is not None and suono != impostazioni.get("suono_transizione"):
        modifiche.append(f"suono_transizione: {impostazioni.get('suono_transizione')} -> {suono}")
        impostazioni["suono_transizione"] = suono
        config_modificato = True
    if outro_modello is not None:
        modifiche.append("outro aggiornato")
    if fonti3 != fonti:
        modifiche.append(f"fonti aggiornate: {len(fonti3)} totali")
    if blocco is not None:
        modifiche.append(blocco)

    if not dry_run:
        if config_modificato:
            (ROOT / "config" / "impostazioni.json").write_text(
                json.dumps(impostazioni, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        if fonti3 != fonti:
            scrivi_fonti_yaml(ROOT / "config" / "fonti.yaml", fonti3)
        if outro_modello is not None:
            (ROOT / "config" / "outro.txt").write_text(
                outro_modello.strip() + "\n", encoding="utf-8", newline="\n"
            )
        nuovo_corpo = corpo
        if nome is not None and _contenuto(corpo, "Nome") is not None:
            nuovo_corpo = _sostituisci_sezione(nuovo_corpo, "Nome", f"nome: {nome}")
        if fonti3 != fonti and fonti_sezione_valida and _contenuto(corpo, "Fonti") is not None:
            nuovo_corpo = _sostituisci_sezione(
                nuovo_corpo, "Fonti", _righe_fonti(fonti3)
            )
        elif fonti3 != fonti:
            avvisi.append(
                "Sezione Fonti assente o malformata: config aggiornata ma blocco invariato."
            )
        if blocco is not None:
            nuovo_corpo = _sostituisci_sezione(nuovo_corpo, "Import feed", blocco)
        if nuovo_corpo != corpo:
            if len(nuovo_corpo) > LIMITE_BODY:
                raise DashboardError(
                    f"Corpo issue oltre {LIMITE_BODY} caratteri: usa l'import locale."
                )
            _aggiorna_issue(token, repo, numero, nuovo_corpo)
            logger.info("Issue #%d aggiornata.", numero)

    return {
        "dry_run": dry_run,
        "nome": nome,
        "aggiunte": aggiunte,
        "duplicate": duplicate,
        "scartate": scartate,
        "avvisi": avvisi,
        "modifiche": modifiche,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dashboard del Notiziario: payload JSON o issue GitHub."
    )
    parser.add_argument("--applica", action="store_true", help="Legge e applica la issue.")
    gruppo = parser.add_mutually_exclusive_group()
    gruppo.add_argument("--payload-json", help="Payload JSON minificato delle impostazioni.")
    gruppo.add_argument("--payload-file", help="File JSON con il payload delle impostazioni.")
    parser.add_argument(
        "--applica-payload",
        action="store_true",
        help="Applica il payload a config/ (senza questo flag fa solo dry-run).",
    )
    parser.add_argument(
        "--genera-corpo",
        action="store_true",
        help="Stampa il markdown della issue dalla config.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Mostra senza scrivere.")
    parser.add_argument("--out", help="Scrive il corpo generato in un file UTF-8.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger("notiziario")

    if args.payload_json is not None or args.payload_file is not None:
        try:
            payload = leggi_payload(args.payload_json, args.payload_file)
            dry_run = args.dry_run or not args.applica_payload
            risultato = applica_payload(
                payload, dry_run=dry_run, logger=logger
            )
        except DashboardError as exc:
            print(f"Payload non applicato: {exc}", file=sys.stderr)
            return 1
        etichetta = "dry-run: nessuna scrittura" if dry_run else "applicato"
        print(
            f"Payload {etichetta}; fonti totali: {risultato['fonti_totali']} "
            f"({risultato['aggiunte']} aggiunte, {risultato['aggiornate']} aggiornate)."
        )
        for modifica in risultato["modifiche"]:
            print(f"- {modifica}")
        for avviso in risultato["avvisi"]:
            print(f"! {avviso}")
        return 0
    if args.applica_payload:
        print(
            "Payload non applicato: manca --payload-json o --payload-file.",
            file=sys.stderr,
        )
        return 1

    if args.genera_corpo:
        impostazioni = carica_impostazioni()
        fonti = carica_fonti_tutte()
        from .incipit import leggi_modello_incipit

        modello, _ = leggi_modello_incipit(
            impostazioni.get("incipit", {}).get("file", "config/incipit.txt")
        )
        from .outro import leggi_modello_outro
        modello_outro, _ = leggi_modello_outro(
            impostazioni.get("outro", {}).get("file", "config/outro.txt")
        )
        corpo = genera_corpo(impostazioni, fonti, modello, modello_outro)
        if args.out:
            Path(args.out).write_text(corpo, encoding="utf-8", newline="\n")
        else:
            print(corpo, end="")
        return 0
    if not args.applica:
        parser.print_help()
        return 2
    try:
        risultato = applica(dry_run=args.dry_run, logger=logger)
    except DashboardError as exc:
        print(f"Dashboard non applicata: {exc}", file=sys.stderr)
        return 1
    print(
        f"Dashboard: {risultato['aggiunte']} aggiunte, "
        f"{risultato['duplicate']} duplicate, {risultato['scartate']} scartate."
    )
    for modifica in risultato["modifiche"]:
        print(f"- {modifica}")
    for avviso in risultato["avvisi"]:
        print(f"! {avviso}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
