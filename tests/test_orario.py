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


def test_controlla_ora_corrispondente_e_non():
    impostazioni = carica_impostazioni()
    assert orario.controlla(impostazioni, datetime(2026, 11, 22, 7, 0, tzinfo=ROMA))
    assert not orario.controlla(impostazioni, datetime(2026, 11, 22, 6, 59, tzinfo=ROMA))


def test_controlla_ora_legale_e_solare():
    impostazioni = carica_impostazioni()
    # 29 marzo 2026: alle 01:00 UTC l'Italia passa a CEST (07:00 locali).
    assert orario.controlla(impostazioni, datetime(2026, 3, 29, 5, 0, tzinfo=timezone.utc))
    # 22 novembre 2026: CET, 06:00 UTC = 07:00 a Roma.
    assert orario.controlla(impostazioni, datetime(2026, 11, 22, 6, 0, tzinfo=timezone.utc))


def test_cli_controlla_stampa_booleano(monkeypatch, capsys):
    monkeypatch.setattr(orario, "controlla", lambda: True)
    assert orario.main(["--controlla"]) == 0
    assert capsys.readouterr().out.strip() == "true"
