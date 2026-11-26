from __future__ import annotations

from helpers import crea_articolo, crea_cluster

from notiziario.clustering import Cluster
from notiziario.config import carica_impostazioni
from notiziario.copione import (
    genera_copione,
    prepara_materiale,
    sezioni_tts_strutturate,
)
from notiziario.selezione import (
    NotiziaSelezionata,
    _nomi_forti,
    _nomi_in_comune,
    seleziona,
)
from notiziario.testi import estrai_nomi_propri, stesso_nome


def _cluster(
    titolo: str,
    sommario: str,
    fonte: str,
    categoria: str = "italia",
    ore_fa: float = 1,
) -> Cluster:
    return crea_cluster(
        [
            crea_articolo(
                titolo,
                fonte=fonte,
                categoria=categoria,
                sommario=sommario,
                ore_fa=ore_fa,
            )
        ]
    )


def _menziona(selezione: NotiziaSelezionata, parola: str) -> bool:
    testi = [selezione.cluster.titolo]
    for articolo in selezione.cluster.articoli:
        testi.extend([articolo.titolo, articolo.sommario])
    return parola.casefold() in " ".join(testi).casefold()


def _cluster_de_gennaro() -> list[Cluster]:
    return [
        _cluster(
            "I telefoni e gli appunti, i pm sulle tracce lasciate da De Gennaro",
            "Il corpo trovato in poltrona. L'autopsia a Firenze, sequestrata la casa.",
            "ANSA",
            ore_fa=1,
        ),
        _cluster(
            "Le lettere, i documenti, le tracce biologiche: i pm ricostruiscono le ultime ore di vita d...",
            "Le lettere a familiari e agli amici, i documenti e soprattutto il bossolo "
            "trovato nel giardino della sua casa a Montiano, in Maremma, segno che Gianni "
            "De Gennaro aveva studiato le sue ultime ore nei minimi dettagli. ... la "
            "procura di Caltanissetta indaga ...",
            "Agi",
            ore_fa=2,
        ),
        _cluster(
            "De Gennaro, sequestrati i telefoni e trovate buste sigillate: si indaga sulle ultime ore prima del suicidio",
            "La Procura di Grosseto procede per istigazione al suicidio, con il "
            "coordinamento dell'antimafia di Firenze. Sotto esame chiamate, messaggi e "
            "documenti rinvenuti nella villa in Maremma. Disposta l'autopsia.",
            "Il Sole 24 Ore",
            ore_fa=3,
        ),
    ]


def test_tre_notizie_sullo_stesso_evento_selezionata_una_sola():
    preset = carica_impostazioni()["preset"]["svelto"]
    scelte = seleziona(_cluster_de_gennaro(), preset, ["italia"], max_notizie=10)
    assert len(scelte) == 1
    selezione = scelte[0]
    assert _menziona(selezione, "Gennaro")
    assert len(selezione.cluster.articoli) == 3
    assert selezione.fonti == ["ANSA", "Agi", "Il Sole 24 Ore"]
    assert len({a.id for a in selezione.cluster.articoli}) == 3
    assert len(selezione.fonti) == len(set(selezione.fonti))

    materiale = prepara_materiale(scelte)
    assert len(materiale[0]["articoli"]) == 3
    assert set(materiale[0]["fonti"]) == {"ANSA", "Agi", "Il Sole 24 Ore"}


def test_duplicati_assorbiti_anche_come_secondarie():
    preset = {
        **carica_impostazioni()["preset"]["svelto"],
        "copertine": 0,
        "secondarie": 1,
        "max_notizie": 1,
    }
    scelte = seleziona(
        _cluster_de_gennaro()[:2], preset, ["italia"], max_notizie=1
    )
    assert len(scelte) == 1
    assert scelte[0].blocco == "secondaria"
    assert len(scelte[0].cluster.articoli) == 2
    assert set(scelte[0].fonti) == {"ANSA", "Agi"}


def test_duplicato_positivo_assorbito_nella_copertina():
    preset = carica_impostazioni()["preset"]["svelto"]
    generale = _cluster_de_gennaro()[0]
    positivo = _cluster(
        "De Gennaro, i telefoni e gli appunti dell'inchiesta",
        "Gianni De Gennaro, i telefoni e gli appunti al centro dell'inchiesta. "
        "L'autopsia a Firenze.",
        "Buone Notizie",
        categoria="buone-notizie",
    )
    scelte = seleziona(
        [generale],
        preset,
        ["italia", "buone-notizie"],
        max_notizie=6,
        buone_notizie=[positivo],
    )
    assert len(scelte) == 1
    assert scelte[0].blocco == "copertina"
    assert len(scelte[0].cluster.articoli) == 2
    assert set(scelte[0].fonti) == {"ANSA", "Buone Notizie"}


