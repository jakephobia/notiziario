from __future__ import annotations

import json
from pathlib import Path

import pytest

from notiziario import dashboard
from notiziario.config import DEFAULT_SETTINGS, Fonte, carica_fonti_tutte
from notiziario.fonti_io import scrivi_fonti_yaml


def fonti_demo():
    return [
        Fonte("ANSA", "https://a.test/feed", "italia", attivo=True),
        Fonte("Alternativa", "https://b.test/feed", "mondo", attivo=False),
        Fonte("Terza", "https://c.test/feed", "cultura", attivo=True),
    ]


@pytest.fixture()
def base(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "impostazioni.json").write_text(
        json.dumps(DEFAULT_SETTINGS, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (config / "incipit.txt").write_text(
        "Ciao [NOME UTENTE], oggi è [DATA].\n", encoding="utf-8"
    )
    (config / "outro.txt").write_text("A domani.\n", encoding="utf-8")
    scrivi_fonti_yaml(config / "fonti.yaml", fonti_demo())
    return tmp_path


def payload_completo():
    return {
        "nome": "Luca",
        "categorie": ["italia", "sport", "economia"],
        "incipit": "Ciao [NOME UTENTE], ecco le notizie di [DATA].",
        "outro": "Fine delle notizie. A domani!",
        "voce": "Leda",
        "velocita": 1.2,
        "motore": "edge",
        "suono": "chime",
        "fonti": [
            {
                "nome": "ANSA aggiornata",
                "url": "https://a.test/feed",
                "categoria": "mondo",
                "attivo": False,
            },
            {
                "nome": "Nuova fonte",
                "url": "https://nuovo.test/feed",
                "categoria": "economia",
                "attivo": True,
            },
        ],
        "durata": "completo",
    }


def test_payload_completo_applica(base):
    risultato = dashboard.applica_payload(payload_completo(), base=base)
    config = json.loads((base / "config" / "impostazioni.json").read_text(encoding="utf-8"))
    assert config["nome_utente"] == "Luca"
    assert config["categorie_default"] == ["italia", "sport", "economia"]
    assert config["voce"]["nome"] == "Leda"
    assert config["voce"]["velocita"] == 1.2
    assert config["tts_motore"] == "edge"
    assert config["suono_transizione"] == "chime"
    assert config["durata_default"] == "completo"
    assert (base / "config" / "incipit.txt").read_text(encoding="utf-8").strip().startswith("Ciao [NOME UTENTE]")
    assert (base / "config" / "outro.txt").read_text(encoding="utf-8").strip() == "Fine delle notizie. A domani!"
    fonti = {f.url: f for f in carica_fonti_tutte(base / "config" / "fonti.yaml")}
    assert fonti["https://a.test/feed"].nome == "ANSA aggiornata"
    assert fonti["https://a.test/feed"].categoria == "mondo"
    assert fonti["https://a.test/feed"].attivo is False
    assert fonti["https://c.test/feed"] == fonti_demo()[2]
    assert fonti["https://nuovo.test/feed"].attivo is True
    assert fonti["https://nuovo.test/feed"].controllo == "da-verificare"
    assert risultato["fonti_totali"] == 4
    assert risultato["aggiunte"] == 1
    assert risultato["aggiornate"] == 1


def test_categorie_sconosciute_e_voce_sconosciuta(base):
    payload = payload_completo()
    payload["categorie"] = ["italia", "sconosciuta", "sport"]
    payload["voce"] = "Sconosciuta"
    risultato = dashboard.applica_payload(payload, base=base)
    config = json.loads((base / "config" / "impostazioni.json").read_text(encoding="utf-8"))
    assert config["categorie_default"] == ["italia", "sport"]
    assert config["voce"]["nome"] == "Kore"
    assert any("Categoria sconosciuta" in a for a in risultato["avvisi"])
    assert any("Voce sconosciuta" in a for a in risultato["avvisi"])


def test_payload_invalido_non_scrive(base):
    settings = base / "config" / "impostazioni.json"
    fonti = base / "config" / "fonti.yaml"
    prima_settings = settings.read_bytes()
    prima_fonti = fonti.read_bytes()
    with pytest.raises(dashboard.DashboardError):
        dashboard.applica_payload({"categorie": "non-una-lista"}, base=base)
    assert settings.read_bytes() == prima_settings
    assert fonti.read_bytes() == prima_fonti


def test_dry_run_non_scrive(base):
    settings = base / "config" / "impostazioni.json"
    prima = settings.read_bytes()
    risultato = dashboard.applica_payload(payload_completo(), dry_run=True, base=base)
    assert settings.read_bytes() == prima
    assert risultato["dry_run"] is True
    assert risultato["modifiche"]


def test_idempotenza(base):
    payload = payload_completo()
    dashboard.applica_payload(payload, base=base)
    settings = (base / "config" / "impostazioni.json").read_bytes()
    fonti = (base / "config" / "fonti.yaml").read_bytes()
    secondo = dashboard.applica_payload(payload, base=base)
    assert secondo["modifiche"] == []
    assert (base / "config" / "impostazioni.json").read_bytes() == settings
    assert (base / "config" / "fonti.yaml").read_bytes() == fonti


def test_dedupe_url_normalizzata(base):
    payload = payload_completo()
    payload["fonti"].append(
        {"nome": "Duplicata", "url": "HTTPS://A.TEST/feed/", "categoria": "italia", "attivo": True}
    )
    risultato = dashboard.applica_payload(payload, base=base)
    assert any("duplicata" in a for a in risultato["avvisi"])
    fonti = carica_fonti_tutte(base / "config" / "fonti.yaml")
    assert sum(1 for f in fonti if f.url == "https://a.test/feed") == 1


def test_categoria_nuova_sconosciuta_diventa_da_assegnare(base):
    payload = payload_completo()
    payload["fonti"] = [
        {"nome": "Nuova", "url": "https://nuovo.test/feed", "categoria": "inventata", "attivo": True}
    ]
    risultato = dashboard.applica_payload(payload, base=base)
    fonti = {f.url: f for f in carica_fonti_tutte(base / "config" / "fonti.yaml")}
    assert fonti["https://nuovo.test/feed"].categoria == "da-assegnare"
    assert fonti["https://nuovo.test/feed"].attivo is False
    assert risultato["aggiunte"] == 1


def test_payload_file_e_cli(monkeypatch, base, tmp_path):
    percorso = tmp_path / "payload.json"
    percorso.write_text(json.dumps(payload_completo()), encoding="utf-8")
    monkeypatch.setattr(dashboard, "ROOT", base)
    assert dashboard.main(["--payload-file", str(percorso), "--dry-run"]) == 0
    assert dashboard.main(["--payload-json", json.dumps(payload_completo()), "--dry-run"]) == 0
    assert dashboard.main(["--payload-file", str(percorso), "--applica-payload"]) == 0
    config = json.loads((base / "config" / "impostazioni.json").read_text(encoding="utf-8"))
    assert config["nome_utente"] == "Luca"


def test_payload_vuoto_e_json_invalido():
    with pytest.raises(dashboard.DashboardError):
        dashboard.leggi_payload("")
    with pytest.raises(dashboard.DashboardError):
        dashboard.leggi_payload("{non-json")
def test_apply_payload_senza_payload_e_errore(monkeypatch, base):
    monkeypatch.setattr(dashboard, "ROOT", base)
    assert dashboard.main(["--applica-payload"]) == 1
