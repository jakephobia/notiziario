from __future__ import annotations

import logging
import os
from datetime import datetime

import pytest

from helpers import crea_articolo, crea_cluster
from notiziario import copione as modulo_copione
from notiziario.config import carica_impostazioni
from notiziario.copione import (
    _finalizza_llm,
    _prompt_utente,
    _pulisci_descrizione_breve,
    _minuscola_dopo_secondo,
    _rimuovi_apertura,
    blocchi_per_tts,
    genera_copione,
    prepara_materiale,
    prova_llm,
)
from notiziario.incipit import aggiungi_incipit
from notiziario.outro import applica_outro, risolvi_outro
from notiziario.selezione import NotiziaSelezionata
from notiziario.stile import analizza
from notiziario.testi import conta_parole


LOGGER = logging.getLogger("test-copione")


def selezioni_finte():
    copertina = crea_cluster(
        [
            crea_articolo(
                "Cop31, nuova bozza sul clima",
                fonte="ANSA",
                categoria="mondo",
                sommario=(
                    "I paesi hanno discusso una nuova bozza sul clima. "
                    "Il testo non cita ancora l'uscita dalle fonti fossili."
                ),
            ),
            crea_articolo(
                "Cop31: la Ue respinge la bozza sul clima",
                fonte="Repubblica",
                categoria="mondo",
                sommario=(
                    "L'Unione europea ha chiesto modifiche al testo. "
                    "I lavori proseguono nelle prossime ore."
                ),
            ),
        ]
    )
    italia = crea_cluster(
        [
            crea_articolo(
                "Il governo approva il piano per la scuola",
                fonte="ANSA",
                categoria="italia",
                sommario=(
                    "Il consiglio dei ministri ha approvato il piano. "
                    "Sono previsti fondi per laboratori e formazione."
                ),
            )
        ]
    )
    economia = crea_cluster(
        [
            crea_articolo(
                "La manovra arriva in Parlamento",
                fonte="Il Sole 24 Ore",
                categoria="economia",
                sommario=(
                    "La manovra sarà esaminata dalla Camera. "
                    "Il voto finale è atteso entro dicembre."
                ),
            )
        ]
    )
    return [
        NotiziaSelezionata(copertina, True, 1, 240),
        NotiziaSelezionata(italia, False, 2, 100),
        NotiziaSelezionata(economia, False, 3, 100),
    ]


def test_prepara_materiale():
    materiale = prepara_materiale(selezioni_finte())
    assert len(materiale) == 3
    assert materiale[0]["copertina"] is True
    assert materiale[0]["fonti"] == ["ANSA", "Repubblica"]
    assert materiale[0]["articoli"][0]["sommario"]


def test_fallback_deterministico_naturale():
    copione = genera_copione(
        selezioni_finte(),
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0),
        logger=LOGGER,
        usa_llm=False,
    )
    assert copione["modalita"] == "fallback"
    assert copione["motivo_fallback"]
    assert copione["titolo_episodio"].startswith("Notiziario di")
    assert len(copione["notizie"]) == 3
    testo = copione["testo"]
    assert "Buongiorno" not in testo
    assert "Per oggi è tutto" in testo
    assert "Apriamo con questa notizia" not in testo
    assert "riguarda un altro fatto" not in testo
    assert "Parliamo di" not in testo
    assert "Passiamo a" not in testo
    assert "Secondo ANSA" in testo or "Come riportano ANSA" in testo
    assert "ANSA" in testo
    assert conta_parole(testo) >= 80
    assert "<" not in testo and ">" not in testo
    assert "*" not in testo and "#" not in testo
    assert "(" not in testo and ")" not in testo
    for vietata in ("in un mondo in cui", "non solo", "ma anche", "in conclusione"):
        assert vietata not in testo.casefold()
    assert not analizza(testo)
    for voce in copione["notizie"]:
        assert voce["testo"]
        assert voce["fonti"]
    assert copione["target_parole"] > 0
    assert copione["divario_parole"] >= 0