def test_duplicato_generale_assorbito_nella_buona_notizia_selezionata_prima():
    preset = {
        **carica_impostazioni()["preset"]["svelto"],
        "copertine": 0,
        "secondarie": 1,
        "max_notizie": 2,
        "buone_notizie": 1,
    }
    generale = _cluster(
        "I telefoni e gli appunti, i pm sulle tracce lasciate da De Gennaro",
        "Il corpo trovato in poltrona. L'autopsia a Firenze, sequestrata la casa.",
        "ANSA",
        ore_fa=2,
    )
    positivo = _cluster(
        "De Gennaro, i telefoni e gli appunti dell'inchiesta",
        "Gianni De Gennaro, i telefoni e gli appunti al centro dell'inchiesta. "
        "L'autopsia a Firenze.",
        "Buone Notizie",
        categoria="buone-notizie",
        ore_fa=1,
    )
    scelte = seleziona(
        [generale],
        preset,
        ["italia", "buone-notizie"],
        max_notizie=2,
        buone_notizie=[positivo],
    )
    assert len(scelte) == 1
    assert scelte[0].blocco == "buone-notizie"
    assert len(scelte[0].cluster.articoli) == 2
    assert set(scelte[0].fonti) == {"ANSA", "Buone Notizie"}


def test_duplicato_di_categoria_inattiva_non_cambia_la_categoria():
    preset = carica_impostazioni()["preset"]["svelto"]
    generale = _cluster(
        "I telefoni e gli appunti, i pm sulle tracce lasciate da De Gennaro",
        "Il corpo trovato in poltrona. L'autopsia a Firenze, sequestrata la casa.",
        "ANSA",
        ore_fa=3,
    )
    sportivo = _cluster(
        "De Gennaro, sequestrati i telefoni e trovate buste sigillate: si indaga "
        "sulle ultime ore prima del suicidio",
        "La Procura di Grosseto procede per istigazione al suicidio, con il "
        "coordinamento dell'antimafia di Firenze. Sotto esame chiamate, messaggi e "
        "documenti rinvenuti nella villa in Maremma. Disposta l'autopsia.",
        "Il Sole 24 Ore",
        categoria="sport",
        ore_fa=0.5,
    )
    scelte = seleziona([generale, sportivo], preset, ["italia"], max_notizie=10)
    assert len(scelte) == 1
    assert scelte[0].blocco == "copertina"
    assert scelte[0].categoria == "italia"
    assert len(scelte[0].cluster.articoli) == 2
    assert set(scelte[0].fonti) == {"ANSA", "Il Sole 24 Ore"}


def test_duplicato_di_categoria_attiva_non_cambia_la_categoria_secondaria():
    preset = {
        **carica_impostazioni()["preset"]["svelto"],
        "copertine": 0,
        "secondarie": 2,
        "max_notizie": 2,
        "buone_notizie": 0,
    }
    italia = _cluster_de_gennaro()[0]
    mondo = _cluster(
        "Le lettere, i documenti, le tracce biologiche: i pm ricostruiscono le "
        "ultime ore di vita d...",
        "Le lettere a familiari e agli amici, i documenti e soprattutto il bossolo "
        "trovato nel giardino della sua casa a Montiano, in Maremma, segno che Gianni "
        "De Gennaro aveva studiato le sue ultime ore nei minimi dettagli. ... la "
        "procura di Caltanissetta indaga ...",
        "Agi",
        categoria="mondo",
        ore_fa=0.5,
    )
    scelte = seleziona([italia, mondo], preset, ["italia", "mondo"], max_notizie=2)
    assert len(scelte) == 1
    assert scelte[0].blocco == "secondaria"
    assert scelte[0].categoria == "italia"
    assert len(scelte[0].cluster.articoli) == 2
    assert set(scelte[0].fonti) == {"ANSA", "Agi"}


