from __future__ import annotations

from pathlib import Path

import yaml

from notiziario.categorie import CATEGORIE_IDS
from notiziario.config import carica_fonti, carica_impostazioni


ROOT = Path(__file__).resolve().parents[1]


def test_impostazioni_reali_valide():
    impostazioni = carica_impostazioni()
    assert set(impostazioni["preset"]) == {"svelto", "standard", "completo"}
    assert impostazioni["durata_default"] == "standard"
    assert impostazioni["tts_motore"] == "gemini"
    assert impostazioni["voce"]["nome"] == "Kore"
    assert impostazioni["voce"]["velocita"] == 1.1
    assert impostazioni["silenzio_iniziale_ms"] == 1000
    assert impostazioni["tts_chunk_max_caratteri"] == 4500
    assert impostazioni["llm_modello_riserva"]
    assert impostazioni["voce"]["edge"]["nome"] == "it-IT-IsabellaNeural"
    assert {v["nome"] for v in impostazioni["voce"]["voci"]} >= {"Kore", "Leda", "Charon", "Puck", "Orus"}
    assert impostazioni["feed"]["max_episodi"] == 60
    assert "buone-notizie" in impostazioni["categorie_default"]
    assert impostazioni["nome_utente"] == "Jacopo"
    assert impostazioni["preset"]["svelto"]["max_notizie"] == 6
    assert impostazioni["preset"]["standard"]["max_notizie"] == 10
    assert impostazioni["preset"]["completo"]["max_notizie"] == 14
    assert impostazioni["preset"]["standard"]["buone_notizie"] == 2
    assert impostazioni["controllo_feed"]["min_caratteri_testo"] == 40
    assert impostazioni["arricchimento"]["attivo"] is True
    assert impostazioni["feed"]["sito_url"] == "https://jakephobia.github.io/notiziario/"
    assert impostazioni["feed"]["titolo"] == "Il notiziario di Jacopo"
    assert 0 <= impostazioni["clustering"]["soglia"] <= 1


def test_fonti_reali_valide_e_uniche():
    fonti = carica_fonti()
    assert len(fonti) >= 30
    assert len({f.url for f in fonti}) == len(fonti)
    for fonte in fonti:
        assert fonte.url.startswith(("http://", "https://"))
        assert fonte.categoria in CATEGORIE_IDS
        assert fonte.nome
    nomi = {f.nome for f in fonti}
    assert {"ANSA", "Repubblica", "Il Post", "Il Sole 24 Ore", "HDblog"} <= nomi
    assert any(f.categoria == "buone-notizie" for f in fonti)
    assert all(f.attivo for f in fonti)


def test_workflow_yaml_valido_con_safe_load():
    percorso = ROOT / ".github" / "workflows" / "notiziario.yml"
    dati = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    assert isinstance(dati, dict)
    assert "jobs" in dati
    assert "episodio" in dati["jobs"]
    permessi = dati["permissions"]
    assert permessi["contents"] == "write"
    assert permessi["issues"] == "read"
    assert "pages" not in permessi
    assert "id-token" not in permessi
    passi = dati["jobs"]["episodio"]["steps"]
    usi = [p.get("uses", "") for p in passi]
    assert any("setup-python" in u for u in usi)
    # Pages legacy: pubblica docs/ da main, nessun artifact/deploy action.
    assert not any("upload-pages-artifact" in u for u in usi)
    assert not any("deploy-pages" in u for u in usi)
    testo = percorso.read_text(encoding="utf-8")
    assert "state/visti.json" in testo
    assert "--feed-site-url" in testo
    release = next(p for p in passi if p.get("name", "").startswith("Pubblica release"))
    assert release.get("continue-on-error") is not True
    assert any(p.get("name") == "Verifica asset release" for p in passi)
    anteprima = ROOT / ".github" / "workflows" / "anteprima-voce.yml"
    dati_anteprima = yaml.safe_load(anteprima.read_text(encoding="utf-8"))
    assert "anteprima" in dati_anteprima["jobs"]
    passi_anteprima = dati_anteprima["jobs"]["anteprima"]["steps"]
    assert any("upload-artifact" in p.get("uses", "") for p in passi_anteprima)
    assert "workflow_dispatch" in anteprima.read_text(encoding="utf-8")


def test_sito_url_da_github_repository(monkeypatch):
    import argparse

    from main import _sito_url

    impostazioni = carica_impostazioni()
    args = argparse.Namespace(feed_site_url=None)
    monkeypatch.setenv("GITHUB_REPOSITORY", "mario/notiziario")
    assert _sito_url(args, impostazioni) == "https://mario.github.io/notiziario/"
    monkeypatch.setenv("GITHUB_REPOSITORY", "mario/mario.github.io")
    assert _sito_url(args, impostazioni) == "https://mario.github.io/"
    args.feed_site_url = "https://owner.test/sito/"
    assert _sito_url(args, impostazioni) == "https://owner.test/sito/"
    args.feed_site_url = "https://jakephobia.github.io/jakephobia.github.io/"
    assert _sito_url(args, impostazioni) == "https://jakephobia.github.io/"


def test_preset_e_intervalli_coerenti():
    impostazioni = carica_impostazioni()
    for nome, preset in impostazioni["preset"].items():
        assert preset["copertine"] <= preset["max_notizie"]
        assert preset["secondarie"] <= preset["max_notizie"]
        assert preset["parole_copertina"] >= impostazioni["intervallo_copertina"][0]
        assert preset["parole_secondaria"] >= impostazioni["intervallo_secondaria"][0]
