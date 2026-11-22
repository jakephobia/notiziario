from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from notiziario.config import carica_impostazioni
from notiziario.feed import (
    NS_ITUNES,
    NS_NOTIZIARIO,
    Episodio,
    aggiungi_episodio,
    carica_storico,
    costruisci_url_audio,
    salva_storico,
    scrivi_feed,
    scrivi_index,
)


def episodio(data="2026-11-22", modalita="fallback"):
    return Episodio(
        data=data,
        titolo=f"Notiziario del {data}",
        descrizione="Le notizie del giorno.",
        filename=f"notiziario-{data}.mp3",
        durata_secondi=420.0,
        dimensione=123456,
        modalita=modalita,
        categorie=["italia", "mondo"],
        voce="Kore",
        velocita=1.1,
        tts_motore="gemini",
        pubblicato=f"{data}T06:30:00+00:00",
    )


def test_costruisci_url_audio_locale_e_release():
    assert (
        costruisci_url_audio(
            "https://esempio.github.io/notiziario/audio",
            "2026-11-22",
            "notiziario-2026-11-22.mp3",
        )
        == "https://esempio.github.io/notiziario/audio/notiziario-2026-11-22.mp3"
    )
    assert (
        costruisci_url_audio(
            "https://github.com/utente/repo/releases/download",
            "2026-11-22",
            "notiziario-2026-11-22.mp3",
        )
        == "https://github.com/utente/repo/releases/download/episodio-2026-11-22/"
        "notiziario-2026-11-22.mp3"
    )
    assert (
        costruisci_url_audio(
            "https://esempio.test/{tag}/{file}", "2026-11-22", "ep.mp3"
        )
        == "https://esempio.test/episodio-2026-11-22/ep.mp3"
    )


def test_feed_xml_ben_formato_e_campi_itunes(tmp_path):
    impostazioni = carica_impostazioni()
    storico = {"episodi": []}
    storico = aggiungi_episodio(storico, episodio("2026-11-22"), 60)
    storico = aggiungi_episodio(storico, episodio("2026-11-21", "llm"), 60)
    percorso = tmp_path / "feed.xml"
    numero = scrivi_feed(
        storico,
        percorso,
        impostazioni,
        sito_url="https://owner.github.io/repo/",
    )
    assert numero == 2
    assert percorso.exists()

    radice = ET.parse(percorso).getroot()
    assert radice.tag == "rss"
    assert radice.attrib["version"] == "2.0"
    canale = radice.find("channel")
    assert canale is not None
    assert canale.find("title").text == "Il notiziario di Jacopo"
    immagine = canale.find("image")
    assert immagine.find("url").text == "https://owner.github.io/repo/copertina.png"
    assert canale.find(f"{{{NS_ITUNES}}}image").attrib["href"].endswith("/copertina.png")
    assert canale.find("language").text == "it-it"
    assert canale.find("link").text == "https://owner.github.io/repo/"
    assert canale.find(f"{{{NS_NOTIZIARIO}}}voce").text == "Kore"
    assert canale.find(f"{{{NS_NOTIZIARIO}}}tts_motore").text == "gemini"
    assert canale.find(f"{{{NS_ITUNES}}}author") is not None
    assert canale.find(f"{{{NS_ITUNES}}}explicit").text == "false"
    assert canale.find(f"{{{NS_NOTIZIARIO}}}categorie").text == "Italia, Mondo"
    assert canale.find(f"{{{NS_NOTIZIARIO}}}modalita").text == "fallback"

    items = canale.findall("item")
    assert len(items) == 2
    primo = items[0]
    assert primo.find("title").text.startswith("Notiziario del 2026-11-22")
    assert primo.find("guid").attrib["isPermaLink"] == "false"
    assert primo.find("guid").text == "notiziario-2026-11-22"
    assert primo.find("pubDate") is not None
    assert parsedate_to_datetime(primo.find("pubDate").text) is not None
    enclosure = primo.find("enclosure")
    assert enclosure is not None
    assert enclosure.attrib["type"] == "audio/mpeg"
    assert enclosure.attrib["length"] == "123456"
    assert "notiziario-2026-11-22.mp3" in enclosure.attrib["url"]
    assert primo.find(f"{{{NS_ITUNES}}}duration").text == "00:07:00"
    assert primo.find(f"{{{NS_NOTIZIARIO}}}modalita").text == "fallback"


def test_storico_deduplica_e_limita(tmp_path):
    percorso = tmp_path / "storico.json"
    storico = {"episodi": []}
    from datetime import date, timedelta

    base = date(2026, 11, 22)
    for giorni_fa in range(65):
        data = (base - timedelta(days=giorni_fa)).isoformat()
        storico = aggiungi_episodio(storico, episodio(data), max_episodi=60)
    assert len(storico["episodi"]) == 60
    aggiornato = episodio("2026-11-22")
    aggiornato.durata_secondi = 500
    storico = aggiungi_episodio(storico, aggiornato, max_episodi=60)
    assert len(storico["episodi"]) == 60
    assert storico["episodi"][0]["data"] == "2026-11-22"
    assert storico["episodi"][0]["durata_secondi"] == 500
    salva_storico(percorso, storico)
    assert carica_storico(percorso)["episodi"][0]["data"] == "2026-11-22"


def test_storico_corrotto_non_blocca(tmp_path):
    percorso = tmp_path / "storico.json"
    percorso.write_text("{non-json", encoding="utf-8")
    assert carica_storico(percorso) == {"episodi": []}
    percorso.write_text(json.dumps({"episodi": "no"}), encoding="utf-8")
    assert carica_storico(percorso) == {"episodi": []}


def test_index_contiene_player_e_fetch_feed(tmp_path):
    impostazioni = carica_impostazioni()
    percorso = tmp_path / "index.html"
    scrivi_index(percorso, impostazioni)
    html = percorso.read_text(encoding="utf-8")
    assert '<audio id="player"' in html
    assert 'fetch("feed.xml"' in html
    assert "DOMParser" in html
    assert "Modalità AI" in html
    assert "viewport" in html
    assert "%%" not in html

def test_normalizza_sito_owner_github_io():
    from notiziario.feed import normalizza_sito_url

    assert normalizza_sito_url("https://jakephobia.github.io/notiziario/") == "https://jakephobia.github.io/notiziario/"
    assert normalizza_sito_url("https://jakephobia.github.io/jakephobia.github.io/") == "https://jakephobia.github.io/"


def test_feed_valido_senza_episodi(tmp_path):
    impostazioni = carica_impostazioni()
    percorso = tmp_path / "feed.xml"
    assert scrivi_feed({"episodi": []}, percorso, impostazioni) == 0
    radice = ET.parse(percorso).getroot()
    canale = radice.find("channel")
    assert canale.find("title").text
    assert canale.find("image/url").text.endswith("/copertina.png")
    assert canale.findall("item") == []
''

def test_robots_docs_disallow_all():
    from pathlib import Path

    robots = Path("docs/robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *" in robots
    assert "Disallow: /" in robots

def test_index_contiene_sezione_impostazioni_e_fetch(tmp_path):
    impostazioni = carica_impostazioni()
    percorso = tmp_path / "index.html"
    scrivi_index(percorso, impostazioni)
    html = percorso.read_text(encoding="utf-8")
    assert "Impostazioni" in html
    assert "fetch(\"impostazioni.json\"" in html
    assert "id=\"modifica-impostazioni\"" in html
    assert "Le modifiche si salvano dalla dashboard GitHub" in html
    assert "innerHTML" not in html
