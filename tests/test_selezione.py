from __future__ import annotations

from helpers import crea_articolo, crea_cluster
from notiziario.config import carica_impostazioni
from notiziario.selezione import seleziona


def multi(titolo, fonti, categoria, ore_fa=1):
    return crea_cluster(
        [
            crea_articolo(
                titolo,
                fonte=fonte,
                categoria=categoria,
                ore_fa=ore_fa + indice * 0.1,
            )
            for indice, fonte in enumerate(fonti)
        ]
    )


def test_copertine_rispettano_categorie_attive():
    preset = carica_impostazioni()["preset"]["standard"]
    clusters = [
        multi(
            "Cop31 nuova bozza sul clima",
            ["ANSA", "Repubblica", "Il Post"],
            "ambiente",
            1,
        ),
        multi(
            "Juve batte il Venezia",
            ["ANSA", "Il Post"],
            "sport",
            2,
        ),
        multi(
            "Premio Strega, la dozzina",
            ["ANSA", "Repubblica"],
            "cultura",
            3,
        ),
        crea_cluster([crea_articolo("Notizia Italia", categoria="italia", ore_fa=1)]),
        crea_cluster([crea_articolo("Notizia Mondo", categoria="mondo", ore_fa=2)]),
        crea_cluster([crea_articolo("Notizia Economia", categoria="economia", ore_fa=3)]),
        crea_cluster(
            [crea_articolo("Notizia Tecnologia", categoria="tecnologia", ore_fa=4)]
        ),
        crea_cluster(
            [crea_articolo("Notizia Scienza", categoria="scienza-salute", ore_fa=5)]
        ),
    ]
    attive = [
        "italia",
        "mondo",
        "economia",
        "tecnologia",
        "scienza-salute",
        "cultura",
    ]
    scelte = seleziona(clusters, preset, attive)
    copertine = [s for s in scelte if s.copertina]
    secondarie = [s for s in scelte if not s.copertina]
    assert len(copertine) == 2
    assert {s.categoria for s in copertine} == {"cultura", "italia"}
    assert all(s.categoria in attive for s in scelte)
    assert len(scelte) <= preset["max_notizie"]
    assert len(secondarie) == 4


def test_override_numero_notizie():
    preset = carica_impostazioni()["preset"]["standard"]
    clusters = [
        multi("Prima notizia multi", ["ANSA", "Repubblica"], "italia", 1),
        multi("Seconda notizia multi", ["ANSA", "Il Post"], "mondo", 2),
        crea_cluster([crea_articolo("Terza notizia", categoria="economia")]),
    ]
    scelte = seleziona(clusters, preset, ["italia", "mondo", "economia"], max_notizie=3)
    assert len(scelte) == 3
    assert sum(1 for s in scelte if s.copertina) == 2
    assert sum(1 for s in scelte if not s.copertina) == 1


def test_se_non_ci_sono_multi_completa_con_singoli_recenti():
    preset = carica_impostazioni()["preset"]["svelto"]
    clusters = [
        crea_cluster([crea_articolo("Vecchia", ore_fa=10)]),
        crea_cluster([crea_articolo("Recente", ore_fa=1)]),
        crea_cluster([crea_articolo("Media", ore_fa=5)]),
        crea_cluster([crea_articolo("Altra", ore_fa=2)]),
    ]
    scelte = seleziona(clusters, preset, ["italia"])
    assert scelte[0].copertina is True
    assert scelte[0].titolo == "Recente"
    assert len([s for s in scelte if s.copertina]) == 1
    assert len(scelte) <= preset["max_notizie"]


def test_evita_notizie_quasi_identiche():
    preset = carica_impostazioni()["preset"]["svelto"]
    clusters = [
        crea_cluster([crea_articolo("Juve batte il Venezia", ore_fa=1)]),
        crea_cluster([crea_articolo("Juve batte il Venezia", ore_fa=2)]),
        crea_cluster([crea_articolo("Notizia diversa sul governo", ore_fa=3)]),
    ]
    scelte = seleziona(clusters, preset, ["italia"], max_notizie=3)
    titoli = [s.titolo for s in scelte]
    assert titoli.count("Juve batte il Venezia") == 1


def test_sport_spento_non_entra_in_copertina():
    preset = carica_impostazioni()["preset"]["standard"]
    clusters = [
        multi(
            "Paura per Paredes, sviene in diretta alla festa del Boca",
            ["ANSA", "Repubblica"],
            "sport",
            1,
        ),
        multi("Notizia italiana multi", ["ANSA", "Il Post"], "italia", 2),
        crea_cluster([crea_articolo("Notizia economia", categoria="economia")]),
    ]
    attive = ["italia", "economia", "buone-notizie"]
    scelte = seleziona(clusters, preset, attive)
    assert all(s.categoria != "sport" for s in scelte)
    assert all("Paredes" not in s.titolo for s in scelte)
    assert scelte[0].copertina
    assert scelte[0].categoria == "italia"


