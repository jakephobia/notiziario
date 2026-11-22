from __future__ import annotations

from datetime import timedelta

from helpers import crea_articolo
from notiziario.clustering import clusterizza
from notiziario.fetch import Article


def test_stesso_evento_fonti_diverse():
    articoli = [
        crea_articolo(
            "Cop31, nuova bozza sul clima",
            fonte="ANSA",
            categoria="mondo",
            ore_fa=1,
        ),
        crea_articolo(
            "Cop31: la Ue respinge la nuova bozza sul clima",
            fonte="Repubblica",
            categoria="mondo",
            ore_fa=2,
        ),
        crea_articolo(
            "Cop31, la Ue si oppone alla bozza sul clima",
            fonte="Il Post",
            categoria="mondo",
            ore_fa=3,
        ),
    ]
    clusters = clusterizza(articoli, soglia=0.58)
    assert len(clusters) == 1
    assert clusters[0].numero_fonti == 3
    assert clusters[0].fonti == ["ANSA", "Il Post", "Repubblica"]
    assert clusters[0].categoria == "mondo"


def test_stessa_fonte_conta_una_volta():
    articoli = [
        crea_articolo(
            "Meloni incontra Trump alla Casa Bianca",
            fonte="ANSA",
            categoria="mondo",
            ore_fa=1,
        ),
        crea_articolo(
            "Meloni e Trump, incontro alla Casa Bianca",
            fonte="ANSA",
            categoria="mondo",
            ore_fa=2,
        ),
    ]
    clusters = clusterizza(articoli, soglia=0.58)
    assert len(clusters) == 1
    assert clusters[0].numero_fonti == 1
    assert clusters[0].fonti == ["ANSA"]
    assert not clusters[0].multi_fonte


def test_notizie_diverse_restano_separate():
    articoli = [
        crea_articolo("Juve batte il Venezia 2-0", fonte="ANSA", categoria="sport"),
        crea_articolo(
            "Nuova bozza Cop31 sul clima", fonte="Repubblica", categoria="mondo"
        ),
    ]
    clusters = clusterizza(articoli, soglia=0.58)
    assert len(clusters) == 2


def test_ordinamento_per_fonti_poi_freschezza():
    articoli = [
        crea_articolo("Cop31 nuova bozza sul clima", fonte="ANSA", ore_fa=10),
        crea_articolo("Cop31 nuova bozza sul clima", fonte="Repubblica", ore_fa=11),
        crea_articolo("Cop31 nuova bozza sul clima", fonte="Il Post", ore_fa=12),
        crea_articolo("Manovra approvata dal governo", fonte="ANSA", ore_fa=1),
        crea_articolo("Manovra approvata dal governo", fonte="Repubblica", ore_fa=2),
        crea_articolo("Juve batte il Venezia", fonte="ANSA", ore_fa=0.1),
    ]
    clusters = clusterizza(articoli, soglia=0.58)
    assert clusters[0].numero_fonti == 3
    assert clusters[1].numero_fonti == 2
    assert clusters[2].numero_fonti == 1


def test_titoli_vuoti_non_si_fondono():
    articoli = [
        crea_articolo("", fonte="ANSA", ore_fa=1),
        crea_articolo("", fonte="Repubblica", ore_fa=2),
    ]
    clusters = clusterizza(articoli, soglia=0.58)
    assert len(clusters) == 2


def test_nessun_articolo():
    assert clusterizza([]) == []

def test_non_unisce_articoli_di_categorie_diverse():
    articoli = [
        crea_articolo(
            "Festa a Borgo Panigale per Marquez e Ducati",
            fonte="ANSA",
            categoria="sport",
            ore_fa=1,
        ),
        crea_articolo(
            "Festa a Borgo Panigale per Marquez e Ducati",
            fonte="Repubblica",
            categoria="italia",
            ore_fa=2,
        ),
    ]
    clusters = clusterizza(articoli, soglia=0.5)
    assert len(clusters) == 2
    assert {c.categoria for c in clusters} == {"sport", "italia"}
