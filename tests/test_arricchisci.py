from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from helpers import crea_articolo, crea_cluster
from notiziario import arricchisci
from notiziario.arricchisci import (
    _rileva_paywall,
    arricchisci_articolo,
    arricchisci_selezioni,
    estrai_da_html,
    leggi_cache,
    robots_consenti,
    scrivi_cache,
)
from notiziario.config import carica_impostazioni
from notiziario.selezione import NotiziaSelezionata
from notiziario.sicurezza import FetchHttpError, UrlRifiutato, valida_url_pubblica


HTML_LUNGO = """<html><body><article>
<h1>Titolo della notizia</h1>
<p>Questo è il primo paragrafo dell'articolo, con abbastanza testo per superare
la soglia minima e verificare l'estrazione del contenuto completo.</p>
<h2>Sottotitolo del primo paragrafo</h2>
<p>Il secondo paragrafo aggiunge altri dettagli utili e resta nel testo finale.</p>
<h3>Altro titolo di paragrafo</h3>
<p>Il terzo paragrafo conclude la ricostruzione dei fatti con altre informazioni.</p>
</article></body></html>"""

HTML_PAYWALL_JSONLD = (
    '<html><head><script type="application/ld+json">'
    '{"@type": "NewsArticle", "isAccessibleForFree": "False"}'
    "</script></head><body>"
    "<p>Un testo qualsiasi senza altri segnali di blocco.</p>"
    "</body></html>"
)

HTML_PAYWALL_DIV = (
    '<html><body><div class="paywall"><p>Testo nascosto.</p></div>'
    "<p>Un altro testo qualsiasi.</p></body></html>"
)


def impostazioni_tmp(tmp_path):
    impostazioni = copy.deepcopy(carica_impostazioni())
    impostazioni["arricchimento"]["cache_dir"] = str(tmp_path / "cache")
    impostazioni["arricchimento"]["min_caratteri_estratto"] = 100
    return impostazioni


def test_estrazione_html_lungo():
    testo, parziale, motivo = estrai_da_html(HTML_LUNGO, "Titolo", 100)
    assert testo and "primo paragrafo" in testo
    assert parziale is False
    assert motivo == "ok"
    assert "Sottotitolo del primo paragrafo" not in testo
    assert "Altro titolo di paragrafo" not in testo


def test_estrazione_bs4_ignora_titoli_paragrafo(monkeypatch):
    monkeypatch.setattr(arricchisci, "_HA_TRAFILATURA", False)
    testo, parziale, motivo = estrai_da_html(HTML_LUNGO, "Titolo", 100)
    assert testo
    assert motivo == "ok"
    assert "primo paragrafo" in testo
    assert "Sottotitolo del primo paragrafo" not in testo
    assert "Altro titolo di paragrafo" not in testo


def test_estrazione_bs4_mantiene_citazioni_senza_duplicarle(monkeypatch):
    html = (
        "<article>"
        "<p>Primo paragrafo dell'articolo con testo sufficientemente lungo per la soglia minima.</p>"
        "<blockquote><p>Citazione annidata che deve comparire una sola volta nel testo.</p></blockquote>"
        "<blockquote>Citazione diretta che deve restare nel testo finale.</blockquote>"
        "<p>Secondo paragrafo dell'articolo con altri dettagli utili al lettore.</p>"
        "</article>"
    )
    monkeypatch.setattr(arricchisci, "_HA_TRAFILATURA", False)
    testo, parziale, motivo = estrai_da_html(html, "Titolo", 50)
    assert testo and motivo == "ok"
    assert testo.count("Citazione annidata") == 1
    assert testo.count("Citazione diretta") == 1
    assert "Primo paragrafo" in testo
    assert "Secondo paragrafo" in testo


def test_estrazione_html_ignora_blocco_pubblicitario(monkeypatch):
    paragrafo = (
        "Il consiglio dei ministri ha approvato la manovra con nuove misure "
        "per la scuola e la sanità. "
    ) * 4
    html = (
        "<html><body><article>"
        '<div class="ad-container"><p>Messaggio del nostro partner '
        "commerciale con un invito speciale per te.</p></div>"
        f"<p>{paragrafo}</p>"
        "</article></body></html>"
    )
    monkeypatch.setattr(arricchisci, "_HA_TRAFILATURA", False)
    testo, parziale, motivo = estrai_da_html(html, "Titolo", 100)
    assert testo
    assert motivo == "ok"
    assert "Messaggio del nostro partner" not in testo
    assert "consiglio dei ministri" in testo


