from __future__ import annotations

from pathlib import Path

import yaml


def carica_workflow():
    percorso = Path(".github/workflows/dashboard.yml")
    testo = percorso.read_text(encoding="utf-8")
    dati = yaml.safe_load(testo)
    eventi = dati.get("on") or dati.get(True)
    return testo, dati, eventi


def test_workflow_dashboard_valido_e_input():
    _, dati, eventi = carica_workflow()
    dispatch = eventi["workflow_dispatch"]
    inputs = dispatch["inputs"]
    assert inputs["payload"]["required"] is True
    assert inputs["payload"]["type"] == "string"
    assert inputs["genera"]["type"] == "boolean"
    assert inputs["genera"]["default"] is True
    assert inputs["durata"]["type"] == "choice"
    assert inputs["durata"]["default"] == "standard"
    assert inputs["durata"]["options"] == ["svelto", "standard", "completo"]
    assert dati["permissions"] == {"contents": "write", "actions": "write"}


def test_workflow_ordine_applica_commit_dispatch():
    _, dati, _ = carica_workflow()
    steps = dati["jobs"]["applica"]["steps"]
    nomi = [s.get("name") for s in steps]
    assert nomi.index("Applica payload") < nomi.index("Salva configurazione")
    assert nomi.index("Salva configurazione") < nomi.index("Avvia generazione")

    applica = steps[nomi.index("Applica payload")]
    assert applica["env"]["PAYLOAD"] == "${{ inputs.payload }}"
    assert '--payload-json "$PAYLOAD" --applica-payload' in applica["run"]
    assert "inputs.payload" not in applica["run"]

    commit = steps[nomi.index("Salva configurazione")]
    assert "git add config/ docs/impostazioni.json" in commit["run"]
    assert 'git commit -m "Dashboard: aggiorna impostazioni"' in commit["run"]
    assert "git pull --rebase" in commit["run"]
    assert "git push" in commit["run"]
    assert "git rebase --abort" in commit["run"]
    assert "Nessuna modifica da committare" in commit["run"]
    assert "push --force" not in commit["run"]

    dispatch = steps[nomi.index("Avvia generazione")]
    assert dispatch["if"] == "${{ inputs.genera }}"
    assert dispatch["env"]["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"
    assert dispatch["env"]["DURATA"] == "${{ inputs.durata }}"
    assert 'gh workflow run notiziario.yml -f durata="$DURATA"' in dispatch["run"]


def test_workflow_senza_chiavi_o_segreti_hardcoded():
    testo, _, _ = carica_workflow()
    for marcatore in ("AIza", "ghp_", "github_pat_", "GEMINI_API_KEY"):
        assert marcatore not in testo
    assert "secrets.GITHUB_TOKEN" in testo
    assert "secrets." not in testo.replace("secrets.GITHUB_TOKEN", "")