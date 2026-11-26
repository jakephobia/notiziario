"""Generazione del feed RSS 2.0 con iTunes e della pagina player statica."""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from .categorie import label_categoria
from .config import Fonte
from .testi import formatta_durata, normalizza_mesi


NS_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
NS_NOTIZIARIO = "https://notiziario.local/ns/1.0"

ET.register_namespace("itunes", NS_ITUNES)
ET.register_namespace("notiziario", NS_NOTIZIARIO)


@dataclass
class Episodio:
    data: str
    titolo: str
    descrizione: str
    filename: str
    descrizione_breve: str = ""
    durata_secondi: float | None = None
    dimensione: int | None = None
    modalita: str = "fallback"
    categorie: list[str] = field(default_factory=list)
    voce: str = ""
    voce_label: str = ""
    velocita: float = 1.1
    tts_motore: str = ""
    pubblicato: str | None = None


def carica_storico(percorso: str | Path) -> dict[str, Any]:
    path = Path(percorso)
    if not path.exists():
        return {"episodi": []}
    try:
        dati = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"episodi": []}
    if not isinstance(dati, dict):
        return {"episodi": []}
    episodi = dati.get("episodi")
    if not isinstance(episodi, list):
        return {"episodi": []}
    validi = [
        e
        for e in episodi
        if isinstance(e, dict) and e.get("data") and e.get("filename")
    ]
    return {"episodi": validi}


