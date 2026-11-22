from __future__ import annotations

import pytest

from notiziario import sicurezza


class Risposta:
    def __init__(self, status=200, headers=None, content=b""):
        self.status_code = status
        self.headers = headers or {}
        self._content = content
        self.closed = False

    def iter_content(self, size):
        if self._content:
            yield self._content

    def close(self):
        self.closed = True


def test_redirect_verso_loopback_rifiutato(monkeypatch):
    chiamate = []

    def get(url, **kwargs):
        chiamate.append((url, kwargs))
        return Risposta(302, {"Location": "http://127.0.0.1:8080/segreti"})

    monkeypatch.setattr(sicurezza.requests, "get", get)
    with pytest.raises(sicurezza.UrlRifiutato):
        sicurezza.fetch_con_limite("https://pubblico.test/start")
    assert len(chiamate) == 1
    assert chiamate[0][1]["allow_redirects"] is False


def test_redirect_legittimo_passa(monkeypatch):
    chiamate = []

    def get(url, **kwargs):
        chiamate.append((url, kwargs))
        if url == "https://pubblico.test/start":
            return Risposta(302, {"Location": "https://cdn.test/feed"})
        return Risposta(200, {"Content-Length": "5"}, b"hello")

    monkeypatch.setattr(sicurezza.requests, "get", get)
    contenuto, finale, stato = sicurezza.fetch_con_limite(
        "https://pubblico.test/start"
    )
    assert contenuto == b"hello"
    assert finale == "https://cdn.test/feed"
    assert stato == 200
    assert len(chiamate) == 2
    assert all(k[1]["allow_redirects"] is False for k in chiamate)


def test_redirect_troppi(monkeypatch):
    def get(url, **kwargs):
        return Risposta(302, {"Location": "/ancora"})

    monkeypatch.setattr(sicurezza.requests, "get", get)
    with pytest.raises(sicurezza.UrlRifiutato):
        sicurezza.fetch_con_limite("https://pubblico.test/start", max_redirect=2)


def test_limite_streaming(monkeypatch):
    def get(url, **kwargs):
        return Risposta(200, {}, b"x" * 100)

    monkeypatch.setattr(sicurezza.requests, "get", get)
    with pytest.raises(sicurezza.UrlRifiutato):
        sicurezza.fetch_con_limite(
            "https://pubblico.test/feed", max_bytes=50
        )
