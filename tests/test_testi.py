from __future__ import annotations

from datetime import datetime

from notiziario.testi import (
    conta_parole,
    data_in_italiano,
    elenco_naturale,
    formatta_durata,
    normalizza_mesi,
    normalizza_per_tts,
    normalizza_titolo,
    pulisci_html,
    pulisci_testo,
    pulisci_titolo,
    rimuovi_pubblicita,
    similarita_titoli,
    spezza_frasi_lunghe,
    tronca_a_frase,
)


def test_pulisci_html_toglia_tag_e_script():
    testo = (
        "<p>Ciao <b>mondo</b></p><script>alert('x')</script>"
        "<style>.x{}</style><p>Leggi tutto</p>"
    )
    pulito = pulisci_html(testo)
    assert "Ciao mondo" in pulito
    assert "alert" not in pulito
    assert "Leggi" in pulito


def test_pulisci_testo_toglia_boilerplate_link_e_spazi():
    grezzo = (
        "  Il governo approva la manovra. Leggi tutto su ANSA.it  "
        "https://example.com/articolo  © 2026 ANSA  "
    )
    pulito = pulisci_testo(grezzo)
    assert "governo approva" in pulito
    assert "Leggi tutto" not in pulito
    assert "https://" not in pulito
    assert "©" not in pulito
    assert "  " not in pulito


def test_pulisci_titolo_toglie_suffisso_testata():
    assert pulisci_titolo("Titolo della notizia - ANSA.it") == "Titolo della notizia"
    assert pulisci_titolo("Titolo <b>forte</b>") == "Titolo forte"


def test_tronca_a_frase():
    testo = "Prima frase breve. Seconda frase un po' più lunga. Terza frase."
    tagliato = tronca_a_frase(testo, 40)
    assert tagliato.startswith("Prima frase breve.")
    assert tagliato.endswith(".")
    assert "Terza" not in tagliato


def test_normalizza_titolo_accenti_stopword_numeri():
    assert (
        normalizza_titolo("Meloni incontra Trump alla Casa Bianca nel 2026!")
        == "meloni incontra trump casa bianca"
    )
    assert normalizza_titolo("Città e Perché") == "citta perche"


def test_similarita_titoli():
    assert similarita_titoli("Stessa notizia", "Stessa notizia") == 1.0
    assert (
        similarita_titoli(
            "Cop31, nuova bozza sul clima",
            "Cop31: la Ue respinge la nuova bozza sul clima",
        )
        > 0.7
    )
    assert (
        similarita_titoli("Juve batte il Venezia", "Nuova bozza sul clima")
        < 0.3
    )


def test_normalizza_per_tts_date_percentuali_migliaia_parentesi():
    testo = "Il 22/11/2026 il 3% e 1.400 euro (stima). Vedi https://example.com"
    normale = normalizza_per_tts(testo)
    assert "22 novembre 2026" in normale
    assert "3 per cento" in normale
    assert "1400 euro" in normale
    assert "(" not in normale and ")" not in normale
    assert "https://" not in normale
    assert normale.endswith(".")


def test_normalizza_per_tts_markdown_e_simboli():
    normale = normalizza_per_tts("**Titolo** & testo + altro ≈ 1.400.000 • nota")
    assert "*" not in normale
    assert "&" not in normale
    assert "•" not in normale
    assert " e " in normale
    assert "circa" in normale
    assert "1400000" in normale


def test_spezza_frasi_lunghe():
    frase = " ".join(["parola"] * 50) + "."
    spezzata = spezza_frasi_lunghe(frase, max_parole=20)
    frasi = [f for f in spezzata.split(".") if f.strip()]
    assert len(frasi) >= 3
    assert all(conta_parole(f) <= 20 for f in frasi)


def test_data_in_italiano_e_formati():
    data = datetime(2026, 11, 22, 7, 30)
    assert "22 novembre 2026" in data_in_italiano(data)
    assert data_in_italiano(data).startswith("domenica")
    assert formatta_durata(3671) == "01:01:11"
    assert formatta_durata(None) == "00:00:00"