def test_incipit_aggiunto_in_testa_senza_toccare_le_notizie():
    copione = genera_copione(
        selezioni_finte(),
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0),
        logger=LOGGER,
        usa_llm=False,
    )
    notizie_prima = [n["titolo"] for n in copione["notizie"]]
    aggiungi_incipit(copione, "Ciao Jacopo, ecco le tue notizie del giorno.")
    assert copione["testo"].startswith("Ciao Jacopo")
    assert notizie_prima == [n["titolo"] for n in copione["notizie"]]


def test_rimuove_saluto_llm_nonostante_il_prompt():
    testo = "Buongiorno a tutti. Il governo ha approvato il piano. " + " ".join(
        ["Parola"] * 50
    )
    ripulito = _rimuovi_apertura(testo)
    assert not ripulito.startswith("Buongiorno")
    assert "governo" in ripulito


def test_llm_json_non_valido_poi_fallback(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    chiamate = {"n": 0}

    def finta_chiamata(prompt, system, impostazioni, api_key, logger, modello=None):
        chiamate["n"] += 1
        return "Questa non è una risposta JSON"

    monkeypatch.setattr(modulo_copione, "_chiama_gemini", finta_chiamata)
    copione = genera_copione(
        selezioni_finte(),
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0),
        logger=LOGGER,
    )
    assert chiamate["n"] == 3
    assert copione["modalita"] == "fallback"
    assert "JSON" in (copione["motivo_fallback"] or "")


def test_llm_json_valido(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    risposta = """
    {
      "titolo_episodio": "Notiziario di prova",
      "descrizione": "Le notizie di prova.",
      "testo": "Buongiorno. Questa è una notizia di prova. Questa è la seconda notizia. Per oggi è tutto.",
      "notizie": [
        {"titolo": "Prima", "categoria": "Mondo", "fonti": ["ANSA"], "testo": "Buongiorno. Questa è una notizia di prova."},
        {"titolo": "Seconda", "categoria": "Italia", "fonti": ["ANSA"], "testo": "Questa è la seconda notizia."}
      ]
    }
    """
    # Il testo ha poche parole: il validatore lo rifiuta e passa al fallback.
    monkeypatch.setattr(
        modulo_copione,
        "_chiama_gemini",
        lambda prompt, system, impostazioni, api_key, logger, modello=None: risposta,
    )
    copione = genera_copione(
        selezioni_finte(),
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0),
        logger=LOGGER,
    )
    assert copione["modalita"] == "fallback"
    assert "troppo corto" in (copione["motivo_fallback"] or "")


def test_llm_testo_corto_accettato_e_divario_riportato(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    testo = " ".join(
        ["Il governo ha approvato il piano e non solo la scuola."] * 8
    )
    risposta = {
        "titolo_episodio": "Notiziario breve",
        "descrizione": "Notizie brevi.",
        "testo": testo,
        "notizie": [
            {"titolo": "Prima", "categoria": "Italia", "fonti": ["ANSA"], "testo": testo},
            {"titolo": "Seconda", "categoria": "Mondo", "fonti": ["ANSA"], "testo": testo},
            {"titolo": "Terza", "categoria": "Economia", "fonti": ["ANSA"], "testo": testo},
        ],
    }
    monkeypatch.setattr(
        modulo_copione,
        "_chiama_gemini",
        lambda *a, **k: __import__("json").dumps(risposta),
    )
    copione = genera_copione(
        selezioni_finte(),
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0),
        logger=LOGGER,
    )
    assert copione["modalita"] == "llm"
    assert copione["divario_parole"] > 0
    assert "non solo" not in copione["testo"].casefold()


