from __future__ import annotations

import json

from notiziario.config import Fonte, carica_fonti_tutte, carica_impostazioni
from notiziario.controllo_feed import EsitoControllo
from notiziario.fonti_io import scrivi_fonti_yaml
from notiziario.importa_feed import (
    _parse_csv,
    _parse_json,
    _parse_opml,
    _parse_txt,
    importa_feed,
    merge_fonti,
)


def esito(fonte: Fonte, stato: str, motivo: str = "") -> EsitoControllo:
    return EsitoControllo(
        fonte=fonte.nome,
        url=fonte.url,
        categoria=fonte.categoria,
        attivo=fonte.attivo,
        stato=stato,
        motivo=motivo,
    )


def test_opml_annidato():
    opml = """<?xml version="1.0"?>
<opml version="2.0"><body>
  <outline text="Gruppo">
    <outline text="ANSA" xmlUrl="https://www.ansa.it/feed.xml" category="italia"/>
    <outline title="Mondo" xmlUrl="https://www.repubblica.it/feed.xml" category="mondo"/>
  </outline>
</body></opml>"""
    fonti = _parse_opml(opml)
    assert len(fonti) == 2
    assert fonti[0].nome == "ANSA"
    assert fonti[1].nome == "Mondo"
    assert fonti[0].categoria == "italia"
    assert fonti[1].categoria == "mondo"
    assert all(not f.attivo for f in fonti)


def test_txt_una_url_per_riga():
    fonti = _parse_txt(
        "# commento\nhttps://a.test/feed\n\nhttps://b.test/feed\n"
    )
    assert [f.url for f in fonti] == ["https://a.test/feed", "https://b.test/feed"]
    assert all(f.categoria == "da-assegnare" for f in fonti)


def test_csv_header_case_insensitive():
    csv_testo = "URL,Titolo,CATEGORIA\nhttps://a.test/feed,La A,Italia\n"
    fonti = _parse_csv(csv_testo)
    assert len(fonti) == 1
    assert fonti[0].nome == "La A"
    assert fonti[0].categoria == "italia"


def test_csv_senza_header_prima_colonna():
    fonti = _parse_csv("https://a.test/feed,Titolo A,mondo\nhttps://b.test/feed\n")
    assert [f.url for f in fonti] == ["https://a.test/feed", "https://b.test/feed"]
    assert fonti[0].categoria == "mondo"


def test_json_lista_e_dict():
    lista = json.dumps(
        [
            {"url": "https://a.test/feed", "title": "A", "category": "economia"},
            {"feed": "https://b.test/feed", "name": "B"},
        ]
    )
    fonti = _parse_json(lista)
    assert fonti[0].categoria == "economia"
    assert fonti[1].nome == "B"

    oggetto = json.dumps(
        {"feeds": [{"url_feed": "https://c.test/feed", "titolo": "C"}]}
    )
    fonti = _parse_json(oggetto)
    assert len(fonti) == 1
    assert fonti[0].url == "https://c.test/feed"


def test_merge_preserva_esistenti():
    esistenti = [
        Fonte("ANSA", "https://a.test/feed", "italia", attivo=True, controllo="ok")
    ]
    nuove = [
        Fonte("A2", "https://a.test/feed", "italia", attivo=False),
        Fonte("B", "https://b.test/feed", "mondo", attivo=False),
    ]
    merged, duplicati = merge_fonti(esistenti, nuove)
    assert len(merged) == 2
    assert merged[0].attivo is True
    assert merged[0].controllo == "ok"
    assert len(duplicati) == 1


def test_categoria_override_solo_senza_categoria(tmp_path, monkeypatch):
    fonti_path = tmp_path / "fonti.yaml"
    scrivi_fonti_yaml(
        fonti_path, [Fonte("Esistente", "https://esistente.test/feed", "italia")]
    )
    opml = tmp_path / "lista.opml"
    opml.write_text(
        """<?xml version="1.0"?><opml><body>
        <outline text="Con categoria" xmlUrl="https://con.test/feed" category="mondo"/>
        <outline text="Senza categoria" xmlUrl="https://senza.test/feed"/>
        </body></opml>""",
        encoding="utf-8",
    )

    def finto_controlla(fonti, impostazioni, **kwargs):
        return [esito(fonte, "ok", "ok") for fonte in fonti]

    monkeypatch.setattr("notiziario.importa_feed.controlla_tutte", finto_controlla)
    importa_feed(
        opml,
        fonti_path,
        categoria="tecnologia",
        impostazioni=carica_impostazioni(),
        output=tmp_path,
    )
    fonti = {f.url: f for f in carica_fonti_tutte(fonti_path)}
    assert fonti["https://con.test/feed"].categoria == "mondo"
    assert fonti["https://senza.test/feed"].categoria == "tecnologia"


def test_opml_titolo_whitespace_fallback_host():
    opml = """<?xml version="1.0"?><opml><body>
    <outline text="   " xmlUrl="https://www.esempio.test/feed.xml"/>
    </body></opml>"""
    fonti = _parse_opml(opml)
    assert len(fonti) == 1
    assert fonti[0].nome == "esempio.test"