def test_cluster_selezionato_resta_dopo_il_cambio_di_id():
    preset = carica_impostazioni()["preset"]["svelto"]
    clusters = _cluster_de_gennaro()
    id_iniziale = clusters[0].id
    scelte = seleziona(clusters, preset, ["italia"], max_notizie=10)
    assert len(scelte) == 1
    assert scelte[0].cluster is clusters[0]
    assert scelte[0].cluster.id != id_iniziale


def test_buone_notizie_inattive_duplicato_positivo_non_blocca_la_generale():
    preset = carica_impostazioni()["preset"]["svelto"]
    generale = _cluster_de_gennaro()[0]
    positivo = _cluster(
        "De Gennaro, i telefoni e gli appunti dell'inchiesta",
        "Gianni De Gennaro, i telefoni e gli appunti al centro dell'inchiesta. "
        "L'autopsia a Firenze.",
        "Buone Notizie",
        categoria="buone-notizie",
    )
    scelte = seleziona(
        [generale],
        preset,
        ["italia"],
        max_notizie=6,
        buone_notizie=[positivo],
    )
    assert len(scelte) == 1
    assert scelte[0].blocco == "copertina"
    assert scelte[0].categoria == "italia"
    assert set(scelte[0].fonti) == {"ANSA", "Buone Notizie"}
    assert all(s.blocco != "buone-notizie" for s in scelte)


def test_assorbimento_rispetta_limiti_e_ordine_dei_blocchi():
    preset = carica_impostazioni()["preset"]["svelto"]
    clusters = _cluster_de_gennaro() + [
        _cluster(
            "Vertice sul clima a Parigi",
            "I ministri discutono gli obiettivi sul clima.",
            "ANSA",
            categoria="mondo",
            ore_fa=4,
        ),
        _cluster(
            "Mercati europei in rialzo",
            "Le borse chiudono positive.",
            "ANSA",
            categoria="economia",
            ore_fa=5,
        ),
        _cluster(
            "Un nuovo museo apre a Napoli",
            "Il museo apre al pubblico da domani.",
            "ANSA",
            categoria="cultura",
            ore_fa=6,
        ),
    ]
    eventi = {a.id for cluster in clusters[:3] for a in cluster.articoli}
    positivi = [
        _cluster(
            "Volontari ripuliscono il parco",
            "I volontari hanno ripulito il parco.",
            "Buone Notizie",
            categoria="buone-notizie",
            ore_fa=7,
        ),
        _cluster(
            "Raccolti fondi per la scuola",
            "La scuola avrà una nuova biblioteca.",
            "Buone Notizie",
            categoria="buone-notizie",
            ore_fa=8,
        ),
    ]
    scelte = seleziona(
        clusters,
        preset,
        ["italia", "mondo", "economia", "cultura", "buone-notizie"],
        max_notizie=6,
        buone_notizie=positivi,
    )
    assert len(scelte) == 6
    assert [s.blocco for s in scelte] == (
        ["copertina"] * 2 + ["secondaria"] * 2 + ["buone-notizie"] * 2
    )
    assert sum(1 for s in scelte if s.copertina) == 2
    assert (
        sum(1 for s in scelte if s.blocco == "secondaria")
        <= preset["secondarie"]
    )
    assert (
        sum(1 for s in scelte if s.blocco == "buone-notizie")
        <= preset["buone_notizie"]
    )
    assert {s.categoria for s in scelte if s.blocco == "secondaria"} == {
        "economia",
        "cultura",
    }
    assert "mondo" in {s.categoria for s in scelte if s.copertina}
    paragrafi_evento = [
        s for s in scelte if any(a.id in eventi for a in s.cluster.articoli)
    ]
    assert len(paragrafi_evento) == 1


def test_copione_e_md_elencano_le_fonti_assorbite(tmp_path):
    from datetime import datetime, timezone

    from main import _scrivi_copione_md

    impostazioni = carica_impostazioni()
    preset = impostazioni["preset"]["svelto"]
    scelte = seleziona(_cluster_de_gennaro(), preset, ["italia"], max_notizie=10)
    data = datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)
    copione = genera_copione(scelte, impostazioni, data, usa_llm=False)
    sezioni, transizioni = sezioni_tts_strutturate(copione)
    assert len(sezioni) == 1
    assert transizioni == []
    assert set(copione["notizie"][0]["fonti"]) == {
        "ANSA",
        "Agi",
        "Il Sole 24 Ore",
    }

    percorso = tmp_path / "copione.md"
    _scrivi_copione_md(
        percorso,
        copione,
        scelte,
        data,
        "svelto",
        preset,
        ["italia"],
        None,
    )
    testo = percorso.read_text(encoding="utf-8")
    for fonte in ("ANSA", "Agi", "Il Sole 24 Ore"):
        assert fonte in testo
    for articolo in scelte[0].cluster.articoli:
        assert articolo.titolo in testo


