from __future__ import annotations

from datetime import datetime

from helpers import crea_articolo, crea_cluster

from notiziario.config import carica_impostazioni
from notiziario.copione import _finalizza_llm, genera_copione, prepara_materiale
from notiziario.selezione import NotiziaSelezionata
from notiziario.tempo import ROMA
from notiziario.copione import sezioni_tts_strutturate
from notiziario.testi import (
    deduplica_frasi,
    deduplica_paragrafi,
    deduplica_testo_finale,
    similarita_testi,
)


def test_paragrafo_ripetuto_una_sola_volta():
    testo = "Primo paragrafo unico.\n\nSecondo paragrafo unico.\n\nPrimo paragrafo unico."
    assert deduplica_paragrafi(testo) == "Primo paragrafo unico.\n\nSecondo paragrafo unico."


def test_frase_quasi_duplicata_ma_frase_unica_resta():
    testo = (
        "Il governo ha approvato la manovra. Il governo ha approvato la manovra! "
        "Una frase completamente diversa."
    )
    risultato = deduplica_frasi(testo)
    assert risultato.count("manovra") == 1
    assert "completamente diversa" in risultato


def test_titolo_ripetuto_all_inizio():
    testo = (
        "Politica australiana in diretta. Politica australiana in diretta. "
        "Chris Bowen parla del clima."
    )
    risultato = deduplica_testo_finale(testo, ["Politica australiana in diretta"])
    assert risultato.count("Politica australiana in diretta") == 1
    assert "Chris Bowen" in risultato


def test_similarita_soglia_e_contenuti_unici():
    a = "La nave russa è stata colpita nel porto di Bengasi."
    b = "La nave russa è stata colpita nel porto di Bengasi!"
    c = "Il governo ha presentato la manovra alla Camera."
    assert similarita_testi(a, b) >= 0.85
    assert similarita_testi(a, c) < 0.85

def test_materiale_non_ripete_frasi_uguali():
    articolo = crea_articolo(
        "Titolo notizia",
        sommario="La nave russa è stata colpita nel porto di Bengasi. La nave russa è stata colpita nel porto di Bengasi. Il governo ha chiesto calma.",
    )
    selezione = NotiziaSelezionata(crea_cluster([articolo]), True, 1, 100, "copertina")
    materiale = prepara_materiale([selezione])
    testo = materiale[0]["articoli"][0]["testo"]
    assert testo.count("La nave russa") == 1
    assert "Il governo" in testo


def test_fallback_deduplica_paragrafi():
    articolo = crea_articolo(
        "Titolo notizia",
        sommario="La nave russa è stata colpita nel porto di Bengasi. La nave russa è stata colpita nel porto di Bengasi. Il governo ha chiesto calma.",
    )
    selezione = NotiziaSelezionata(crea_cluster([articolo]), True, 1, 100, "copertina")
    copione = genera_copione(
        [selezione], carica_impostazioni(), datetime(2026, 11, 22, 7, tzinfo=ROMA), usa_llm=False
    )
    assert copione["testo"].casefold().count("la nave russa") == 1
    assert "Il governo" in copione["testo"]


def test_copione_ai_deduplica_titolo_e_paragrafi():
    dati = {
        "titolo_episodio": "Notiziario di prova",
        "descrizione": "Notizie.",
        "descrizione_breve": "22 novembre 2026 - Manovra approvata, Cop31 fallita",
        "testo": "Titolo notizia. Titolo notizia. Contenuto unico della notizia. Contenuto unico della notizia.",
        "notizie": [
            {
                "titolo": "Titolo notizia",
                "categoria": "Italia",
                "fonti": ["ANSA"],
                "testo": "Riassunto.",
                "paragrafi": ["Titolo notizia. Contenuto unico della notizia.", "Contenuto unico della notizia."],
            }
        ],
    }
    risultato = _finalizza_llm(dati, [NotiziaSelezionata(crea_cluster([crea_articolo("Titolo notizia")]), True, 1, 100, "copertina")], datetime(2026, 11, 22, 7, tzinfo=ROMA))
    assert risultato["testo"].count("Titolo notizia") == 1
    assert risultato["testo"].count("Contenuto unico della notizia") == 1

def test_dedup_non_cambia_i_nove_suoni_tra_dieci_notizie():
    notizie = [
        {"paragrafi": [f"Notizia numero {i}.", f"Notizia numero {i}."]}
        for i in range(10)
    ]
    for notizia in notizie:
        notizia["paragrafi"] = [
            p for p in deduplica_paragrafi("\n\n".join(notizia["paragrafi"])).split("\n\n") if p
        ]
    sezioni, indici = sezioni_tts_strutturate({"notizie": notizie})
    assert len(sezioni) == 10
    assert len(indici) == 9

def test_materiale_deduplica_anche_tra_articoli_della_stessa_notizia():
    sommario = "La nave russa è stata colpita nel porto di Bengasi. Il governo ha chiesto calma."
    articoli = [
        crea_articolo("Titolo notizia", fonte="ANSA", sommario=sommario),
        crea_articolo("Titolo notizia", fonte="Repubblica", sommario=sommario, ore_fa=2),
    ]
    selezione = NotiziaSelezionata(crea_cluster(articoli), True, 1, 100, "copertina")
    materiale = prepara_materiale([selezione])
    testi = " ".join(a["testo"] for a in materiale[0]["articoli"])
    assert testi.count("La nave russa") == 1
    assert testi.count("Il governo") == 1
