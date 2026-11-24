from __future__ import annotations

import json
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


def test_workflow_durata_coerente_con_config():
    percorso = ROOT / ".github" / "workflows" / "notiziario.yml"
    dati = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    eventi = dati.get("on") or dati.get(True)
    config = json.loads(
        (ROOT / "config" / "impostazioni.json").read_text(encoding="utf-8-sig")
    )
    attesa = config["durata_default"]
    input_durata = eventi["workflow_dispatch"]["inputs"]["durata"]
    assert input_durata["default"] == attesa
    assert attesa in input_durata["options"]
    passo = next(
        p
        for p in dati["jobs"]["episodio"]["steps"]
        if p.get("name") == "Genera episodio"
    )
    assert f"|| '{attesa}'" in passo["run"]


def test_workflow_orario_e_dispatch_manuale():
    percorso = ROOT / ".github" / "workflows" / "notiziario.yml"
    dati = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    eventi = dati.get("on") or dati.get(True)
    assert eventi["schedule"][0]["cron"] == "*/30 * * * *"
    passi = dati["jobs"]["episodio"]["steps"]
    nomi = [p.get("name", "") for p in passi]
    controllo = next(p for p in passi if p.get("name") == "Controlla orario")
    assert controllo["id"] == "orario"
    assert "python -m notiziario.orario --controlla" in controllo["run"]
    condizione = (
        "${{ github.event_name == 'workflow_dispatch' || "
        "steps.orario.outputs.run == 'true' }}"
    )
    for nome in (
        "Applica dashboard",
        "Genera episodio",
        "Pubblica release con mp3",
        "Verifica asset release",
        "Aggiorna feed, sito e stato nel repository",
    ):
        passo = next(p for p in passi if p.get("name") == nome)
        assert passo.get("if") == condizione
    assert nomi.index("Controlla orario") < nomi.index("Genera episodio")


def test_workflow_notifiche_issue_e_email():
    percorso = ROOT / ".github" / "workflows" / "notiziario.yml"
    dati = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    passi = dati["jobs"]["episodio"]["steps"]
    nomi = [p.get("name") for p in passi]
    assert nomi.index("Aggiorna feed, sito e stato nel repository") < nomi.index("Notifica episodio")
    assert nomi.index("Notifica episodio") < nomi.index("Email episodio")

    notifica = passi[nomi.index("Notifica episodio")]
    assert notifica.get("continue-on-error") is True
    assert notifica["env"]["ISSUE_NOTIFICHE"] == "${{ vars.ISSUE_NOTIFICHE }}"
    assert "gh issue comment \"$ISSUE_NOTIFICHE\" --body-file" in notifica["run"]
    assert "ISSUE_NOTIFICHE non impostata" in notifica["run"]

    email = passi[nomi.index("Email episodio")]
    assert email.get("continue-on-error") is True
    assert "env.MAIL_TO != ''" in email["if"]
    assert "--email" in email["run"]
    for chiave in ("MAIL_TO", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD"):
        assert f"secrets.{chiave}" in email["env"][chiave]

    testo = percorso.read_text(encoding="utf-8")
    for marcatore in ("password-segreta", "AIza", "ghp_", "github_pat_"):
        assert marcatore not in testo

def test_workflow_commit_pull_rebase_push_e_caso_vuoto():
    percorso = ROOT / ".github" / "workflows" / "notiziario.yml"
    dati = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    passi = dati["jobs"]["episodio"]["steps"]
    passo = next(p for p in passi if p.get("name") == "Aggiorna feed, sito e stato nel repository")
    run = passo["run"]
    assert 'git commit -m "Aggiorna feed notiziario' in run
    assert "git pull --rebase" in run
    assert "git push" in run
    assert run.index("git commit") < run.index("git pull --rebase") < run.index("git push")
    assert "Nessuna modifica da committare" in run
    assert "git diff --cached --quiet" in run
    assert "git rebase --abort" in run
    assert "push --force" not in run

def test_workflow_genera_episodio_espone_chiave_google():
    percorso = ROOT / ".github" / "workflows" / "notiziario.yml"
    dati = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    passi = dati["jobs"]["episodio"]["steps"]
    passo = next(p for p in passi if p.get("name") == "Genera episodio")
    assert passo["env"]["GOOGLE_CLOUD_TTS_API_KEY"] == (
        "${{ secrets.GOOGLE_CLOUD_TTS_API_KEY }}"
    )


def test_workflow_prove_voci_google():
    percorso = ROOT / ".github" / "workflows" / "voci-google.yml"
    dati = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    eventi = dati.get("on") or dati.get(True)
    assert "workflow_dispatch" in eventi
    passi = dati["jobs"]["campioni"]["steps"]
    testo = percorso.read_text(encoding="utf-8")
    assert "python scripts/prova_voci_google.py" in testo
    assert "python-version: \"3.11\"" in testo
    upload = next(p for p in passi if "upload-artifact" in p.get("uses", ""))
    assert upload["with"]["name"] == "prove-voci"
    assert "output/prove-voci" in upload["with"]["path"]
    assert "output/voci-google.json" in upload["with"]["path"]
    assert "git push" not in testo
    assert "git commit" not in testo

def test_dashboard_workflow_passa_taglio_e_durata():
    percorso = ROOT / ".github" / "workflows" / "dashboard.yml"
    dati = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    eventi = dati.get("on") or dati.get(True)
    inputs = eventi["workflow_dispatch"]["inputs"]
    config = json.loads(
        (ROOT / "config" / "impostazioni.json").read_text(encoding="utf-8-sig")
    )
    assert inputs["durata"]["default"] == config["durata_default"]
    assert "adesso" in inputs
    passo = next(
        p
        for p in dati["jobs"]["applica"]["steps"]
        if p.get("name") == "Avvia generazione"
    )
    assert "ADESSO" in passo["run"]
    assert "-f adesso=" in passo["run"]
