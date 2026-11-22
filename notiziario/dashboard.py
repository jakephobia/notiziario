"""Dashboard GitHub: la issue #1 diventa il punto unico di configurazione."""

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
    carica_fonti_tutte,
    carica_impostazioni,
    numero_issue_categorie,
    repository_github,
)
from .controllo_feed import controlla_tutte
from .fetch import normalizza_url
from .fonti_io import merge_fonti, scrivi_fonti_yaml, sostituisci_fonte
from .importa_feed import ImportError_, _nome_fonte, _parse_opml
from .outro import OUTRO_DEFAULT, estrai_outro_issue
from .tempo import adesso_roma, iso_roma
from .visti import Visti


LIMITE_BODY = 60_000
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
        description="Dashboard unica della issue GitHub per il Notiziario."
    )
    parser.add_argument("--applica", action="store_true", help="Legge e applica la issue.")
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
