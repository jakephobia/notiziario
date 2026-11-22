from __future__ import annotations

from notiziario.stile import analizza


def test_testo_pulito_nessun_avviso():
    testo = (
        "Buongiorno. Oggi parliamo di tre notizie. "
        "La prima riguarda il clima. La seconda riguarda il lavoro. "
        "Chiudiamo con una notizia di cultura."
    )
    assert analizza(testo) == []


def test_espressione_vietata():
    avvisi = analizza("In un mondo in cui tutto cambia, la notizia è questa.")
    assert any("in un mondo in cui" in a for a in avvisi)


def test_frase_troppo_lunga():
    frase = "Questa è una frase molto lunga " + " ".join(["parola"] * 40) + "."
    avvisi = analizza(frase)
    assert any("Frase troppo lunga" in a for a in avvisi)


def test_parentesi_markdown_ed_elenchi():
    avvisi = analizza("- **Notizia** (con parentesi)")
    assert any("parentesi" in a for a in avvisi)
    assert any("markdown" in a for a in avvisi)
    assert any("elenco" in a for a in avvisi)


def test_attacco_frase_ripetuto():
    testo = (
        "La notizia è questa. La seconda è questa. La terza è questa. "
        "La quarta è questa. La quinta è questa."
    )
    avvisi = analizza(testo)
    assert any("Ripetizione di attacco frase" in a for a in avvisi)


def test_frase_ripetuta():
    testo = (
        "Il governo approva la manovra. Il governo approva la manovra. "
        "Poi arriva la replica."
    )
    avvisi = analizza(testo)
    assert any("Frase ripetuta" in a for a in avvisi)