def test_modello_riserva_usato_solo_dopo_errore(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    impostazioni = carica_impostazioni()
    primario = impostazioni["llm"]["modello"]
    riserva = impostazioni["llm_modello_riserva"]
    chiamate = []
    testo = " ".join(["Il governo ha approvato il piano per la scuola."] * 8)
    risposta = {
        "titolo_episodio": "Notiziario di riserva",
        "descrizione": "Notizie.",
        "testo": testo,
        "notizie": [
            {"titolo": "Prima", "categoria": "Italia", "fonti": ["ANSA"], "testo": testo},
            {"titolo": "Seconda", "categoria": "Mondo", "fonti": ["ANSA"], "testo": testo},
            {"titolo": "Terza", "categoria": "Economia", "fonti": ["ANSA"], "testo": testo},
        ],
    }

    def finto(prompt, system, impostazioni, api_key, logger, modello=None):
        chiamate.append(modello)
        if modello == primario:
            raise modulo_copione.LlmError("HTTP 429 quota")
        return __import__("json").dumps(risposta)

    monkeypatch.setattr(modulo_copione, "_chiama_gemini", finto)
    copione = genera_copione(
        selezioni_finte(),
        impostazioni,
        datetime(2026, 11, 22, 7, 0),
        logger=LOGGER,
    )
    assert copione["modalita"] == "llm"
    assert copione["modello_usato"] == riserva
    assert "riserva" in (copione["motivo_modello"] or "")
    assert chiamate == [primario, primario, riserva]


def test_quota_429_poi_fallback(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")

    class Risposta:
        status_code = 429

        def json(self):
            return {"error": {"message": "quota exceeded"}}

    monkeypatch.setattr(modulo_copione.time, "sleep", lambda *_: None)
    monkeypatch.setattr(modulo_copione.requests, "post", lambda *a, **k: Risposta())
    copione = genera_copione(
        selezioni_finte(),
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0),
        logger=LOGGER,
    )
    assert copione["modalita"] == "fallback"
    assert "429" in (copione["motivo_fallback"] or "")
    assert "quota exceeded" in (copione["motivo_fallback"] or "")


def test_prova_llm_senza_chiave(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    ok, messaggio = prova_llm(carica_impostazioni(), LOGGER)
    assert ok is False
    assert "GEMINI_API_KEY" in messaggio
    assert "--test-llm" in messaggio


def test_minuscola_dopo_secondo_solo_parole_comuni():
    assert _minuscola_dopo_secondo("Da lunedì lavora") == "da lunedì lavora"
    assert _minuscola_dopo_secondo("L'ex comandante") == "l'ex comandante"
    assert _minuscola_dopo_secondo("Meloni incontra Trump") == "Meloni incontra Trump"
    assert _minuscola_dopo_secondo("ANSA comunica") == "ANSA comunica"
    assert _minuscola_dopo_secondo("GTA 6 è uscito") == "GTA 6 è uscito"


def test_fallback_buone_notizie_in_chiusura():
    positiva = crea_cluster(
        [
            crea_articolo(
                "Ragazzi ripuliscono il parco",
                fonte="Buone Notizie",
                categoria="buone-notizie",
                sommario="Hanno raccolto rifiuti e piantato nuovi alberi.",
            )
        ]
    )
    selezioni = selezioni_finte() + [
        NotiziaSelezionata(
            positiva,
            copertina=False,
            ordine=4,
            parole_target=100,
            blocco="buone-notizie",
        )
    ]
    copione = genera_copione(
        selezioni,
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0),
        logger=LOGGER,
        usa_llm=False,
    )
    assert copione["notizie"][-1]["categoria"] == "Buone notizie"
    assert copione["testo"].rstrip().endswith("A domani.")
    assert copione["testo"].index("Ragazzi") < copione["testo"].index("Per oggi")


def test_riordina_buone_notizie_se_ai_le_mette_all_inizio():
    positiva = crea_cluster(
        [
            crea_articolo(
                "Ragazzi ripuliscono il parco",
                fonte="Buone Notizie",
                categoria="buone-notizie",
                sommario="Hanno raccolto rifiuti e piantato alberi.",
            )
        ]
    )
    selezioni = selezioni_finte() + [
        NotiziaSelezionata(
            positiva,
            copertina=False,
            ordine=4,
            parole_target=100,
            blocco="buone-notizie",
        )
    ]
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    testo = (
        ("Ragazzi ripuliscono il parco. " * 12)
        + "\n\n"
        + ("Il governo approva il piano. " * 12)
        + "\n\nQueste le principali notizie per oggi."
    )
    risposta = {
        "titolo_episodio": "Notiziario di prova",
        "descrizione": "Notizie.",
        "testo": testo,
        "notizie": [
            {
                "titolo": "Ragazzi ripuliscono il parco",
                "categoria": "Buone notizie",
                "fonti": ["Buone Notizie"],
                "testo": "Ragazzi ripuliscono il parco.",
            },
            {
                "titolo": "Il governo approva il piano",
                "categoria": "Italia",
                "fonti": ["ANSA"],
                "testo": "Il governo approva il piano.",
            },
        ],
    }
    monkeypatch.setattr(
        modulo_copione,
        "_chiama_gemini",
        lambda *a, **k: __import__("json").dumps(risposta),
    )
    try:
        copione = genera_copione(
            selezioni,
            carica_impostazioni(),
            datetime(2026, 11, 22, 7, 0),
            logger=LOGGER,
        )
    finally:
        monkeypatch.undo()
    finale = copione["testo"]
    assert finale.index("Ragazzi") > finale.index("governo")
    assert finale.index("Ragazzi") < finale.index("Queste le principali")
    assert finale.rstrip().endswith("Queste le principali notizie per oggi.")


def test_blocchi_per_tts_paragrafi():
    testo = "Primo paragrafo.\n\nSecondo paragrafo.\n\nTerzo paragrafo."
    assert blocchi_per_tts(testo) == [
        "Primo paragrafo.",
        "Secondo paragrafo.",
        "Terzo paragrafo.",
    ]


def test_blocchi_per_tts_testo_unico():
    testo = " ".join(["Questa è una frase di prova."] * 20)
    blocchi = blocchi_per_tts(testo)
    assert len(blocchi) >= 2
    assert all(conta_parole(b) <= 100 for b in blocchi)

def test_outro_prima_delle_buone_notizie_viene_spostato_in_fondo(monkeypatch):
    positiva = crea_cluster(
        [
            crea_articolo(
                "Ragazzi ripuliscono il parco",
                fonte="Buone Notizie",
                categoria="buone-notizie",
                sommario="Hanno raccolto rifiuti e piantato alberi.",
            )
        ]
    )
    selezioni = selezioni_finte() + [
        NotiziaSelezionata(
            positiva,
            copertina=False,
            ordine=4,
            parole_target=100,
            blocco="buone-notizie",
        )
    ]
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    testo = (
        ("Il governo approva il piano. " * 10)
        + "\n\nPer il momento è tutto. A domani."
        + "\n\n"
        + ("Ragazzi ripuliscono il parco. " * 10)
    )
    risposta = {
        "titolo_episodio": "Notiziario di prova",
        "descrizione": "Notizie.",
        "testo": testo,
        "notizie": [
            {"titolo": "Il governo approva", "categoria": "Italia", "fonti": ["ANSA"], "testo": "Il governo approva."},
            {"titolo": "Ragazzi ripuliscono il parco", "categoria": "Buone notizie", "fonti": ["Buone Notizie"], "testo": "Ragazzi ripuliscono il parco."},
            {"titolo": "Economia", "categoria": "Economia", "fonti": ["ANSA"], "testo": "Economia."},
            {"titolo": "Mondo", "categoria": "Mondo", "fonti": ["ANSA"], "testo": "Mondo."},
        ],
    }
    monkeypatch.setattr(
        modulo_copione,
        "_chiama_gemini",
        lambda *a, **k: __import__("json").dumps(risposta),
    )
    copione = genera_copione(
        selezioni,
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0),
        logger=LOGGER,
    )
    finale = copione["testo"]
    paragrafi = [p.strip() for p in finale.split("\n\n") if p.strip()]
    assert paragrafi[-1].startswith("Per il momento è tutto")
    assert finale.index("Ragazzi") < finale.index("Per il momento è tutto")

