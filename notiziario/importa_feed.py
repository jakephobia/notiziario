"""Import di liste RSS da OPML, TXT, CSV e JSON, con verifica reale."""

from __future__ import annotations

import csv
import io
import json
import logging
import re
try:
    from defusedxml import ElementTree as ET
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .categorie import CATEGORIA_DA_ASSEGNARE, trova_categoria
from .config import Fonte, carica_fonti_tutte, carica_impostazioni
from .controllo_feed import controlla_tutte
from .fetch import normalizza_url
from .sicurezza import UrlRifiutato, valida_url_pubblica
from .fonti_io import merge_fonti, scrivi_fonti_yaml, sostituisci_fonte
from .tempo import adesso_roma, data_iso_roma
from .visti import Visti


class ImportError_(Exception):
    """Errore bloccante dell'import."""


@dataclass
class RisultatoImport:
    tipo: str = ""
    importati: int = 0
    duplicati: int = 0
    scartati: int = 0
    motivi: list[str] = field(default_factory=list)
    nuove: list[Fonte] = field(default_factory=list)
    fonti: list[Fonte] = field(default_factory=list)
    esiti: list[dict] = field(default_factory=list)


def _nome_fonte(valore: str | None, url: str, indice: int) -> str:
    nome = str(valore or "").strip()
    if nome:
        return nome[:200]
    host = urlsplit(url).netloc.replace("www.", "").strip()
    return host[:200]


def _mappa_categoria(valore: str | None) -> str:
    if not valore:
        return CATEGORIA_DA_ASSEGNARE
    trovata = trova_categoria(str(valore))
    return trovata or CATEGORIA_DA_ASSEGNARE


