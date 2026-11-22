from __future__ import annotations

import json
from datetime import datetime

import pytest

from helpers import crea_articolo, crea_cluster
from notiziario import traduzione as modulo_traduzione
from notiziario.config import carica_impostazioni
from notiziario.copione import _contiene_stopword_inglese, genera_copione, prepara_materiale
from notiziario.selezione import NotiziaSelezionata
from notiziario.tempo import ROMA
from notiziario.traduzione import TraduzioneError, prepara_selezioni_italiane


def selezione(ordine, titolo, sommario, categoria="mondo"):
    cluster = crea_cluster([crea_articolo(titolo, sommario=sommario, categoria=categoria)])
    return NotiziaSelezionata(
        cluster=cluster,
        copertina=ordine <= 2,
        ordine=ordine,
        parole_target=100,
        blocco="copertina" if ordine <= 2 else "secondaria",
    )


def inglesi():
    return [
        selezione(1, "Australian politics live", "The government said the election was close."),
        selezione(2, "Fire breaks out at popular tourist site", "Police and fire crews were at the scene."),
        selezione(3, "Jensen Huang's reported affair", "The company has not commented on the report."),
    ]


def italiane():
    return [
        selezione(4, "Nave russa colpita a Bengasi", "La nave è stata colpita nel porto."),
        selezione(5, "Grillo se il giudice dice", "Il tribunale ha ascoltato le parti."),
        selezione(6, "La manovra arriva in Parlamento", "Il governo ha presentato il testo."),
    ]


def test_traduzione_disponibile_rende_italiane_le_notizie(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    risposta = {
        "traduzioni": [
            {"id": 1, "titolo_it": "Politica australiana", "testo_it": "Il governo ha parlato delle elezioni."},
            {"id": 2, "titolo_it": "Incendio nel sito turistico", "testo_it": "I soccorritori sono arrivati sul posto."},
            {"id": 3, "titolo_it": "Presunto caso Huang", "testo_it": "L'azienda non ha commentato la notizia."},
        ]
    }
    chiamate = {"n": 0}
    monkeypatch.setattr(
        modulo_traduzione,
        "_chiama_gemini",
        lambda *a, **k: chiamate.__setitem__("n", chiamate["n"] + 1) or json.dumps(risposta),
    )
    selezioni = prepara_selezioni_italiane(inglesi(), carica_impostazioni())[0]
    assert len(selezioni) == 3
    assert chiamate["n"] == 1
    assert all(s.titolo_tradotto and s.testo_tradotto for s in selezioni)
    assert not any(_contiene_stopword_inglese(s.titolo + " " + s.testo_tradotto) for s in selezioni)
    materiale = prepara_materiale(selezioni)
    assert materiale[0]["articoli"][0]["testo"] == "Il governo ha parlato delle elezioni."


def test_senza_chiave_filtra_e_tiene_solo_italiane(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    tutte = inglesi() + italiane()
    risultato, avvisi = prepara_selezioni_italiane(tutte, carica_impostazioni())
    assert len(risultato) == 3
    assert all(not _contiene_stopword_inglese(s.titolo) for s in risultato)
    assert any("GEMINI_API_KEY" in a for a in avvisi)


def test_meno_di_tre_italiane_senza_traduzione_e_errore(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(TraduzioneError):
        prepara_selezioni_italiane(inglesi()[:2] + italiane()[:1], carica_impostazioni())


def test_traduzione_fallita_non_publica_inglese(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")

    def errore(*args, **kwargs):
        raise RuntimeError("quota")

    monkeypatch.setattr(modulo_traduzione, "_chiama_gemini", errore)
    with pytest.raises(TraduzioneError):
        prepara_selezioni_italiane(inglesi(), carica_impostazioni())


def test_fallback_usa_testi_tradotti_e_resta_italiano(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    risposta = {
        "traduzioni": [
            {"id": 1, "titolo_it": "Politica australiana", "testo_it": "Il governo australiano ha parlato delle elezioni."},
            {"id": 2, "titolo_it": "Incendio nel sito turistico", "testo_it": "I soccorritori sono arrivati sul posto."},
            {"id": 3, "titolo_it": "Presunto caso Huang", "testo_it": "L'azienda non ha commentato la notizia."},
        ]
    }
    monkeypatch.setattr(modulo_traduzione, "_chiama_gemini", lambda *a, **k: json.dumps(risposta))
    selezioni = prepara_selezioni_italiane(inglesi(), carica_impostazioni())[0]
    copione = genera_copione(
        selezioni,
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
        usa_llm=False,
    )
    assert copione["modalita"] == "fallback"
    assert not _contiene_stopword_inglese(copione["testo"])
    assert not _contiene_stopword_inglese(copione["descrizione_breve"])