def test_buone_notizie_in_chiusura_e_riducono_le_secondarie():
    preset = carica_impostazioni()["preset"]["standard"]
    clusters = [
        multi("Governo approva la manovra", ["ANSA", "Repubblica"], "italia", 1),
        multi("Cop31, nuova bozza sul clima", ["ANSA", "Il Post"], "mondo", 2),
    ]
    titoli = [
        "Borsa di Milano in rialzo",
        "Nuova cura per l'emicrania",
        "Mostra apre a Venezia",
        "Stadio pieno per la finale",
        "Sole e caldo in arrivo",
        "Startup assume cento persone",
        "Treno veloce verso Parigi",
        "Biblioteca apre di sera",
    ]
    for indice, titolo in enumerate(titoli):
        clusters.append(
            crea_cluster(
                [
                    crea_articolo(
                        titolo,
                        categoria="economia" if indice % 2 else "cultura",
                        ore_fa=3 + indice * 0.1,
                    )
                ]
            )
        )
    positive = [
        crea_cluster(
            [
                crea_articolo(
                    "Ragazzi ripuliscono il parco",
                    fonte="Buone Notizie",
                    categoria="buone-notizie",
                    ore_fa=4,
                )
            ]
        ),
        crea_cluster(
            [
                crea_articolo(
                    "Volontari salvano una biblioteca",
                    fonte="Buone Notizie",
                    categoria="buone-notizie",
                    ore_fa=5,
                )
            ]
        ),
    ]
    scelte = seleziona(
        clusters,
        preset,
        ["italia", "mondo", "economia", "cultura", "buone-notizie"],
        buone_notizie=positive,
    )
    assert len(scelte) == preset["max_notizie"] == 10
    assert sum(1 for s in scelte if s.copertina) == 2
    positive_scelte = [s for s in scelte if s.blocco == "buone-notizie"]
    assert len(positive_scelte) == 2
    assert [s.blocco for s in scelte[-2:]] == [
        "buone-notizie",
        "buone-notizie",
    ]
    assert scelte[-1].categoria == "buone-notizie"
    assert sum(1 for s in scelte if s.blocco == "secondaria") == 6


def test_buone_notizie_inattive_non_entrano():
    preset = carica_impostazioni()["preset"]["standard"]
    positive = [
        crea_cluster(
            [
                crea_articolo(
                    "Scoperta positiva",
                    fonte="Buone Notizie",
                    categoria="buone-notizie",
                )
            ]
        )
    ]
    clusters = [crea_cluster([crea_articolo("Notizia Italia")]), *positive]
    scelte = seleziona(
        clusters,
        preset,
        ["italia"],
        buone_notizie=positive,
    )
    assert all(s.blocco != "buone-notizie" for s in scelte)


def test_solo_categorie_attive_per_le_secondarie():
    preset = carica_impostazioni()["preset"]["svelto"]
    clusters = [
        multi("Notizia copertina", ["ANSA", "Repubblica"], "sport", 1),
        crea_cluster([crea_articolo("Notizia cultura", categoria="cultura")]),
        crea_cluster([crea_articolo("Notizia sport", categoria="sport")]),
    ]
    scelte = seleziona(clusters, preset, ["cultura"], max_notizie=6)
    secondarie = [s for s in scelte if not s.copertina]
    assert all(s.categoria == "cultura" for s in secondarie)

def test_sport_da_feed_generalista_escluso_se_categoria_spenta():
    preset = carica_impostazioni()["preset"]["standard"]
    clusters = [
        multi("Festa a Borgo Panigale per Marquez e Ducati", ["ANSA", "Repubblica"], "sport", 1)
    ]
    assert seleziona(clusters, preset, ["italia", "economia"]) == []
    attive = seleziona(clusters, preset, ["sport"])
    assert len(attive) == 1
    assert attive[0].categoria == "sport"


def test_live_blog_escluso_se_ci_sono_alternative():
    preset = carica_impostazioni()["preset"]["svelto"]
    clusters = [
        crea_cluster([crea_articolo("Australian politics live", categoria="mondo", ore_fa=1)]),
        crea_cluster([crea_articolo("Notizia italiana", categoria="italia", ore_fa=2)]),
    ]
    scelte = seleziona(clusters, preset, ["italia", "mondo"], max_notizie=2)
    assert all("live" not in s.titolo.casefold() for s in scelte)
    assert any(s.titolo == "Notizia italiana" for s in scelte)


def test_live_blog_unico_non_viene_selezionato():
    preset = carica_impostazioni()["preset"]["svelto"]
    clusters = [
        crea_cluster([crea_articolo("Politica australiana in diretta", categoria="mondo")])
    ]
    assert seleziona(clusters, preset, ["mondo"]) == []

