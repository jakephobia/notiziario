from __future__ import annotations

from helpers import crea_articolo, crea_cluster

from notiziario.classificazione import (
    categorie_cluster,
    notiziabilita_cluster,
)


def _cluster(
    titolo: str,
    sommario: str = "",
    categoria: str = "italia",
    fonte: str = "ANSA",
):
    return crea_cluster(
        [
            crea_articolo(
                titolo,
                fonte=fonte,
                categoria=categoria,
                sommario=sommario,
            )
        ]
    )


def test_femminicidio_evento_e_cronaca_nera():
    cluster = _cluster(
        "Femminicidio a Roma, uomo arrestato: ha ucciso la compagna",
        "La vittima aveva 34 anni. La procura ha aperto un fascicolo.",
    )
    categorie = categorie_cluster(cluster)
    assert categorie == {"italia", "cronaca", "cronaca-nera"}
    assert notiziabilita_cluster(cluster) == 3


def test_seguito_giudiziario_de_gennaro_non_e_cronaca_nera():
    cluster = _cluster(
        "De Gennaro, il processo si riapre: la reazione della famiglia",
        "L'udienza è fissata per dicembre. I legali chiedono nuovi accertamenti.",
    )
    categorie = categorie_cluster(cluster)
    assert "cronaca-nera" not in categorie
    assert "cronaca" in categorie
    assert notiziabilita_cluster(cluster) <= 3


def test_seguito_suicidio_con_indagini_non_e_cronaca_nera():
    cluster = _cluster(
        "De Gennaro, si indaga sulle ultime ore prima del suicidio",
        "La Procura di Grosseto procede per istigazione al suicidio. "
        "Disposta l'autopsia e sequestrati i telefoni.",
    )
    categorie = categorie_cluster(cluster)
    assert "cronaca-nera" not in categorie
    assert notiziabilita_cluster(cluster) <= 3


def test_guerra_resta_mondo_e_cronaca_non_nera():
    cluster = _cluster(
        "Guerra in Medio Oriente, nuova offensiva e attacco",
        "Strage di civili nel conflitto, migliaia di sfollati.",
        categoria="mondo",
    )
    categorie = categorie_cluster(cluster)
    assert "cronaca-nera" not in categorie
    assert {"mondo", "cronaca"} <= categorie
    assert notiziabilita_cluster(cluster) == 4


def test_attacco_armato_a_base_militare_e_cronaca_nera():
    cluster = _cluster(
        "Attacco armato contro una base militare",
        "Due soldati uccisi e altri feriti.",
        categoria="mondo",
    )
    categorie = categorie_cluster(cluster)
    assert "cronaca-nera" in categorie
    assert "cronaca" in categorie


def test_editoriale_diventa_approfondimento():
    cluster = _cluster(
        "Editoriale: cosa significa la manovra per le famiglie",
        "Un'analisi delle misure del governo.",
    )
    categorie = categorie_cluster(cluster)
    assert "approfondimento" in categorie
    assert "cronaca" in categorie
    assert "cronaca-nera" not in categorie
    assert notiziabilita_cluster(cluster) >= 3


def test_libro_presentato_e_promozione():
    cluster = _cluster(
        "Esce in libreria il nuovo romanzo",
        "Presentazione del libro in libreria.",
        categoria="cultura",
    )
    categorie = categorie_cluster(cluster)
    assert {"cultura", "promozione"} <= categorie
    assert notiziabilita_cluster(cluster) == 1


def test_recensione_prodotto_e_promozione():
    cluster = _cluster(
        "Recensione: il nuovo smartphone",
        "Prova su strada e prezzo.",
        categoria="tecnologia",
    )
    categorie = categorie_cluster(cluster)
    assert "promozione" in categorie
    assert notiziabilita_cluster(cluster) == 1


