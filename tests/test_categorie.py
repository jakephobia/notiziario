from __future__ import annotations

import pytest

from notiziario.categorie import (
    CATEGORIE,
    CATEGORIE_IDS,
    parse_issue_body,
    trova_categoria,
)


DEFAULT = [
    "italia",
    "mondo",
    "economia",
    "tecnologia",
    "scienza-salute",
    "cultura",
    "ambiente",
    "buone-notizie",
]


def test_categorie_fisse():
    assert CATEGORIE_IDS == (
        "italia",
        "mondo",
        "economia",
        "tecnologia",
        "scienza-salute",
        "cultura",
        "sport",
        "ambiente",
        "buone-notizie",
    )
    assert [c.label for c in CATEGORIE][4] == "Scienza e salute"


def test_parse_issue_con_checkbox_miste():
    corpo = """
## Categorie per oggi

- [x] Italia
- [ ] Mondo
- [X] **Economia**
- [x] Tecnologia
- [ ] Scienza e salute
- [x] cultura
- [ ] Sport
"""
    attive, avvisi = parse_issue_body(corpo, DEFAULT)
    assert attive == [
        "italia",
        "economia",
        "tecnologia",
        "cultura",
        "ambiente",
        "buone-notizie",
    ]
    assert avvisi == []


def test_parse_issue_case_insensitive_e_markdown():
    corpo = """## Categorie
- [X] `MONDO`
- [x] **Scienza e Salute**
- [ ] *SPORT*
- [x] Tecnologia
"""
    attive, _ = parse_issue_body(corpo, DEFAULT)
    assert "mondo" in attive
    assert "scienza-salute" in attive
    assert "sport" not in attive
    assert "tecnologia" in attive
    # Le categorie non citate mantengono il default.
    assert "italia" in attive
    assert "economia" in attive


def test_categoria_non_citata_mantiene_default():
    attive, avvisi = parse_issue_body("## Categorie\n- [x] Sport", DEFAULT)
    assert set(attive) == set(CATEGORIE_IDS)
    assert avvisi == []


def test_issue_vuota_usa_default():
    attive, avvisi = parse_issue_body("", DEFAULT)
    assert attive == DEFAULT
    assert any("predefinite" in a for a in avvisi)


def test_riga_non_riconosciuta_avvisa_solo_se_selezionata():
    attive, avvisi = parse_issue_body(
        "## Categorie\n- [x] Categoria inventata\n- [ ] Altra cosa", DEFAULT
    )
    assert attive == DEFAULT
    assert len(avvisi) == 1
    assert "non riconosciuta" in avvisi[0]


def test_checked_e_unchecked_stessa_categoria():
    attive, avvisi = parse_issue_body(
        "## Categorie\n- [x] Italia\n- [ ] italia", DEFAULT
    )
    assert "italia" in attive
    assert any("sia selezionata sia no" in a for a in avvisi)


@pytest.mark.parametrize(
    "testo, atteso",
    [
        ("Italia", "italia"),
        ("**Scienza e salute**", "scienza-salute"),
        ("scienza-salute", "scienza-salute"),
        ("Sport", "sport"),
        ("Ambiente", "ambiente"),
        ("Buone notizie", "buone-notizie"),
        ("buone-notizie", "buone-notizie"),
        ("Sportivo", None),
        ("Trasporti", None),
        ("", None),
    ],
)
def test_trova_categoria(testo, atteso):
    assert trova_categoria(testo) == atteso

def test_fonti_non_attivano_categoria_sport():
    corpo = """## Categorie
- [ ] Sport
- [x] Italia

## Fonti
- [x] ANSA Sport (sport) — https://www.ansa.it/sport.xml
"""
    attive, avvisi = parse_issue_body(corpo, DEFAULT)
    assert "sport" not in attive
    assert "italia" in attive
    assert avvisi == []


def test_sezione_categorie_assente_usa_default():
    corpo = "## Fonti\n- [x] ANSA Sport (sport) — https://www.ansa.it/sport.xml"
    attive, avvisi = parse_issue_body(corpo, DEFAULT)
    assert attive == DEFAULT
    assert "sport" not in attive
    assert any("assente" in a for a in avvisi)
