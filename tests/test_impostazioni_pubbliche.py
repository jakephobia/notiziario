from __future__ import annotations

import json
from pathlib import Path

from notiziario.config import carica_fonti, carica_fonti_tutte, carica_impostazioni
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
        motore="edge",
        motore_richiesto="gemini",
        data="2026-11-22",
        nome_utente="Jacopo",
        fonti_totali=31,
        fonti_attive=31,
        suono="ding",
        outro="Queste erano le notizie.",
        issue_url="https://github.com/o/r/issues/1",
        repo_url="https://github.com/o/r",
        fonti=[
            {
                "nome": "ANSA",
                "url": "https://www.ansa.it/feed",
                "categoria": "italia",
                "attivo": True,
            }
        ],
    )
    assert set(dati) == {
        "categorie_attive",
        "categorie_label",
        "incipit_template",
        "incipit_risolto",
        "voce",
        "voce_label",
        "voce_configurata",
        "durata_default",
        "orario_generazione",
        "velocita",
        "motore",
        "motore_richiesto",
        "data",
        "nome_utente",
        "fonti_totali",
        "fonti_attive",
        "suono",
        "outro",
        "issue_url",
        "repo_url",
        "fonti",
    }
    letto = json.loads(percorso.read_text(encoding="utf-8"))
    assert letto["categorie_label"] == ["Italia", "Buone notizie"]
    assert letto["motore"] == "edge"
    assert letto["motore_richiesto"] == "gemini"
    assert letto["velocita"] == 1.1
    assert letto["nome_utente"] == "Jacopo"
    assert letto["fonti_totali"] == 31
    assert letto["fonti_attive"] == 31
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
        "motore_richiesto": "gemini",
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
    assert dati["voce"] == "it-IT-IsabellaNeural"
    assert dati["velocita"] == carica_impostazioni()["voce"]["velocita"]
    assert dati["motore"] == "edge"
    assert dati["motore_richiesto"] == "google"
    assert dati["voce_configurata"] == "Kore"
    assert dati["durata_default"] in {"svelto", "standard", "completo"}
    assert dati["orario_generazione"] == "07:00"
    assert len(dati["fonti"]) == len(carica_fonti_tutte())
    assert dati["fonti_totali"] == len(carica_fonti_tutte())
    assert dati["fonti_attive"] == len(carica_fonti())
    assert dati["fonti"][0].keys() == {"nome", "url", "categoria", "attivo"}
    incipit = dati["incipit_risolto"]
    assert incipit.startswith("Ciao")
    assert "Jacopo" in incipit
    assert "[" not in incipit and "]" not in incipit
    assert dati["repo_url"] == "https://github.com/jakephobia/notiziario"

def test_link_issue_corretto(monkeypatch):
    import copy
    from main import _issue_url

    impostazioni = copy.deepcopy(carica_impostazioni())
    impostazioni["github"]["issue_categorie"] = 12
    monkeypatch.setenv("GITHUB_REPOSITORY", "jakephobia/notiziario")
    assert _issue_url(impostazioni) == "https://github.com/jakephobia/notiziario/issues/12"

def test_motore_richiesto_deriva_da_configurazione(tmp_path):
    dati = scrivi_impostazioni_pubbliche(
        tmp_path / "impostazioni.json",
        categorie_attive=["italia"],
        incipit_template="Ciao [NOME].",
        incipit_risolto="Ciao Jacopo.",
        voce="it-IT-IsabellaNeural",
        voce_label="Isabella (edge-tts)",
        velocita=1.1,
        motore="edge",
        motore_configurato="gemini",
        data="2026-11-22",
    )
    assert dati["motore"] == "edge"
    assert dati["motore_richiesto"] == "gemini"