def salva_storico(percorso: str | Path, storico: dict[str, Any]) -> None:
    path = Path(percorso)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(storico, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def aggiungi_episodio(
    storico: dict[str, Any], episodio: Episodio, max_episodi: int = 60
) -> dict[str, Any]:
    episodi = [
        e
        for e in storico.get("episodi", [])
        if isinstance(e, dict)
        and e.get("data") != episodio.data
        and e.get("guid") != f"notiziario-{episodio.data}"
    ]
    voce = asdict(episodio)
    voce["titolo"] = normalizza_mesi(str(voce.get("titolo", "")))
    voce["guid"] = f"notiziario-{episodio.data}"
    episodi.append(voce)
    episodi.sort(key=lambda e: str(e.get("data", "")), reverse=True)
    return {"episodi": episodi[: max(1, max_episodi)]}


def costruisci_url_audio(base_url: str, data: str, filename: str) -> str:
    """URL dell'enclosure.

    - con placeholder ``{data}``, ``{file}`` o ``{tag}`` li sostituisce;
    - se base_url termina con ``/download`` (release GitHub) aggiunge
      ``episodio-YYYY-MM-DD/nome.mp3``;
    - altrimenti aggiunge solo ``/nome.mp3``.
    """
    base = base_url.rstrip("/")
    if "{" in base:
        return base.format(
            data=data,
            file=filename,
            tag=f"episodio-{data}",
        )
    if base.endswith("/download"):
        return f"{base}/episodio-{data}/{filename}"
    return f"{base}/{filename}"


def _data_pubblicazione(episodio: dict[str, Any]) -> datetime:
    grezza = episodio.get("pubblicato")
    if grezza:
        try:
            data = datetime.fromisoformat(str(grezza).replace("Z", "+00:00"))
            if data.tzinfo is None:
                data = data.replace(tzinfo=timezone.utc)
            return data
        except ValueError:
            pass
    try:
        giorno = datetime.strptime(str(episodio["data"]), "%Y-%m-%d")
        return datetime.combine(giorno.date(), time(6, 0), tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return datetime.now(timezone.utc)


def normalizza_sito_url(url: str) -> str:
    """Evita owner.github.io/owner.github.io e garantisce lo slash finale."""
    url = (url or "").strip()
    if not url:
        return url
    parti = urlsplit(url)
    host = parti.netloc.casefold()
    percorso = parti.path.rstrip("/")
    if host.endswith(".github.io"):
        owner = host[: -len(".github.io")]
        duplicato = f"/{owner}.github.io"
        if percorso.casefold() == duplicato:
            percorso = ""
        elif percorso.casefold().startswith(duplicato + "/"):
            percorso = percorso[len(duplicato) :]
    percorso = percorso.rstrip("/") + "/"
    return urlunsplit((parti.scheme, parti.netloc, percorso, "", ""))


def _testo(elemento: ET.Element, namespace: str, tag: str, valore: Any) -> None:
    figlio = ET.SubElement(elemento, f"{{{namespace}}}{tag}" if namespace else tag)
    figlio.text = str(valore)


def scrivi_feed(
    storico: dict[str, Any],
    percorso: str | Path,
    impostazioni: dict[str, Any],
    base_url: str | None = None,
    sito_url: str | None = None,
) -> int:
    """Scrive docs/feed.xml. Restituisce il numero di episodi."""
    path = Path(percorso)
    path.parent.mkdir(parents=True, exist_ok=True)
    configurazione = impostazioni["feed"]
    base = base_url or configurazione.get("base_url", "")
    episodi = list(storico.get("episodi", []))

    rss = ET.Element("rss", {"version": "2.0"})
    canale = ET.SubElement(rss, "channel")
    ET.SubElement(canale, "title").text = configurazione.get("titolo", "Notiziario")
    sito = normalizza_sito_url(
        sito_url or configurazione.get("sito_url") or "https://jakephobia.github.io/notiziario/"
    )
    copertina_url = urljoin(sito, configurazione.get("copertina", "copertina.png"))
    ET.SubElement(canale, "link").text = sito
    ET.SubElement(canale, "description").text = configurazione.get(
        "descrizione", "Le notizie del giorno lette in italiano."
    )
    ET.SubElement(canale, "language").text = configurazione.get("lingua", "it-it")
    ET.SubElement(canale, "lastBuildDate").text = format_datetime(
        datetime.now(timezone.utc)
    )
    _testo(canale, NS_ITUNES, "author", configurazione.get("autore", "Notiziario"))
    _testo(canale, NS_ITUNES, "explicit", "false")
    _testo(canale, NS_ITUNES, "summary", configurazione.get("descrizione", ""))
    immagine = ET.SubElement(canale, "image")
    ET.SubElement(immagine, "url").text = copertina_url
    ET.SubElement(immagine, "title").text = configurazione.get("titolo", "Notiziario")
    ET.SubElement(immagine, "link").text = sito
    ET.SubElement(canale, f"{{{NS_ITUNES}}}image", {"href": copertina_url})

    ultimo = episodi[0] if episodi else {}
    categorie = ultimo.get("categorie") or []
    _testo(
        canale,
        NS_NOTIZIARIO,
        "categorie",
        ", ".join(label_categoria(c) for c in categorie)
        if categorie
        else "non disponibili",
    )
    _testo(canale, NS_NOTIZIARIO, "modalita", ultimo.get("modalita", "fallback"))
    _testo(canale, NS_NOTIZIARIO, "voce", ultimo.get("voce", ""))
    _testo(canale, NS_NOTIZIARIO, "voce_label", ultimo.get("voce_label", ""))
    _testo(canale, NS_NOTIZIARIO, "velocita", ultimo.get("velocita", 1.1))
    _testo(
        canale, NS_NOTIZIARIO, "tts_motore", ultimo.get("tts_motore", "")
    )

    for episodio in episodi:
        item = ET.SubElement(canale, "item")
        ET.SubElement(item, "title").text = normalizza_mesi(
            str(episodio.get("titolo", "Notiziario"))
        )
        descrizione = str(episodio.get("descrizione_breve") or episodio.get("descrizione", ""))
        ET.SubElement(item, "description").text = descrizione
        ET.SubElement(item, "pubDate").text = format_datetime(
            _data_pubblicazione(episodio)
        )
        ET.SubElement(
            item,
            "guid",
            {"isPermaLink": "false"},
        ).text = f"notiziario-{episodio.get('data', '')}"
        url = costruisci_url_audio(
            base, str(episodio.get("data", "")), str(episodio.get("filename", ""))
        )
        ET.SubElement(
            item,
            "enclosure",
            {
                "url": url,
                "length": str(int(episodio.get("dimensione") or 0)),
                "type": "audio/mpeg",
            },
        )
        _testo(
            item,
            NS_ITUNES,
            "duration",
            formatta_durata(episodio.get("durata_secondi")),
        )
        _testo(item, NS_ITUNES, "summary", descrizione)
        _testo(item, NS_ITUNES, "explicit", "false")
        ET.SubElement(item, f"{{{NS_ITUNES}}}image", {"href": copertina_url})
        _testo(item, NS_NOTIZIARIO, "modalita", episodio.get("modalita", "fallback"))
        _testo(item, NS_NOTIZIARIO, "voce", episodio.get("voce", ""))
        _testo(item, NS_NOTIZIARIO, "voce_label", episodio.get("voce_label", ""))
        _testo(item, NS_NOTIZIARIO, "velocita", episodio.get("velocita", 1.1))
        _testo(
            item, NS_NOTIZIARIO, "tts_motore", episodio.get("tts_motore", "")
        )

    albero = ET.ElementTree(rss)
    ET.indent(albero, space="  ")
    albero.write(path, encoding="utf-8", xml_declaration=True)
    return len(episodi)


def fonti_pubbliche(fonti: list[Fonte]) -> list[dict[str, Any]]:
    """Serializza le fonti per il form pubblico, senza campi interni."""
    return [
        {
            "nome": fonte.nome,
            "url": fonte.url,
            "categoria": fonte.categoria,
            "attivo": bool(fonte.attivo),
        }
        for fonte in fonti
    ]


def scrivi_impostazioni_pubbliche(
    percorso: str | Path,
    *,
    categorie_attive: list[str],
    incipit_template: str,
    incipit_risolto: str,
    voce: str,
    voce_label: str,
    velocita: float,
    motore: str,
    motore_richiesto: str = "",
    motore_configurato: str = "",
    data: str,
    nome_utente: str = "",
    suono: str = "ding",
    outro: str = "",
    fonti_totali: int = 0,
    fonti_attive: int = 0,
    issue_url: str | None = None,
    repo_url: str | None = None,
    voce_configurata: str = "",
    durata_default: str = "standard",
    orario_generazione: str = "07:00",
    fonti: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    path = Path(percorso)
    path.parent.mkdir(parents=True, exist_ok=True)
    dati = {
        "categorie_attive": list(categorie_attive),
        "categorie_label": [label_categoria(c) for c in categorie_attive],
        "incipit_template": incipit_template,
        "incipit_risolto": incipit_risolto,
        "voce": voce,
        "voce_label": voce_label,
        "voce_configurata": voce_configurata,
        "durata_default": durata_default,
        "orario_generazione": orario_generazione,
        "velocita": float(velocita),
        "motore": motore,
        "motore_richiesto": motore_richiesto or motore_configurato or "",
        "data": data,
        "nome_utente": nome_utente,
        "suono": suono,
        "outro": outro,
        "fonti_totali": int(fonti_totali),
        "fonti_attive": int(fonti_attive),
        "issue_url": issue_url,
        "repo_url": repo_url,
        "fonti": list(fonti or []),
    }
    path.write_text(
        json.dumps(dati, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return dati

def scrivi_index(percorso: str | Path, impostazioni: dict[str, Any]) -> None:
    """Scrive una pagina statica che legge feed.xml e mostra il player."""
    path = Path(percorso)
    path.parent.mkdir(parents=True, exist_ok=True)
    configurazione = impostazioni["feed"]
    titolo = _escape_html(configurazione.get("titolo", "Notiziario"))
    descrizione = _escape_html(
        configurazione.get("descrizione", "Le notizie del giorno lette in italiano.")
    )
    html = _TEMPLATE_INDEX.replace("%%TITOLO%%", titolo).replace(
        "%%DESCRIZIONE%%", descrizione
    )
    path.write_text(html, encoding="utf-8", newline="\n")


def scrivi_anteprime_fonti(percorso: str | Path, dati: dict[str, Any]) -> None:
    """Scrive il JSON delle anteprime fonti, leggibile e con newline finale."""
    path = Path(percorso)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dati, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _escape_html(testo: Any) -> str:
    return (
        str(testo)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_TEMPLATE_INDEX = r"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>%%TITOLO%%</title>
  <style>
    :root {
      color-scheme: light dark;
      --sfondo: #f4efe7; --testo: #1e2a24; --tenue: #5d665f;
      --card: #fffdf8; --bordo: #d8d1c4; --accento: #176b4d;
      --accento-soft: #e2efe8; --errore: #a12828;
      --ombra: 0 12px 40px rgba(31, 45, 38, .10);
    }
    @media (prefers-color-scheme: dark) {
      :root { --sfondo:#111814; --testo:#eef2ed; --tenue:#a8b4aa; --card:#18221c; --bordo:#34433a; --accento:#74d3a5; --accento-soft:#20372b; --errore:#ff9b9b; --ombra:0 12px 40px rgba(0,0,0,.35); }
    }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--sfondo); color:var(--testo); font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; line-height:1.55; }
    main { width:min(100% - 28px,980px); margin:0 auto; padding:28px 0 48px; }
    header { text-align:center; margin-bottom:24px; }
    .copertina { width:148px; height:148px; border-radius:18px; display:block; margin:0 auto 16px; border:1px solid var(--bordo); }
    h1 { font-size:clamp(2rem,7vw,2.8rem); letter-spacing:-.03em; margin:0 0 6px; }
    .sottotitolo { color:var(--tenue); margin:0; }
    h2 { margin:0 0 14px; font-size:1.35rem; }
    .player-card,.playlist-card,.impostazioni,.stato { background:var(--card); border:1px solid var(--bordo); border-radius:20px; box-shadow:var(--ombra); }
    .player-layout { display:grid; gap:18px; margin-bottom:18px; }
    .player-card,.playlist-card { padding:16px; }
    .playlist-card { display:flex; flex-direction:column; min-height:0; }
    @media (min-width:760px) { .player-layout { grid-template-columns:minmax(0,.95fr) minmax(0,1.05fr); align-items:start; } }
    .playlist-intestazione { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:10px; }
    .playlist-intestazione h2 { margin:0; font-size:1.2rem; }
    .badge-conteggio { display:inline-flex; align-items:center; justify-content:center; min-width:2.1em; padding:2px 9px; border-radius:999px; background:var(--accento-soft); color:var(--accento); font-size:.84rem; font-weight:700; }
    .in-riproduzione { margin:0 0 10px; color:var(--tenue); }
    audio { width:100%; }
    .playlist { list-style:none; padding:0 4px 0 0; margin:0; display:grid; gap:10px; overflow-y:auto; max-height:min(52vh,380px); overscroll-behavior:contain; }
    .playlist > li { background:var(--sfondo); border:1px solid var(--bordo); border-radius:12px; padding:10px 12px; }
    .episodio-titolo { display:block; width:100%; text-align:left; background:transparent; color:var(--testo); border:0; padding:0; font-weight:700; font-size:.98rem; line-height:1.35; }
    .episodio-titolo:hover,.episodio-titolo:focus-visible { color:var(--accento); }
    .playlist .meta { font-size:.8rem; margin:3px 0 0; }
    .playlist .descrizione { font-size:.86rem; margin:5px 0 0; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; line-clamp:2; overflow:hidden; }
    .impostazioni { padding:18px; margin-bottom:18px; }
    .intestazione-impostazioni { display:flex; flex-wrap:wrap; justify-content:space-between; gap:12px; align-items:start; }
    .riepilogo { color:var(--tenue); margin:0 0 12px; }
    .bottone,button { font:inherit; border-radius:999px; border:1px solid var(--accento); background:var(--accento); color:#fff; padding:10px 16px; cursor:pointer; text-decoration:none; display:inline-block; }
    button.secondario,.bottone.secondario { background:transparent; color:var(--accento); }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .nota { color:var(--tenue); font-size:.9rem; margin:0 0 16px; }
    form { display:grid; gap:16px; }
    fieldset { border:1px solid var(--bordo); border-radius:14px; padding:14px; margin:0; }
    legend { padding:0 6px; font-weight:700; }
    .form-grid { display:grid; gap:12px; }
    @media (min-width:700px) { .form-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .form-grid .largo { grid-column:1/-1; } }
    label { display:grid; gap:6px; font-size:.92rem; font-weight:650; }
    input,select,textarea { width:100%; font:inherit; color:var(--testo); background:var(--sfondo); border:1px solid var(--bordo); border-radius:10px; padding:10px 12px; }
    textarea { min-height:92px; resize:vertical; }
    input[type="range"] { padding:0; }
    .valore-range { font-weight:500; color:var(--tenue); }
    .categorie-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:8px; }
    .categoria { display:flex; align-items:center; gap:8px; font-weight:500; }
    .categoria input { width:auto; }
    .fonti-dettagli { border:1px solid var(--bordo); border-radius:14px; padding:10px 14px; margin-bottom:12px; }
    .fonti-dettagli > summary { cursor:pointer; font-weight:700; }
    .fonti-dettagli > summary:focus-visible { outline:2px solid var(--accento); outline-offset:2px; border-radius:6px; }
    .fonti-dettagli[open] > summary { margin-bottom:10px; }
    .fonti-lista { display:grid; gap:10px; }
    .fonte { display:grid; gap:8px; padding:10px; border:1px solid var(--bordo); border-radius:12px; }
    .fonte input,.fonte select { min-width:0; }
    .fonte input[readonly] { color:var(--tenue); }
    .fonte .campo { display:grid; gap:4px; }
    .fonte .campo span { font-size:.74rem; color:var(--tenue); font-weight:600; }
    .fonte-anteprima { justify-self:start; padding:7px 12px; font-size:.84rem; background:transparent; color:var(--accento); border:1px solid var(--accento); }
    .fonte-anteprima:hover,.fonte-anteprima:focus-visible { background:var(--accento-soft); }
    @media (min-width:760px) { .fonte { grid-template-columns:46px minmax(100px,1fr) minmax(130px,.9fr) minmax(180px,1.4fr) auto; align-items:end; } }
    .aggiungi-fonte { display:grid; gap:8px; padding-top:10px; border-top:1px dashed var(--bordo); }
    @media (min-width:760px) { .aggiungi-fonte { grid-template-columns:1fr 1.2fr .8fr auto; align-items:end; } }
    .azioni { display:flex; flex-wrap:wrap; gap:10px; }
    .stato-salvataggio { min-height:1.5em; margin:0; color:var(--tenue); word-break:break-word; }
    .stato-salvataggio.errore { color:var(--errore); }
    .progress-banner { display:none; position:fixed; top:12px; left:50%; transform:translateX(-50%); width:min(100% - 24px,760px); z-index:100; background:var(--card); border:1px solid var(--accento); border-radius:15px; box-shadow:var(--ombra); padding:12px 14px; }
    .progress-banner[hidden] { display:none; }
    .progress-banner.visibile { display:block; }
    .banner-riga { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }
    .banner-testo { margin:0; color:var(--testo); }
    .banner-chiudi { flex:0 0 32px; width:32px; height:32px; padding:0; border:0; background:transparent; color:var(--tenue); font-size:1.3rem; line-height:1; }
    .banner-azioni { display:flex; flex-wrap:wrap; gap:8px; margin-top:9px; font-size:.88rem; }
    .banner-azioni a,.banner-azioni button { font-size:.84rem; padding:6px 10px; }
    .token-box { display:grid; gap:10px; }
    .token-azioni { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
    .suoni { display:grid; gap:10px; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); }
    .suono { border:1px solid var(--bordo); border-radius:12px; padding:10px; }
    .suono.selezionato { border-color:var(--accento); background:var(--accento-soft); }
    .suono-nome { font-weight:700; margin-bottom:6px; }
    .suono audio { height:32px; }
    .link-repo,.fallback { margin:14px 0 0; color:var(--tenue); font-size:.9rem; }
    .stato { display:flex; flex-wrap:wrap; gap:12px 24px; padding:14px 16px; color:var(--tenue); }
    .avviso { color:var(--errore); background:var(--card); border:1px solid var(--bordo); border-radius:12px; padding:12px 14px; }
    .playlist-card .avviso { margin-bottom:10px; }
    .anteprima-fonte { width:min(100% - 24px,640px); max-height:min(86vh,720px); padding:0; border:1px solid var(--bordo); border-radius:20px; background:var(--card); color:var(--testo); box-shadow:var(--ombra); }
    .anteprima-fonte::backdrop { background:rgba(10,18,14,.6); }
    .anteprima-fonte-contenuto { display:grid; gap:12px; padding:18px; max-height:inherit; overflow:auto; }
    .anteprima-intestazione { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
    .anteprima-intestazione h2 { margin:0; font-size:1.2rem; }
    .anteprima-chiudi { flex:0 0 32px; width:32px; height:32px; padding:0; border:0; background:transparent; color:var(--tenue); font-size:1.3rem; line-height:1; }
    .anteprima-chiudi:hover,.anteprima-chiudi:focus-visible { color:var(--testo); }
    .anteprima-url { margin:0; font-size:.86rem; word-break:break-word; }
    .anteprima-stato { margin:0; font-size:.84rem; font-weight:700; }
    .anteprima-stato.attiva { color:var(--accento); }
    .anteprima-stato.inattiva { color:var(--errore); }
    .anteprima-articoli { list-style:none; margin:0; padding:0; display:grid; gap:10px; }
    .anteprima-articoli li { border-top:1px solid var(--bordo); padding-top:10px; }
    .anteprima-articoli li:first-child { border-top:0; padding-top:0; }
    .anteprima-articolo-titolo { font-weight:700; text-decoration:none; }
    .anteprima-articolo-titolo:hover,.anteprima-articolo-titolo:focus-visible { text-decoration:underline; }
    .anteprima-articolo-sommario { margin:4px 0 0; color:var(--tenue); font-size:.88rem; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; line-clamp:2; overflow:hidden; }
    .anteprima-articolo-data { margin:4px 0 0; color:var(--tenue); font-size:.8rem; }
    .anteprima-messaggio { margin:0; color:var(--tenue); }
    .anteprima-azioni { display:flex; justify-content:flex-end; margin-top:2px; }
    .anteprima-fonte.anteprima-fonte-fallback { position:fixed; top:50%; left:50%; transform:translate(-50%,-50%); margin:0; z-index:300; }
    @media (max-width:480px) { .anteprima-fonte-contenuto { padding:14px; } }
    footer { color:var(--tenue); font-size:.82rem; margin-top:36px; border-top:1px solid var(--bordo); padding-top:16px; }
    a { color:var(--accento); }
    .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
  </style>
</head>
<body>
<aside id="banner-generazione" class="progress-banner" role="status" aria-live="polite" aria-atomic="true" hidden>
  <div class="banner-riga">
    <p class="banner-testo" id="banner-testo"></p>
    <button id="banner-chiudi" class="banner-chiudi" type="button" aria-label="Chiudi stato generazione">×</button>
  </div>
  <div class="banner-azioni" id="banner-azioni"></div>
</aside>
<main>
  <header>
    <img class="copertina" src="copertina.png" alt="Copertina del podcast">
    <h1>%%TITOLO%%</h1>
    <p class="sottotitolo">%%DESCRIZIONE%%</p>
  </header>

  <section class="player-layout" aria-label="Player e playlist">
    <div class="player-card">
      <p class="in-riproduzione" id="in-riproduzione">Scegli un episodio dalla playlist.</p>
      <audio id="player" controls preload="metadata"></audio>
    </div>
    <div class="playlist-card" aria-labelledby="titolo-playlist">
      <div class="playlist-intestazione">
        <h2 id="titolo-playlist">Playlist</h2>
        <span class="badge-conteggio" id="conteggio" aria-live="polite">caricamento...</span>
      </div>
      <div id="messaggio" class="avviso" hidden></div>
      <ul id="episodi" class="playlist" aria-label="Episodi disponibili"></ul>
    </div>
  </section>

  <section class="impostazioni" aria-labelledby="titolo-impostazioni">
    <div class="intestazione-impostazioni">
      <div><h2 id="titolo-impostazioni">Impostazioni</h2><p id="nome-fonti" class="riepilogo">...</p></div>
      <a id="modifica-impostazioni" class="bottone secondario" href="https://github.com/jakephobia/notiziario/issues/1" target="_blank" rel="noopener noreferrer">Modalità avanzata: issue #1</a>
    </div>
    <p class="nota">Le modifiche si salvano dalla dashboard GitHub e vengono applicate al run successivo.</p>

    <form id="form-impostazioni" novalidate>
      <div class="form-grid">
        <label>Nome <input id="nome" name="nome" type="text" maxlength="80" autocomplete="name" required></label>
        <label>Durata
          <select id="durata" name="durata">
            <option value="svelto">Svelto</option><option value="standard">Standard</option><option value="completo">Completo</option>
          </select>
        </label>
        <label>Notizie fino alle (opzionale)
          <input id="taglio" name="taglio" type="time">
        </label>
        <label>Orario di generazione (Europe/Rome)
          <select id="orario" name="orario"><option value="00:00">00:00</option><option value="01:00">01:00</option><option value="02:00">02:00</option><option value="03:00">03:00</option><option value="04:00">04:00</option><option value="05:00">05:00</option><option value="06:00">06:00</option><option value="07:00">07:00</option><option value="08:00">08:00</option><option value="09:00">09:00</option><option value="10:00">10:00</option><option value="11:00">11:00</option><option value="12:00">12:00</option><option value="13:00">13:00</option><option value="14:00">14:00</option><option value="15:00">15:00</option><option value="16:00">16:00</option><option value="17:00">17:00</option><option value="18:00">18:00</option><option value="19:00">19:00</option><option value="20:00">20:00</option><option value="21:00">21:00</option><option value="22:00">22:00</option><option value="23:00">23:00</option></select>
        </label>
        <label class="largo">Incipit <textarea id="incipit" name="incipit" maxlength="500" required></textarea></label>
        <label class="largo">Outro <textarea id="outro" name="outro" maxlength="500"></textarea></label>
      </div>

      <fieldset>
        <legend>Voci e audio</legend>
        <div class="form-grid">
          <label>Voce
            <select id="voce" name="voce">
              <option value="Kore">Kore — femminile, calda</option>
              <option value="Leda">Leda — femminile, luminosa</option>
              <option value="Charon">Charon — maschile, profonda</option>
              <option value="Puck">Puck — maschile, vivace</option>
            </select>
          </label>
          <label>Motore TTS
            <select id="tts-motore" name="motore"><option value="gemini">Gemini TTS</option><option value="edge">edge-tts</option><option value="google">Google Chirp 3 HD</option></select>
          </label>
          <label class="largo">Velocità <span class="valore-range" id="velocita-valore">1.10×</span>
            <input id="velocita" name="velocita" type="range" min="0.75" max="1.25" step="0.05" value="1.1">
          </label>
          <label>Suono di transizione
            <select id="suono" name="suono"><option value="ding">Ding</option><option value="chime">Chime</option><option value="whoosh">Whoosh</option><option value="nessuno">Nessuno</option></select>
          </label>
          <p class="nota" id="tts-motore-nota"></p>
        </div>
        <div class="suoni" id="suoni" aria-label="Anteprime dei suoni">
          <div class="suono" data-suono="ding"><div class="suono-nome">Ding</div><audio controls preload="none" src="suoni/ding.mp3"></audio></div>
          <div class="suono" data-suono="chime"><div class="suono-nome">Chime</div><audio controls preload="none" src="suoni/chime.mp3"></audio></div>
          <div class="suono" data-suono="whoosh"><div class="suono-nome">Whoosh</div><audio controls preload="none" src="suoni/whoosh.mp3"></audio></div>
        </div>
      </fieldset>

      <fieldset><legend>Categorie</legend><div id="categorie" class="categorie-grid"></div></fieldset>

      <fieldset>
        <legend>Fonti RSS</legend>
        <details id="fonti-dettagli" class="fonti-dettagli">
          <summary id="fonti-riepilogo">Elenco fonti (0)</summary>
          <div id="fonti-lista" class="fonti-lista"></div>
        </details>
        <div class="aggiungi-fonte">
          <label>Nuova fonte <input id="nuova-fonte-nome" type="text" maxlength="120" placeholder="Nome testata"></label>
          <label>URL feed <input id="nuova-fonte-url" type="url" placeholder="https://esempio.it/feed.xml"></label>
          <label>Categoria <select id="nuova-fonte-categoria"></select></label>
          <button id="aggiungi-fonte" type="button" class="secondario">Aggiungi fonte</button>
        </div>
        <p class="nota">Le nuove fonti vengono aggiunte spente e con categoria da assegnare, se non la scegli. L'import non verifica i feed in rete.</p>
        <label>Importa feed OPML, TXT, CSV o JSON
          <input id="importa-feed" type="file" accept=".opml,.xml,.txt,.csv,.json,text/plain,text/xml,application/json">
        </label>
      </fieldset>

      <fieldset>
        <legend>Accesso GitHub</legend>
        <div class="token-box">
          <p class="nota">Serve un token fine-grained limitato al repository <strong>jakephobia/notiziario</strong>, con permesso <strong>Actions: read and write</strong>. Non inserirlo nell'URL e non condividerlo.</p>
          <label>Token GitHub <input id="token" type="password" autocomplete="off" spellcheck="false" placeholder="github_pat_..."></label>
          <div class="token-azioni">
            <button id="salva-token" type="button" class="secondario">Salva token nel browser</button>
            <button id="dimentica-token" type="button" class="secondario">Dimentica token</button>
            <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener noreferrer">Crea un token fine-grained</a>
          </div>
          <p class="nota" id="token-stato" role="status" aria-live="polite"></p>
        </div>
      </fieldset>

      <div class="azioni">
        <button id="salva-impostazioni" type="button">Salva impostazioni</button>
        <button id="salva-genera" type="button">Salva e genera ora</button>
      </div>
      <p id="stato-salvataggio" class="stato-salvataggio" role="status" aria-live="polite"></p>
    </form>
    <p class="link-repo"><a id="repo-link" href="https://github.com/jakephobia/notiziario" target="_blank" rel="noopener noreferrer">Repository del progetto</a></p>
  </section>

  <section class="stato" aria-label="Stato del notiziario">
    <div>Modalità AI: <strong id="modalita">caricamento...</strong></div>
    <div>Ultimo aggiornamento: <strong id="data-aggiornamento">caricamento...</strong></div>
  </section>

  <dialog id="anteprima-fonte" class="anteprima-fonte" aria-labelledby="anteprima-titolo">
    <div class="anteprima-fonte-contenuto">
      <div class="anteprima-intestazione">
        <h2 id="anteprima-titolo">Anteprima fonte</h2>
        <button id="anteprima-chiudi" type="button" class="anteprima-chiudi" aria-label="Chiudi anteprima">×</button>
      </div>
      <p id="anteprima-url" class="anteprima-url"></p>
      <p id="anteprima-stato" class="anteprima-stato" hidden></p>
      <ul id="anteprima-articoli" class="anteprima-articoli"></ul>
      <p id="anteprima-messaggio" class="anteprima-messaggio" role="status" aria-live="polite" hidden></p>
      <div class="anteprima-azioni">
        <button id="anteprima-chiudi-basso" type="button" class="secondario">Chiudi</button>
      </div>
    </div>
  </dialog>

  <footer>Notiziario personale. Le notizie appartengono alle testate citate nel copione. Il player legge il feed RSS statico di questa pagina.</footer>
</main>

<script>
(function () {
  "use strict";
  const NS_NOTIZIARIO = "https://notiziario.local/ns/1.0";
  const NS_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd";
  const TOKEN_KEY = "notiziario.dashboard.token";
  const WORKFLOW_DISPATCH = "https://api.github.com/repos/jakephobia/notiziario/actions/workflows/dashboard.yml/dispatches";
  const WORKFLOW_PAGE = "https://github.com/jakephobia/notiziario/actions/workflows/dashboard.yml";
  const RUNS_API = "https://api.github.com/repos/jakephobia/notiziario/actions/workflows/notiziario.yml/runs?per_page=10";
  const DASHBOARD_RUNS_API = "https://api.github.com/repos/jakephobia/notiziario/actions/workflows/dashboard.yml/runs?per_page=10";
  const NOTIZIARIO_PAGE = "https://github.com/jakephobia/notiziario/actions/workflows/notiziario.yml";
  const PLAYER_URL = "https://jakephobia.github.io/notiziario/";
  const FEED_URL = "https://jakephobia.github.io/notiziario/feed.xml";
  const POLL_INTERVAL_MS = 15000;
  const POLL_TIMEOUT_MS = 20 * 60 * 1000;
  const DASHBOARD_POLL_TIMEOUT_MS = 8 * 60 * 1000;
  const STARTUP_GRACE_MS = 3 * 60 * 1000;
  const ISSUE_URL = "https://github.com/jakephobia/notiziario/issues/1";
  const CATEGORIE = [
    {id:"italia",label:"Italia"},{id:"mondo",label:"Mondo"},{id:"economia",label:"Economia"},
    {id:"tecnologia",label:"Tecnologia"},{id:"scienza-salute",label:"Scienza e salute"},
    {id:"cultura",label:"Cultura"},{id:"sport",label:"Sport"},{id:"ambiente",label:"Ambiente"},
    {id:"buone-notizie",label:"Buone notizie"},{id:"cronaca",label:"Cronaca"},
    {id:"cronaca-nera",label:"Cronaca nera"},{id:"approfondimento",label:"Approfondimento"},
    {id:"promozione",label:"Promozione/PR"}
  ];
  const CAT_IDS = new Set(CATEGORIE.map(function (c) { return c.id; }));
  const player = document.getElementById("player");
  const inRiproduzione = document.getElementById("in-riproduzione");
  const lista = document.getElementById("episodi");
  const messaggio = document.getElementById("messaggio");
  const categorieEl = document.getElementById("categorie");
  const modalitaEl = document.getElementById("modalita");
  const conteggioEl = document.getElementById("conteggio");
  const dataAggiornamentoEl = document.getElementById("data-aggiornamento");
  const nomeFontiEl = document.getElementById("nome-fonti");
  const modificaLink = document.getElementById("modifica-impostazioni");
  const repoLink = document.getElementById("repo-link");
  const form = document.getElementById("form-impostazioni");
  const nomeEl = document.getElementById("nome");
  const incipitEl = document.getElementById("incipit");
  const outroEl = document.getElementById("outro");
  const voceEl = document.getElementById("voce");
  const velocitaEl = document.getElementById("velocita");
  const velocitaValoreEl = document.getElementById("velocita-valore");
  const motoreEl = document.getElementById("tts-motore");
  const motoreNotaEl = document.getElementById("tts-motore-nota");
  const suonoEl = document.getElementById("suono");
  const durataEl = document.getElementById("durata");
const taglioEl = document.getElementById("taglio");
  const orarioEl = document.getElementById("orario");
  const fontiLista = document.getElementById("fonti-lista");
  const fontiDettagli = document.getElementById("fonti-dettagli");
  const fontiRiepilogo = document.getElementById("fonti-riepilogo");
  const anteprimaDialog = document.getElementById("anteprima-fonte");
  const anteprimaTitolo = document.getElementById("anteprima-titolo");
  const anteprimaUrl = document.getElementById("anteprima-url");
  const anteprimaStato = document.getElementById("anteprima-stato");
  const anteprimaArticoli = document.getElementById("anteprima-articoli");
  const anteprimaMessaggio = document.getElementById("anteprima-messaggio");
  const anteprimaChiudiBtn = document.getElementById("anteprima-chiudi");
  const anteprimaChiudiBassoBtn = document.getElementById("anteprima-chiudi-basso");
  const nuovaNomeEl = document.getElementById("nuova-fonte-nome");
  const nuovaUrlEl = document.getElementById("nuova-fonte-url");
  const nuovaCategoriaEl = document.getElementById("nuova-fonte-categoria");
  const aggiungiFonteBtn = document.getElementById("aggiungi-fonte");
  const importaInput = document.getElementById("importa-feed");
  const tokenEl = document.getElementById("token");
  const tokenStatoEl = document.getElementById("token-stato");
  const salvaTokenBtn = document.getElementById("salva-token");
  const dimenticaTokenBtn = document.getElementById("dimentica-token");
  const salvaBtn = document.getElementById("salva-impostazioni");
  const salvaGeneraBtn = document.getElementById("salva-genera");
  const statoSalvataggioEl = document.getElementById("stato-salvataggio");
  const bannerGenerazione = document.getElementById("banner-generazione");
  const bannerTestoEl = document.getElementById("banner-testo");
  const bannerAzioniEl = document.getElementById("banner-azioni");
  const bannerChiudiBtn = document.getElementById("banner-chiudi");
  let pollingTimer = null;
  let pollingTimeout = null;
  let pollingStart = 0;
  let clickedAt = 0;
  let pollingAttivo = false;
  let anteprimaTrigger = null;
  let anteprimaRichiesta = 0;

  function testoDi(el) { return el && el.textContent ? el.textContent.trim() : ""; }
  function primoNS(radice, ns, nome) { const t = radice.getElementsByTagNameNS(ns, nome); return t.length ? t[0] : null; }
  function crea(tag, classe, testo) { const e = document.createElement(tag); if (classe) e.className = classe; if (testo !== undefined) e.textContent = testo; return e; }
  function formattaData(grezza) { const d = new Date(grezza); if (isNaN(d.getTime())) return grezza || ""; return d.toLocaleDateString("it-IT",{weekday:"long",day:"numeric",month:"long",year:"numeric"}); }
  function mostraStato(testo, errore) { statoSalvataggioEl.textContent = testo || ""; statoSalvataggioEl.classList.toggle("errore", Boolean(errore)); }
  function mostraErrore(testo) { messaggio.textContent = testo; messaggio.hidden = false; }
  function normalizzaTesto(t) { return String(t||"").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/[^a-z0-9]+/g," ").trim(); }
  function categoriaDaTesto(t) {
    const c = normalizzaTesto(t);
    if (!c) return "";
    if (c === "da assegnare" || c === "daassegnare") return "da-assegnare";
    for (const cat of CATEGORIE) if (normalizzaTesto(cat.id) === c || normalizzaTesto(cat.label) === c) return cat.id;
    return "";
  }
  function categoriaDaUrl(url) {
    let path = ""; try { path = new URL(url).pathname.toLowerCase(); } catch (e) { return ""; }
    const s = new Set(path.split("/").filter(Boolean));
    const mappa = [
      ["sport",["sport","calcio","motori","formula-1","motogp","tennis","basket"]],
      ["economia",["economia","finanza","mercati","borsa","business"]],
      ["tecnologia",["tecnologia","tech","digitale","innovazione"]],
      ["cultura",["cultura","spettacoli","cinema","musica","libri","arte"]],
      ["scienza-salute",["scienza","scienze","salute","medicina","sanita"]],
      ["ambiente",["ambiente","green","clima","ecologia"]],
      ["mondo",["esteri","mondo","internazionale"]],["italia",["politica","cronaca","italia"]]
    ];
    for (const voce of mappa) if (voce[1].some(function (m) { return s.has(m); })) return voce[0];
    return "";
  }
  function normalizzaUrl(valore) {
    try { const u = new URL(String(valore||"").trim()); if (u.protocol !== "http:" && u.protocol !== "https:") return ""; return (u.origin + u.pathname.replace(/\/+$/,"") + u.search).toLowerCase(); } catch (e) { return ""; }
  }
  function aggiornaConteggioFonti() {
    const totale = fontiLista ? fontiLista.querySelectorAll(".fonte").length : 0;
    if (fontiRiepilogo) fontiRiepilogo.textContent = "Elenco fonti (" + totale + ")";
  }
  function urlSicuro(href) {
    try {
      const url = new URL(String(href || ""));
      if (url.protocol === "https:" || url.protocol === "http:") return url.href;
    } catch (e) {}
    return "";
  }
  function linkArticolo(testo, href, classe) {
    const valore = urlSicuro(href);
    if (!valore) return crea("span", classe, testo);
    const link = crea("a", classe, testo);
    link.href = valore;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
  }
  function cercaAnteprima(fonti, url) {
    if (!fonti || typeof fonti !== "object") return null;
    if (Object.prototype.hasOwnProperty.call(fonti, url)) return fonti[url];
    const cercato = normalizzaUrl(url);
    if (!cercato) return null;
    const chiavi = Object.keys(fonti);
    for (let i = 0; i < chiavi.length; i += 1) {
      const gruppo = fonti[chiavi[i]];
      if (normalizzaUrl(chiavi[i]) === cercato) return gruppo;
      if (gruppo && typeof gruppo === "object" && normalizzaUrl(gruppo.url) === cercato) return gruppo;
    }
    return null;
  }
  function messaggioAnteprima(testo) {
    anteprimaMessaggio.textContent = testo || "";
    anteprimaMessaggio.hidden = !testo;
  }
  function apriDialogAnteprima(trigger) {
    anteprimaTrigger = trigger || null;
    if (typeof anteprimaDialog.showModal === "function") {
      try {
        if (!anteprimaDialog.open) anteprimaDialog.showModal();
        return;
      } catch (e) {}
    }
    anteprimaDialog.setAttribute("open", "");
    anteprimaDialog.classList.add("anteprima-fonte-fallback");
  }
  function chiudiDialogAnteprima() {
    anteprimaRichiesta += 1;
    if (typeof anteprimaDialog.close === "function") {
      if (anteprimaDialog.open) anteprimaDialog.close();
    } else {
      anteprimaDialog.removeAttribute("open");
      anteprimaDialog.classList.remove("anteprima-fonte-fallback");
    }
    if (anteprimaTrigger && typeof anteprimaTrigger.focus === "function") {
      try { anteprimaTrigger.focus(); } catch (e) {}
    }
  }
  function apriAnteprimaFonte(url, nome, trigger) {
    const richiesta = ++anteprimaRichiesta;
    anteprimaTitolo.textContent = nome || "Anteprima fonte";
    anteprimaUrl.replaceChildren();
    const linkFeed = crea("a", "anteprima-url-link", String(url || ""));
    const hrefFeed = urlSicuro(url);
    if (hrefFeed) { linkFeed.href = hrefFeed; linkFeed.target = "_blank"; linkFeed.rel = "noopener noreferrer"; }
    anteprimaUrl.appendChild(linkFeed);
    anteprimaStato.hidden = true;
    anteprimaStato.textContent = "";
    anteprimaStato.className = "anteprima-stato";
    anteprimaArticoli.replaceChildren();
    messaggioAnteprima("Caricamento anteprima…");
    apriDialogAnteprima(trigger);
    (async function () {
      let dati = null;
      try {
        const risposta = await fetch("anteprime-fonti.json?t=" + Date.now(), { cache: "no-store" });
        if (risposta.ok) dati = await risposta.json();
      } catch (e) { dati = null; }
      if (richiesta !== anteprimaRichiesta) return;
      if (!dati || typeof dati !== "object" || !dati.fonti || typeof dati.fonti !== "object") {
        messaggioAnteprima("Anteprima non disponibile: verrà aggiornata alla prossima generazione.");
        return;
      }
      const gruppo = cercaAnteprima(dati.fonti, url);
      if (!gruppo || typeof gruppo !== "object") {
        messaggioAnteprima("Anteprima non disponibile: verrà aggiornata alla prossima generazione.");
        return;
      }
      if (gruppo.nome) anteprimaTitolo.textContent = String(gruppo.nome);
      const hrefGruppo = urlSicuro(gruppo.url || url);
      anteprimaUrl.replaceChildren();
      if (hrefGruppo) {
        anteprimaUrl.appendChild(linkArticolo(String(gruppo.url || url), hrefGruppo, "anteprima-url-link"));
      } else {
        anteprimaUrl.textContent = String(gruppo.url || url || "");
      }
      if (gruppo.attivo === false) {
        anteprimaStato.textContent = "Fonte inattiva";
        anteprimaStato.className = "anteprima-stato inattiva";
      } else {
        anteprimaStato.textContent = "Fonte attiva";
        anteprimaStato.className = "anteprima-stato attiva";
      }
      anteprimaStato.hidden = false;
      const articoli = (Array.isArray(gruppo.articoli) ? gruppo.articoli : []).slice(0, 5);
      if (!articoli.length) {
        messaggioAnteprima("Nessun articolo recente disponibile.");
        return;
      }
      messaggioAnteprima("");
      articoli.forEach(function (articolo) {
        if (!articolo || typeof articolo !== "object" || !articolo.titolo) return;
        const voce = document.createElement("li");
        voce.appendChild(linkArticolo(String(articolo.titolo), articolo.link, "anteprima-articolo-titolo"));
        if (articolo.sommario) voce.appendChild(crea("p", "anteprima-articolo-sommario", String(articolo.sommario)));
        if (articolo.pubblicato) voce.appendChild(crea("p", "anteprima-articolo-data", formattaData(articolo.pubblicato)));
        anteprimaArticoli.appendChild(voce);
      });
      if (!anteprimaArticoli.children.length) messaggioAnteprima("Nessun articolo recente disponibile.");
    })();
  }
  function opzioniCategoria(selezionata) {
    const select = crea("select","fonte-categoria"); select.setAttribute("aria-label","Categoria della fonte");
    const vuota = crea("option","","Da assegnare"); vuota.value = "da-assegnare"; select.appendChild(vuota);
    for (const cat of CATEGORIE) { const o = crea("option","",cat.label); o.value = cat.id; select.appendChild(o); }
    select.value = CAT_IDS.has(selezionata) ? selezionata : "da-assegnare"; return select;
  }
  function creaFonte(fonte, nuova) {
    const riga = crea("div","fonte");
    const attiva = crea("label","fonte-attiva");
    const check = document.createElement("input"); check.type="checkbox"; check.className="fonte-attivo"; check.checked=Boolean(fonte.attivo); check.setAttribute("aria-label","Fonte attiva");
    attiva.appendChild(check); attiva.appendChild(crea("span","sr-only","Attiva"));
    function campo(etichetta,input) { const l=crea("label","campo"); l.appendChild(crea("span","",etichetta)); l.appendChild(input); return l; }
    const nome=document.createElement("input"); nome.type="text"; nome.className="fonte-nome"; nome.maxLength=120; nome.value=fonte.nome||""; nome.setAttribute("aria-label","Nome della fonte");
    const categoria=opzioniCategoria(fonte.categoria);
    const url=document.createElement("input"); url.type="url"; url.className="fonte-url"; url.value=fonte.url||""; url.readOnly=!nuova; url.setAttribute("aria-label","URL del feed");
    riga.dataset.nuova=nuova?"1":"0"; riga.appendChild(attiva); riga.appendChild(campo("Nome",nome)); riga.appendChild(campo("Categoria",categoria)); riga.appendChild(campo("URL feed",url));
    const anteprima=crea("button","fonte-anteprima","Anteprima"); anteprima.type="button"; anteprima.setAttribute("aria-label","Anteprima della fonte "+(nome.value||"senza nome"));
    anteprima.addEventListener("click",function () { apriAnteprimaFonte(url.value.trim(),nome.value.trim(),anteprima); }); riga.appendChild(anteprima); return riga;
  }
  function fontiPresenti() { return new Set(Array.from(fontiLista.querySelectorAll(".fonte-url")).map(function (e) { return normalizzaUrl(e.value); }).filter(Boolean)); }
  function aggiungiFonte(fonte, nuova, silenzioso) {
    const url=normalizzaUrl(fonte.url);
    if (!url) { if (!silenzioso) mostraStato("Inserisci un URL http o https valido.",true); return false; }
    if (fontiPresenti().has(url)) { if (!silenzioso) mostraStato("Questa fonte è già presente.",true); return false; }
    if (fontiLista.querySelectorAll(".fonte").length >= 200) { if (!silenzioso) mostraStato("Hai raggiunto il limite di 200 fonti.",true); return false; }
    const categoria=CAT_IDS.has(fonte.categoria)?fonte.categoria:"da-assegnare";
    fontiLista.appendChild(creaFonte({nome:(fonte.nome||"").trim(),url:String(fonte.url||"").trim(),categoria:categoria,attivo:Boolean(fonte.attivo)},nuova)); aggiornaConteggioFonti(); return true;
  }
  function renderCategorie(attive) {
    const set=new Set(Array.isArray(attive)?attive:[]); categorieEl.replaceChildren();
    for (const cat of CATEGORIE) { const label=crea("label","categoria"); const input=document.createElement("input"); input.type="checkbox"; input.value=cat.id; input.checked=set.has(cat.id); label.appendChild(input); label.appendChild(crea("span","",cat.label)); categorieEl.appendChild(label); }
  }
  function renderFonti(fonti) {
    fontiLista.replaceChildren(); (Array.isArray(fonti)?fonti:[]).forEach(function (f) { if (f && typeof f==="object" && f.url) aggiungiFonte({nome:f.nome||"",url:f.url,categoria:f.categoria||"da-assegnare",attivo:Boolean(f.attivo)},false,true); });
    if (!fontiLista.querySelector(".fonte")) fontiLista.appendChild(crea("p","nota","Nessuna fonte caricata: aggiungine una o importa un file."));
    aggiornaConteggioFonti();
  }
  function aggiornaSuoni() { document.querySelectorAll(".suono").forEach(function (card) { card.classList.toggle("selezionato",card.getAttribute("data-suono")===suonoEl.value); }); }
  function popolaForm(dati) {
    const d=dati||{}; const attive=Array.isArray(d.categorie_attive)?d.categorie_attive:[];
    nomeEl.value=d.nome_utente||"Jacopo"; incipitEl.value=d.incipit_template||""; outroEl.value=d.outro||"";
    const voce=d.voce_configurata||d.voce||"Kore"; voceEl.value=Array.from(voceEl.options).some(function (o) { return o.value===voce; })?voce:"Kore";
    const v=Number(d.velocita); const valore=Number.isFinite(v)?Math.min(1.25,Math.max(.75,v)):1.1; velocitaEl.value=String(valore); velocitaValoreEl.textContent=Number(valore).toFixed(2)+"×";
    const motore=d.motore_richiesto||d.motore||"gemini"; motoreEl.value=["gemini","edge","google"].indexOf(motore)>=0?motore:"gemini";
    const suono=d.suono||"ding"; suonoEl.value=["ding","chime","whoosh","nessuno"].indexOf(suono)>=0?suono:"ding";
    const durata=d.durata_default||"standard"; durataEl.value=["svelto","standard","completo"].indexOf(durata)>=0?durata:"standard";
    const orario=d.orario_generazione||"07:00"; orarioEl.value=/^\d{2}:00$/.test(orario)?orario:"07:00";
    renderCategorie(attive); renderFonti(d.fonti); aggiornaSuoni();
    const eff=d.motore||"non disponibile"; const rich=d.motore_richiesto||""; motoreNotaEl.textContent="Ultimo episodio: "+eff+(rich && rich!==eff?" (richiesto "+rich+")":"")+".";
    const fontiAttive=Array.isArray(d.fonti)?d.fonti.filter(function (f) { return f.attivo; }).length:0;
    nomeFontiEl.textContent=(d.nome_utente||"Jacopo")+" · "+fontiAttive+" fonti attive";
    dataAggiornamentoEl.textContent=d.data?formattaData(d.data):"non disponibile";
    if (d.repo_url) repoLink.href=d.repo_url; modificaLink.href=d.issue_url||ISSUE_URL; modificaLink.textContent="Modalità avanzata: issue #1";
  }
  function creaEpisodio(item, indice) {
    const titolo=testoDi(item.querySelector("title"))||"Episodio "+(indice+1); const descrizione=testoDi(item.querySelector("description")); const pubDate=testoDi(item.querySelector("pubDate"));
    const enclosure=item.querySelector("enclosure"); const url=enclosure?enclosure.getAttribute("url"):""; const durata=testoDi(primoNS(item,NS_ITUNES,"duration"));
    const li=document.createElement("li"); const bottone=document.createElement("button"); bottone.type="button"; bottone.className="episodio-titolo"; bottone.textContent=titolo;
    bottone.addEventListener("click",function () { if (!url) { mostraErrore("Questo episodio non ha un file audio nel feed."); return; } player.src=url; inRiproduzione.textContent="In ascolto: "+titolo; player.play().catch(function () { mostraErrore("Premi play sul player per ascoltare l'episodio."); }); });
    li.appendChild(bottone); const meta=document.createElement("p"); meta.className="meta"; const pezzi=[]; if (pubDate) pezzi.push(formattaData(pubDate)); if (durata) pezzi.push(durata); meta.textContent=pezzi.join(" · "); if (pezzi.length) li.appendChild(meta);
    if (descrizione) { const desc=document.createElement("p"); desc.className="descrizione"; desc.textContent=descrizione; li.appendChild(desc); } return li;
  }
  async function caricaImpostazioni(canale, episodi) {
    const fallback={categorie_attive:[],voce:"",voce_configurata:"",velocita:1.1,motore:"",motore_richiesto:"",incipit_template:"",outro:"",suono:"ding",durata_default:"standard",orario_generazione:"07:00",data:episodi.length?testoDi(episodi[0].querySelector("pubDate")):"",nome_utente:"",fonti:[],issue_url:ISSUE_URL,repo_url:"https://github.com/jakephobia/notiziario"};
    if (canale) {
      const categorie=primoNS(canale,NS_NOTIZIARIO,"categorie"); const labels=(testoDi(categorie)||"").split(",").map(function (x) { return x.trim(); }).filter(Boolean);
      fallback.categorie_attive=labels.map(function (label) { const c=CATEGORIE.find(function (x) { return normalizzaTesto(x.label)===normalizzaTesto(label); }); return c?c.id:""; }).filter(Boolean);
      fallback.voce=testoDi(primoNS(canale,NS_NOTIZIARIO,"voce")); fallback.velocita=Number(testoDi(primoNS(canale,NS_NOTIZIARIO,"velocita")))||1.1; fallback.motore=testoDi(primoNS(canale,NS_NOTIZIARIO,"tts_motore")); fallback.outro=testoDi(primoNS(canale,NS_NOTIZIARIO,"outro"));
    }
    let dati=null; try { const r=await fetch("impostazioni.json?t="+Date.now(),{cache:"no-store"}); if (r.ok) dati=await r.json(); } catch (e) { dati=null; }
    popolaForm(dati && typeof dati==="object"?dati:fallback);
  }
  function leggiToken() { try { return localStorage.getItem(TOKEN_KEY)||""; } catch (e) { return ""; } }
  function aggiornaTokenStato() { tokenStatoEl.textContent=leggiToken()?"Token presente nel browser. Non viene mostrato né registrato nei log.":"Nessun token salvato: il form resta leggibile, ma il salvataggio richiede il token."; }
  function salvaToken() { const token=tokenEl.value.trim(); if (!token) { tokenStatoEl.textContent="Inserisci un token prima di salvarlo."; return; } try { localStorage.setItem(TOKEN_KEY,token); tokenEl.value=token; aggiornaTokenStato(); mostraStato("Token salvato nel browser."); } catch (e) { tokenStatoEl.textContent="Il browser non permette di salvare il token (modalità privata?)."; } }
  function dimenticaToken() { try { localStorage.removeItem(TOKEN_KEY); } catch (e) {} tokenEl.value=""; aggiornaTokenStato(); mostraStato("Token rimosso dal browser."); }
  function costruisciPayload() {
    const categorie=Array.from(categorieEl.querySelectorAll("input[type=checkbox]:checked")).map(function (e) { return e.value; });
    const fonti=Array.from(fontiLista.querySelectorAll(".fonte")).map(function (r) { return {nome:r.querySelector(".fonte-nome").value.trim(),url:r.querySelector(".fonte-url").value.trim(),categoria:r.querySelector(".fonte-categoria").value,attivo:r.querySelector(".fonte-attivo").checked}; });
    return {nome:nomeEl.value.trim(),categorie:categorie,incipit:incipitEl.value.trim(),outro:outroEl.value.trim(),voce:voceEl.value,velocita:Number(velocitaEl.value),motore:motoreEl.value,suono:suonoEl.value,fonti:fonti,durata:durataEl.value,orario:orarioEl.value};
  }
  function validaPayload(p) {
    if (!p.nome) throw new Error("Il nome non può essere vuoto."); if (!p.categorie.length) throw new Error("Seleziona almeno una categoria.");
    if (!p.incipit) throw new Error("L'incipit non può essere vuoto."); if (p.incipit.length>500) throw new Error("L'incipit supera 500 caratteri."); if (p.outro.length>500) throw new Error("L'outro supera 500 caratteri.");
    if (!Number.isFinite(p.velocita)||p.velocita<.75||p.velocita>1.25) throw new Error("La velocità deve essere tra 0.75 e 1.25.");
    if (p.fonti.length>200) throw new Error("Massimo 200 fonti."); if (!/^\d{2}:00$/.test(p.orario)) throw new Error("Orario non valido.");
    p.fonti.forEach(function (f,i) { if (!f.nome) throw new Error("La fonte "+(i+1)+" non ha un nome."); if (!normalizzaUrl(f.url)) throw new Error("La fonte "+(i+1)+" non ha un URL valido."); });
  }
  function erroreHttp(status) { if (status===401||status===403) return "Token non valido o senza permesso Actions. Creane uno fine-grained con Actions read/write sul repository."; if (status===404) return "Workflow dashboard.yml non trovato o token senza accesso al repository."; if (status===422) return "Payload troppo grande o input non valido. Riduci fonti o testi e riprova."; return "GitHub ha rifiutato la richiesta (HTTP "+status+"). Riprova più tardi."; }
  function linkSicuro(testo, href) {
    let valore = WORKFLOW_PAGE;
    try {
      const url = new URL(String(href || ""));
      if (url.protocol === "https:" || url.protocol === "http:") valore = url.href;
    } catch (e) {}
    const link = document.createElement("a");
    link.href = valore;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = testo;
    return link;
  }

  function bottoneAzione(testo, azione) {
    const bottone = document.createElement("button");
    bottone.type = "button";
    bottone.className = "secondario";
    bottone.textContent = testo;
    bottone.addEventListener("click", azione);
    return bottone;
  }

  function formattaTrascorso(millisecondi) {
    const secondi = Math.max(0, Math.floor(millisecondi / 1000));
    const minuti = Math.floor(secondi / 60);
    return minuti > 0 ? minuti + "m " + (secondi % 60) + "s" : secondi + "s";
  }

  function mostraBanner(testo, azioni) {
    bannerGenerazione.hidden = false;
    bannerGenerazione.classList.add("visibile");
    bannerTestoEl.textContent = testo;
    bannerAzioniEl.replaceChildren();
    (azioni || []).forEach(function (azione) { bannerAzioniEl.appendChild(azione); });
  }

  function fermaPolling() {
    pollingAttivo = false;
    if (pollingTimer !== null) { clearInterval(pollingTimer); pollingTimer = null; }
    if (pollingTimeout !== null) { clearTimeout(pollingTimeout); pollingTimeout = null; }
  }

  function chiudiBanner() {
    fermaPolling();
    bannerGenerazione.hidden = true;
    bannerGenerazione.classList.remove("visibile");
  }

  async function ricaricaPubblico() {
    try {
      const risposta = await fetch("impostazioni.json?t=" + Date.now(), { cache: "no-store" });
      if (risposta.ok) {
        const dati = await risposta.json();
        if (dati && typeof dati === "object") popolaForm(dati);
      }
    } catch (e) {}
  }

  async function controllaRunDashboard(token, genera) {
    if (!pollingAttivo) return;
    let risposta;
    try {
      risposta = await fetch(DASHBOARD_RUNS_API, {
        method: "GET",
        cache: "no-store",
        headers: {
          Authorization: "Bearer " + token,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28"
        }
      });
    } catch (e) {
      if (pollingAttivo) mostraBanner("Controllo del salvataggio non disponibile. Riprovo tra poco.", [linkSicuro("Apri le run", WORKFLOW_PAGE)]);
      return;
    }
    if (risposta.status === 401 || risposta.status === 403) {
      fermaPolling();
      mostraBanner("Non riesco a controllare il salvataggio con questo token (serve Actions: read); apri le run", [linkSicuro("Apri le run della dashboard", WORKFLOW_PAGE)]);
      return;
    }
    if (!risposta.ok) {
      if (pollingAttivo) mostraBanner("Controllo del salvataggio non disponibile (HTTP " + risposta.status + "). Riprovo tra poco.", [linkSicuro("Apri le run", WORKFLOW_PAGE)]);
      return;
    }
    let dati;
    try { dati = await risposta.json(); } catch (e) { return; }
    const run = (Array.isArray(dati.workflow_runs) ? dati.workflow_runs : [])
      .filter(function (r) {
        const creato = Date.parse(r.created_at || "");
        return r.head_branch === "main" && Number.isFinite(creato) && creato >= clickedAt - 60000;
      })
      .sort(function (a, b) { return Date.parse(b.created_at) - Date.parse(a.created_at); })[0];
    if (!run) {
      const azioni = [linkSicuro("Apri le run della dashboard", WORKFLOW_PAGE)];
      if (Date.now() - pollingStart < STARTUP_GRACE_MS) {
        mostraBanner("Salvataggio avvenuto, dashboard in avvio...", azioni);
      } else {
        mostraBanner("La dashboard non ha risposto: controlla le run del workflow Dashboard", azioni);
      }
      return;
    }
    const stato = String(run.status || "").toLowerCase();
    const conclusione = String(run.conclusion || "").toLowerCase();
    const linkRun = run.html_url || WORKFLOW_PAGE;
    if (stato === "completed") {
      fermaPolling();
      if (conclusione === "success") {
        if (genera) {
          avviaPolling(token);
        } else {
          await ricaricaPubblico();
          mostraBanner("Salvato", [linkSicuro("Apri il log del salvataggio", linkRun)]);
          mostraStato("Salvato.");
        }
      } else {
        mostraBanner("Salvataggio fallito" + (conclusione ? " (" + conclusione + ")" : ""), [
          linkSicuro("Apri il log della dashboard", linkRun)
        ]);
      }
      return;
    }
    if (["queued", "in_progress", "waiting", "pending", "requested", ""].indexOf(stato) >= 0) {
      mostraBanner("Salvataggio in corso · " + formattaTrascorso(Date.now() - clickedAt), [linkSicuro("Apri la run", linkRun)]);
    }
  }

  function avviaPollingDashboard(token, genera) {
    fermaPolling();
    clickedAt = Date.now();
    pollingStart = clickedAt;
    pollingAttivo = true;
    mostraBanner(genera ? "Salvataggio e generazione in corso..." : "Salvataggio in corso...", [linkSicuro("Apri le run della dashboard", WORKFLOW_PAGE)]);
    pollingTimer = setInterval(function () { controllaRunDashboard(token, genera); }, POLL_INTERVAL_MS);
    pollingTimeout = setTimeout(function () {
      if (!pollingAttivo) return;
      fermaPolling();
      mostraBanner("Tempo scaduto: il salvataggio non ha dato esito. Controlla le run.", [linkSicuro("Apri le run della dashboard", WORKFLOW_PAGE)]);
    }, DASHBOARD_POLL_TIMEOUT_MS);
    controllaRunDashboard(token, genera);
  }

  async function controllaRun(token) {
    if (!pollingAttivo) return;
    let risposta;
    try {
      risposta = await fetch(RUNS_API, {
        method: "GET",
        cache: "no-store",
        headers: {
          Authorization: "Bearer " + token,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28"
        }
      });
    } catch (e) {
      if (pollingAttivo) mostraBanner("Controllo dello stato non disponibile. Riprovo tra poco.", [linkSicuro("Apri le run", WORKFLOW_PAGE)]);
      return;
    }
    if (risposta.status === 401 || risposta.status === 403) {
      fermaPolling();
      mostraBanner("Non riesco a controllare lo stato con questo token (serve Actions: read); apri le run", [linkSicuro("Apri le run del notiziario", NOTIZIARIO_PAGE)]);
      return;
    }
    if (!risposta.ok) {
      if (pollingAttivo) mostraBanner("Controllo dello stato non disponibile (HTTP " + risposta.status + "). Riprovo tra poco.", [linkSicuro("Apri le run", WORKFLOW_PAGE)]);
      return;
    }
    let dati;
    try { dati = await risposta.json(); } catch (e) { return; }
    const run = (Array.isArray(dati.workflow_runs) ? dati.workflow_runs : [])
      .filter(function (r) {
        const creato = Date.parse(r.created_at || "");
        return r.head_branch === "main" && Number.isFinite(creato) && creato >= clickedAt - 60000;
      })
      .sort(function (a, b) { return Date.parse(b.created_at) - Date.parse(a.created_at); })[0];
    if (!run) {
      const azioni = [linkSicuro("Apri le run della dashboard", WORKFLOW_PAGE)];
      if (Date.now() - pollingStart < STARTUP_GRACE_MS) {
        mostraBanner("Salvataggio avvenuto, generazione in avvio...", azioni);
      } else {
        mostraBanner("La generazione non è partita: controlla le run del workflow Dashboard", azioni);
      }
      return;
    }
    const stato = String(run.status || "").toLowerCase();
    const conclusione = String(run.conclusion || "").toLowerCase();
    const linkRun = run.html_url || WORKFLOW_PAGE;
    if (stato === "completed") {
      fermaPolling();
      if (conclusione === "success") {
        mostraBanner("Episodio pronto", [
          linkSicuro("Apri il player", PLAYER_URL),
          linkSicuro("Apri il feed", FEED_URL),
          bottoneAzione("Aggiorna pagina", function () { location.reload(); })
        ]);
      } else {
        mostraBanner("Generazione fallita" + (conclusione ? " (" + conclusione + ")" : ""), [
          linkSicuro("Apri il log della run", linkRun),
          linkSicuro("Apri le run del notiziario", NOTIZIARIO_PAGE)
        ]);
      }
      return;
    }
    const inCorso = ["queued", "in_progress", "waiting", "pending", "requested"];
    if (inCorso.indexOf(stato) >= 0 || stato === "") {
      mostraBanner("Generazione in corso · " + formattaTrascorso(Date.now() - clickedAt), [
        linkSicuro("Apri la run", linkRun)
      ]);
    }
  }

  function avviaPolling(token) {
    fermaPolling();
    clickedAt = Date.now();
    pollingStart = clickedAt;
    pollingAttivo = true;
    mostraBanner("Generazione in corso...", [linkSicuro("Apri le run della dashboard", WORKFLOW_PAGE)]);
    pollingTimer = setInterval(function () { controllaRun(token); }, POLL_INTERVAL_MS);
    pollingTimeout = setTimeout(function () {
      if (!pollingAttivo) return;
      fermaPolling();
      mostraBanner("Tempo scaduto: la generazione è ancora in corso. Controlla le run.", [
        linkSicuro("Apri le run del notiziario", NOTIZIARIO_PAGE)
      ]);
    }, POLL_TIMEOUT_MS);
    controllaRun(token);
  }

  bannerChiudiBtn.addEventListener("click", chiudiBanner);

  async function invia(genera) {
    const tokenInserito=tokenEl.value.trim();
    if (tokenInserito) { try { localStorage.setItem(TOKEN_KEY,tokenInserito); } catch (e) {} }
    let payload; try { payload=costruisciPayload(); validaPayload(payload); } catch (e) { mostraStato(e.message,true); return; }
    const token=tokenInserito||leggiToken(); if (!token) { mostraStato("Token mancante: salvalo nel browser oppure creane uno fine-grained dal link qui sopra.",true); return; }
    let adesso="";
    if (taglioEl&&taglioEl.value) {
      const parti=taglioEl.value.split(":"); const ore=Number(parti[0]); const minuti=Number(parti[1]);
      if (Number.isFinite(ore)&&Number.isFinite(minuti)) {
        const data=new Date(); data.setHours(ore,minuti,0,0);
        // Il fetch considera "futuro" fino a +3h: arretro il riferimento
        // per fermare le notizie esattamente all'ora scelta.
        data.setHours(data.getHours()-3); adesso=data.toISOString();
      }
    }
    salvaBtn.disabled=true; salvaGeneraBtn.disabled=true; mostraStato("Invio delle impostazioni a GitHub…");
    try {
      const r=await fetch(WORKFLOW_DISPATCH, {method: "POST", headers: {Authorization: "Bearer " + token, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"}, body: JSON.stringify({ref: "main", inputs: {payload: JSON.stringify(payload), genera: genera ? "true" : "false", durata: payload.durata, adesso: adesso}})});
      if (r.status===204) { const link=document.createElement("a"); link.href=WORKFLOW_PAGE; link.target="_blank"; link.rel="noopener noreferrer"; link.textContent="Apri le run della dashboard"; statoSalvataggioEl.replaceChildren(document.createTextNode("Impostazioni inviate. "),link); statoSalvataggioEl.classList.remove("errore"); if (genera) statoSalvataggioEl.appendChild(document.createTextNode(" La generazione partirà dopo il commit.")); avviaPollingDashboard(token, genera); }
      else mostraStato(erroreHttp(r.status),true);
    } catch (e) { mostraStato("Errore di rete: impossibile raggiungere GitHub. Controlla la connessione.",true); }
    finally { salvaBtn.disabled=false; salvaGeneraBtn.disabled=false; }
  }
  function parseCsvLine(riga) { const valori=[]; let corrente=""; let virgolette=false; for (let i=0;i<riga.length;i+=1) { const c=riga[i]; if (c==='"') { if (virgolette&&riga[i+1]==='"') { corrente+='"'; i+=1; } else virgolette=!virgolette; } else if (c===","&&!virgolette) { valori.push(corrente.trim()); corrente=""; } else corrente+=c; } valori.push(corrente.trim()); return valori; }
  function parseCsv(testo) {
    const righe=testo.split(/\r?\n/).map(function (r) { return r.trim(); }).filter(Boolean); if (!righe.length) return [];
    const prima=parseCsvLine(righe[0]).map(normalizzaTesto); const header=prima.some(function (v) { return v==="url"||v==="url feed"||v==="feed"||v==="url feed"; }); const col={};
    if (header) prima.forEach(function (n,i) { if (["url","url feed","feed","url_feed"].indexOf(n)>=0) col.url=i; if (["nome","titolo","title","name"].indexOf(n)>=0) col.nome=i; if (["categoria","category"].indexOf(n)>=0) col.categoria=i; });
    const out=[]; for (let i=header?1:0;i<righe.length;i+=1) { const v=parseCsvLine(righe[i]); const url=col.url!==undefined?v[col.url]:v[0]; if (!url||!normalizzaUrl(url)) continue; let nome=col.nome!==undefined?v[col.nome]:""; if (!nome) { try { nome=new URL(url).hostname; } catch (e) { nome="Fonte"; } } out.push({url:url,nome:nome,categoria:col.categoria!==undefined?categoriaDaTesto(v[col.categoria]):categoriaDaUrl(url)}); } return out;
  }
  function parseOpml(testo) {
    const doc=new DOMParser().parseFromString(testo,"text/xml"); if (doc.getElementsByTagName("parsererror").length) throw new Error("OPML non valido.");
    return Array.from(doc.getElementsByTagName("outline")).map(function (o) { const url=o.getAttribute("xmlUrl")||""; if (!normalizzaUrl(url)) return null; const nome=o.getAttribute("title")||o.getAttribute("text")||""; const categoria=categoriaDaTesto(o.getAttribute("category")||"")||categoriaDaUrl(url); return {url:url,nome:nome||"Fonte",categoria:categoria}; }).filter(Boolean);
  }
  function parseJsonFeed(testo) {
    const dati=JSON.parse(testo); let elenco=[]; if (Array.isArray(dati)) elenco=dati; else if (dati&&typeof dati==="object") elenco=dati.fonti||dati.feeds||dati.data||dati.items||[];
    if (!Array.isArray(elenco)) return [];
    return elenco.map(function (el) { if (typeof el==="string") { if (!normalizzaUrl(el)) return null; return {url:el,nome:new URL(el).hostname,categoria:categoriaDaUrl(el)}; } if (!el||typeof el!=="object") return null; const url=el.url||el.url_feed||el.feed||""; if (!normalizzaUrl(url)) return null; let nome=el.nome||el.titolo||el.title||el.name||""; if (!nome) { try { nome=new URL(url).hostname; } catch (e) { nome="Fonte"; } } return {url:url,nome:nome,categoria:categoriaDaTesto(el.categoria||el.category||"")||categoriaDaUrl(url)}; }).filter(Boolean);
  }
  function parseTestoFeed(testo) { return testo.split(/\r?\n/).map(function (r) { return r.trim(); }).filter(function (r) { return r&&!r.startsWith("#")&&normalizzaUrl(r); }).map(function (url) { let nome=""; try { nome=new URL(url).hostname; } catch (e) { nome="Fonte"; } return {url:url,nome:nome,categoria:categoriaDaUrl(url)}; }); }
  function interpretaFeed(testo,nomeFile) { const basso=String(nomeFile||"").toLowerCase(); if (basso.endsWith(".opml")||basso.endsWith(".xml")||/<opml[\s>]/i.test(testo)) return parseOpml(testo); if (basso.endsWith(".json")||/^\s*[\[{]/.test(testo)) return parseJsonFeed(testo); if (basso.endsWith(".csv")||(testo.split(/\r?\n/)[0]||"").includes(",")) return parseCsv(testo); return parseTestoFeed(testo); }
  async function importaFeedFile(file) {
    if (!file) return; if (file.size>5*1024*1024) { mostraStato("Il file supera 5 MB.",true); return; }
    try { const testo=await file.text(); const candidate=interpretaFeed(testo,file.name); let aggiunte=0; let duplicate=0; for (const f of candidate) { const prima=fontiLista.querySelectorAll(".fonte").length; if (prima>=200) break; aggiungiFonte({nome:f.nome,url:f.url,categoria:f.categoria||"da-assegnare",attivo:false},true,true); if (fontiLista.querySelectorAll(".fonte").length>prima) aggiunte+=1; else duplicate+=1; } mostraStato(aggiunte+" fonti importate spente, "+duplicate+" duplicate o scartate."); if (fontiDettagli) fontiDettagli.open=true; } catch (e) { mostraStato("Import non riuscito: "+e.message,true); } finally { importaInput.value=""; }
  }
  async function carica() {
    let canale=null; const episodi=[];
    try {
      const r=await fetch("feed.xml",{cache:"no-store"}); if (!r.ok) throw new Error("HTTP "+r.status); const xml=await r.text(); const doc=new DOMParser().parseFromString(xml,"application/xml"); if (doc.querySelector("parsererror")) throw new Error("XML non valido"); canale=doc.querySelector("channel"); if (!canale) throw new Error("canale RSS assente");
      const modo=testoDi(primoNS(canale,NS_NOTIZIARIO,"modalita")); modalitaEl.textContent=modo==="llm"?"Gemini":(modo==="fallback"?"Fallback locale (senza AI)":"non disponibile");
      const voci=Array.from(doc.querySelectorAll("item")).map(function (item,indice) { const quando=Date.parse(testoDi(item.querySelector("pubDate"))); return {item:item,indice:indice,quando:Number.isFinite(quando)?quando:-Infinity}; });
      voci.sort(function (a,b) { return (b.quando-a.quando)||(a.indice-b.indice); });
      conteggioEl.textContent=String(voci.length);
      voci.forEach(function (voce) { episodi.push(voce.item); lista.appendChild(creaEpisodio(voce.item,episodi.length-1)); });
      if (!episodi.length) mostraErrore("Non ci sono ancora episodi nel feed.");
    } catch (e) { mostraErrore("Non riesco a leggere feed.xml. Apri questa pagina con GitHub Pages oppure avvia un server dalla cartella del progetto con python -m http.server 8000 e vai su http://localhost:8000/docs/"); modalitaEl.textContent="non disponibile"; conteggioEl.textContent="0"; }
    await caricaImpostazioni(canale,episodi);
  }
  velocitaEl.addEventListener("input",function () { velocitaValoreEl.textContent=Number(velocitaEl.value).toFixed(2)+"×"; });
  suonoEl.addEventListener("change",aggiornaSuoni); salvaBtn.addEventListener("click",function () { invia(false); }); salvaGeneraBtn.addEventListener("click",function () { invia(true); }); salvaTokenBtn.addEventListener("click",salvaToken); dimenticaTokenBtn.addEventListener("click",dimenticaToken);
  anteprimaChiudiBtn.addEventListener("click",chiudiDialogAnteprima); anteprimaChiudiBassoBtn.addEventListener("click",chiudiDialogAnteprima);
  anteprimaDialog.addEventListener("click",function (evento) { if (evento.target===anteprimaDialog) chiudiDialogAnteprima(); });
  anteprimaDialog.addEventListener("close",function () { anteprimaRichiesta += 1; });
  aggiungiFonteBtn.addEventListener("click",function () { const url=nuovaUrlEl.value.trim(); if (!url) { mostraStato("Inserisci l'URL della nuova fonte.",true); return; } if (aggiungiFonte({nome:nuovaNomeEl.value,url:url,categoria:nuovaCategoriaEl.value,attivo:false},true,false)) { nuovaNomeEl.value=""; nuovaUrlEl.value=""; nuovaCategoriaEl.value="da-assegnare"; mostraStato("Fonte aggiunta spenta. Ricordati di salvare."); if (fontiDettagli) fontiDettagli.open=true; } });
  importaInput.addEventListener("change",function () { if (importaInput.files&&importaInput.files[0]) importaFeedFile(importaInput.files[0]); });
  form.addEventListener("submit",function (evento) { evento.preventDefault(); });
  nuovaCategoriaEl.replaceChildren(); { const d=crea("option","","Da assegnare"); d.value="da-assegnare"; nuovaCategoriaEl.appendChild(d); for (const cat of CATEGORIE) { const o=crea("option","",cat.label); o.value=cat.id; nuovaCategoriaEl.appendChild(o); } }
    tokenEl.value=leggiToken(); aggiornaTokenStato(); modificaLink.href=ISSUE_URL; carica();
})();
</script>
</body>
</html>
"""


def aggiorna_docs(
    episodio: Episodio,
    impostazioni: dict[str, Any],
    docs_dir: str | Path,
    base_url: str | None = None,
    sito_url: str | None = None,
    impostazioni_pubbliche: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
    anteprime_fonti: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Aggiorna storico, feed, index e anteprime; restituisce i percorsi."""
    logger = logger or logging.getLogger("notiziario")
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)
    storico_path = docs / "storico.json"
    storico = carica_storico(storico_path)
    massimo = int(impostazioni["feed"].get("max_episodi", 60))
    storico = aggiungi_episodio(storico, episodio, max_episodi=massimo)
    salva_storico(storico_path, storico)
    feed_path = docs / "feed.xml"
    numero = scrivi_feed(
        storico, feed_path, impostazioni, base_url=base_url, sito_url=sito_url
    )
    index_path = docs / "index.html"
    scrivi_index(index_path, impostazioni)
    if impostazioni_pubbliche:
        scrivi_impostazioni_pubbliche(
            docs / "impostazioni.json", **impostazioni_pubbliche
        )
    percorsi = {
        "feed": str(feed_path),
        "index": str(index_path),
        "storico": str(storico_path),
    }
    if anteprime_fonti is not None:
        anteprime_path = docs / "anteprime-fonti.json"
        scrivi_anteprime_fonti(anteprime_path, anteprime_fonti)
        percorsi["anteprime"] = str(anteprime_path)
    logger.info("Feed aggiornato: %s (%d episodi).", feed_path, numero)
    return percorsi
