from __future__ import annotations

from main import _deve_salvare_visti, _indici_transizioni, _solo_senza_novita


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