def test_elenco_naturale():
    assert elenco_naturale(["ANSA"]) == "ANSA"
    assert elenco_naturale(["ANSA", "Repubblica"]) == "ANSA e Repubblica"
    assert (
        elenco_naturale(["ANSA", "Repubblica", "Il Post"])
        == "ANSA, Repubblica e Il Post"
    )

def test_normalizza_mesi_minuscolo():
    assert normalizza_mesi("22 Novembre 2026") == "22 novembre 2026"
    assert normalizza_mesi("Notiziario di 22 NOVEMBRE 2026") == "Notiziario di 22 novembre 2026"
    assert normalizza_mesi("Marzo e Maggio") == "marzo e maggio"


def test_pulisci_html_rimuove_elementi_pubblicitari_e_lascia_il_resto():
    html = (
        '<div class="header"><p>Testata locale</p></div>'
        '<div class="ad-container"><p>Acquista il prodotto del partner</p></div>'
        '<div class="sponsored"><p>Messaggio sponsor</p></div>'
        '<div id="taboola"><p>Storie consigliate</p></div>'
        '<div class="loading">Caricamento</div>'
        '<p class="read-more">Leggi tutto</p>'
        "<p>La notizia vera continua qui.</p>"
    )
    pulito = pulisci_html(html)
    assert "Testata locale" in pulito
    assert "La notizia vera continua qui" in pulito
    assert "Caricamento" in pulito
    assert "Leggi tutto" in pulito
    assert "Acquista il prodotto" not in pulito
    assert "Messaggio sponsor" not in pulito
    assert "Storie consigliate" not in pulito


def test_rimuovi_pubblicita_etichette_cta_e_contesto_informativo():
    testo = (
        "Pubblicità\n"
        "Contenuto sponsorizzato: scopri l'offerta e acquista ora con il codice sconto.\n\n"
        "Il governo ha approvato la manovra. "
        "La pubblicità online cresce del 5 per cento."
    )
    pulito = rimuovi_pubblicita(testo)
    assert not pulito.startswith("Pubblicità")
    assert "Contenuto sponsorizzato" not in pulito
    assert "acquista ora" not in pulito.casefold()
    assert "Il governo ha approvato la manovra" in pulito
    assert "La pubblicità online cresce del 5 per cento" in pulito


def test_rimuovi_pubblicita_continua_e_collaborazione_breve():
    testo = (
        "Continua dopo la pubblicità\n\n"
        "In collaborazione con Acme.\n\n"
        "In collaborazione con il ministero, il progetto coinvolge dieci "
        "scuole e due università italiane."
    )
    pulito = rimuovi_pubblicita(testo)
    assert "Continua dopo" not in pulito
    assert "Acme" not in pulito
    assert "dieci scuole" in pulito


def test_rimuovi_pubblicita_continua_in_linea_mista_non_cancella_la_notizia():
    testo = (
        "Leggi tutto su ANSA. Continua dopo la pubblicità. "
        "Il fatto è accaduto ieri."
    )
    pulito = rimuovi_pubblicita(testo)
    assert "Continua dopo" not in pulito
    assert "Il fatto è accaduto ieri" in pulito


def test_rimuovi_pubblicita_salta_blocco_prodotto_dopo_etichetta():
    testo = (
        "Pubblicità\n\n"
        "Il nuovo smartphone costa 499 euro ed è disponibile in tutti i negozi."
    )
    assert rimuovi_pubblicita(testo) == ""


def test_rimuovi_pubblicita_non_scarta_notizie_legittime():
    testo = (
        "Gli abbonati a Netflix sono aumentati del 10 per cento. "
        "Il governo taglia gli sconti del 20 per cento sulle bollette. "
        "La società ha offerto un'offerta limitata ai dipendenti."
    )
    pulito = rimuovi_pubblicita(testo)
    assert "abbonati a Netflix" in pulito
    assert "taglia gli sconti del 20 per cento" in pulito
    assert "offerta limitata ai dipendenti" in pulito


def test_rimuovi_pubblicita_rimuove_cta_a_inizio_frase():
    testo = (
        "Abbonati a Il Foglio con l'offerta speciale. "
        "Sconti del 20 per cento su tutto. "
        "Offerta limitata: approfitta subito."
    )
    assert rimuovi_pubblicita(testo) == ""
