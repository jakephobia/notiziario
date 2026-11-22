from __future__ import annotations

from main import (
    _deve_salvare_visti,
    _indici_transizioni,
    _prepara_blocchi_tts,
    _solo_senza_novita,
)


def test_state_salvato_con_audio_e_senza_audio():
    assert _deve_salvare_visti(False, False, {"durata": 1}) is True
    assert _deve_salvare_visti(False, True, None) is True


def test_dry_run_non_salva_state():
    assert _deve_salvare_visti(True, False, None) is False
    assert _deve_salvare_visti(True, True, None) is False

def test_no_news_gestisce_anche_feed_ko():
    from notiziario.fetch import EsitoFeed, RisultatoFetch

    risultato = RisultatoFetch(
        articoli=[],
        esiti=[
            EsitoFeed(
                fonte="SenzaData",
                url="https://a.test/rss",
                categoria="italia",
                stato="ok-senza-novita",
            ),
            EsitoFeed(
                fonte="Rotta",
                url="https://b.test/rss",
                categoria="italia",
                stato="ko",
                errore="nessun articolo valido",
            ),
        ],
    )
    assert _solo_senza_novita(risultato) is True

def test_transizioni_non_dopo_ultima_notizia():
    assert _indici_transizioni(4) == [0, 1]
    assert _indici_transizioni(3) == [0]
    assert _indici_transizioni(2) == []
    assert _indici_transizioni(1) == []

def test_prepara_blocchi_tts_usa_confini_strutturati():
    from notiziario.config import carica_impostazioni

    copione = {
        "incipit": "Ciao.",
        "outro": "A domani.",
        "notizie": [
            {"paragrafi": ["A1.", "A2.", "A3."]},
            {"paragrafi": ["B1.", "B2."]},
        ],
    }
    sezioni, indici = _prepara_blocchi_tts(copione, carica_impostazioni())
    assert len(sezioni) == 7
    assert indici == [0, 3]

def test_prepara_blocchi_tts_non_indovina_confini_incompleti():
    from notiziario.config import carica_impostazioni

    corpo = "\n\n".join(["Paragrafo completo del corpo."] * 20)
    copione = {
        "testo": corpo,
        "notizie": [{"paragrafi": ["Riassunto breve."]}],
    }
    sezioni, indici = _prepara_blocchi_tts(copione, carica_impostazioni())
    assert indici == []
    assert len(sezioni) >= 2
