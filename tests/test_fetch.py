from __future__ import annotations

import logging
from datetime import timedelta
from email.utils import format_datetime

from notiziario import fetch
from notiziario.config import Fonte
from notiziario.fetch import FetchError, fetch_all, fetch_fonte, normalizza_url


LOGGER = logging.getLogger("test-notiziario")


def _rss(adesso) -> bytes:
    def data(ore_fa: float) -> str:
        return format_datetime(adesso - timedelta(hours=ore_fa))

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Feed di prova</title>
    <link>https://esempio.test/</link>
    <description>Prova</description>
    <item>
      <title>Notizia valida sul governo</title>
      <link>https://esempio.test/articolo?utm_source=newsletter</link>
      <description><![CDATA[<p>Il governo ha approvato il piano. <b>Leggi tutto</b></p>]]></description>
      <pubDate>{data(1)}</pubDate>
    </item>
    <item>
      <title>Notizia troppo vecchia</title>
      <link>https://esempio.test/vecchia</link>
      <description>Vecchia notizia.</description>
      <pubDate>{data(48)}</pubDate>
    </item>
    <item>
      <title>Notizia senza data</title>
      <link>https://esempio.test/senza-data</link>
      <description>Nessuna data.</description>
    </item>
    <item>
      <title>Duplicato dello stesso link</title>
      <link>https://esempio.test/articolo</link>
      <description>Duplicato.</description>
      <pubDate>{data(1.5)}</pubDate>
    </item>
  </channel>