def test_attiva_tutte_non_attiva_da_assegnare(tmp_path, monkeypatch):
    fonti_path = tmp_path / "fonti.yaml"
    scrivi_fonti_yaml(
        fonti_path, [Fonte("Esistente", "https://esistente.test/feed", "italia")]
    )
    opml = tmp_path / "lista.opml"
    opml.write_text(
        """<?xml version="1.0"?><opml><body>
        <outline text="Senza categoria" xmlUrl="https://senza-cat.test/feed"/>
        </body></opml>""",
        encoding="utf-8",
    )

    def finto_controlla(fonti, impostazioni, **kwargs):
        return [esito(fonte, "ok", "ok") for fonte in fonti]

    monkeypatch.setattr("notiziario.importa_feed.controlla_tutte", finto_controlla)
    report = importa_feed(
        opml,
        fonti_path,
        attiva_tutte=True,
        impostazioni=carica_impostazioni(),
        output=tmp_path,
    )
    fonti = {f.url: f for f in carica_fonti_tutte(fonti_path)}
    assert fonti["https://senza-cat.test/feed"].attivo is False
    assert fonti["https://senza-cat.test/feed"].categoria == "da-assegnare"
    assert any("senza categoria" in m for m in report.motivi)


def test_import_data_assente_coerente(tmp_path, monkeypatch):
    fonti_path = tmp_path / "fonti.yaml"
    scrivi_fonti_yaml(
        fonti_path, [Fonte("Esistente", "https://esistente.test/feed", "italia")]
    )
    opml = tmp_path / "lista.opml"
    opml.write_text(
        """<?xml version="1.0"?><opml><body>
        <outline text="Senza date" xmlUrl="https://senza-date.test/feed" category="italia"/>
        </body></opml>""",
        encoding="utf-8",
    )

    def finto_controlla(fonti, impostazioni, **kwargs):
        return [esito(fonte, "data-assente", "feed senza date") for fonte in fonti]

    monkeypatch.setattr("notiziario.importa_feed.controlla_tutte", finto_controlla)
    report = importa_feed(
        opml,
        fonti_path,
        impostazioni=carica_impostazioni(),
        output=tmp_path,
    )
    assert report.esiti[0]["stato"] == "data-assente"
    fonti = {f.url: f for f in carica_fonti_tutte(fonti_path)}
    assert fonti["https://senza-date.test/feed"].attivo is False
    assert fonti["https://senza-date.test/feed"].controllo == "data-assente"


def test_importa_feed_merge_attivazione_e_podcast(tmp_path, monkeypatch):
    fonti_path = tmp_path / "fonti.yaml"
    scrivi_fonti_yaml(
        fonti_path,
        [Fonte("Esistente", "https://esistente.test/feed", "italia", attivo=True)],
    )
    opml = """<?xml version="1.0"?><opml><body>
    <outline text="Esistente" xmlUrl="https://esistente.test/feed" category="italia"/>
    <outline text="Buona" xmlUrl="https://buona.test/feed" category="mondo"/>
    <outline text="Podcast" xmlUrl="https://podcast.test/feed" category="cultura"/>
    <outline text="Invalida" xmlUrl="file:///etc/passwd" category="italia"/>
    <outline text="Senza categoria" xmlUrl="https://senza.test/feed"/>
    </body></opml>"""
    file_opml = tmp_path / "lista.opml"
    file_opml.write_text(opml, encoding="utf-8")

    def finto_controlla(fonti, impostazioni, **kwargs):
        esiti = []
        for fonte in fonti:
            if "podcast" in fonte.url:
                esiti.append(esito(fonte, "podcast", "audio"))
            elif "buona" in fonte.url:
                esiti.append(esito(fonte, "ok", "testo utile"))
            else:
                esiti.append(esito(fonte, "solo-titoli", "poche righe"))
        return esiti

    monkeypatch.setattr("notiziario.importa_feed.controlla_tutte", finto_controlla)
    report = importa_feed(
        file_opml,
        fonti_path,
        attiva_fonti="2",
        attiva_tutte=False,
        impostazioni=carica_impostazioni(),
        output=tmp_path,
    )
    assert report.importati == 2  # Buona + Senza categoria, podcast scartato
    assert report.duplicati >= 1
    assert report.scartati >= 2  # podcast + URL invalido
    fonti = {f.url: f for f in carica_fonti_tutte(fonti_path)}
    assert fonti["https://buona.test/feed"].attivo is True
    assert fonti["https://senza.test/feed"].attivo is False
    assert fonti["https://senza.test/feed"].categoria == "da-assegnare"
    assert fonti["https://esistente.test/feed"].attivo is True
    assert list(tmp_path.glob("importa-feed-*.json"))

def test_attiva_tutte_non_attiva_solo_titoli(tmp_path, monkeypatch):
    fonti_path = tmp_path / "fonti.yaml"
    scrivi_fonti_yaml(
        fonti_path, [Fonte("Esistente", "https://esistente.test/feed", "italia")]
    )
    opml = tmp_path / "lista.opml"
    opml.write_text(
        """<?xml version="1.0"?><opml><body>
        <outline text="Solo titoli" xmlUrl="https://solo.test/feed" category="italia"/>
        </body></opml>""",
        encoding="utf-8",
    )

    def finto_controlla(fonti, impostazioni, **kwargs):
        return [esito(fonte, "solo-titoli", "solo titoli") for fonte in fonti]

    monkeypatch.setattr("notiziario.importa_feed.controlla_tutte", finto_controlla)
    report = importa_feed(
        opml,
        fonti_path,
        attiva_tutte=True,
        impostazioni=carica_impostazioni(),
        output=tmp_path,
    )
    fonti = {f.url: f for f in carica_fonti_tutte(fonti_path)}
    assert fonti["https://solo.test/feed"].attivo is False
    assert any("solo-titoli" in m for m in report.motivi)
