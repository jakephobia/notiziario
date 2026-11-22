from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from notiziario import dashboard
from notiziario.config import Fonte, carica_fonti_tutte, carica_impostazioni
from notiziario.controllo_feed import EsitoControllo


def fonti_demo():
    return [
        Fonte("ANSA", "https://a.test/feed", "italia", attivo=True),
        Fonte("Alternativa", "https://b.test/feed", "mondo", attivo=False),
        Fonte("Terza", "https://c.test/feed", "cultura", attivo=True),
    ]


def esito(fonte, stato="ok"):
    return EsitoControllo(
        fonte=fonte.nome,
        url=fonte.url,
        categoria=fonte.categoria,
        attivo=False,
        stato=stato,
    )


def test_parse_nome():
    assert dashboard.parse_nome("## Nome\nnome: Luca\n")[0] == "Luca"
    nome, avvisi = dashboard.parse_nome("## Nome\nnome:   \n")
    assert nome is None and avvisi
    nome, avvisi = dashboard.parse_nome("## Nome\nnome: A\nnome: B\n")
    assert nome is None and avvisi


def test_parse_fonti_per_url_e_nome_preserva_non_citate():
    corpo = """## Fonti
- [ ] ANSA (mondo) — https://a.test/feed
- [x] Alternativa (da-assegnare) — https://b.test/feed
- [ ] Terza (sport) — https://c.test/feed
"""
    aggiornate, avvisi = dashboard.parse_fonti(corpo, fonti_demo())
    assert avvisi == []
    assert aggiornate[0].attivo is False
    assert aggiornate[0].categoria == "mondo"
    assert aggiornate[1].attivo is True
    assert aggiornate[1].categoria == "mondo"  # da-assegnare lascia l'esistente
    assert aggiornate[2].attivo is False
    assert aggiornate[2].categoria == "sport"


def test_parse_fonti_ignora_url_non_in_config_e_blocca_malformata():
    corpo = "## Fonti\n- [x] Sconosciuta (italia) — https://nuovo.test/feed\n"
    aggiornate, avvisi = dashboard.parse_fonti(corpo, fonti_demo())
    assert aggiornate == fonti_demo()
    assert any("non presente" in a for a in avvisi)

    malformata = "## Fonti\nquesta riga non va bene\n"
    aggiornate2, avvisi2 = dashboard.parse_fonti(malformata, fonti_demo())
    assert aggiornate2 == fonti_demo()
    assert any("malformata" in a for a in avvisi2)


def test_import_opml_aggiunge_inattive_e_scarta_podcast(monkeypatch):
    corpo = """## Import feed
<opml><body>
<outline text="Buona" xmlUrl="https://nuovo.test/feed" category="economia"/>
<outline text="Podcast" xmlUrl="https://podcast.test/feed" category="cultura"/>
</body></opml>
"""
    nuove = [
        Fonte("Buona", "https://nuovo.test/feed", "economia", attivo=False),
        Fonte("Podcast", "https://podcast.test/feed", "cultura", attivo=False),
    ]

    def finto_controlla(fonti, *args, **kwargs):
        return [esito(f, "podcast" if "podcast" in f.url else "ok") for f in fonti]

    monkeypatch.setattr(dashboard, "controlla_tutte", finto_controlla)
    merged, aggiunte, duplicate, scartate, avvisi, blocco = dashboard.parse_import(
        corpo, carica_impostazioni(), fonti_demo()
    )
    assert aggiunte == 1
    assert scartate == 1
    assert any(f.url == "https://nuovo.test/feed" and not f.attivo for f in merged)
    assert all("podcast.test" not in f.url for f in merged)
    assert blocco == "Import completato: 1 aggiunte, 0 duplicate, 1 scartate."
    assert any("podcast" in a for a in avvisi)


def test_import_idempotente_dopo_blocco(monkeypatch):
    corpo = "## Import feed\nImport completato: 2 aggiunte, 0 duplicate, 0 scartate.\n"
    merged, aggiunte, duplicate, scartate, avvisi, blocco = dashboard.parse_import(
        corpo, carica_impostazioni(), fonti_demo()
    )
    assert merged == fonti_demo()
    assert (aggiunte, duplicate, scartate) == (0, 0, 0)
    assert blocco == "Import completato: 2 aggiunte, 0 duplicate, 0 scartate."


def test_import_url_per_riga(monkeypatch):
    corpo = "## Import feed\nhttps://nuovo.test/feed\nhttps://a.test/feed\n"
    monkeypatch.setattr(
        dashboard,
        "controlla_tutte",
        lambda fonti, *a, **k: [esito(f, "ok") for f in fonti],
    )
    merged, aggiunte, duplicate, scartate, avvisi, blocco = dashboard.parse_import(
        corpo, carica_impostazioni(), fonti_demo()
    )
    assert aggiunte == 1
    assert duplicate == 1
    assert scartate == 0
    assert any(f.url == "https://nuovo.test/feed" for f in merged)


