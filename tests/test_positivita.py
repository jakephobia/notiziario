from __future__ import annotations

from helpers import crea_articolo, crea_cluster
from notiziario.config import carica_impostazioni
from notiziario.positivita import (
    buona_notizia_importante,
    filtra_buone_notizie,
    non_positiva,
    titolo_negativo,
)


def candidati():
    dedicate = crea_cluster(
        [
            crea_articolo(
                "Una terapia genica restituisce l'udito a bambini nati sordi",
                fonte="Buone Notizie",
                categoria="buone-notizie",
                sommario="Uno studio clinico mostra un risultato concreto.",
            )
        ]
    )
    generalista = crea_cluster(
        [
            crea_articolo(
                "Uno studio clinico riduce del 40% il rischio di Alzheimer",
                fonte="ANSA",
                categoria="scienza-salute",
                sommario="Ricerca pubblicata su una rivista internazionale.",
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
    locale = crea_cluster(
        [
            crea_articolo(
                "Ragazzi ripuliscono il parco del quartiere",
                fonte="Buone Notizie",
                categoria="buone-notizie",
                sommario="Un gruppo di studenti ha raccolto rifiuti e piantato alberi.",
            )
        ]
    )
    return [dedicate, generalista, negativa, locale]


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
    assert "terapia genica" in esito.notizie[0].titolo
    assert esito.usato_ai is False
    assert esito.scartate_negative >= 1
    assert esito.scartate_poco_rilevanti >= 1


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
    assert any("terapia genica" in t for t in titoli)
    assert any("Alzheimer" in t for t in titoli)
    assert not any("Ragazzi" in t for t in titoli)
    assert not any("Tragedia" in t for t in titoli)


def test_ai_errore_torna_ai_dedicati(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    import notiziario.positivita as modulo

    def errore(*args, **kwargs):
        raise RuntimeError("quota")

    monkeypatch.setattr(modulo, "_chiama_gemini", errore)
    esito = filtra_buone_notizie(
        candidati(),
        ["italia", "scienza-salute", "buone-notizie"],
        carica_impostazioni(),
    )
    assert esito.usato_ai is False
    assert len(esito.notizie) == 1
    assert "terapia genica" in esito.notizie[0].titolo


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


def test_buone_notizie_importanti_approvate():
    titoli = [
        "L'OMS dichiara eradidata la malaria in un paese africano",
        "Una terapia genica restituisce l'udito a bambini nati sordi",
        "La povertà estrema nel mondo scende ai minimi storici",
        "Le rinnovabili superano il carbone nella produzione elettrica europea",
        "Una specie dichiarata estinta viene reintrodotta in natura",
        "Il vaccino contro la malaria raggiunge 10 milioni di bambini",
        "Un paese garantisce l'istruzione primaria gratuita a tutte le bambine",
        "Un filtro low-cost rende potabile l'acqua in una regione colpita dalla siccità",
        "Uno studio clinico riduce del 40% il rischio di Alzheimer",
        "La povertà infantile dimezzata in dieci anni in un paese",
    ]
    for titolo in titoli:
        cluster = crea_cluster(
            [crea_articolo(titolo, fonte="ANSA", categoria="mondo", sommario="Testo.")]
        )
        assert buona_notizia_importante(cluster) is True, titolo


def test_buone_notizie_locali_e_promo_scartate():
    titoli = [
        "Ragazzi ripuliscono il parco del quartiere",
        "Startup assume 100 persone",
        "25 anni di Buone Notizie. Silvio Malvolti, il suo ideatore, si racconta",
        "Nuovo gadget o offerta",
        "Influencer raccoglie fondi",
        "Nuovo centro commerciale",
        "Record di visualizzazioni",
        "Sulla vecchiaia manca consapevolezza",
        "CEO Anthropic in Puglia per la masseria",
    ]
    for titolo in titoli:
        cluster = crea_cluster(
            [
                crea_articolo(
                    titolo,
                    fonte="Buone Notizie",
                    categoria="buone-notizie",
                    sommario="Testo.",
                )
            ]
        )
        assert buona_notizia_importante(cluster) is False, titolo
