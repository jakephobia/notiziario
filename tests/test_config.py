from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from notiziario.categorie import CATEGORIE_IDS
from notiziario.config import (
    ConfigError,
    carica_fonti,
    carica_impostazioni,
    valida_impostazioni,
)


ROOT = Path(__file__).resolve().parents[1]


def test_impostazioni_reali_valide():
    impostazioni = carica_impostazioni()
    assert set(impostazioni["preset"]) == {"svelto", "standard", "completo"}
    assert impostazioni["durata_default"] in impostazioni["preset"]
    assert impostazioni["orario_generazione"] == "07:00"
    assert impostazioni["tts_motore"] == "google"
    assert impostazioni["voce"]["nome"] == "Kore"
    velocita = impostazioni["voce"]["velocita"]
    assert 0.75 <= velocita <= 1.25
    assert round(velocita * 100) % 5 == 0
    assert impostazioni["silenzio_iniziale_ms"] == 1000
    assert impostazioni["tts_chunk_max_caratteri"] == 4500
    assert impostazioni["tts_motore"] in {"gemini", "edge", "google"}
    assert impostazioni["tts_google"]["lingua"] == "it-IT"
    assert impostazioni["tts_google"]["max_caratteri_chunk"] == 3000
    assert impostazioni["tts_google"]["timeout"] == 90
    assert impostazioni["tts_google"]["endpoint"].startswith("https://")
    assert impostazioni["voce"]["google"]["nome"] == "it-IT-Chirp3-HD-Kore"
    assert impostazioni["voce"]["google"]["voci"]["Leda"] == "it-IT-Chirp3-HD-Leda"
    assert impostazioni["llm_modello_riserva"]
    assert impostazioni["llm_modello_traduzione"] == "gemini-3.1-flash-lite"
    assert impostazioni["voce"]["edge"]["nome"] == "it-IT-IsabellaNeural"
    assert {v["nome"] for v in impostazioni["voce"]["voci"]} == {
        "Kore",
        "Leda",
        "Charon",
        "Puck",
    }
    assert impostazioni["feed"]["max_episodi"] == 60
    assert "buone-notizie" in impostazioni["categorie_default"]
    assert "cronaca" in impostazioni["categorie_default"]
    assert "approfondimento" in impostazioni["categorie_default"]
    assert "cronaca-nera" not in impostazioni["categorie_default"]
    assert "promozione" not in impostazioni["categorie_default"]
    assert "economia" not in impostazioni["categorie_default"]
    assert "cultura" not in impostazioni["categorie_default"]
    assert "sport" not in impostazioni["categorie_default"]
    assert impostazioni["nome_utente"] == "Jacopo"
    assert impostazioni["preset"]["svelto"]["max_notizie"] == 12
    assert impostazioni["preset"]["standard"]["max_notizie"] == 18
    assert impostazioni["preset"]["completo"]["max_notizie"] == 24
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
    assert permessi["issues"] == "write"
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


def test_llm_revisione_valido_e_protetto():
    impostazioni = carica_impostazioni()
    revisione = impostazioni["llm_revisione"]
    assert revisione["modello"] == "gemini-2.5-flash"
    assert revisione["temperatura"] == 0.15
    assert revisione["max_output_tokens"] == 16384
    # Le chiavi storiche della traduzione non sono state toccate.
    assert impostazioni["llm_modello_traduzione"] == "gemini-3.1-flash-lite"
    assert impostazioni["llm_modello_riserva"] == "gemini-3.1-flash-lite"

    for chiave, valore in (
        ("modello", ""),
        ("modello", 5),
        ("temperatura", -0.1),
        ("temperatura", 2.1),
        ("max_output_tokens", 999),
        ("max_output_tokens", 65537),
    ):
        rotto = copy.deepcopy(impostazioni)
        rotto["llm_revisione"][chiave] = valore
        with pytest.raises(ConfigError):
            valida_impostazioni(rotto)