def test_outro_configurato_vince_e_resta_ultimo():
    copione = {
        "testo": (
            "Notizia uno.\n\n"
            "Ragazzi ripuliscono il parco.\n\n"
            "Questa è la fine del notiziario.\n\n"
            "Per oggi è tutto. A domani."
        ),
        "target_parole": 100,
    }
    applica_outro(copione, "Queste erano le notizie di oggi. A domani!")
    paragrafi = [p.strip() for p in copione["testo"].split("\n\n") if p.strip()]
    assert paragrafi[-1] == "Queste erano le notizie di oggi. A domani!"
    assert copione["testo"].count("Queste erano le notizie di oggi") == 1
    assert copione["testo"].index("Ragazzi") < copione["testo"].index("Queste erano")


def test_outro_marker_e_default():
    from datetime import datetime
    from notiziario.tempo import ROMA

    testo, _ = risolvi_outro(
        "Ciao [NOME UTENTE], a domani. Oggi è [DATA].",
        "Jacopo",
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
    )
    assert "Ciao Jacopo" in testo
    assert "22 novembre" in testo
    default, avvisi = risolvi_outro("", "Jacopo", datetime(2026, 11, 22, 7, 0, tzinfo=ROMA))
    assert default.startswith("Queste erano")
    assert avvisi