def test_paywall_breve_fallback():
    html = "<html><body><p>Abbonati per leggere l'articolo completo</p></body></html>"
    testo, parziale, motivo = estrai_da_html(html, "Titolo", 100)
    assert testo is None
    assert parziale is True
    assert motivo in {"paywall", "estratto troppo corto"}


@pytest.mark.parametrize(
    ("html", "link"),
    [
        (HTML_PAYWALL_JSONLD, "https://paywall.test/jsonld"),
        (HTML_PAYWALL_DIV, "https://paywall.test/div"),
    ],
    ids=["jsonld", "div"],
)
def test_arricchisci_paywall_usa_sommario_e_cache(
    tmp_path, monkeypatch, html, link
):
    impostazioni = impostazioni_tmp(tmp_path)
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    articolo = crea_articolo(
        "Titolo con paywall",
        link=link,
        sommario="Il sommario RSS racconta i fatti principali.",
    )
    monkeypatch.setattr(arricchisci, "robots_consenti", lambda *a, **k: True)
    monkeypatch.setattr(arricchisci, "valida_url_pubblica", lambda *a, **k: None)
    monkeypatch.setattr(
        arricchisci,
        "fetch_con_limite",
        lambda *a, **k: (html.encode("utf-8"), link, 200),
    )

    assert arricchisci_articolo(articolo, impostazioni, adesso=now) is False
    assert articolo.paywall is True
    assert articolo.contenuto == ""
    assert articolo.contenuto_parziale is True
    assert articolo.arricchito is True

    cache = leggi_cache(link, impostazioni, now)
    assert cache is not None
    assert cache["paywall"] is True
    assert cache["motivo"] == "paywall"
    assert cache["testo"] is None
    assert cache["parziale"] is True
    assert cache["versione"] == 3


def test_abbonamento_in_frase_normale_non_e_paywall():
    html = (
        "<html><body><article><p>L'abbonamento annuale alla rivista costa "
        "ottanta euro e gli abbonati ricevono anche l'archivio digitale.</p>"
        "</article></body></html>"
    )
    testo = (
        "L'abbonamento annuale alla rivista costa ottanta euro e gli abbonati "
        "ricevono anche l'archivio digitale."
    )
    assert _rileva_paywall(html, testo) is False


def test_frase_paywall_con_apostrofo_tipografico():
    assert (
        _rileva_paywall("", "Per leggere l’articolo completo serve un abbonamento.")
        is True
    )


def test_marcatore_subscription_nel_markup():
    html = (
        '<html><body><div class="subscription-wall">Testo qualsiasi.</div>'
        "</body></html>"
    )
    assert _rileva_paywall(html, "Testo qualsiasi.") is True


def test_cache_paywall_non_ripresenta_il_testo(tmp_path, monkeypatch):
    impostazioni = impostazioni_tmp(tmp_path)
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    link = "https://paywall.test/cache"
    scrivi_cache(
        link,
        impostazioni,
        "Testo riservato che non deve riemergere",
        True,
        "paywall",
        now,
        paywall=True,
    )
    articolo = crea_articolo(
        "Titolo in cache", link=link, sommario="Sommario RSS."
    )

    def fetch_non_atteso(*args, **kwargs):
        raise AssertionError("fetch non atteso")

    monkeypatch.setattr(arricchisci, "fetch_con_limite", fetch_non_atteso)
    assert arricchisci_articolo(articolo, impostazioni, adesso=now) is False
    assert articolo.paywall is True
    assert articolo.contenuto == ""
    assert articolo.contenuto_parziale is True
    assert articolo.arricchito is True


