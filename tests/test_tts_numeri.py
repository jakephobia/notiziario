"""Regole di lettura TTS per orari, date, temperature, unità e numeri."""

from __future__ import annotations

from notiziario.testi import normalizza_per_tts

MESI = (
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
)


def normale(testo: str) -> str:
    return normalizza_per_tts(testo)


# --- Orari ---------------------------------------------------------------


def test_orario_con_punto_e_contesto_mattina():
    out = normale("Alle 8.30 di mattina")
    assert "8 e 30" in out
    assert "punto" not in out
    assert "8.30" not in out


def test_orario_con_due_punti():
    assert "20 e 45" in normale("20:45")
    assert "8 e 30" in normale("8:30")


def test_orario_con_punto_preceduto_da_parola_chiave():
    assert "8 e 30" in normale("ore 8.30")
    assert "8 e 30" in normale("dalle 8.30 in poi")
    assert "20 e 45" in normale("fino alle 20.45")


def test_orario_con_punto_seguito_da_momento_della_giornata():
    assert "8 e 30" in normale("8.30 di sera")
    assert "20 e 45" in normale("20.45 del pomeriggio")
    assert "2 e 15" in normale("2.15 di notte")


def test_punto_senza_contesto_resta_un_decimale():
    out = normale("8.30")
    assert "8,30" in out
    assert "8 e 30" not in out


def test_percentuale_con_punto_non_diventa_orario():
    out = normale("8.30%")
    assert "8,30 per cento" in out
    assert "e 30" not in out


# --- Temperature ---------------------------------------------------------


def test_temperature_con_gradi_celsius():
    for testo in ("16°C", "16 °C", "16° C"):
        out = normale(testo)
        assert "16 gradi" in out
        assert "gradi C" not in out
        assert "°" not in out


def test_gradi_c_gia_a_parole():
    out = normale("16 gradi C")
    assert "16 gradi" in out
    assert "gradi C" not in out
    assert "gradi" in normale("16 gradi c")
    assert "gradi c" not in normale("16 gradi c")


def test_temperature_fahrenheit_e_negative():
    out = normale("16°F")
    assert "16 gradi Fahrenheit" in out
    assert "°" not in out
    assert "meno 5 gradi" in normale("-5°C")
    assert "°" not in normale("-5°C")


def test_grado_isolato_dopo_un_numero():
    out = normale("20°")
    assert "20 gradi" in out
    assert "°" not in out


# --- Unità di misura -----------------------------------------------------


def test_unita_velocita_e_distanza():
    assert "5 chilometri orari" in normale("5 km/h")
    assert "10 metri al secondo" in normale("10 m/s")
    assert "120 chilometri" in normale("120 km")
    assert "3 chilogrammi" in normale("3 kg")
    assert "10 centimetri" in normale("10 cm")
    assert "5 millimetri" in normale("5 mm")


def test_unita_superficie_e_volume():
    assert "10 metri quadrati" in normale("10 m²")
    assert "10 metri quadrati" in normale("10 mq")
    assert "5 metri cubi" in normale("5 m³")
    assert "5 metri cubi" in normale("5 mc")


def test_unita_potenza_ed_energia():
    assert "100 chilowatt" in normale("100 kW")
    assert "50 megawatt" in normale("50 MW")
    assert "2 gigawatt" in normale("2 GW")
    assert "10 chilowattora" in normale("10 kWh")


def test_unita_liquidi_peso_e_superficie_agricola():
    assert "250 millilitri" in normale("250 ml")
    assert "75 centilitri" in normale("75 cl")
    assert "2 litri" in normale("2 l")
    assert "3 litri" in normale("3 L")
    assert "5 tonnellate" in normale("5 t")
    assert "20 ettari" in normale("20 ha")


def test_percentuali_e_valute():
    assert "8 per cento" in normale("8%")
    assert "5 euro" in normale("5 €")
    assert "5 dollari" in normale("5 $")
    assert "5 sterline" in normale("5 £")


def test_unita_solo_dopo_un_numero():
    out = normale("La velocità è espressa in km/h")
    assert "chilometri orari" not in out


def test_unita_ambigue_non_toccano_verbi_e_anni():
    out = normale("Nel 2026 ha detto che nel 2026 l'Italia crescerà")
    assert "ettari" not in out
    assert "litri" not in out
    assert "ha detto" in out
    assert "l'Italia" in out


# --- Date ----------------------------------------------------------------


def test_date_italiane_e_iso():
    atteso = "26 novembre 2026"
    assert atteso in normale("26/11/2026")
    assert atteso in normale("26-11-2026")
    assert atteso in normale("2026-11-26")


def test_intervallo_di_anni_non_diventa_una_data():
    out = normale("Il confronto 2025-2026 è in corso")
    basso = out.lower()
    assert all(mese not in basso for mese in MESI)
    assert "2025-2026" in out
    assert "meno" not in out


def test_data_non_valida_resta_non_data():
    out = normale("32/13/2026")
    basso = out.lower()
    assert all(mese not in basso for mese in MESI)


# --- Numeri --------------------------------------------------------------


def test_migliaia_senza_punto():
    assert "1000 euro" in normale("1.000 euro")
    assert "2500000" in normale("2.500.000")


def test_decimali_con_virgola():
    assert "8,30" in normale("8.30")
    assert "8,30" in normale("Il valore è 8.30.")
    assert "3,14" in normale("3.14")


def test_sequenze_con_piu_punti_non_diventano_decimali():
    out = normale("La versione v1.2.3 resta invariata")
    assert "1.2.3" in out


def test_numeri_positivi_e_negativi():
    assert "più 3" in normale("+3")
    out = normale("-5")
    assert "meno 5" in out


def test_intervallo_numerico():
    assert "da 8 a 10" in normale("8-10")
    assert "da 8 a 10 gradi" in normale("8-10°C")
    assert "da 8 a 10 per cento" in normale("8-10%")
    assert "da 8 a 10 chilometri" in normale("8-10km")


def test_codici_con_trattino_non_diventano_intervalli_o_negativi():
    out = normale("COVID-19")
    assert "COVID-19" in out
    assert "meno" not in out
    assert "da 19" not in out


def test_risultato_sportivo_non_diventa_intervallo():
    out = normale("Il risultato è 2-1")
    assert "2 a 1" in out
    assert "da 2 a 1" not in out


def test_testo_ormai_normale_non_cambia_significato():
    out = normale("La temperatura è salita di 2 gradi e il vento soffia a 30 km/h")
    assert "2 gradi" in out
    assert "30 chilometri orari" in out
