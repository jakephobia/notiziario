from __future__ import annotations

from notiziario.copione import sezioni_tts_strutturate


def notizia(categoria, *paragrafi):
    return {
        "titolo": "Titolo",
        "categoria": categoria,
        "testo": "Riassunto.",
        "paragrafi": list(paragrafi),
    }


def test_multi_paragrafo_un_suono_tra_due_notizie():
    copione = {
        "notizie": [
            notizia("italia", "A uno.", "A due.", "A tre."),
            notizia("italia", "B uno.", "B due."),
        ]
    }
    sezioni, indici = sezioni_tts_strutturate(copione)
    assert [testo for testo, _ in sezioni] == ["A uno.", "A due.", "A tre.", "B uno.", "B due."]
    assert indici == [2]
    assert [pausa for _, pausa in sezioni] == [0.3, 0.3, 0.0, 0.3, 0.0]


def test_dieci_notizie_nove_suoni():
    copione = {"notizie": [notizia("italia", f"Notizia {i}.") for i in range(10)]}
    sezioni, indici = sezioni_tts_strutturate(copione)
    assert len(sezioni) == 10
    assert len(indici) == 9
    assert indici == list(range(9))


def test_cambio_categoria_non_raddoppia_il_suono():
    copione = {
        "notizie": [
            notizia("italia", "Notizia Italia."),
            notizia("economia", "Notizia Economia."),
        ]
    }
    _, indici = sezioni_tts_strutturate(copione)
    assert len(indici) == 1


def test_intro_e_ultima_notizia_verso_outro_senza_suono():
    copione = {
        "incipit": "Ciao Jacopo.",
        "outro": "A domani.",
        "notizie": [
            notizia("italia", "Prima.", "Prima bis."),
            notizia("italia", "Seconda."),
        ],
    }
    sezioni, indici = sezioni_tts_strutturate(copione)
    assert [t for t, _ in sezioni] == ["Ciao Jacopo.", "Prima.", "Prima bis.", "Seconda.", "A domani."]
    assert indici == [2]
    assert 0 not in indici
    assert 3 not in indici


def test_nessun_suono_tra_paragrafi_interni():
    copione = {"notizie": [notizia("mondo", "P1.", "P2.", "P3.", "P4.")]}
    _, indici = sezioni_tts_strutturate(copione)
    assert indici == []