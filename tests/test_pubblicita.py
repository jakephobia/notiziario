from __future__ import annotations

from helpers import crea_articolo, crea_cluster

from notiziario.copione import prepara_materiale
from notiziario.selezione import NotiziaSelezionata


def test_prepara_materiale_rimuove_pubblicita_dal_sommario():
    sommario = (
        "Contenuto sponsorizzato: acquista ora il nuovo prodotto con lo "
        "sconto del 30 per cento. "
        "Il parlamento ha approvato la legge sul bilancio."
    )
    articolo = crea_articolo("Titolo notizia", sommario=sommario)
    selezione = NotiziaSelezionata(crea_cluster([articolo]), True, 1, 100)
    materiale = prepara_materiale([selezione])
    voce = materiale[0]["articoli"][0]
    for campo in (voce["testo"], voce["sommario"]):
        assert "sponsorizzato" not in campo.casefold()
        assert "acquista ora" not in campo.casefold()
        assert "sconto del" not in campo.casefold()
        assert "parlamento ha approvato" in campo


def test_prepara_materiale_rimuove_pubblicita_dal_testo_tradotto():
    articolo = crea_articolo("Titolo notizia")
    selezione = NotiziaSelezionata(crea_cluster([articolo]), True, 1, 100)
    selezione.testo_tradotto = (
        "Contenuto sponsorizzato: acquista ora con il codice sconto. "
        "Il governo ha approvato la manovra."
    )
    materiale = prepara_materiale([selezione])
    voce = materiale[0]["articoli"][0]
    for campo in (voce["testo"], voce["sommario"]):
        assert "sponsorizzato" not in campo.casefold()
        assert "acquista ora" not in campo.casefold()
        assert "governo ha approvato" in campo
