from __future__ import annotations

import json
from pathlib import Path

from notiziario.notifica import invia_email, main, messaggio_episodio


def test_messaggio_episodio_contiene_link_e_durata():
    messaggio = messaggio_episodio(
        titolo="Notiziario di prova",
        data="2026-11-22",
        durata=428,
        descrizione="Le notizie del giorno.",
        player_url="https://esempio.test/player/",
        feed_url="https://esempio.test/feed.xml",
        mp3_url="https://esempio.test/audio.mp3",
    )
    assert "## Nuovo episodio" in messaggio
    assert "**Notiziario di prova**" in messaggio
    assert "2026-11-22" in messaggio
    assert "7 min 8 s" in messaggio
    assert "Le notizie del giorno." in messaggio
    for link in ("player/", "feed.xml", "audio.mp3"):
        assert link in messaggio


def test_messaggio_episodio_tronca_descrizione_lunga():
    messaggio = messaggio_episodio(
        "Titolo", "2026-11-22", "standard", "parola " * 100, "p", "f", "m"
    )
    assert len(messaggio) < 1000
    assert "..." in messaggio


def test_email_non_configurata_non_chiama_smtp(capsys):
    chiamata = {"n": 0}

    def factory(*args, **kwargs):
        chiamata["n"] += 1
        raise AssertionError("non deve essere chiamata")

    esito = invia_email("test", env={}, smtp_factory=factory)
    assert esito is None
    assert chiamata["n"] == 0
    assert "email non configurata" in capsys.readouterr().out


def test_email_inviata_con_mock():
    eventi = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=20):
            eventi.append(("connect", host, port, timeout))

        def ehlo(self):
            eventi.append(("ehlo",))

        def starttls(self):
            eventi.append(("starttls",))

        def login(self, utente, password):
            eventi.append(("login", utente))

        def sendmail(self, mittente, destinatari, messaggio):
            eventi.append(("sendmail", mittente, tuple(destinatari)))
            assert "Subject: Nuovo episodio" in messaggio

        def quit(self):
            eventi.append(("quit",))

    esito = invia_email(
        "Corpo della notifica",
        env={
            "MAIL_TO": "uno@example.test,due@example.test",
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "587",
            "SMTP_USER": "mittente@example.test",
            "SMTP_PASSWORD": "password-segreta",
        },
        smtp_factory=FakeSMTP,
    )
    assert esito is True
    assert ("connect", "smtp.example.test", 587, 20) in eventi
    assert ("starttls",) in eventi
    assert ("login", "mittente@example.test") in eventi
    assert ("sendmail", "mittente@example.test", ("uno@example.test", "due@example.test")) in eventi
    assert eventi[-1] == ("quit",)


def test_errore_email_non_mostra_la_password(capsys):
    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def ehlo(self):
            pass

        def starttls(self):
            raise RuntimeError("password-segreta")

        def quit(self):
            pass

    esito = invia_email(
        "test",
        env={
            "MAIL_TO": "uno@example.test",
            "SMTP_HOST": "smtp.example.test",
            "SMTP_USER": "mittente@example.test",
            "SMTP_PASSWORD": "password-segreta",
        },
        smtp_factory=FakeSMTP,
    )
    assert esito is False
    assert "password-segreta" not in capsys.readouterr().err


def test_cli_stampa_messaggio_da_stato(tmp_path, monkeypatch, capsys):
    output = tmp_path / "output"
    output.mkdir()
    (output / "stato-2026-11-22.json").write_text(
        json.dumps(
            {
                "titolo": "Notiziario di prova",
                "descrizione": "Descrizione breve.",
                "durata_secondi": 60,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["--data", "2026-11-22"]) == 0
    testo = capsys.readouterr().out
    assert "Notiziario di prova" in testo
    assert "https://jakephobia.github.io/notiziario/" in testo
    assert "https://github.com/jakephobia/notiziario/releases/download" in testo


def test_cli_email_senza_configurazione_esce_zero(tmp_path, monkeypatch, capsys):
    output = tmp_path / "output"
    output.mkdir()
    (output / "stato-2026-11-22.json").write_text(
        json.dumps({"titolo": "Titolo", "durata_secondi": 1}), encoding="utf-8"
    )
    for chiave in ("MAIL_TO", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_PORT"):
        monkeypatch.delenv(chiave, raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["--email", "--data", "2026-11-22"]) == 0
    assert "email non configurata" in capsys.readouterr().out
