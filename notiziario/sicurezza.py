"""SSRF, redirect e limiti di download per URL esterni."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import requests


class UrlRifiutato(Exception):
    """URL non pubblico o schema non consentito."""


class FetchHttpError(Exception):
    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} su {url}")
        self.status = status
        self.url = url


def _ip_pubblica(testo: str) -> bool:
    try:
        ip = ipaddress.ip_address(testo)
    except ValueError:
        return False
    return ip.is_global


def valida_url_pubblica(url: str, risolvi: bool = True) -> str:
    """Accetta solo http/https verso host pubblici.

    Se il DNS non risolve, lascia passare la validazione: il fetch successivo
    fallirà comunque e non c'è rischio di raggiungere un host privato.
    """
    if not url or not isinstance(url, str):
        raise UrlRifiutato("URL vuoto")
    parti = urlsplit(url.strip())
    if parti.scheme not in {"http", "https"}:
        raise UrlRifiutato(f"schema non consentito: {parti.scheme}")
    if parti.username or parti.password:
        raise UrlRifiutato("credenziali nell'URL non consentite")
    host = (parti.hostname or "").strip().casefold()
    if not host:
        raise UrlRifiutato("host mancante")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise UrlRifiutato(f"host locale non consentito: {host}")
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise UrlRifiutato(f"IP non pubblico: {host}")
        return url
    except ValueError:
        pass

    if not risolvi:
        return url
    try:
        porta = parti.port or (443 if parti.scheme == "https" else 80)
    except ValueError as exc:
        raise UrlRifiutato("porta non valida") from exc
    try:
        risultati = socket.getaddrinfo(host, porta, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return url
    for risultato in risultati:
        indirizzo = risultato[4][0]
        if not _ip_pubblica(indirizzo):
            raise UrlRifiutato(f"{host} risolve su un IP non pubblico: {indirizzo}")
    return url


def fetch_con_limite(
    url: str,
    timeout: int = 15,
    max_bytes: int = 2_000_000,
    max_redirect: int = 3,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str, int]:
    """Scarica seguendo redirect validati, con limite dimensione."""
    corrente = url
    for _ in range(max_redirect + 1):
        valida_url_pubblica(corrente, risolvi=True)
        risposta = requests.get(
            corrente,
            headers=headers or {},
            timeout=timeout,
            stream=True,
            allow_redirects=False,
        )
        try:
            if risposta.status_code in (301, 302, 303, 307, 308):
                location = risposta.headers.get("Location")
                if not location:
                    raise UrlRifiutato("redirect senza Location")
                corrente = urljoin(corrente, location)
                continue
            if risposta.status_code >= 400:
                raise FetchHttpError(risposta.status_code, corrente)
            lunghezza = risposta.headers.get("Content-Length")
            try:
                troppa = bool(lunghezza) and int(lunghezza) > max_bytes
            except ValueError:
                troppa = False
            if troppa:
                raise UrlRifiutato(f"file troppo grande: {lunghezza} byte")
            pezzi: list[bytes] = []
            totale = 0
            for chunk in risposta.iter_content(65536):
                if not chunk:
                    continue
                totale += len(chunk)
                if totale > max_bytes:
                    raise UrlRifiutato(f"download oltre {max_bytes} byte")
                pezzi.append(chunk)
            return b"".join(pezzi), corrente, risposta.status_code
        finally:
            risposta.close()
    raise UrlRifiutato("troppi redirect")


def headers_browser(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
    }
