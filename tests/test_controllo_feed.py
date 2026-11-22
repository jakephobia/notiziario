from __future__ import annotations

from datetime import timedelta
from email.utils import format_datetime

from helpers import crea_articolo
from notiziario.config import Fonte, carica_impostazioni
from notiziario.controllo_feed import (
    EsitoControllo,
    aggiorna_fonti_con_controllo,
    controlla_feed,
    salva_report,
)
from notiziario.visti import Visti


class Risposta:
    def __init__(self, contenuto: bytes, status: int = 200):
        self.content = contenuto
        self.status_code = status


def rss(items: list[str]) -> bytes:
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<title>Test</title><link>https://esempio.test/</link>"
        "<description>x</description>" + "".join(items) + "</channel></rss>"
    ).encode("utf-8")


def item(titolo: str, sommario: str, adesso, data: bool = True, audio: bool = False):
    data_xml = (
        f"<pubDate>{format_datetime(adesso - timedelta(hours=2))}</pubDate>"
        if data
        else ""
    )
    enclosure = (
        '<enclosure url="https://esempio.test/podcast.mp3" type="audio/mpeg" length="1"/>'
        if audio
        else ""
    )
    return (
        f"<item><title>{titolo}</title><link>https://esempio.test/{titolo}</link>"
        f"<description>{sommario}</description>{data_xml}{enclosure}</item>"
    )


def test_feed_ok_con_testo(monkeypatch, adesso):
    contenuto = rss(
        [
            item(
                f"Titolo {i}",
                "Un testo utile e sufficientemente lungo per il controllo del feed. " * 2,
                adesso,
            )
            for i in range(6)
        ]
    )
    monkeypatch.setattr(
        "notiziario.controllo_feed.fetch_con_limite",
        lambda *a, **k: (contenuto, "https://esempio.test/rss", 200),
    )
    esito = controlla_feed(
        Fonte("Buona", "https://esempio.test/rss", "italia"),
        carica_impostazioni(),
        adesso=adesso,
    )
    assert esito.stato == "ok"
    assert esito.percentuale_testo >= 50


def test_feed_solo_titoli(monkeypatch, adesso):
    contenuto = rss(
        [item(f"Titolo {i}", f"Titolo {i}", adesso) for i in range(6)]
    )
    monkeypatch.setattr(
        "notiziario.controllo_feed.fetch_con_limite",
        lambda *a, **k: (contenuto, "https://esempio.test/rss", 200),
    )
    esito = controlla_feed(
        Fonte("Titoli", "https://esempio.test/rss", "italia"),
        carica_impostazioni(),
        adesso=adesso,
    )
    assert esito.stato == "solo-titoli"


def test_feed_testo_breve_non_disattivabile(monkeypatch, adesso):
    breve = "Summary reale ma breve, con abbastanza caratteri per non essere un titolo."
    contenuto = rss([item(f"Titolo {i}", breve, adesso) for i in range(6)])
    monkeypatch.setattr(
        "notiziario.controllo_feed.fetch_con_limite",
        lambda *a, **k: (contenuto, "https://esempio.test/rss", 200),
    )
    esito = controlla_feed(
        Fonte("ANSA breve", "https://esempio.test/rss", "italia"),
        carica_impostazioni(),
        adesso=adesso,
    )
    assert esito.stato == "testo-breve"
    assert esito.testo_breve is True
    fonti = [Fonte("ANSA breve", "https://esempio.test/rss", "italia", attivo=True)]
    con_flag = aggiorna_fonti_con_controllo(fonti, [esito], True, adesso)
    assert con_flag[0].attivo is True


def test_xml_malformato_e_errore(monkeypatch, adesso):
    monkeypatch.setattr(
        "notiziario.controllo_feed.fetch_con_limite",
        lambda *a, **k: (b"<rss><channel><title>rotto</title>", "https://esempio.test/rss", 200),
    )
    esito = controlla_feed(
        Fonte("Rotto", "https://esempio.test/rss", "italia"),
        carica_impostazioni(),
        adesso=adesso,
    )
    assert esito.stato == "errore"


def test_summary_molto_breve_non_e_solo_titoli(monkeypatch, adesso):
    contenuto = rss(
        [item(f"Titolo {i}", "Notizia breve.", adesso) for i in range(6)]
    )
    monkeypatch.setattr(
        "notiziario.controllo_feed.fetch_con_limite",
        lambda *a, **k: (contenuto, "https://esempio.test/rss", 200),
    )
    esito = controlla_feed(
        Fonte("Breve", "https://esempio.test/rss", "italia"),
        carica_impostazioni(),
        adesso=adesso,
    )
    assert esito.stato == "testo-breve"
    assert esito.percentuale_presente == 100


def test_feed_paywall(monkeypatch, adesso):
    contenuto = rss(
        [item(f"Titolo {i}", "Abbonati per leggere l'articolo", adesso) for i in range(6)]
    )
    monkeypatch.setattr(
        "notiziario.controllo_feed.fetch_con_limite",
        lambda *a, **k: (contenuto, "https://esempio.test/rss", 200),
    )
    esito = controlla_feed(
        Fonte("Paywall", "https://esempio.test/rss", "italia"),
        carica_impostazioni(),
        adesso=adesso,
    )
    assert esito.stato == "paywall"


def test_paywall_falso_positivo_su_testo_lungo(monkeypatch, adesso):
    lungo = (
        "Questo articolo parla di abbonamento e della storia del servizio. "
        "Il testo è lungo e non è un paywall. " * 4
    )
    contenuto = rss([item(f"Titolo {i}", lungo, adesso) for i in range(6)])
    monkeypatch.setattr(
        "notiziario.controllo_feed.fetch_con_limite",
        lambda *a, **k: (contenuto, "https://esempio.test/rss", 200),
    )
    esito = controlla_feed(
        Fonte("Lungo", "https://esempio.test/rss", "italia"),
        carica_impostazioni(),
        adesso=adesso,
    )
    assert esito.stato == "ok"
    assert esito.percentuale_paywall == 0