</rss>
""".encode("utf-8")
    return xml


def test_normalizza_url_toglie_tracciamento():
    assert (
        normalizza_url("https://Esempio.test/a/?utm_source=x&fbclid=y&id=3#frag")
        == "https://esempio.test/a?id=3"
    )
    assert (
        normalizza_url("https://www.repubblica.it/a/?rss")
        == "https://www.repubblica.it/a"
    )


def test_parse_feed_filtra_date_e_duplicati(adesso):
    contenuto = _rss(adesso)
    articoli, senza_data, fuori, totale = fetch._parse_feed(
        contenuto,
        Fonte("ANSA", "https://esempio.test/rss", "italia"),
        adesso,
        24,
        LOGGER,
    )
    assert totale == 4
    assert len(articoli) == 1
    assert senza_data == 1
    assert fuori == 1
    assert articoli[0].titolo == "Notizia valida sul governo"
    assert "Leggi tutto" not in articoli[0].sommario
    assert "<" not in articoli[0].sommario
    assert articoli[0].categoria == "italia"


def test_fetch_fonte_ok_con_scarica_finta(monkeypatch, adesso):
    monkeypatch.setattr(fetch, "_scarica", lambda *a, **k: _rss(adesso))
    articoli, esito = fetch_fonte(
        Fonte("ANSA", "https://esempio.test/rss", "italia"),
        24,
        15,
        2,
        adesso=adesso,
        logger=LOGGER,
    )
    assert esito.stato == "ok"
    assert esito.articoli == 1
    assert len(articoli) == 1


def test_url_non_valido_non_blocca(adesso):
    articoli, esito = fetch_fonte(
        Fonte("Rotta", "non-un-url", "italia"),
        24,
        15,
        0,
        adesso=adesso,
        logger=LOGGER,
    )
    assert articoli == []
    assert esito.stato == "ko"
    assert "errore" in (esito.errore or "").lower()


def test_una_fonte_rotta_non_ferma_le_altre(monkeypatch, adesso):
    def scarica(url, timeout, retry, session=None):
        if "rotta" in url:
            raise FetchError("HTTP 500")
        return _rss(adesso)

    monkeypatch.setattr(fetch, "_scarica", scarica)
    fonti = [
        Fonte("Rotta", "https://rotta.test/rss", "italia"),
        Fonte("Buona", "https://buona.test/rss", "italia"),
    ]
    risultato = fetch_all(
        fonti,
        ore=24,
        timeout=15,
        retry=1,
        max_workers=2,
        logger=LOGGER,
        adesso=adesso,
    )
    assert risultato.ko == 1
    assert risultato.ok == 1
    assert len(risultato.articoli) == 1
    assert any(e.errore == "HTTP 500" for e in risultato.esiti if e.stato == "ko")


def test_usa_content_rss_se_molto_piu_ricco(adesso):
    contenuto_lungo = " ".join(["Dettaglio dal feed."] * 60)
    xml = f"""<?xml version="1.0"?><rss version="2.0"><channel>
    <title>Content ricco</title><link>https://esempio.test/</link><description>x</description>
    <item><title>Notizia con content</title><link>https://esempio.test/content</link>
    <description>Breve.</description>
    <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/"><![CDATA[<p>{contenuto_lungo}</p>]]></content:encoded>
    <pubDate>{format_datetime(adesso - timedelta(hours=1))}</pubDate>
    </item></channel></rss>"""
    articoli, _, _, _ = fetch._parse_feed(
        xml.encode("utf-8"),
        Fonte("Test", "https://esempio.test/rss", "italia"),
        adesso,
        24,
        LOGGER,
    )
    assert len(articoli) == 1
    assert "Dettaglio dal feed" in articoli[0].sommario
    assert len(articoli[0].sommario) > 100


def test_feed_senza_date_e_ko(monkeypatch, adesso):
    contenuto = b"""<?xml version="1.0"?><rss version="2.0"><channel>
    <title>Senza date</title><link>https://esempio.test/</link><description>x</description>
    <item><title>Notizia</title><link>https://esempio.test/a</link>
    <description>Testo</description></item>
    </channel></rss>"""
    monkeypatch.setattr(fetch, "_scarica", lambda *a, **k: contenuto)
    articoli, esito = fetch_fonte(
        Fonte("SenzaData", "https://esempio.test/rss", "italia"),
        24,
        15,
        0,
        adesso=adesso,
        logger=LOGGER,
    )
    assert articoli == []
    assert esito.stato == "ko"
    assert "senza data" in (esito.errore or "").lower()


def _rss_senza_date(quanti: int, extra: str = "") -> bytes:
    items = []
    for indice in range(quanti):
        items.append(
            f"<item><title>Notizia senza data {indice}</title>"
            f"<link>https://esempio.test/senza-data/{indice}</link>"
            "<description>Un testo utile per il feed senza date.</description></item>"
        )
    if extra:
        items.append(extra)
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        '<title>Senza date</title><link>https://esempio.test/</link>'
        "<description>x</description>" + "".join(items) + "</channel></rss>"
    ).encode("utf-8")


def test_cold_start_solo_primi_cinque(tmp_path):
    from notiziario.visti import Visti

    visti = Visti(tmp_path / "visti.json", adesso=__import__("datetime").datetime(2026, 11, 22, 12, 0, tzinfo=__import__("datetime").timezone.utc))
    articoli, senza, fuori, totale = fetch._parse_feed(
        _rss_senza_date(7),
        Fonte("SenzaData", "https://esempio.test/rss", "italia"),
        __import__("datetime").datetime(2026, 11, 22, 12, 0, tzinfo=__import__("datetime").timezone.utc),
        24,
        LOGGER,
        visti=visti,
    )
    assert totale == 7
    assert len(articoli) == 5
    assert all(a.data_stimata for a in articoli)
    assert all(a.prima_vista is not None for a in articoli)
    assert visti.ha_visti_feed("SenzaData")
    visti.salva()

    # I due item oltre i primi 5 vengono recuperati al passaggio successivo.
    articoli2, _, _, _ = fetch._parse_feed(
        _rss_senza_date(7),
        Fonte("SenzaData", "https://esempio.test/rss", "italia"),
        __import__("datetime").datetime(2026, 11, 22, 12, 0, tzinfo=__import__("datetime").timezone.utc),
        24,
        LOGGER,
        visti=visti,
    )
    assert len(articoli2) == 2
    import pytest
    with pytest.raises(FetchError):
        fetch._parse_feed(
            _rss_senza_date(7),
            Fonte("SenzaData", "https://esempio.test/rss", "italia"),
            __import__("datetime").datetime(2026, 11, 22, 12, 0, tzinfo=__import__("datetime").timezone.utc),
            24,
            LOGGER,
            visti=visti,
        )


def test_feed_senza_novita_e_ok_senza_novita(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from notiziario.visti import Visti

    adesso = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    visti = Visti(tmp_path / "visti.json", adesso=adesso)
    fonte = Fonte("SenzaData", "https://esempio.test/rss", "italia")
    articoli, _, _, _ = fetch._parse_feed(
        _rss_senza_date(5), fonte, adesso, 24, LOGGER, visti=visti
    )
    assert len(articoli) == 5
    monkeypatch.setattr(fetch, "_scarica", lambda *a, **k: _rss_senza_date(5))
    articoli2, esito = fetch.fetch_fonte(
        fonte,
        24,
        15,
        0,
        adesso=adesso,
        logger=LOGGER,
        visti=visti,
    )
    assert articoli2 == []
    assert esito.stato == "ok-senza-novita"
    assert "novità" in (esito.errore or "").lower() or "novita" in (esito.errore or "").lower()


def test_nuovo_articolo_senza_data_entra(tmp_path):
    from datetime import datetime, timezone
    from notiziario.visti import Visti

    adesso = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    percorso = tmp_path / "visti.json"
    visti = Visti(percorso, adesso=adesso)
    fonte = Fonte("SenzaData", "https://esempio.test/rss", "italia")
    articoli, _, _, _ = fetch._parse_feed(
        _rss_senza_date(5), fonte, adesso, 24, LOGGER, visti=visti
    )
    assert len(articoli) == 5
    visti.salva()

    extra = (
        "<item><title>Notizia nuova</title>"
        "<link>https://esempio.test/senza-data/nuova</link>"
        "<description>Questa è nuova.</description></item>"
    )
    articoli2, _, _, _ = fetch._parse_feed(
        _rss_senza_date(5, extra), fonte, adesso, 24, LOGGER, visti=visti
    )
    assert len(articoli2) == 1
    assert articoli2[0].titolo == "Notizia nuova"


def test_data_futura_viene_normalizzata(adesso):
    futuro = format_datetime(adesso + timedelta(days=2))
    xml = f"""<?xml version="1.0"?><rss version="2.0"><channel>
    <title>Futuro</title><link>https://esempio.test/</link><description>x</description>
    <item><title>Notizia dal futuro</title><link>https://esempio.test/futuro</link>
    <description>Testo.</description><pubDate>{futuro}</pubDate></item>
    </channel></rss>""".encode("utf-8")
    articoli, _, _, _ = fetch._parse_feed(
        xml, Fonte("Futuro", "https://esempio.test/rss", "italia"), adesso, 24, LOGGER
    )
    assert len(articoli) == 1
    assert articoli[0].data_stimata is True
    assert articoli[0].pubblicato <= adesso + timedelta(seconds=1)


def test_pruning_visti_60_giorni(tmp_path):
    import json
    from datetime import datetime, timezone
    from notiziario.visti import Visti

    percorso = tmp_path / "visti.json"
    percorso.write_text(
        json.dumps(
            {
                "visti": {
                    "url:vecchio": {
                        "first_seen": "2026-01-01T10:00:00+01:00",
                        "fonte": "Vecchia",
                        "titolo": "Vecchia",
                    },
                    "url:recente": {
                        "first_seen": "2026-11-21T10:00:00+01:00",
                        "fonte": "Recente",
                        "titolo": "Recente",
                    },
                },
                "feed_last_seen": {"Vecchia": "2026-01-01T10:00:00+01:00"},
            }
        ),
        encoding="utf-8",
    )
    visti = Visti(
        percorso,
        giorni_pruning=60,
        adesso=datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert "url:vecchio" not in visti.visti
    assert "url:recente" in visti.visti
    assert visti.ultimo_first_seen_feed("Vecchia") is not None


def test_visti_separa_feed_con_lo_stesso_nome(tmp_path):
    from datetime import datetime, timezone
    from notiziario.visti import Visti

    visti = Visti(
        tmp_path / "visti.json",
        adesso=datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc),
    )
    visti.registra(
        "url:a",
        "ANSA",
        "Titolo A",
        feed_url="https://ansa.test/feed-a.xml",
    )
    assert visti.ha_visti_feed("https://ansa.test/feed-a.xml")
    assert not visti.ha_visti_feed("https://ansa.test/feed-b.xml")
    assert visti.ultimo_first_seen_feed("ANSA") is not None


def test_first_seen_europe_rome(tmp_path):
    from datetime import datetime, timezone
    from notiziario.visti import Visti

    visti = Visti(
        tmp_path / "visti.json",
        adesso=datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc),
    )
    quando = visti.registra("url:x", "Fonte", "Titolo")
    assert quando.isoformat().endswith("+01:00")
    assert quando.hour == 13


def test_scarica_rifiuta_feed_oltre_10mb(monkeypatch):
    from notiziario.sicurezza import UrlRifiutato

    def troppo_grande(*args, **kwargs):
        raise UrlRifiutato("file troppo grande")

    monkeypatch.setattr(fetch, "fetch_con_limite", troppo_grande)
    with __import__("pytest").raises(FetchError):
        fetch._scarica("https://esempio.test/feed", timeout=15, retry=0)


def test_risultato_fetch_conta_senza_novita_come_ok():
    from notiziario.fetch import EsitoFeed, RisultatoFetch

    risultato = RisultatoFetch(
        articoli=[],
        esiti=[
            EsitoFeed(
                fonte="SenzaData",
                url="https://esempio.test/rss",
                categoria="italia",
                stato="ok-senza-novita",
            )
        ],
    )
    assert risultato.ok == 1
    assert risultato.ko == 0
    assert risultato.senza_novita == 1
