from __future__ import annotations

from notiziario.tempo import ROMA, parse_iso


def test_parse_iso_con_offset_e_zulu():
    roma = parse_iso("2026-11-24T11:00:00+01:00")
    assert roma is not None
    assert roma.astimezone(ROMA).hour == 11

    zulu = parse_iso("2026-11-24T10:00:00Z")
    assert zulu is not None
    assert zulu.astimezone(ROMA).hour == 11


def test_parse_iso_senza_fuso_assume_roma():
    valore = parse_iso("2026-11-24T11:00:00")
    assert valore is not None
    assert valore.tzinfo == ROMA
    assert valore.hour == 11


def test_parse_iso_non_valido():
    assert parse_iso("non-una-data") is None
    assert parse_iso("") is None
