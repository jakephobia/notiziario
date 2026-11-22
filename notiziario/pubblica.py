"""Pubblicazione dell'episodio come release GitHub (usato dal workflow cloud)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests


API = "https://api.github.com"
HEADERS_BASE = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "Notiziario/0.1",
}


class PubblicazioneError(Exception):
    """Errore di pubblicazione con messaggio leggibile."""


def _headers(token: str) -> dict[str, str]:
    return {**HEADERS_BASE, "Authorization": f"Bearer {token}"}


def _messaggio_http(risposta: requests.Response) -> str:
    try:
        dati = risposta.json()
        messaggio = str(dati.get("message", ""))
    except ValueError:
        messaggio = ""
    base = f"GitHub ha risposto {risposta.status_code}"
    if messaggio:
        base += f": {messaggio}"
    if risposta.status_code == 403:
        base += (
            " (controlla i permessi: contents write per la release, "
            "issues read se usi la issue delle categorie)"
        )
    return base


def trova_release(
    sessione: requests.Session, repo: str, tag: str, token: str
) -> dict | None:
    risposta = sessione.get(
        f"{API}/repos/{repo}/releases/tags/{tag}",
        headers=_headers(token),
        timeout=30,
    )
    if risposta.status_code == 404:
        return None
    if risposta.status_code >= 400:
        raise PubblicazioneError(_messaggio_http(risposta))
    try:
        return risposta.json()
    except ValueError as exc:
        raise PubblicazioneError("Risposta GitHub non JSON.") from exc


def crea_o_aggiorna_release(
    sessione: requests.Session,
    repo: str,
    tag: str,
    titolo: str,
    corpo: str,
    token: str,
) -> dict:
    esistente = trova_release(sessione, repo, tag, token)
    if esistente:
        risposta = sessione.patch(
            f"{API}/repos/{repo}/releases/{esistente['id']}",
            headers=_headers(token),
            json={
                "name": titolo,
                "body": corpo,
                "draft": False,
                "prerelease": False,
            },
            timeout=30,
        )
        if risposta.status_code >= 400:
            raise PubblicazioneError(_messaggio_http(risposta))
        return risposta.json()

    payload = {
        "tag_name": tag,
        "name": titolo,
        "body": corpo,
        "draft": False,
        "prerelease": False,
        "generate_release_notes": False,
    }
    commit = os.environ.get("GITHUB_SHA", "").strip()
    if commit:
        payload["target_commitish"] = commit
    risposta = sessione.post(
        f"{API}/repos/{repo}/releases",
        headers=_headers(token),
        json=payload,
        timeout=30,
    )
    if risposta.status_code >= 400:
        raise PubblicazioneError(_messaggio_http(risposta))
    return risposta.json()


def carica_allegato(
    sessione: requests.Session,
    release: dict,
    file_path: Path,
    token: str,
) -> dict:
    if not file_path.exists() or file_path.stat().st_size == 0:
        raise PubblicazioneError(f"File da pubblicare mancante o vuoto: {file_path}")
    if file_path.suffix.lower() != ".mp3":
        raise PubblicazioneError("La release deve contenere un file .mp3.")

    # Se esiste già un allegato con lo stesso nome (rerun), lo sostituisco.
    assets_url = release.get("assets_url") or release.get("url", "") + "/assets"
    risposta = sessione.get(assets_url, headers=_headers(token), timeout=30)
    if risposta.status_code < 400:
        for asset in risposta.json() or []:
            if asset.get("name") == file_path.name:
                elimina = sessione.delete(
                    asset["url"], headers=_headers(token), timeout=30
                )
                if elimina.status_code >= 400:
                    raise PubblicazioneError(_messaggio_http(elimina))

    upload_url = str(release.get("upload_url", "")).split("{", 1)[0]
    if not upload_url:
        raise PubblicazioneError("La release non espone upload_url.")
    with file_path.open("rb") as file_audio:
        contenuto = file_audio.read()
    risposta = sessione.post(
        upload_url,
        headers={
            **_headers(token),
            "Content-Type": "audio/mpeg",
            "Content-Length": str(len(contenuto)),
        },
        params={"name": file_path.name},
        data=contenuto,
        timeout=180,
    )
    if risposta.status_code >= 400:
        raise PubblicazioneError(_messaggio_http(risposta))
    return risposta.json()


def verifica_url_asset(url: str, timeout: int = 20) -> int:
    """HEAD sull'URL pubblico dell'enclosure; deve rispondere 200."""
    if not url.startswith(("http://", "https://")):
        raise PubblicazioneError(f"URL asset non valido: {url!r}")
    try:
        risposta = requests.head(
            url, allow_redirects=True, timeout=timeout
        )
    except requests.RequestException as exc:
        raise PubblicazioneError(
            f"HEAD non riuscita sull'asset: {type(exc).__name__}"
        ) from exc
    if risposta.status_code != 200:
        raise PubblicazioneError(
            f"Asset non raggiungibile: HTTP {risposta.status_code} su {url}"
        )
    return risposta.status_code

def pubblica(
    tag: str,
    file_path: str | Path,
    titolo: str,
    corpo: str,
    repo: str | None = None,
    token: str | None = None,
) -> dict:
    token = (token or os.environ.get("GITHUB_TOKEN", "")).strip()
    repo = (repo or os.environ.get("GITHUB_REPOSITORY", "")).strip()
    if not token:
        raise PubblicazioneError(
            "GITHUB_TOKEN assente. Nel workflow è fornito da GitHub Actions."
        )
    if not repo or "/" not in repo:
        raise PubblicazioneError(
            "Repository GitHub assente. Imposta GITHUB_REPOSITORY=owner/repo."
        )
    percorso = Path(file_path)
    with requests.Session() as sessione:
        release = crea_o_aggiorna_release(
            sessione, repo, tag, titolo, corpo, token
        )
        asset = carica_allegato(sessione, release, percorso, token)
    return {
        "release": release.get("html_url"),
        "asset": asset.get("browser_download_url"),
        "dimensione": asset.get("size"),
        "tag": tag,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Crea o aggiorna una release GitHub e allega l'mp3."
    )
    parser.add_argument("--tag", help="Es. episodio-2026-11-22")
    parser.add_argument("--file", help="Percorso dell'mp3")
    parser.add_argument("--title", help="Titolo della release")
    parser.add_argument(
        "--verifica-url",
        help="Solo verifica HEAD di un URL asset; non pubblica nulla.",
    )
    parser.add_argument("--body-file", help="File markdown con la descrizione")
    parser.add_argument("--body", default="", help="Descrizione testuale")
    parser.add_argument("--repo", help="owner/repo (default: GITHUB_REPOSITORY)")
    args = parser.parse_args(argv)

    if args.verifica_url:
        try:
            codice = verifica_url_asset(args.verifica_url)
        except PubblicazioneError as exc:
            print(f"Verifica asset fallita: {exc}", file=sys.stderr)
            return 1
        print(f"Asset raggiungibile: HTTP {codice} {args.verifica_url}")
        return 0

    if not args.tag or not args.file or not args.title:
        print("Servono --tag, --file e --title (oppure --verifica-url).", file=sys.stderr)
        return 2

    corpo = args.body
    if args.body_file:
        percorso_body = Path(args.body_file)
        if not percorso_body.exists():
            print(f"File descrizione non trovato: {percorso_body}", file=sys.stderr)
            return 1
        corpo = percorso_body.read_text(encoding="utf-8")
    corpo = corpo[:120000]

    try:
        risultato = pubblica(
            tag=args.tag,
            file_path=args.file,
            titolo=args.title,
            corpo=corpo,
            repo=args.repo,
        )
    except PubblicazioneError as exc:
        print(f"Pubblicazione non riuscita: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(
            f"Pubblicazione non riuscita: errore di rete ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(f"Release: {risultato['release']}")
    print(f"Allegato: {risultato['asset']}")
    print(f"Dimensione: {risultato['dimensione']} byte")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
