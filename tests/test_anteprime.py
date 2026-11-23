from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from notiziario.anteprime import costruisci_anteprime
from notiziario.config import Fonte, carica_impostazioni
from notiziario.feed import Episodio, aggiorna_docs, scrivi_anteprime_fonti
from notiziario.fetch import Article

URL_ANSA = "https://www.ansa.it/feed.xml"
URL_REPUBBLICA = "https://www.repubblica.it/feed.xml"
BASE = datetime(2026, 11, 23, 11, 30, tzinfo=timezone.utc)


def articolo(
    titolo: str,
    *,
    fonte: str = "ANSA",
    feed_url: str = URL_ANSA,
    ore: float = 1,
    link: str | None = None,
    sommario: str | None = None,
) -> Article:
    return Article(
        titolo=titolo,
        link=link or f"https://esempio.test/{titolo.replace(' ', '-').lower()}",
        sommario=sommario if sommario is not None else f"Testo di {titolo}.",
        pubblicato=BASE - timedelta(hours=ore),
        fonte=fonte,
        categoria="italia",
        feed_url=feed_url,
    )


def test_tiene_i_cinque_articoli_piu_recenti_ordinati():
    fonti = [Fonte("ANSA", URL_ANSA, "italia")]
    articoli = [
        articolo(f"Notizia {ore}", ore=ore) for ore in (5, 3, 0, 4, 1, 2)
    ]
    dati = costruisci_anteprime(articoli, fonti)
    gruppo = dati["fonti"][URL_ANSA]
    titoli = [voce["titolo"] for voce in gruppo["articoli"]]
    assert titoli == [
        "Notizia 0",
        "Notizia 1",
        "Notizia 2",
        "Notizia 3",
        "Notizia 4",
    ]
    assert gruppo["nome"] == "ANSA"
    assert gruppo["url"] == URL_ANSA
    assert gruppo["attivo"] is True


def test_due_fonti_gruppi_separati_per_url():
    fonti = [
        Fonte("ANSA", URL_ANSA, "italia"),
        Fonte("Repubblica", URL_REPUBBLICA, "italia"),
    ]
    articoli = [
        articolo("Notizia ANSA", feed_url=URL_ANSA, ore=1),
        articolo(
            "Notizia Repubblica",
            fonte="Repubblica",
            feed_url=URL_REPUBBLICA,
            ore=2,
        ),
    ]
    dati = costruisci_anteprime(articoli, fonti)
    assert set(dati["fonti"]) == {URL_ANSA, URL_REPUBBLICA}
    assert dati["fonti"][URL_ANSA]["articoli"][0]["titolo"] == "Notizia ANSA"
    assert (
        dati["fonti"][URL_REPUBBLICA]["articoli"][0]["titolo"]
        == "Notizia Repubblica"
    )
    assert len(dati["fonti"][URL_ANSA]["articoli"]) == 1
    assert len(dati["fonti"][URL_REPUBBLICA]["articoli"]) == 1


def test_fonte_senza_articoli_ha_lista_vuota_e_resta_inattiva():
    fonti = [
        Fonte("ANSA", URL_ANSA, "italia"),
        Fonte("Fonte spenta", URL_REPUBBLICA, "italia", attivo=False),
    ]
    dati = costruisci_anteprime([articolo("Notizia ANSA")], fonti)
    vuota = dati["fonti"][URL_REPUBBLICA]
    assert vuota["articoli"] == []
    assert vuota["attivo"] is False
    assert vuota["nome"] == "Fonte spenta"
    assert len(dati["fonti"][URL_ANSA]["articoli"]) == 1


def test_fallback_per_nome_fonte_senza_feed_url():
    fonti = [Fonte("ANSA", URL_ANSA, "italia")]
    articoli = [
        articolo("Notizia senza feed", fonte="ANSA", feed_url=""),
    ]
    dati = costruisci_anteprime(articoli, fonti)
    assert dati["fonti"][URL_ANSA]["articoli"][0]["titolo"] == "Notizia senza feed"


def test_deduplica_per_link():
    fonti = [Fonte("ANSA", URL_ANSA, "italia")]
    articoli = [
        articolo("Prima versione", ore=1, link="https://esempio.test/stesso"),
        articolo("Versione vecchia", ore=3, link="https://esempio.test/stesso"),
        articolo("Altra notizia", ore=2, link="https://esempio.test/altra"),
    ]
    dati = costruisci_anteprime(articoli, fonti)
    titoli = [voce["titolo"] for voce in dati["fonti"][URL_ANSA]["articoli"]]
    assert titoli == ["Prima versione", "Altra notizia"]


def test_sommario_pulito_troncato_e_senza_html():
    fonti = [Fonte("ANSA", URL_ANSA, "italia")]
    lungo = "Parola " * 120
    articoli = [articolo("Notizia", sommario=f"<p>{lungo}</p>")]
    dati = costruisci_anteprime(articoli, fonti)
    sommario = dati["fonti"][URL_ANSA]["articoli"][0]["sommario"]
    assert "<" not in sommario
    assert ">" not in sommario
    assert "Parola" in sommario
    assert len(sommario) <= 260


def test_generato_e_pubblicato_sono_iso_con_timezone():
    fonti = [Fonte("ANSA", URL_ANSA, "italia")]
    dati = costruisci_anteprime([articolo("Notizia", ore=1)], fonti)
    assert dati["generato"].endswith("+00:00")
    pubblicato = dati["fonti"][URL_ANSA]["articoli"][0]["pubblicato"]
    data = datetime.fromisoformat(pubblicato)
    assert data.tzinfo is not None


def test_scrivi_anteprime_fonti_json_leggibile(tmp_path):
    dati = {
        "generato": "2026-11-23T11:30:00+00:00",
        "fonti": {
            URL_ANSA: {
                "nome": "ANSA",
                "url": URL_ANSA,
                "attivo": True,
                "articoli": [
                    {
                        "titolo": "Notizia",
                        "sommario": "Testo.",
                        "link": "https://esempio.test/notizia",
                        "pubblicato": "2026-11-23T10:00:00+00:00",
                    }
                ],
            }
        },
    }
    percorso = tmp_path / "anteprime-fonti.json"
    scrivi_anteprime_fonti(percorso, dati)
    testo = percorso.read_text(encoding="utf-8")
    assert testo.endswith("\n")
    assert '\n  "fonti"' in testo
    assert json.loads(testo) == dati


def test_aggiorna_docs_restituisce_percorso_anteprime(tmp_path):
    episodio = Episodio(
        data="2026-11-23",
        titolo="Notiziario del 23 novembre",
        descrizione="Le notizie del giorno.",
        filename="notiziario-2026-11-23.mp3",
    )
    dati = costruisci_anteprime(
        [articolo("Notizia")],
        [Fonte("ANSA", URL_ANSA, "italia")],
    )
    percorsi = aggiorna_docs(
        episodio,
        carica_impostazioni(),
        tmp_path,
        anteprime_fonti=dati,
    )
    atteso = tmp_path / "anteprime-fonti.json"
    assert percorsi["anteprime"] == str(atteso)
    assert atteso.exists()
    assert json.loads(atteso.read_text(encoding="utf-8")) == dati