def test_numero_di_rivista_e_promozione_ma_numero_di_legge_no():
    rivista = _cluster("Il numero 12 di Focus", categoria="cultura")
    legge = _cluster("Il numero 3 della Costituzione", categoria="italia")
    assert "promozione" in categorie_cluster(rivista)
    assert "promozione" not in categorie_cluster(legge)


def test_nuovo_numero_di_vittime_non_e_promozione():
    cluster = _cluster(
        "Terremoto, nuovo numero di vittime",
        "Il bilancio sale mentre continuano i soccorsi.",
        categoria="mondo",
    )
    assert "promozione" not in categorie_cluster(cluster)


def test_concorso_di_colpa_non_e_promozione():
    cluster = _cluster(
        "Concorso di colpa, la sentenza del tribunale",
        "I giudici hanno deciso il risarcimento.",
        categoria="italia",
    )
    assert "promozione" not in categorie_cluster(cluster)


def test_cop_e_clima_non_e_eccezionale():
    cluster = _cluster(
        "Cop31, nuova bozza sul clima",
        "I paesi discutono di emissioni e rinnovabili.",
        categoria="ambiente",
    )
    assert notiziabilita_cluster(cluster) == 4


def test_vertice_ue_e_sanita_pubblica_sono_alte():
    vertice = _cluster(
        "Vertice UE sulla difesa, accordo sui fondi",
        "I leader approvano un nuovo piano.",
        categoria="mondo",
    )
    sanita = _cluster(
        "OMS, nuovo vaccino contro il virus: studio clinico",
        "La sperimentazione coinvolge milioni di persone.",
        categoria="scienza-salute",
    )
    assert "cronaca" in categorie_cluster(vertice)
    assert notiziabilita_cluster(vertice) > 3
    assert notiziabilita_cluster(sanita) == 4


def test_anti_ciclo_seguito_non_supera_tre_ma_il_vertice_si():
    evento = _cluster(
        "Femminicidio a Roma, uomo arrestato: ha ucciso la compagna",
        "La vittima aveva 34 anni.",
    )
    seguito_processo = _cluster(
        "Femminicidio, il processo: la reazione della famiglia",
        "L'udienza è fissata per dicembre.",
    )
    seguito_commento = _cluster(
        "Femminicidio, il commento del ministro scatena la polemica",
        "Dichiarazioni e reazioni politiche.",
    )
    vertice = _cluster(
        "Vertice NATO sulla difesa, accordo sui fondi",
        "I leader approvano un nuovo piano.",
        categoria="mondo",
    )

    assert "cronaca-nera" in categorie_cluster(evento)
    assert "cronaca-nera" not in categorie_cluster(seguito_processo)
    assert "cronaca-nera" not in categorie_cluster(seguito_commento)
    assert notiziabilita_cluster(seguito_processo) <= 3
    assert notiziabilita_cluster(seguito_commento) <= 3
    assert notiziabilita_cluster(vertice) > 3


def test_guerra_maggiore_puo_arrivare_a_cinque():
    cluster = _cluster(
        "Guerra mondiale, invasione e genocidio",
        "Milioni di profughi e un accordo di pace storico ancora lontano.",
        categoria="mondo",
    )
    assert notiziabilita_cluster(cluster) == 5


def test_cultura_non_promozionale_resta_bassa():
    cluster = _cluster(
        "Il nuovo museo apre a Napoli",
        "Il museo apre al pubblico da domani.",
        categoria="cultura",
    )
    assert categorie_cluster(cluster) == {"cultura"}
    assert notiziabilita_cluster(cluster) <= 2


def test_cluster_espone_categorie_e_notiziabilita():
    cluster = _cluster(
        "Guerra in Medio Oriente, nuova offensiva",
        "Il conflitto continua.",
        categoria="mondo",
    )
    assert cluster.categorie == categorie_cluster(cluster)
    assert cluster.notiziabilita == notiziabilita_cluster(cluster)
    assert cluster.categoria == "mondo"