def test_nome_comune_senza_stesso_evento_non_blocca():
    preset = carica_impostazioni()["preset"]["svelto"]
    clusters = [
        _cluster(
            "Meloni incontra Trump a Washington",
            "La presidente del Consiglio, Giorgia Meloni, ha incontrato Donald Trump "
            "alla Casa Bianca per parlare di dazi e commercio.",
            "ANSA",
            ore_fa=1,
        ),
        _cluster(
            "Meloni annuncia il taglio delle tasse",
            "La premier Giorgia Meloni annuncia un piano per ridurre le tasse a "
            "famiglie e imprese.",
            "Repubblica",
            ore_fa=2,
        ),
    ]
    scelte = seleziona(clusters, preset, ["italia"], max_notizie=6)
    titoli = {selezione.titolo for selezione in scelte}
    assert titoli == {
        "Meloni incontra Trump a Washington",
        "Meloni annuncia il taglio delle tasse",
    }


def test_estrai_nomi_propri_multiparola():
    nomi = estrai_nomi_propri("Il premier Gianni De Gennaro ha parlato con i pm.")
    assert ("gianni", "de", "gennaro") in nomi


def test_particella_e_nome_completo_sono_lo_stesso_nome():
    primo = estrai_nomi_propri("Gianni De Gennaro")
    secondo = estrai_nomi_propri("De Gennaro")
    assert any(stesso_nome(a, b) for a in primo for b in secondo)


def test_stesso_nome_di_battesimo_con_particella_non_basta():
    primo = estrai_nomi_propri("Maria De Luca")
    secondo = estrai_nomi_propri("Maria De Gennaro")
    assert not any(stesso_nome(a, b) for a in primo for b in secondo)


def test_cognome_come_nome_non_combacia_con_prefisso():
    primo = estrai_nomi_propri("Gennaro De Luca")
    secondo = estrai_nomi_propri("De Gennaro")
    assert not any(stesso_nome(a, b) for a in primo for b in secondo)


def test_cognome_da_solo_combacia_con_il_nome_completo():
    cognome = estrai_nomi_propri("De Gennaro")
    completo = estrai_nomi_propri("Gianni De Gennaro")
    assert any(stesso_nome(a, b) for a in cognome for b in completo)


def test_nomi_forti_tiene_il_cognome_con_particella():
    cluster = _cluster(
        "De Gennaro, sequestrati i telefoni e le buste sigillate",
        "La Procura di Grosseto indaga sulle ultime ore.",
        "Il Sole 24 Ore",
    )
    assert ("gennaro",) in _nomi_forti(cluster)


def test_nomi_in_comune_non_include_la_particella():
    primo = _cluster(
        "De Gennaro, sequestrati i telefoni",
        "Si indaga sulle ultime ore prima del suicidio.",
        "ANSA",
    )
    secondo = _cluster(
        "Le ultime ore di Gianni De Gennaro",
        "I pm ricostruiscono le tracce lasciate nella villa.",
        "Agi",
    )
    assert _nomi_in_comune(primo, secondo) == {"gennaro", "gianni"}


def test_nomi_diversi_con_un_token_in_comune_non_sono_lo_stesso_nome():
    primo = estrai_nomi_propri("Paolo Borsellino")
    secondo = estrai_nomi_propri("Paolo Rossi")
    assert not any(stesso_nome(a, b) for a in primo for b in secondo)


def test_nome_singolo_non_e_un_nome_forte():
    assert estrai_nomi_propri("Firenze") == set()
    assert estrai_nomi_propri("Firenze e l'ANSA") == set()


def test_nome_troncato_trovato_nel_sommario():
    titolo = (
        "Le lettere, i documenti, le tracce biologiche: i pm ricostruiscono "
        "le ultime ore di vita d..."
    )
    assert all("gennaro" not in nome for nome in estrai_nomi_propri(titolo))
    nomi = estrai_nomi_propri(
        titolo
        + " ... segno che Gianni De Gennaro aveva studiato le sue ultime ore ..."
    )
    assert ("gianni", "de", "gennaro") in nomi