def test_feed_podcast(monkeypatch, adesso):
    contenuto = rss(
        [
            item(f"Episodio {i}", "Descrizione del podcast.", adesso, audio=True)
            for i in range(6)
        ]
    )
    monkeypatch.setattr(
        "notiziario.controllo_feed.fetch_con_limite",
        lambda *a, **k: (contenuto, "https://esempio.test/rss", 200),
    )
    esito = controlla_feed(
        Fonte("Podcast", "https://esempio.test/rss", "italia"),
        carica_impostazioni(),
        adesso=adesso,
    )
    assert esito.stato == "podcast"


def test_feed_inattivo(monkeypatch, adesso):
    vecchio = adesso - timedelta(days=300)
    contenuto = rss(
        [item(f"Titolo {i}", "Testo lungo " * 20, vecchio) for i in range(6)]
    )
    monkeypatch.setattr(
        "notiziario.controllo_feed.fetch_con_limite",
        lambda *a, **k: (contenuto, "https://esempio.test/rss", 200),
    )
    esito = controlla_feed(
        Fonte("Vecchio", "https://esempio.test/rss", "italia"),
        carica_impostazioni(),
        adesso=adesso,
    )
    assert esito.stato == "inattivo"
    assert esito.giorni_inattivita >= 180


def test_feed_data_assente(monkeypatch, adesso, tmp_path):
    contenuto = rss(
        [item(f"Titolo {i}", "Testo lungo " * 20, adesso, data=False) for i in range(6)]
    )
    monkeypatch.setattr(
        "notiziario.controllo_feed.fetch_con_limite",
        lambda *a, **k: (contenuto, "https://esempio.test/rss", 200),
    )
    visti = Visti(tmp_path / "visti.json", adesso=adesso)
    esito = controlla_feed(
        Fonte("SenzaData", "https://esempio.test/rss", "italia"),
        carica_impostazioni(),
        adesso=adesso,
        visti=visti,
    )
    assert esito.stato == "data-assente"
    assert esito.data_assente is True


def test_feed_senza_date_inattivo_da_sei_mesi(monkeypatch, adesso, tmp_path):
    import json

    contenuto = rss(
        [item(f"Titolo {i}", "Testo lungo " * 20, adesso, data=False) for i in range(6)]
    )
    monkeypatch.setattr(
        "notiziario.controllo_feed.fetch_con_limite",
        lambda *a, **k: (contenuto, "https://esempio.test/rss", 200),
    )
    percorso = tmp_path / "visti.json"
    percorso.write_text(
        json.dumps(
            {
                "visti": {},
                "feed_last_seen": {"SenzaData": "2026-01-01T10:00:00+01:00"},
            }
        ),
        encoding="utf-8",
    )
    visti = Visti(percorso, adesso=adesso)
    esito = controlla_feed(
        Fonte("SenzaData", "https://esempio.test/rss", "italia"),
        carica_impostazioni(),
        adesso=adesso,
        visti=visti,
    )
    assert esito.stato == "inattivo"
    assert esito.giorni_inattivita > 180


def test_feed_campione_insufficiente(monkeypatch, adesso):
    contenuto = rss(
        [item(f"Titolo {i}", "Testo lungo " * 20, adesso) for i in range(3)]
    )
    monkeypatch.setattr(
        "notiziario.controllo_feed.fetch_con_limite",
        lambda *a, **k: (contenuto, "https://esempio.test/rss", 200),
    )
    esito = controlla_feed(
        Fonte("Corto", "https://esempio.test/rss", "italia"),
        carica_impostazioni(),
        adesso=adesso,
    )
    assert esito.stato == "campione-insufficiente"


def test_feed_errore(monkeypatch, adesso):
    import requests

    def errore(*args, **kwargs):
        raise requests.ConnectionError("no")

    monkeypatch.setattr("notiziario.controllo_feed.fetch_con_limite", errore)
    esito = controlla_feed(
        Fonte("Rotta", "https://esempio.test/rss", "italia"),
        carica_impostazioni(),
        adesso=adesso,
    )
    assert esito.stato == "errore"


def test_report_e_disattivazione(tmp_path, adesso):
    fonti = [
        Fonte("A", "https://a.test/rss", "italia", attivo=True),
        Fonte("B", "https://b.test/rss", "italia", attivo=True),
        Fonte("C", "https://c.test/rss", "italia", attivo=True),
    ]
    esiti = [
        EsitoControllo(
            fonte="A",
            url="https://a.test/rss",
            categoria="italia",
            attivo=True,
            stato="ok",
        ),
        EsitoControllo(
            fonte="B",
            url="https://b.test/rss",
            categoria="italia",
            attivo=True,
            stato="solo-titoli",
        ),
        EsitoControllo(
            fonte="C",
            url="https://c.test/rss",
            categoria="italia",
            attivo=True,
            stato="campione-insufficiente",
        ),
    ]
    percorso = tmp_path / "report.json"
    salva_report(percorso, esiti, carica_impostazioni(), adesso)
    assert percorso.exists()
    senza_flag = aggiorna_fonti_con_controllo(fonti, esiti, False, adesso)
    assert all(f.attivo for f in senza_flag)
    assert senza_flag[1].controllo == "solo-titoli"
    con_flag = aggiorna_fonti_con_controllo(fonti, esiti, True, adesso)
    assert con_flag[0].attivo is True
    assert con_flag[1].attivo is False
    assert con_flag[2].attivo is True
