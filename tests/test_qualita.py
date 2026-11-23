from __future__ import annotations

from notiziario.qualita import (
    ESIGENZE,
    EsitoCompletezza,
    frase_per_esigenza,
    istruzioni_retry,
    verifica_completezza,
)


MATERIALE_COMPLETO = (
    "Il 20 novembre 2026 il governo ha approvato a Roma la riforma della scuola. "
    "La riforma potrebbe aumentare i costi per le famiglie."
)
TESTO_INCOMPLETO = "Il governo ha approvato la riforma della scuola."


def test_esigenze_attese():
    assert ESIGENZE == ("cosa", "chi", "quando", "dove", "perche", "conseguenze")


def test_materiale_completo_testo_incompleto_individua_mancanti():
    esito = verifica_completezza(
        TESTO_INCOMPLETO,
        MATERIALE_COMPLETO,
        "Il governo approva la riforma",
        posizione=3,
    )
    assert isinstance(esito, EsitoCompletezza)
    assert esito.posizione == 3
    assert esito.titolo == "Il governo approva la riforma"
    assert esito.mancanti == ["quando", "dove", "conseguenze"]
    assert "cosa" in esito.applicabili
    assert "chi" in esito.applicabili
    assert "perche" not in esito.applicabili


def test_materiale_con_causa_segnala_perche():
    materiale = (
        "Il 20 novembre 2026 il governo ha approvato a Roma la riforma della "
        "scuola per ridurre le disuguaglianze. La riforma potrebbe aumentare "
        "i costi per le famiglie."
    )
    esito = verifica_completezza(
        "Il governo ha approvato la riforma della scuola.",
        materiale,
        "Riforma scuola",
    )
    assert esito.mancanti == ["quando", "dove", "perche", "conseguenze"]


def test_testo_completo_non_ha_mancanze():
    testo = (
        "Il 20 novembre 2026 il governo ha approvato a Roma la riforma della "
        "scuola. La misura potrebbe aumentare i costi per le famiglie."
    )
    esito = verifica_completezza(testo, MATERIALE_COMPLETO)
    assert esito.mancanti == []


def test_materiale_povero_non_rende_applicabili_data_luogo_causa_effetti():
    materiale = "Il consiglio dei ministri ha esaminato il testo della riforma."
    esito = verifica_completezza(materiale, materiale)
    assert esito.applicabili == ["cosa", "chi"]
    assert "quando" not in esito.applicabili
    assert "dove" not in esito.applicabili
    assert "perche" not in esito.applicabili
    assert "conseguenze" not in esito.applicabili
    assert esito.mancanti == []


def test_frase_per_esigenza_copre_quando_senza_confondere_pubblicita_informativa():
    materiale = (
        "La pubblicità online è cresciuta del 5 per cento nel 2026. "
        "Il mercato vale tre miliardi di euro."
    )
    frase = frase_per_esigenza(materiale, "quando")
    assert frase is not None
    assert "2026" in frase
    assert "pubblicità" in frase


def test_frase_per_esigenza_non_ripete_una_frase_gia_presente():
    assert frase_per_esigenza(
        MATERIALE_COMPLETO, "quando", MATERIALE_COMPLETO
    ) is None


def test_frase_per_esigenza_restituisce_una_frase_del_materiale():
    frase = frase_per_esigenza(MATERIALE_COMPLETO, "conseguenze", TESTO_INCOMPLETO)
    assert frase is not None
    assert "potrebbe aumentare" in frase
    assert frase.endswith(".")


def test_istruzioni_retry_riassume_le_mancanze():
    esiti = [
        EsitoCompletezza(
            posizione=2,
            titolo="Riforma scuola",
            mancanti=["quando", "dove"],
            applicabili=["cosa", "chi", "quando", "dove"],
        ),
        EsitoCompletezza(
            posizione=4,
            titolo="",
            mancanti=[],
            applicabili=["cosa"],
        ),
    ]
    messaggio = istruzioni_retry(esiti)
    assert "posizione 2" in messaggio
    assert "Riforma scuola" in messaggio
    assert "quando" in messaggio
    assert "dove" in messaggio
    assert "posizione 4" not in messaggio
    assert not istruzioni_retry([esiti[1]])