def test_genera_corpo_e_riparsabile():
    corpo = dashboard.genera_corpo(
        carica_impostazioni(),
        carica_fonti_tutte(),
        "Ciao [NOME UTENTE], oggi è [DATA].",
    )
    assert "## Nome" in corpo
    assert "## Fonti" in corpo
    assert corpo.count("— https://") == len(carica_fonti_tutte())
    assert dashboard.parse_nome(corpo)[0] == "Jacopo"
    fonti, avvisi = dashboard.parse_fonti(corpo, carica_fonti_tutte())
    assert len(fonti) == len(carica_fonti_tutte())
    assert avvisi == []


def test_body_oltre_limite_rifiutato(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token-test")
    monkeypatch.setattr(dashboard, "repository_github", lambda: "o/r")
    monkeypatch.setattr(dashboard, "numero_issue_categorie", lambda _: 1)
    monkeypatch.setattr(dashboard, "leggi_issue", lambda *a, **k: "x" * 60001)
    with pytest.raises(dashboard.DashboardError):
        dashboard.applica(dry_run=True)


def test_applica_scrive_solo_sezioni_previste(monkeypatch, tmp_path):
    impostazioni = copy.deepcopy(carica_impostazioni())
    fonti = fonti_demo()
    (tmp_path / "config").mkdir()
    corpo = """## Nome
nome: Luca

## Categorie
- [x] Italia

## Incipit
Ciao [NOME], buongiorno.

## Voce
voce: Kore
velocita: 1.1
motore: gemini

## Suono
suono: chime

## Outro
Queste erano le notizie. A domani!

## Fonti
- [ ] ANSA (mondo) — https://a.test/feed

## Import feed
https://nuovo.test/feed
"""
    catturato = {}

    def patch(url, **kwargs):
        catturato["url"] = url
        catturato["body"] = kwargs["json"]["body"]
        class R:
            status_code = 200
        return R()

    monkeypatch.setattr(dashboard, "ROOT", tmp_path)
    monkeypatch.setattr(dashboard, "carica_impostazioni", lambda: impostazioni)
    monkeypatch.setattr(dashboard, "carica_fonti_tutte", lambda: fonti)
    monkeypatch.setattr(dashboard, "repository_github", lambda: "o/r")
    monkeypatch.setattr(dashboard, "numero_issue_categorie", lambda _: 1)
    monkeypatch.setattr(dashboard, "leggi_issue", lambda *a, **k: corpo)
    monkeypatch.setattr(dashboard, "controlla_tutte", lambda fs, *a, **k: [esito(f, "ok") for f in fs])
    monkeypatch.setenv("GITHUB_TOKEN", "token-test")
    monkeypatch.setattr(dashboard.requests, "patch", patch)

    risultato = dashboard.applica(dry_run=False)
    assert risultato["nome"] == "Luca"
    assert catturato["url"].endswith("/repos/o/r/issues/1")
    aggiornato = catturato["body"]
    assert aggiornato.startswith("## Nome\nnome: Luca")
    assert "## Categorie\n- [x] Italia" in aggiornato
    assert "Ciao [NOME], buongiorno." in aggiornato
    assert "voce: Kore" in aggiornato
    assert "## Suono\nsuono: chime" in aggiornato
    assert "## Outro\nQueste erano le notizie. A domani!" in aggiornato
    assert "- [ ] ANSA (mondo) — https://a.test/feed" in aggiornato
    assert "- [ ] nuovo.test (da-assegnare) — https://nuovo.test/feed" in aggiornato
    assert "Import completato: 1 aggiunte, 0 duplicate, 0 scartate." in aggiornato
    config = json.loads((tmp_path / "config" / "impostazioni.json").read_text(encoding="utf-8"))
    assert config["nome_utente"] == "Luca"
    assert config["suono_transizione"] == "chime"
    assert (tmp_path / "config" / "outro.txt").read_text(encoding="utf-8").strip() == "Queste erano le notizie. A domani!"
    yaml = (tmp_path / "config" / "fonti.yaml").read_text(encoding="utf-8")
    assert "https://nuovo.test/feed" in yaml

def test_parse_suono_e_outro():
    corpo = """## Suono
suono: chime

## Outro
Queste erano le notizie. A domani!
"""
    assert dashboard.parse_suono(corpo) == ("chime", [])
    assert dashboard.parse_outro(corpo)[0] == "Queste erano le notizie. A domani!"
    assert dashboard.parse_suono("## Suono\nsuono: strano\n")[0] == "ding"
    assert dashboard.parse_outro("## Outro\n   ")[0].startswith("Queste erano")


def test_genera_corpo_include_suono_e_outro():
    corpo = dashboard.genera_corpo(
        carica_impostazioni(),
        carica_fonti_tutte(),
        "Ciao [NOME], [DATA].",
        "Queste erano le notizie. A domani!",
    )
    assert "## Suono\nsuono: ding" in corpo
    assert "## Outro\nQueste erano le notizie. A domani!" in corpo
