from __future__ import annotations

from datetime import datetime, timezone

from notiziario.incipit import (
    INCIPIT_DEFAULT,
    aggiungi_incipit,
    estrai_incipit_issue,
    risolvi_incipit,
    scegli_modello,
)
from notiziario.tempo import ROMA


def test_incipit_default_esatto():
    testo, avvisi = risolvi_incipit(
        INCIPIT_DEFAULT,
        "Jacopo",
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
    )
    assert testo == (
        "Ciao Jacopo, ecco le tue notizie del giorno. Oggi è il 22 novembre."
    )
    assert avvisi == []


def test_marker_case_insensitive_e_spazi():
    modello = (
        "Ciao [ nome   utente ], oggi è [ data  completa ]. "
        "Siamo nel mese di [data]."
    )
    testo, avvisi = risolvi_incipit(
        modello, "Jacopo", datetime(2026, 11, 22, 7, 0, tzinfo=ROMA)
    )
    assert testo == (
        "Ciao Jacopo, oggi è domenica 22 novembre 2026. "
        "Siamo nel mese di 22 novembre."
    )
    assert avvisi == []


def test_marker_sconosciuto_rimosso_e_segnalato():
    testo, avvisi = risolvi_incipit(
        "Ciao [NOME], [SCONOSCIUTO] oggi è [DATA].",
        "Jacopo",
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
    )
    assert testo == "Ciao Jacopo, oggi è 22 novembre."
    assert any("SCONOSCIUTO" in a for a in avvisi)
    assert "[" not in testo and "]" not in testo


def test_nome_vuoto_rimuove_marker_senza_parentesi():
    testo, avvisi = risolvi_incipit(
        "Ciao [NOME UTENTE], ecco le notizie.",
        "",
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
    )
    assert testo == "Ciao, ecco le notizie."
    assert "[" not in testo and "]" not in testo
    assert any("nome_utente vuoto" in a for a in avvisi)


def test_data_usa_europe_rome_non_utc():
    # Le 23:30 UTC del 22 novembre sono già le 00:30 del 23 a Roma.
    testo, _ = risolvi_incipit(
        "[DATA COMPLETA]",
        "Jacopo",
        datetime(2026, 11, 22, 23, 30, tzinfo=timezone.utc),
    )
    assert testo == "lunedì 23 novembre 2026"


def test_estrai_incipit_da_issue_testo_e_codice():
    corpo = """
## Categorie
- [x] italia

## Incipit
Ciao [NOME], oggi è [DATA].

## Note
Altro testo.
"""
    assert (
        estrai_incipit_issue(corpo)
        == "Ciao [NOME], oggi è [DATA]."
    )
    corpo_codice = """
## Incipit
```
Ciao [NOME UTENTE], buongiorno.
```
## Altro
"""
    assert estrai_incipit_issue(corpo_codice) == "Ciao [NOME UTENTE], buongiorno."
    assert estrai_incipit_issue("## Categorie\n- [x] italia") is None


def test_priorita_issue_su_file():
    modello, fonte = scegli_modello(
        "## Incipit\nCiao [NOME], buongiorno.\n## Altro\ntesto",
        "Ciao [NOME], dal file.",
    )
    assert modello == "Ciao [NOME], buongiorno."
    assert fonte == "issue"
    modello, fonte = scegli_modello("## Categorie\n- [x] italia", "Dal file.")
    assert modello == "Dal file."
    assert fonte == "file"


def test_aggiungi_incipit_in_testa():
    copione = {
        "testo": "Prima notizia. Seconda notizia.",
        "notizie": [{"titolo": "x"}],
        "target_parole": 20,
        "divario_parole": 16,
    }
    aggiungi_incipit(copione, "Ciao Jacopo.")
    assert copione["testo"] == "Ciao Jacopo.\n\nPrima notizia. Seconda notizia."
    assert copione["notizie"] == [{"titolo": "x"}]
    assert copione["incipit"] == "Ciao Jacopo."
    assert copione["divario_parole"] == 14