def _url_valido(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parti = urlsplit(url.strip())
    except ValueError:
        return False
    if parti.scheme not in {"http", "https"} or not parti.netloc:
        return False
    try:
        valida_url_pubblica(url, risolvi=False)
    except UrlRifiutato:
        return False
    return True


def _parse_opml(testo: str) -> list[Fonte]:
    try:
        radice = ET.fromstring(testo)
    except ET.ParseError as exc:
        raise ImportError_(f"OPML non valido: {exc}") from exc
    fonti = []
    for outline in radice.iter("outline"):
        url = (outline.get("xmlUrl") or outline.get("xmlurl") or "").strip()
        if not url:
            continue
        titolo = outline.get("title") or outline.get("text") or ""
        categoria = _mappa_categoria(
            outline.get("category") or outline.get("categoria")
        )
        fonti.append(
            Fonte(
                nome=_nome_fonte(titolo, url, len(fonti) + 1),
                url=url,
                categoria=categoria,
                attivo=False,
                note="importato da OPML",
            )
        )
    return fonti


def _parse_txt(testo: str) -> list[Fonte]:
    fonti = []
    for riga in testo.splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#"):
            continue
        fonti.append(
            Fonte(
                nome=_nome_fonte("", riga, len(fonti) + 1),
                url=riga,
                categoria=CATEGORIA_DA_ASSEGNARE,
                attivo=False,
                note="importato da TXT",
            )
        )
    return fonti


def _parse_csv(testo: str) -> list[Fonte]:
    righe = list(csv.reader(io.StringIO(testo)))
    if not righe:
        return []
    prima = [c.strip().casefold().lstrip("\ufeff") for c in righe[0]]
    chiavi_url = {"url", "url_feed", "feed", "link"}
    chiavi_titolo = {"titolo", "title", "nome", "name"}
    chiavi_categoria = {"categoria", "category"}
    idx_url = next((i for i, c in enumerate(prima) if c in chiavi_url), None)
    idx_titolo = next((i for i, c in enumerate(prima) if c in chiavi_titolo), None)
    idx_categoria = next(
        (i for i, c in enumerate(prima) if c in chiavi_categoria), None
    )
    if idx_url is None:
        # Nessun header: prima colonna URL, poi titolo e categoria se presenti.
        corpo = righe
        idx_url, idx_titolo, idx_categoria = 0, 1, 2
    else:
        corpo = righe[1:]

    fonti = []
    for riga in corpo:
        if not riga or not any(c.strip() for c in riga):
            continue
        url = riga[idx_url].strip() if idx_url < len(riga) else ""
        titolo = (
            riga[idx_titolo].strip()
            if idx_titolo is not None and idx_titolo < len(riga)
            else ""
        )
        categoria = (
            riga[idx_categoria].strip()
            if idx_categoria is not None and idx_categoria < len(riga)
            else ""
        )
        fonti.append(
            Fonte(
                nome=_nome_fonte(titolo, url, len(fonti) + 1),
                url=url,
                categoria=_mappa_categoria(categoria),
                attivo=False,
                note="importato da CSV",
            )
        )
    return fonti


def _parse_json(testo: str) -> list[Fonte]:
    try:
        dati = json.loads(testo)
    except json.JSONDecodeError as exc:
        raise ImportError_(f"JSON non valido: {exc}") from exc
    if isinstance(dati, dict):
        lista = None
        for chiave in ("fonti", "feeds", "items", "sources", "data"):
            if isinstance(dati.get(chiave), list):
                lista = dati[chiave]
                break
        if lista is None:
            raise ImportError_("JSON senza una lista di feed.")
        dati = lista
    if not isinstance(dati, list):
        raise ImportError_("Il JSON deve essere una lista o un oggetto con lista.")
    fonti = []
    for indice, voce in enumerate(dati, start=1):
        if isinstance(voce, str):
            voce = {"url": voce}
        if not isinstance(voce, dict):
            continue
        url = str(
            voce.get("url")
            or voce.get("url_feed")
            or voce.get("feed")
            or ""
        ).strip()
        titolo = str(
            voce.get("titolo")
            or voce.get("title")
            or voce.get("name")
            or ""
        ).strip()
        categoria = str(voce.get("categoria") or voce.get("category") or "").strip()
        fonti.append(
            Fonte(
                nome=_nome_fonte(titolo, url, indice),
                url=url,
                categoria=_mappa_categoria(categoria),
                attivo=False,
                note="importato da JSON",
            )
        )
    return fonti


def _leggi_lista(percorso: str | Path, max_mb: int) -> tuple[list[Fonte], str]:
    path = Path(percorso)
    if not path.exists():
        raise ImportError_(f"File non trovato: {path}")
    dimensione = path.stat().st_size
    if dimensione > max_mb * 1024 * 1024:
        raise ImportError_(f"File troppo grande: {dimensione} byte (max {max_mb} MB).")
    testo = path.read_text(encoding="utf-8-sig")
    suffisso = path.suffix.casefold()
    if suffisso == ".opml":
        return _parse_opml(testo), "OPML"
    if suffisso == ".txt":
        return _parse_txt(testo), "TXT"
    if suffisso == ".csv":
        return _parse_csv(testo), "CSV"
    if suffisso == ".json":
        return _parse_json(testo), "JSON"
    # Auto-detect sul contenuto.
    inizio = testo.lstrip()
    if inizio.startswith("<"):
        return _parse_opml(testo), "OPML"
    if inizio.startswith(("[", "{")):
        return _parse_json(testo), "JSON"
    if "," in inizio.splitlines()[0]:
        return _parse_csv(testo), "CSV"
    return _parse_txt(testo), "TXT"


def _indici_attivazione(valore: str | None, massimo: int) -> list[int]:
    if not valore:
        return []
    indici = []
    for pezzo in re.split(r"[,;\s]+", valore.strip()):
        if not pezzo:
            continue
        try:
            indice = int(pezzo)
        except ValueError:
            continue
        if 1 <= indice <= massimo:
            indici.append(indice - 1)
    return indici


def elenco_fonti(fonti: list[Fonte]) -> None:
    for indice, fonte in enumerate(fonti, start=1):
        segno = "x" if fonte.attivo else " "
        print(
            f"{indice:3}. [{segno}] {fonte.nome[:30]:30} "
            f"{fonte.categoria:16} {fonte.url}"
            + (f"  controllo={fonte.controllo}" if fonte.controllo else "")
        )


def importa_feed(
    percorso: str | Path,
    fonti_path: str | Path,
    categoria: str | None = None,
    attiva_tutte: bool = False,
    attiva_fonti: str | None = None,
    impostazioni: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
    output: str | Path = "output",
) -> RisultatoImport:
    logger = logger or logging.getLogger("notiziario")
    impostazioni = impostazioni or carica_impostazioni()
    esistenti = carica_fonti_tutte(fonti_path)
    report = RisultatoImport()
    nuove, tipo_file = _leggi_lista(
        percorso, int(impostazioni["importa_feed"]["max_file_mb"])
    )
    report.tipo = tipo_file
    massimo = int(impostazioni["importa_feed"]["max_feed"])
    if len(nuove) > massimo:
        report.scartati += len(nuove) - massimo
        report.motivi.append(f"Limite di {massimo} feed: scartati {len(nuove) - massimo}")
        nuove = nuove[:massimo]

    categoria_override = None
    if categoria:
        categoria_override = trova_categoria(categoria)
        if not categoria_override:
            report.motivi.append(
                f"Categoria '{categoria}' sconosciuta: uso da-assegnare."
            )

    dedupe: set[str] = {normalizza_url(f.url) for f in esistenti}
    valide: list[Fonte] = []
    for fonte in nuove:
        fonte = Fonte(
            nome=fonte.nome,
            url=fonte.url,
            categoria=fonte.categoria,
            attivo=False,
            note=fonte.note,
        )
        if categoria_override and fonte.categoria == CATEGORIA_DA_ASSEGNARE:
            fonte = Fonte(
                **{**fonte.__dict__, "categoria": categoria_override}
            )
        if not fonte.nome.strip():
            report.scartati += 1
            report.motivi.append(
                f"Titolo vuoto e URL senza host: scartata {fonte.url!r}"
            )
            continue
        if fonte.categoria == CATEGORIA_DA_ASSEGNARE:
            report.motivi.append(
                f"Fonte {fonte.url} senza categoria valida: da-assegnare, "
                "esclusa finché non viene assegnata."
            )
        if not _url_valido(fonte.url):
            report.scartati += 1
            report.motivi.append(f"URL non valido scartato: {fonte.url!r}")
            continue
        chiave = normalizza_url(fonte.url)
        if chiave in dedupe:
            report.duplicati += 1
            continue
        dedupe.add(chiave)
        valide.append(fonte)

    if valide:
        logger.info("Controllo reale di %d feed importati...", len(valide))
        percorso_visti = Path(impostazioni.get("stato", {}).get("visti", "state/visti.json"))
        if not percorso_visti.is_absolute():
            from .config import ROOT
            percorso_visti = ROOT / percorso_visti
        visti = Visti(
            percorso_visti,
            giorni_pruning=int(impostazioni.get("stato", {}).get("giorni_pruning", 60)),
            logger=logger,
            adesso=adesso_roma(),
        )
        esiti = controlla_tutte(
            valide,
            impostazioni,
            visti=visti,
            logger=logger,
            max_workers=int(impostazioni["fetch"]["max_workers"]),
        )
    else:
        esiti = []
    esiti_per_url = {normalizza_url(e.url): e for e in esiti}
    da_aggiungere: list[Fonte] = []
    for fonte in valide:
        esito = esiti_per_url.get(normalizza_url(fonte.url))
        stato = esito.stato if esito else "errore"
        if stato == "podcast":
            report.scartati += 1
            report.motivi.append(f"Feed podcast scartato: {fonte.url}")
            continue
        controllata = Fonte(
            **{
                **fonte.__dict__,
                "controllo": stato,
                "ultimo_controllo": adesso_roma().isoformat(),
            }
        )
        da_aggiungere.append(controllata)
        report.esiti.append(
            {
                "url": fonte.url,
                "nome": fonte.nome,
                "stato": stato,
                "motivo": esito.motivo if esito else "non verificato",
            }
        )

    merged, duplicati = merge_fonti(esistenti, da_aggiungere)
    report.duplicati += len(duplicati)
    report.importati = len(da_aggiungere)

    # Gli indici si riferiscono alla lista unita stampata (1-based).
    indici = _indici_attivazione(attiva_fonti, len(merged))
    esistenti_url = {normalizza_url(f.url) for f in esistenti}
    attivabili = {"ok", "testo-breve"}
    for posizione, fonte in enumerate(merged):
        if normalizza_url(fonte.url) in esistenti_url:
            continue
        esito = esiti_per_url.get(normalizza_url(fonte.url))
        stato = esito.stato if esito else fonte.controllo
        da_assegnare = fonte.categoria == CATEGORIA_DA_ASSEGNARE
        attiva = attiva_tutte and stato in attivabili and not da_assegnare
        if posizione in indici:
            attiva = stato in attivabili and not da_assegnare
        if attiva_tutte and stato in {"solo-titoli", "campione-insufficiente"}:
            report.motivi.append(
                f"Fonte {fonte.url}: {stato}, resta spenta (qualità insufficiente)."
            )
        if da_assegnare and (attiva_tutte or posizione in indici):
            report.motivi.append(
                f"Fonte {fonte.url} senza categoria: resta da-assegnare e "
                "non viene attivata."
            )
        if attiva:
            merged = sostituisci_fonte(
                merged, fonte.url, attivo=stato in attivabili
            )

    scrivi_fonti_yaml(fonti_path, merged)
    report.fonti = merged
    data_iso = data_iso_roma()
    report_path = Path(output) / f"importa-feed-{data_iso}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "file": str(percorso),
                "tipo": tipo_file,
                "importati": report.importati,
                "duplicati": report.duplicati,
                "scartati": report.scartati,
                "motivi": report.motivi,
                "esiti": report.esiti,
                "totale_fonti": len(merged),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def stampa_report(report: RisultatoImport, tipo: str = "") -> None:
    print(
        f"\nImport {tipo or report.tipo}: {report.importati} importati, "
        f"{report.duplicati} duplicati, {report.scartati} scartati."
    )
    for motivo in report.motivi:
        print(f"  - {motivo}")
    print("\nElenco fonti (indici per --attiva-fonti):")
    elenco_fonti(report.fonti)
