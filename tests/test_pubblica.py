from __future__ import annotations

import pytest

from notiziario import pubblica


class Risposta:
    def __init__(self, status):
        self.status_code = status


def test_verifica_asset_200(monkeypatch):
    catturato = {}

    def head(url, **kwargs):
        catturato["url"] = url
        catturato["kwargs"] = kwargs
        return Risposta(200)

    monkeypatch.setattr(pubblica.requests, "head", head)
    assert pubblica.verifica_url_asset("https://github.com/o/r/releases/download/x/a.mp3") == 200
    assert catturato["kwargs"]["allow_redirects"] is True


def test_verifica_asset_non_200(monkeypatch):
    monkeypatch.setattr(pubblica.requests, "head", lambda *a, **k: Risposta(404))
    with pytest.raises(pubblica.PubblicazioneError):
        pubblica.verifica_url_asset("https://github.com/o/r/releases/download/x/a.mp3")


def test_cli_verifica_url(monkeypatch, capsys):
    monkeypatch.setattr(pubblica.requests, "head", lambda *a, **k: Risposta(200))
    assert pubblica.main(["--verifica-url", "https://github.com/o/r/x.mp3"]) == 0
    assert "HTTP 200" in capsys.readouterr().out
