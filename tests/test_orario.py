from __future__ import annotations

from datetime import datetime, timezone

from notiziario import orario
from notiziario.config import carica_impostazioni
from notiziario.tempo import ROMA


def test_orario_valido_solo_ore_intere():
    assert orario.orario_valido("07:00")
    assert orario.orario_valido("23:00")
    assert not orario.orario_valido("7:00")
    assert not orario.orario_valido("07:30")
    assert not orario.orario_valido("24:00")


def test_controlla_recupero_dopo_orario(tmp_path):
    impostazioni = carica_impostazioni()
    storico = tmp_path / "storico.json"
    feed = tmp_path / "feed.xml"
    assert not orario.controlla(
        impostazioni, datetime(2026, 11, 22, 6, 59, tzinfo=ROMA), storico, feed
    )
    assert orario.controlla(
        impostazioni, datetime(2026, 11, 22, 7, 0, tzinfo=ROMA), storico, feed
    )
    assert orario.controlla(
        impostazioni, datetime(2026, 11, 22, 7, 30, tzinfo=ROMA), storico, feed
    )
    assert orario.controlla(
        impostazioni, datetime(2026, 11, 22, 23, 0, tzinfo=ROMA), storico, feed
    )


def test_controlla_episodio_gia_presente(tmp_path):
    import json

    impostazioni = carica_impostazioni()
    storico = tmp_path / "storico.json"
    storico.write_text(
        json.dumps({"episodi": [{"data": "2026-11-22"}]}), encoding="utf-8"
    )
    assert not orario.controlla(
        impostazioni,
        datetime(2026, 11, 22, 7, 30, tzinfo=ROMA),
        storico,
        tmp_path / "feed.xml",
    )


def test_controlla_ora_legale_e_solare(tmp_path):
    impostazioni = carica_impostazioni()
    storico = tmp_path / "storico.json"
    feed = tmp_path / "feed.xml"
    # 29 marzo 2026: alle 01:00 UTC l'Italia passa a CEST (07:00 locali).
    assert orario.controlla(
        impostazioni, datetime(2026, 3, 29, 5, 0, tzinfo=timezone.utc), storico, feed
    )
    # 22 novembre 2026: CET, 06:00 UTC = 07:00 a Roma.
    assert orario.controlla(
        impostazioni, datetime(2026, 11, 22, 6, 0, tzinfo=timezone.utc), storico, feed
    )


def test_cli_controlla_stampa_booleano(monkeypatch, capsys):
    monkeypatch.setattr(orario, "controlla", lambda: True)
    assert orario.main(["--controlla"]) == 0
    assert capsys.readouterr().out.strip() == "true"
