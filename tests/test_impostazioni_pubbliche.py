from __future__ import annotations

import json
from pathlib import Path

from notiziario.config import carica_impostazioni
from notiziario.feed import Episodio, aggiorna_docs, scrivi_impostazioni_pubbliche


def test_struttura_impostazioni_pubbliche(tmp_path):
    percorso = tmp_path / "impostazioni.json"
    dati = scrivi_impostazioni_pubbliche(
        percorso,
        categorie_attive=["italia", "buone-notizie"],
        incipit_template="Ciao [NOME UTENTE], oggi è [DATA].",
        incipit_risolto="Ciao Jacopo, oggi è 22 novembre.",
        voce="Kore",
        voce_label="Kore — femminile, calda",
        velocita=1.1,
        motore="gemini",
        data="2026-11-22",
        issue_url="https://github.com/o/r/issues/1",
        repo_url="https://github.com/o/r",
    )
    assert set(dati) == {
        "categorie_attive",
        "categorie_label",
        "incipit_template",
        "incipit_risolto",
        "voce",
        "voce_label",
        "velocita",
        "motore",
        "data",
        "issue_url",
        "repo_url",
    }
    letto = json.loads(percorso.read_text(encoding="utf-8"))
    assert letto["categorie_label"] == ["Italia", "Buone notizie"]
    assert letto["velocita"] == 1.1
    assert "GEMINI_API_KEY" not in percorso.read_text(encoding="utf-8").upper()
    assert "AIza" not in percorso.read_text(encoding="utf-8")


def test_aggiorna_docs_scrive_impostazioni(tmp_path):
    impostazioni = carica_impostazioni()
    episodio = Episodio(
        data="2026-11-22",
        titolo="Notiziario",
        descrizione="Descrizione",
        filename="notiziario-2026-11-22.mp3",
        durata_secondi=10,
        dimensione=100,
        categorie=["italia"],
        voce="Kore",
        voce_label="Kore — femminile, calda",
        velocita=1.1,
        tts_motore="gemini",
    )
    pubbliche = {
        "categorie_attive": ["italia"],
        "incipit_template": "Ciao [NOME].",
        "incipit_risolto": "Ciao Jacopo.",
        "voce": "Kore",
        "voce_label": "Kore — femminile, calda",
        "velocita": 1.1,
        "motore": "gemini",
        "data": "2026-11-22",
        "issue_url": None,
        "repo_url": "https://github.com/o/r",
    }
    aggiorna_docs(
        episodio,
        impostazioni,
        tmp_path,
        base_url="https://github.com/o/r/releases/download",
        sito_url="https://o.github.io/r/",
        impostazioni_pubbliche=pubbliche,
    )
    file = json.loads((tmp_path / "impostazioni.json").read_text(encoding="utf-8"))
    assert file["voce"] == "Kore"
    assert file["motore"] == "gemini"
    assert file["issue_url"] is None
    assert (tmp_path / "feed.xml").exists()


def test_impostazioni_iniziali_esistono_e_sono_valide():
    percorso = Path("docs/impostazioni.json")
    assert percorso.exists()
    dati = json.loads(percorso.read_text(encoding="utf-8"))
    assert dati["voce"] == "Kore"
    assert dati["velocita"] == 1.1
    assert dati["motore"] == "gemini"
    assert dati["incipit_risolto"].startswith("Ciao Jacopo")
    assert dati["repo_url"] == "https://github.com/jakephobia/notiziario"

def test_link_issue_corretto(monkeypatch):
    import copy
    from main import _issue_url
    from notiziario.config import carica_impostazioni

    impostazioni = copy.deepcopy(carica_impostazioni())
    impostazioni["github"]["issue_categorie"] = 12
    monkeypatch.setenv("GITHUB_REPOSITORY", "jakephobia/notiziario")
    assert _issue_url(impostazioni) == "https://github.com/jakephobia/notiziario/issues/12"
