from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from notiziario.config import carica_fonti


PAGINA = Path("docs/index.html").read_text(encoding="utf-8")
SETTINGS = Path("docs/impostazioni.json").read_text(encoding="utf-8")


def test_form_completo_e_campi_accessibili():
    for identificatore in (
        'id="nome"', 'id="incipit"', 'id="outro"', 'id="voce"',
        'id="velocita"', 'id="tts-motore"', 'id="suono"', 'id="categorie"',
        'id="fonti-lista"', 'id="nuova-fonte-nome"', 'id="importa-feed"',
        'id="token"', 'id="salva-impostazioni"', 'id="salva-genera"',
    ):
        assert identificatore in PAGINA
    assert 'type="password"' in PAGINA
    assert 'type="range"' in PAGINA
    assert 'min="0.75"' in PAGINA and 'max="1.25"' in PAGINA and 'step="0.05"' in PAGINA
    assert "Salva e genera ora" in PAGINA
    assert "Importa feed OPML, TXT, CSV o JSON" in PAGINA
    assert "DOMParser" in PAGINA
    assert 'id="modifica-impostazioni"' in PAGINA
    assert "issues/1" in PAGINA


def test_chiamata_workflow_e_token():
    assert "https://api.github.com/repos/jakephobia/notiziario/actions/workflows/dashboard.yml/dispatches" in PAGINA
    assert "ref: \"main\"" in PAGINA or 'ref:"main"' in PAGINA
    assert "genera: genera ? \"true\" : \"false\"" in PAGINA
    assert "payload: JSON.stringify(payload)" in PAGINA
    assert "Authorization" in PAGINA and "Bearer" in PAGINA
    assert "application/vnd.github+json" in PAGINA
    assert "2022-11-28" in PAGINA
    assert "localStorage" in PAGINA
    assert "notiziario.dashboard.token" in PAGINA
    assert "innerHTML" not in PAGINA
    assert not re.search(r"github_pat_[A-Za-z0-9_]{10,}|ghp_[A-Za-z0-9]{10,}|AIza[A-Za-z0-9_-]{10,}", PAGINA)
    assert "github_pat_..." in PAGINA


def test_impostazioni_pubbliche_contengono_tutte_le_fonti():
    import json

    dati = json.loads(SETTINGS)
    assert len(dati["fonti"]) == len(carica_fonti())
    assert dati["durata_default"] in {"svelto", "standard", "completo"}
    assert set(dati["fonti"][0]) == {"nome", "url", "categoria", "attivo"}
    assert all(f["url"].startswith(("http://", "https://")) for f in dati["fonti"])


def test_javascript_pagina_valido_con_node(tmp_path):
    eseguibile = shutil.which("node")
    if not eseguibile:
        return
    javascript = re.search(r"<script>(.*?)</script>", PAGINA, re.S)
    assert javascript
    percorso = tmp_path / "index.js"
    percorso.write_text(javascript.group(1), encoding="utf-8")
    risultato = subprocess.run(
        [eseguibile, "--check", str(percorso)],
        capture_output=True,
        text=True,
    )
    assert risultato.returncode == 0, risultato.stderr