from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_release_bloccante_e_ordine():
    percorso = ROOT / ".github" / "workflows" / "notiziario.yml"
    dati = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    passi = dati["jobs"]["episodio"]["steps"]
    nomi = [p.get("name", "") for p in passi]
    release = next(p for p in passi if p.get("name") == "Pubblica release con mp3")
    assert "continue-on-error" not in release
    verifica = next(p for p in passi if p.get("name") == "Verifica asset release")
    assert "--verifica-url" in verifica["run"]
    indice_release = nomi.index("Pubblica release con mp3")
    indice_verifica = nomi.index("Verifica asset release")
    indice_feed = nomi.index("Aggiorna feed, sito e stato nel repository")
    assert indice_release < indice_verifica < indice_feed
    # Pages legacy pubblica docs/ da main: niente step di deploy nel workflow.
    assert "Deploy Pages" not in nomi
    assert "Carica artefatto Pages" not in nomi


def test_workflow_tests_senza_segreti():
    percorso = ROOT / ".github" / "workflows" / "tests.yml"
    dati = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    assert "test" in dati["jobs"]
    testo = percorso.read_text(encoding="utf-8")
    assert "secrets." not in testo
    assert "pytest" in testo


def test_workflow_anteprima_velocita_110():
    percorso = ROOT / ".github" / "workflows" / "anteprima-voce.yml"
    testo = percorso.read_text(encoding="utf-8")
    assert "0.75-1.25" in testo
    assert 'default: "1.1"' in testo
