from __future__ import annotations

from helpers import crea_articolo, crea_cluster
from notiziario.config import carica_impostazioni
from notiziario.positivita import (
    filtra_buone_notizie,
    non_positiva,
    titolo_negativo,
)


def candidati():
    dedicate = crea_cluster(
        [
            crea_articolo(
                "Ragazzi ripuliscono il parco del quartiere",
                fonte="Buone Notizie",
                categoria="buone-notizie",
                sommario="Un gruppo di studenti ha raccolto rifiuti e piantato alberi.",
            )
        ]
    )
    generalista = crea_cluster(
        [
            crea_articolo(
                "Nuova cura riduce le complicanze",
                fonte="ANSA",
                categoria="scienza-salute",
                sommario="Uno studio mostra risultati incoraggianti.",
            )
        ]
    )
    negativa = crea_cluster(
        [
            crea_articolo(
                "Tragedia sul lavoro: morto un operaio",
                fonte="Buone Notizie",
                categoria="buone-notizie",
                sommario="Indagini in corso.",
            )
        ]
    )
    return [dedicate, generalista, negativa]


def test_titoli_negativi_riconosciuti():
    assert titolo_negativo("Tragedia sul lavoro: morto un operaio")
    assert titolo_negativo("Guerra in Ucraina, nuovi attacchi")
    assert titolo_negativo("Alluvione devasta il paese")
    assert not titolo_negativo("Nuova cura riduce le complicanze")
    assert not titolo_negativo("Ragazzi ripuliscono il parco")


def test_fallback_senza_ai_solo_feed_dedicati(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    esito = filtra_buone_notizie(
        candidati(),
        ["italia", "scienza-salute", "buone-notizie"],
        carica_impostazioni(),
        usa_ai=False,
    )
    assert len(esito.notizie) == 1
    assert esito.notizie[0].categoria == "buone-notizie"
    assert "Ragazzi" in esito.notizie[0].titolo
    assert esito.usato_ai is False
    assert esito.scartate_negative >= 1


def test_ai_puo_aggiungere_generalista_positiva(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    import notiziario.positivita as modulo

    def finta(prompt, system, impostazioni, api_key, logger, **kwargs):
        return '{"positive": [0, 1]}'

    monkeypatch.setattr(modulo, "_chiama_gemini", finta)
    esito = filtra_buone_notizie(
        candidati(),
        ["italia", "scienza-salute", "buone-notizie"],
        carica_impostazioni(),
    )
    assert esito.usato_ai is True
    titoli = [c.titolo for c in esito.notizie]
    assert any("Ragazzi" in t for t in titoli)
    assert any("Nuova cura" in t for t in titoli)
    assert not any("Tragedia" in t for t in titoli)


def test_ai_errore_torna_ai_dedicati(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    import notiziario.positivita as modulo

    def errore(*args, **kwargs):
        raise RuntimeError("quota")

    monkeypatch.setattr(modulo, "_chiama_gemini", errore)
    esito = filtra_buone_notizie(
        candidati(),
        ["italia", "buone-notizie"],
        carica_impostazioni(),
    )
    assert esito.usato_ai is False
    assert len(esito.notizie) == 1
    assert "Ragazzi" in esito.notizie[0].titolo


def test_categoria_inattiva_non_produce_blocco():
    esito = filtra_buone_notizie(
        candidati(), ["italia"], carica_impostazioni(), usa_ai=False
    )
    assert esito.notizie == []
    assert "non attiva" in esito.motivo


def test_senza_candidati_non_rompe(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    esito = filtra_buone_notizie(
        [], ["italia", "buone-notizie"], carica_impostazioni(), usa_ai=False
    )
    assert esito.notizie == []

def test_falsi_positivi_reali_esclusi():
    for titolo in (
        "Sulla vecchiaia manca consapevolezza",
        "CEO Anthropic in Puglia per la masseria",
    ):
        cluster = crea_cluster(
            [
                crea_articolo(
                    titolo,
                    fonte="Repubblica",
                    categoria="cultura",
                    sommario="Testo.",
                )
            ]
        )
        assert non_positiva(cluster) is True
        esito = filtra_buone_notizie(
            [cluster], ["cultura", "buone-notizie"], carica_impostazioni(), usa_ai=False
        )
        assert esito.notizie == []
