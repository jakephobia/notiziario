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
from .testi import formatta_durata


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
        ET.SubElement(item, "title").text = str(episodio.get("titolo", "Notiziario"))
        descrizione = str(episodio.get("descrizione", ""))
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


def _escape_html(testo: Any) -> str:
    return (
        str(testo)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_TEMPLATE_INDEX = """<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>%%TITOLO%%</title>
  <style>
    :root {
      color-scheme: light dark;
      --sfondo: #f6f7f4;
      --testo: #17211b;
      --tenue: #5a675f;
      --card: #ffffff;
      --bordo: #dde3dc;
      --accento: #146b4b;
      --accento-scuro: #0d4f37;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --sfondo: #111713;
        --testo: #eef4ef;
        --tenue: #a7b4aa;
        --card: #19221c;
        --bordo: #2a382f;
        --accento: #5cc79a;
        --accento-scuro: #3da77c;
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--sfondo);
      color: var(--testo);
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      line-height: 1.55;
    }
    main { max-width: 760px; margin: 0 auto; padding: 28px 18px 64px; }
    header { padding: 18px 0 10px; }
    .copertina { width: 148px; height: 148px; border-radius: 18px; display: block; margin: 0 0 16px; border: 1px solid var(--bordo); }
    h1 { font-size: clamp(2rem, 7vw, 2.8rem); letter-spacing: -0.03em; margin: 0 0 6px; }
    .sottotitolo { color: var(--tenue); margin: 0; font-size: 1.02rem; }
    .player-card {
      background: var(--card);
      border: 1px solid var(--bordo);
      border-radius: 18px;
      padding: 18px;
      margin: 22px 0;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.06);
      position: sticky;
      top: 10px;
      z-index: 2;
    }
    .in-riproduzione { font-weight: 600; margin: 0 0 10px; min-height: 1.5em; }
    audio { width: 100%; margin-top: 6px; }
    .stato {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
      background: var(--card);
      border: 1px solid var(--bordo);
      border-radius: 14px;
      padding: 14px 16px;
      margin: 0 0 24px;
      font-size: 0.94rem;
    }
    .stato div { color: var(--tenue); }
    .stato strong { color: var(--testo); font-weight: 600; }
    h2 { font-size: 1.15rem; margin: 26px 0 12px; }
    ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }
    li {
      background: var(--card);
      border: 1px solid var(--bordo);
      border-radius: 14px;
      padding: 14px 16px;
    }
    .episodio-titolo {
      display: block;
      width: 100%;
      text-align: left;
      border: 0;
      background: transparent;
      color: var(--testo);
      font: inherit;
      font-weight: 650;
      cursor: pointer;
      padding: 0;
    }
    .episodio-titolo:hover, .episodio-titolo:focus-visible { color: var(--accento); }
    .meta { color: var(--tenue); font-size: 0.88rem; margin: 4px 0 0; }
    .descrizione { color: var(--tenue); font-size: 0.94rem; margin: 8px 0 0; }
    .avviso {
      background: var(--card);
      border: 1px solid var(--bordo);
      border-left: 4px solid var(--accento);
      border-radius: 12px;
      padding: 14px 16px;
      color: var(--tenue);
    }
    footer { color: var(--tenue); font-size: 0.82rem; margin-top: 36px; border-top: 1px solid var(--bordo); padding-top: 16px; }
    a { color: var(--accento); }
  </style>
</head>
<body>
<main>
  <header>
    <img class="copertina" src="copertina.png" alt="Copertina del podcast">
    <h1>%%TITOLO%%</h1>
    <p class="sottotitolo">%%DESCRIZIONE%%</p>
  </header>

  <section class="player-card" aria-label="Player del podcast">
    <p class="in-riproduzione" id="in-riproduzione">Scegli un episodio dalla lista.</p>
    <audio id="player" controls preload="metadata"></audio>
  </section>

  <section class="stato" aria-label="Stato del notiziario">
    <div>Categorie attive: <strong id="categorie">caricamento...</strong></div>
    <div>Modalità AI: <strong id="modalita">caricamento...</strong></div>
    <div>Voce: <strong id="voce">caricamento...</strong></div>
    <div>Velocità: <strong id="velocita">caricamento...</strong></div>
    <div>Motore TTS: <strong id="tts-motore">caricamento...</strong></div>
    <div>Episodi disponibili: <strong id="conteggio">caricamento...</strong></div>
  </section>

  <h2>Episodi</h2>
  <div id="messaggio" class="avviso" hidden></div>
  <ul id="episodi"></ul>

  <footer>
    Notiziario personale. Le notizie appartengono alle testate citate nel copione.
    Il player legge il feed RSS statico di questa pagina.
  </footer>
</main>

<script>
(function () {
  "use strict";
  const NS_NOTIZIARIO = "https://notiziario.local/ns/1.0";
  const NS_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd";
  const player = document.getElementById("player");
  const inRiproduzione = document.getElementById("in-riproduzione");
  const lista = document.getElementById("episodi");
  const messaggio = document.getElementById("messaggio");
  const categorieEl = document.getElementById("categorie");
  const modalitaEl = document.getElementById("modalita");
  const voceEl = document.getElementById("voce");
  const velocitaEl = document.getElementById("velocita");
  const motoreTtsEl = document.getElementById("tts-motore");
  const conteggioEl = document.getElementById("conteggio");

  function testoDi(elemento) {
    return elemento && elemento.textContent ? elemento.textContent.trim() : "";
  }

  function primoPerNamespace(radice, namespace, nome) {
    const trovati = radice.getElementsByTagNameNS(namespace, nome);
    return trovati.length ? trovati[0] : null;
  }

  function mostraErrore(testo) {
    messaggio.textContent = testo;
    messaggio.hidden = false;
    categorieEl.textContent = "non disponibili";
    modalitaEl.textContent = "non disponibile";
    voceEl.textContent = "non disponibile";
    velocitaEl.textContent = "non disponibile";
    motoreTtsEl.textContent = "non disponibile";
    conteggioEl.textContent = "0";
  }

  function formattaData(grezza) {
    const data = new Date(grezza);
    if (isNaN(data.getTime())) return grezza || "";
    return data.toLocaleDateString("it-IT", {
      weekday: "long", day: "numeric", month: "long", year: "numeric"
    });
  }

  function creaEpisodio(item, indice) {
    const titolo = testoDi(item.querySelector("title")) || "Episodio " + (indice + 1);
    const descrizione = testoDi(item.querySelector("description"));
    const pubDate = testoDi(item.querySelector("pubDate"));
    const enclosure = item.querySelector("enclosure");
    const url = enclosure ? enclosure.getAttribute("url") : "";
    const durataEl = primoPerNamespace(item, NS_ITUNES, "duration");
    const durata = testoDi(durataEl);

    const li = document.createElement("li");
    const bottone = document.createElement("button");
    bottone.type = "button";
    bottone.className = "episodio-titolo";
    bottone.textContent = titolo;
    bottone.addEventListener("click", function () {
      if (!url) {
        mostraErrore("Questo episodio non ha un file audio nel feed.");
        return;
      }
      player.src = url;
      inRiproduzione.textContent = "In ascolto: " + titolo;
      player.play().catch(function () {
        mostraErrore("Premi play sul player per ascoltare l'episodio.");
      });
    });
    li.appendChild(bottone);

    const meta = document.createElement("p");
    meta.className = "meta";
    const pezzi = [];
    if (pubDate) pezzi.push(formattaData(pubDate));
    if (durata) pezzi.push(durata);
    meta.textContent = pezzi.join(" · ");
    if (pezzi.length) li.appendChild(meta);

    if (descrizione) {
      const desc = document.createElement("p");
      desc.className = "descrizione";
      desc.textContent = descrizione;
      li.appendChild(desc);
    }
    return li;
  }

  async function carica() {
    try {
      const risposta = await fetch("feed.xml", { cache: "no-store" });
      if (!risposta.ok) throw new Error("HTTP " + risposta.status);
      const xml = await risposta.text();
      const doc = new DOMParser().parseFromString(xml, "application/xml");
      if (doc.querySelector("parsererror")) throw new Error("XML non valido");
      const canale = doc.querySelector("channel");
      if (!canale) throw new Error("canale RSS assente");

      const categorie = primoPerNamespace(canale, NS_NOTIZIARIO, "categorie");
      const modalita = primoPerNamespace(canale, NS_NOTIZIARIO, "modalita");
      categorieEl.textContent = testoDi(categorie) || "non disponibili";
      const modo = testoDi(modalita);
      modalitaEl.textContent = modo === "llm" ? "Gemini" : (modo === "fallback" ? "Fallback locale (senza AI)" : "non disponibile");
      const voce = primoPerNamespace(canale, NS_NOTIZIARIO, "voce");
      const voceLabel = primoPerNamespace(canale, NS_NOTIZIARIO, "voce_label");
      const velocita = primoPerNamespace(canale, NS_NOTIZIARIO, "velocita");
      const motoreTts = primoPerNamespace(canale, NS_NOTIZIARIO, "tts_motore");
      voceEl.textContent = testoDi(voceLabel) || testoDi(voce) || "non disponibile";
      velocitaEl.textContent = testoDi(velocita) ? testoDi(velocita) + "×" : "non disponibile";
      const motore = testoDi(motoreTts);
      motoreTtsEl.textContent = motore === "gemini" ? "Gemini TTS" : (motore === "edge" ? "edge-tts" : "non disponibile");

      const episodi = Array.from(doc.querySelectorAll("item"));
      conteggioEl.textContent = String(episodi.length);
      if (!episodi.length) {
        mostraErrore("Non ci sono ancora episodi nel feed.");
        return;
      }
      episodi.forEach(function (item, indice) {
        lista.appendChild(creaEpisodio(item, indice));
      });
    } catch (errore) {
      mostraErrore(
        "Non riesco a leggere feed.xml. Apri questa pagina con GitHub Pages " +
        "oppure avvia un server dalla cartella del progetto con " +
        "python -m http.server 8000 e vai su http://localhost:8000/docs/"
      );
    }
  }

  carica();
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
    logger: logging.Logger | None = None,
) -> dict[str, str]:
    """Aggiorna storico, feed e index; restituisce i percorsi scritti."""
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
    logger.info("Feed aggiornato: %s (%d episodi).", feed_path, numero)
    return {
        "feed": str(feed_path),
        "index": str(index_path),
        "storico": str(storico_path),
    }