def test_riepilogo_arricchimento_conta_paywall(tmp_path, monkeypatch):
    impostazioni = impostazioni_tmp(tmp_path)
    articolo = crea_articolo(
        "Titolo paywall", link="https://paywall.test/riepilogo"
    )
    selezione = NotiziaSelezionata(crea_cluster([articolo]), True, 1, 100)

    def finto_paywall(articolo, *args, **kwargs):
        articolo.paywall = True
        articolo.contenuto = ""
        articolo.contenuto_parziale = True
        articolo.arricchito = True
        return False

    monkeypatch.setattr(arricchisci, "arricchisci_articolo", finto_paywall)
    riepilogo = arricchisci_selezioni(
        [selezione],
        impostazioni,
        adesso=datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert riepilogo["paywall"] == 1
    assert riepilogo["parziali"] == 1
    assert riepilogo["arricchiti"] == 0


def test_robots_disallow():
    url = "https://robots-vietato-123.test/articolo"
    arricchisci._ROBOTS_CACHE.clear()

    def finto(*args, **kwargs):
        return (b"User-agent: *\nDisallow: /\n", args[0], 200)

    import notiziario.arricchisci as modulo

    original = modulo.fetch_con_limite
    modulo.fetch_con_limite = finto
    try:
        assert robots_consenti(url, carica_impostazioni()) is False
        assert robots_consenti(url, carica_impostazioni()) is False
    finally:
        modulo.fetch_con_limite = original


def test_403_fallback_summary(tmp_path, monkeypatch):
    impostazioni = impostazioni_tmp(tmp_path)
    articolo = crea_articolo(
        "Titolo 403", link="https://403.test/articolo", sommario="Summary originale."
    )

    def errore(*args, **kwargs):
        raise FetchHttpError(403, args[0])

    monkeypatch.setattr(arricchisci, "fetch_con_limite", errore)
    monkeypatch.setattr(arricchisci, "robots_consenti", lambda *a, **k: True)
    assert arricchisci_articolo(articolo, impostazioni) is False
    assert articolo.contenuto is None
    assert articolo.contenuto_parziale is True


def test_ssrf_blocca_loopback_e_file():
    with pytest.raises(UrlRifiutato):
        valida_url_pubblica("http://127.0.0.1/", risolvi=False)
    with pytest.raises(UrlRifiutato):
        valida_url_pubblica("http://[::1]/", risolvi=False)
    with pytest.raises(UrlRifiutato):
        valida_url_pubblica("file:///etc/passwd", risolvi=False)
    with pytest.raises(UrlRifiutato):
        valida_url_pubblica("http://10.0.0.5/", risolvi=False)


def test_cache_ttl(tmp_path):
    impostazioni = impostazioni_tmp(tmp_path)
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    scrivi_cache("https://cache.test/a", impostazioni, "testo", False, "ok", now)
    assert leggi_cache("https://cache.test/a", impostazioni, now) is not None
    vecchio = now - timedelta(hours=25)
    assert leggi_cache("https://cache.test/a", impostazioni, vecchio) is not None
    futuro = now + timedelta(hours=25)
    assert leggi_cache("https://cache.test/a", impostazioni, futuro) is None


def test_cache_vecchia_senza_versione_viene_ignorata(tmp_path):
    impostazioni = impostazioni_tmp(tmp_path)
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    url = "https://cache.test/vecchia"
    percorso = arricchisci._cache_path(url, impostazioni)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(
        json.dumps(
            {
                "url": url,
                "testo": "Sottotitolo vecchio Titolo del paragrafo",
                "parziale": False,
                "motivo": "ok",
                "salvato": now.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    assert leggi_cache(url, impostazioni, now) is None


def test_limiti_arricchimento_per_cluster_e_totale(tmp_path, monkeypatch):
    impostazioni = impostazioni_tmp(tmp_path)
    impostazioni["arricchimento"]["max_articoli"] = 20
    impostazioni["arricchimento"]["max_per_cluster"] = 3
    selezioni = []
    for cluster_indice in range(8):
        articoli = [
            crea_articolo(
                f"Titolo {cluster_indice}-{i}",
                link=f"https://arricchisci.test/{cluster_indice}/{i}",
            )
            for i in range(5)
        ]
        selezioni.append(
            NotiziaSelezionata(
                crea_cluster(articoli),
                copertina=cluster_indice == 0,
                ordine=cluster_indice + 1,
                parole_target=100,
            )
        )

    def finto(articolo, *args, **kwargs):
        articolo.contenuto = "Contenuto completo " * 30
        articolo.arricchito = True
        return True

    monkeypatch.setattr(arricchisci, "arricchisci_articolo", finto)
    riepilogo = arricchisci_selezioni(
        selezioni, impostazioni, adesso=datetime(2026, 11, 22, tzinfo=timezone.utc)
    )
    assert riepilogo["articoli"] == 20
    assert riepilogo["arricchiti"] == 20
    assert riepilogo["caratteri"] > 0

def test_robots_non_raggiungibile_consente_con_avviso(caplog):
    from notiziario import arricchisci as modulo

    arricchisci._ROBOTS_CACHE.clear()

    def errore(*args, **kwargs):
        raise __import__("requests").ConnectionError("no")

    originale = modulo.fetch_con_limite
    modulo.fetch_con_limite = errore
    try:
        assert robots_consenti("https://robots-irraggiungibile.test/a", carica_impostazioni()) is True
        assert any("consento il fetch" in r.message for r in caplog.records)
    finally:
        modulo.fetch_con_limite = originale