def test_descrizione_breve_fallback():
    copione = genera_copione(
        selezioni_finte(),
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0),
        logger=LOGGER,
        usa_llm=False,
    )
    breve = copione["descrizione_breve"]
    assert breve.startswith("22 novembre 2026 - ")
    assert len(breve) <= 200
    assert "<" not in breve and ">" not in breve
    assert breve.count(",") <= 7

def test_descrizione_breve_generica_reale_viene_rifiutata():
    from datetime import datetime
    from notiziario.tempo import ROMA

    generica = (
        "22 novembre 2026 - Le principali notizie del 22 novembre 2026: "
        "attacco a nave russa in Libia, Schettino ai servizi sociali, e molto altro."
    )
    assert _pulisci_descrizione_breve(
        generica, datetime(2026, 11, 22, 7, 0, tzinfo=ROMA)
    ) == ""
    valida = "22 novembre 2026 - Manovra approvata, Schettino libero, Cop31 fallita"
    assert _pulisci_descrizione_breve(
        valida, datetime(2026, 11, 22, 7, 0, tzinfo=ROMA)
    ) == valida

def test_titolo_llm_mese_minuscolo():
    from datetime import datetime
    from notiziario.tempo import ROMA

    dati = {
        "titolo_episodio": "Notiziario di 22 Novembre 2026",
        "descrizione": "Le notizie del giorno.",
        "descrizione_breve": "22 novembre 2026 - Manovra approvata, Cop31 fallita",
        "testo": "Buongiorno, ecco le notizie.",
        "notizie": [],
    }
    risultato = _finalizza_llm(dati, [], datetime(2026, 11, 22, 7, 0, tzinfo=ROMA))
    assert risultato["titolo_episodio"] == "Notiziario di 22 novembre 2026"

def test_prompt_descrizione_breve_contiene_regole():
    from notiziario.tempo import ROMA

    prompt, _ = _prompt_utente(
        [{"parole_target": 100}],
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
        {},
    )
    assert "22 novembre 2026 - " in prompt
    assert "3-8 micro-riassunti" in prompt
    assert "e molto altro" in prompt
    assert "le\n  principali notizie" in prompt
