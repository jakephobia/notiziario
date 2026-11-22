from __future__ import annotations

from notiziario.config import carica_impostazioni
from notiziario.voce import normalizza_velocita, risolvi_voce, sezione_voce


def test_griglia_velocita_aggancia_e_limita():
    valore, avvisi = normalizza_velocita(1.07)
    assert valore == 1.05
    assert avvisi
    assert normalizza_velocita(1.08)[0] == 1.10
    assert normalizza_velocita(2)[0] == 1.25
    assert normalizza_velocita(0.5)[0] == 0.75
    assert normalizza_velocita("non-numero")[0] == 1.10
    for passo in (0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25):
        assert normalizza_velocita(passo)[0] == passo


def test_sezione_voce():
    corpo = """
## Voce
voce: Leda
velocita: 1,10
motore: gemini

## Altro
testo
"""
    assert sezione_voce(corpo) == {
        "voce": "Leda",
        "velocita": "1,10",
        "motore": "gemini",
    }


def test_issue_prevale_su_config():
    scelta = risolvi_voce(
        carica_impostazioni(),
        corpo_issue="## Voce\nvoce: Puck\nvelocita: 1.1\n",
    )
    assert scelta.nome == "Puck"
    assert scelta.velocita == 1.1
    assert scelta.fonte == "issue"
    assert scelta.motore == "gemini"


def test_voce_o_velocita_invalida_limita_il_bordo():
    scelta = risolvi_voce(
        carica_impostazioni(),
        corpo_issue="## Voce\nvoce: Isabella\nvelocita: 2.0\n",
    )
    assert scelta.nome == "Kore"
    assert scelta.velocita == 1.25
    assert len(scelta.avvisi) == 2


def test_cli_prevale_e_edge_mappa_voce():
    scelta = risolvi_voce(
        carica_impostazioni(),
        voce_cli="Charon",
        velocita_cli=1.1,
        motore_cli="edge",
    )
    assert scelta.nome == "it-IT-IsabellaNeural"
    assert scelta.motore == "edge"
    assert scelta.velocita == 1.1
    assert any("non è disponibile" in a for a in scelta.avvisi)
