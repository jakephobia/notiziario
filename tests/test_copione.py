from __future__ import annotations

import logging
import os
from datetime import datetime

import pytest

from helpers import crea_articolo, crea_cluster
from notiziario import copione as modulo_copione
from notiziario.config import carica_impostazioni
from notiziario.copione import (
    _accorcia_titolo_breve,
    _contiene_stopword_inglese,
    _frasi_con_inglese,
    _descrizione_breve,
    _finalizza_llm,
    _prompt_utente,
    _pulisci_descrizione_breve,
    _minuscola_dopo_secondo,
    _paragrafo_copertina,
    _rimuovi_apertura,
    _system_prompt,
    blocchi_per_tts,
    genera_copione,
    migliora_completezza,
    prepara_materiale,
    prova_llm,
)
from notiziario.incipit import aggiungi_incipit
from notiziario.outro import applica_outro, risolvi_outro
from notiziario.selezione import NotiziaSelezionata
from notiziario.stile import analizza
from notiziario.testi import conta_parole
from notiziario.tempo import ROMA


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
        assert voce["paragrafi"]
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

    def finto(prompt, system, impostazioni, api_key, logger, modello=None, **kwargs):
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
    # Le prime tre chiamate sono i due tentativi del modello primario e la
    # riserva; eventuali chiamate successive appartengono al layer di revisione.
    assert chiamate[:3] == [primario, primario, riserva]


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
    assert breve.count(",") <= 4
    assert breve.endswith(".")

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
    assert "3-5 micro-riassunti" in prompt
    assert "interamente in italiano" in prompt
    assert "titoli stranieri" in prompt
    assert "e molto altro" in prompt
    assert "le\n  principali notizie" in prompt

def test_fallback_descrizione_pulisce_titoli_problematici():
    from notiziario.tempo import ROMA

    titoli = [
        "Nave russa colpita in Libia, attacco nel porto",
        "Schettino fuori dal carcere, ai servizi sociali",
        "La villa di De Gennaro, il corpo a Firenze",
        "Fallita la Cop31, l'accordo sul clima non è stato approvato",
        "Rendimenti dei Treasury al",
        "Le prime ore di GTA 6, il gioco che mi ha fatto affezionare",
        "Rischio cardiometabolico legato",
        "Ovazioni",
    ]
    breve = _descrizione_breve(titoli, datetime(2026, 11, 22, 7, 0, tzinfo=ROMA))
    assert breve.startswith("22 novembre 2026 - ")
    assert breve.endswith(".")
    assert len(breve) <= 200
    assert breve.count(",") == 4
    assert " al," not in breve and " al." not in breve
    assert "legato" not in breve.casefold()
    assert "accordo" not in breve.casefold()
    assert "Ovazioni" not in breve
    assert "Rendimenti dei Treasury" in breve
    assert _accorcia_titolo_breve("Rischio cardiometabolico legato") == "Rischio cardiometabolico"
    assert _accorcia_titolo_breve("Fallita la Cop31 accordo") == "Fallita la Cop31"


def test_fallback_descrizione_rispetta_200_caratteri():
    from notiziario.tempo import ROMA

    lunghi = [
        f"{parola} numero due tre quattro cinque"
        for parola in (
            "PrimaMoltoLunga",
            "SecondaMoltoLunga",
            "TerzaMoltoLunga",
            "QuartaMoltoLunga",
            "QuintaMoltoLunga",
        )
    ]
    breve = _descrizione_breve(lunghi, datetime(2026, 11, 22, 7, 0, tzinfo=ROMA))
    assert len(breve) <= 200
    assert breve.startswith("22 novembre 2026 - ")
    assert breve.endswith(".")
    assert "QuartaMoltoLunga" not in breve
    assert breve.count(",") <= 2


def test_descrizione_ai_invalida_usa_fallback_pulito():
    from notiziario.tempo import ROMA

    dati = {
        "titolo_episodio": "Notiziario di 22 novembre 2026",
        "descrizione": "Le notizie del giorno.",
        "descrizione_breve": (
            "22 novembre 2026 - Le principali notizie del 22 novembre 2026: "
            "attacco a nave russa in Libia, Schettino ai servizi sociali, e molto altro."
        ),
        "testo": "Buongiorno, ecco le notizie.",
        "notizie": [],
    }
    risultato = _finalizza_llm(
        dati, selezioni_finte(), datetime(2026, 11, 22, 7, 0, tzinfo=ROMA)
    )
    breve = risultato["descrizione_breve"]
    assert breve.startswith("22 novembre 2026 - ")
    assert "principali notizie" not in breve.casefold()
    assert "molto altro" not in breve.casefold()
    assert "22 novembre 2026" not in breve[len("22 novembre 2026 - ") :]
    assert breve.endswith(".")

def test_llm_con_paragrafi_espliciti_ricostruisce_il_corpo():
    dati = {
        "titolo_episodio": "Notiziario di 22 novembre 2026",
        "descrizione": "Le notizie.",
        "descrizione_breve": "22 novembre 2026 - Manovra approvata, Cop31 fallita",
        "testo": (
            "Primo paragrafo A.\n\nSecondo paragrafo A.\n\nTerzo paragrafo A.\n\n"
            "Primo paragrafo B.\n\nSecondo paragrafo B.\n\nPer oggi è tutto."
        ),
        "notizie": [
            {
                "titolo": "A",
                "categoria": "Italia",
                "fonti": ["ANSA"],
                "testo": "Riassunto A.",
                "paragrafi": [
                    "Primo paragrafo A.",
                    "Secondo paragrafo A.",
                    "Terzo paragrafo A.",
                ],
            },
            {
                "titolo": "B",
                "categoria": "Mondo",
                "fonti": ["ANSA"],
                "testo": "Riassunto B.",
                "paragrafi": ["Primo paragrafo B.", "Secondo paragrafo B."],
            },
        ],
    }
    risultato = _finalizza_llm(
        dati, selezioni_finte(), datetime(2026, 11, 22, 7, 0, tzinfo=ROMA)
    )
    assert len(risultato["notizie"][0]["paragrafi"]) == 3
    assert len(risultato["notizie"][1]["paragrafi"]) == 2
    assert "Terzo paragrafo A." in risultato["testo"]
    assert "Secondo paragrafo B." in risultato["testo"]
    assert risultato["testo"].rstrip().endswith("Per oggi è tutto.")

def test_descrizione_ai_con_titoli_inglesi_viene_scartata():
    descrizione = (
        "22 novembre 2026 - Nave russa colpita a Bengasi, Australian politics live, "
        "Grillo se il giudice dice, Fire breaks out at popular tourist, "
        "Jensen Huang's reported affair was most."
    )
    assert _pulisci_descrizione_breve(descrizione, datetime(2026, 11, 22, 7, 0, tzinfo=ROMA)) == ""


def test_fallback_misto_filtra_i_titoli_inglesi():
    titoli = [
        "Nave russa colpita a Bengasi",
        "Australian politics live",
        "Grillo se il giudice dice",
        "Fire breaks out at popular tourist",
        "Jensen Huang's reported affair was most",
    ]
    breve = _descrizione_breve(titoli, datetime(2026, 11, 22, 7, 0, tzinfo=ROMA))
    assert breve.startswith("22 novembre 2026 - ")
    assert "Nave russa colpita" in breve
    assert "Grillo se il giudice" in breve
    for inglese in ("politics", "live", "fire", "tourist", "reported", "affair"):
        assert inglese not in breve.casefold()


def test_fallback_solo_inglese_usa_descrizione_generica_italiana():
    breve = _descrizione_breve(
        ["Australian politics live", "Fire breaks out at popular tourist"],
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
    )
    assert breve == "22 novembre 2026 - Notizie del giorno, aggiornamenti e approfondimenti."
    assert not _contiene_stopword_inglese(breve)


def test_traduzione_dedicata_aggiunge_solo_micro_italiani(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    monkeypatch.setattr(
        modulo_copione,
        "_chiama_gemini",
        lambda *a, **k: '{"titoli": ["Nave russa colpita", "Incendio turisti", "Politica australiana"]}',
    )
    breve = _descrizione_breve(
        ["Australian politics live", "Fire breaks out at popular tourist"],
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
        impostazioni=carica_impostazioni(),
    )
    assert "Nave russa colpita" in breve
    assert "Incendio turisti" in breve
    assert "Politica australiana" in breve
    assert not _contiene_stopword_inglese(breve)


def test_traduzione_che_resta_inglese_viene_scartata(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    monkeypatch.setattr(
        modulo_copione,
        "_chiama_gemini",
        lambda *a, **k: '{"titoli": ["Australian politics live", "Fire breaks out at popular tourist"]}',
    )
    breve = _descrizione_breve(
        ["Australian politics live", "Fire breaks out at popular tourist"],
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
        impostazioni=carica_impostazioni(),
    )
    assert breve == "22 novembre 2026 - Notizie del giorno, aggiornamenti e approfondimenti."
    assert not _contiene_stopword_inglese(breve)

def test_copione_ai_con_descrizione_inglese_resta_italiano():
    dati = {
        "titolo_episodio": "Notiziario di 22 novembre 2026",
        "descrizione": "Le notizie del giorno.",
        "descrizione_breve": (
            "22 novembre 2026 - Nave russa colpita a Bengasi, Australian politics live, "
            "Grillo se il giudice dice, Fire breaks out at popular tourist, "
            "Jensen Huang's reported affair was most."
        ),
        "testo": "Buongiorno. Questa è una notizia italiana. Per oggi è tutto.",
        "notizie": [],
    }
    risultato = _finalizza_llm(
        dati, selezioni_finte(), datetime(2026, 11, 22, 7, 0, tzinfo=ROMA)
    )
    assert risultato["descrizione_breve"].startswith("22 novembre 2026 - ")
    assert not _contiene_stopword_inglese(risultato["descrizione_breve"])
    assert "Australian" not in risultato["descrizione_breve"]

def _risposta_copione(testo: str) -> str:
    return __import__("json").dumps(
        {
            "titolo_episodio": "Notiziario di prova",
            "descrizione": "Le notizie di prova.",
            "descrizione_breve": "22 novembre 2026 - Manovra approvata, Cop31 fallita",
            "testo": testo,
            "notizie": [
                {"titolo": "Prima", "categoria": "Italia", "fonti": ["ANSA"], "testo": "Prima notizia."},
                {"titolo": "Seconda", "categoria": "Mondo", "fonti": ["ANSA"], "testo": "Seconda notizia."},
                {"titolo": "Terza", "categoria": "Economia", "fonti": ["ANSA"], "testo": "Terza notizia."},
            ],
        }
    )


def test_frasi_con_inglese_rileva_titoli_e_frasi():
    assert _frasi_con_inglese("Australian politics live. Tutto il resto è in italiano.")
    assert _frasi_con_inglese("Fire breaks out at popular tourist. La notizia continua.")
    assert not _frasi_con_inglese("Il governo ha presentato la manovra in Parlamento.")


def test_copione_ai_inglese_rigenera_una_volta(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    italiano = " ".join(["Il governo ha presentato il piano alla Camera."] * 20)
    inglese = "Australian politics live. Fire breaks out at popular tourist. " + italiano
    risposte = [_risposta_copione(inglese), _risposta_copione(italiano)]
    chiamate = {"n": 0}

    def finta(*args, **kwargs):
        chiamate["n"] += 1
        return risposte[min(chiamate["n"] - 1, 1)]

    monkeypatch.setattr(modulo_copione, "_chiama_gemini", finta)
    copione = genera_copione(
        selezioni_finte(),
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
        logger=LOGGER,
    )
    assert chiamate["n"] >= 2
    assert not _contiene_stopword_inglese(copione["testo"])


def test_copione_ai_sempre_inglese_usa_fallback_italiano(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    inglese = "Australian politics live. Fire breaks out at popular tourist. " + " ".join(
        ["Italian words are still English here."] * 20
    )
    chiamate = {"n": 0}
    monkeypatch.setattr(
        modulo_copione,
        "_chiama_gemini",
        lambda *a, **k: chiamate.__setitem__("n", chiamate["n"] + 1) or _risposta_copione(inglese),
    )
    copione = genera_copione(
        selezioni_finte(),
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
        logger=LOGGER,
    )
    assert copione["modalita"] == "fallback"
    assert chiamate["n"] >= 2
    assert not _contiene_stopword_inglese(copione["testo"])

def test_prompt_e_system_contengono_domande_e_posizione():
    prompt, _ = _prompt_utente(
        prepara_materiale(selezioni_finte()),
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
        {},
    )
    sistema = _system_prompt()
    for parola in (
        "cosa è successo",
        "chi o cosa è coinvolto",
        "quando e dove",
        "conseguenze",
        "posizione",
        "Non omettere notizie",
    ):
        assert parola.casefold() in prompt.casefold()
    assert '"posizione"' in prompt
    for parola in ("cosa è successo", "quando e dove", "conseguenze"):
        assert parola.casefold() in sistema.casefold()
    assert "non omettere notizie" in sistema.casefold()


def test_finalizza_llm_assegna_posizione_dal_titolo_se_manca():
    dati = {
        "titolo_episodio": "Notiziario di prova",
        "descrizione": "Notizie.",
        "testo": "Testo uno.\n\nTesto due.\n\nPer oggi è tutto.",
        "notizie": [
            {
                "titolo": "La manovra arriva in Parlamento",
                "categoria": "Economia",
                "fonti": ["Il Sole 24 Ore"],
                "testo": "La manovra arriva in Parlamento.",
            },
            {
                "titolo": "Il governo approva il piano per la scuola",
                "categoria": "Italia",
                "fonti": ["ANSA"],
                "testo": "Il governo approva il piano per la scuola.",
            },
            {
                "titolo": "Cop31, nuova bozza sul clima",
                "categoria": "Mondo",
                "fonti": ["ANSA"],
                "testo": "Cop31, nuova bozza sul clima.",
            },
        ],
    }
    risultato = _finalizza_llm(
        dati,
        selezioni_finte(),
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
    )
    assert [n["posizione"] for n in risultato["notizie"]] == [3, 2, 1]


def test_migliora_completezza_aggiunge_quando_dove_e_conseguenze():
    articolo = crea_articolo(
        "Il governo approva la riforma della scuola",
        fonte="ANSA",
        categoria="italia",
        sommario=(
            "Il 20 novembre 2026 il governo ha approvato a Roma la riforma "
            "della scuola. La riforma potrebbe aumentare i costi per le famiglie."
        ),
    )
    selezione = NotiziaSelezionata(crea_cluster([articolo]), True, 1, 100)
    materiale = prepara_materiale([selezione])
    copione = {
        "titolo_episodio": "Notiziario di prova",
        "descrizione": "Notizie.",
        "descrizione_breve": "",
        "testo": (
            "Il governo ha approvato la riforma della scuola.\n\n"
            "Per oggi è tutto. A domani."
        ),
        "notizie": [
            {
                "posizione": 1,
                "titolo": "Il governo approva la riforma della scuola",
                "categoria": "Italia",
                "fonti": ["ANSA"],
                "testo": "Il governo ha approvato la riforma della scuola.",
                "paragrafi": ["Il governo ha approvato la riforma della scuola."],
            }
        ],
        "modalita": "llm",
        "motivo_fallback": None,
        "target_parole": 100,
        "divario_parole": 90,
    }
    risultato = migliora_completezza(
        copione, [selezione], materiale, LOGGER
    )
    notizia = risultato["notizie"][0]
    testo_notizia = " ".join(notizia["paragrafi"])
    assert "20 novembre 2026" in testo_notizia
    assert "Roma" in testo_notizia
    assert "potrebbe aumentare" in testo_notizia
    assert len(notizia["paragrafi"]) == 3
    assert "20 novembre 2026" in risultato["testo"]
    assert "potrebbe aumentare" in risultato["testo"]
    assert risultato["testo"].rstrip().endswith("Per oggi è tutto. A domani.")
    assert risultato["modalita"] == "llm"
    assert risultato["motivo_fallback"] is None
    assert risultato["target_parole"] == 100
    assert risultato["divario_parole"] <= 90
    assert risultato["qualita"]["aggiunte"] == 2
    assert risultato["qualita"]["mancanti_iniziali"][0]["mancanti"] == [
        "quando",
        "dove",
        "conseguenze",
    ]
    assert risultato["qualita"]["mancanti_finali"] == []


def test_fallback_produce_posizione_e_passa_dal_controllo_qualita():
    copione = genera_copione(
        selezioni_finte(),
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
        logger=LOGGER,
        usa_llm=False,
    )
    posizioni = {voce["posizione"] for voce in copione["notizie"]}
    assert posizioni == {1, 2, 3}
    assert set(copione["qualita"]) == {
        "mancanti_iniziali",
        "aggiunte",
        "mancanti_finali",
    }
    assert copione["qualita"]["aggiunte"] >= 0


def test_migliora_completezza_non_solleva_se_il_materiale_non_basta(caplog):
    materiale = [
        {
            "posizione": 1,
            "titolo": "Riforma",
            "articoli": [
                {"titolo": "Riforma", "sommario": "Il 20 novembre 2026.", "testo": ""}
            ],
        }
    ]
    copione = {
        "testo": (
            "Il governo ha approvato la riforma.\n\n"
            "Per oggi è tutto. A domani."
        ),
        "notizie": [
            {
                "posizione": 1,
                "titolo": "Riforma",
                "categoria": "Italia",
                "fonti": ["ANSA"],
                "testo": "Il governo ha approvato la riforma.",
                "paragrafi": ["Il governo ha approvato la riforma."],
            }
        ],
        "modalita": "llm",
        "motivo_fallback": None,
        "target_parole": 100,
        "divario_parole": 90,
    }
    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        risultato = migliora_completezza(copione, [], materiale, LOGGER)
    assert risultato["testo"] == copione["testo"]
    assert risultato["qualita"]["aggiunte"] == 0
    assert risultato["qualita"]["mancanti_finali"]
    assert "mancano ancora" in caplog.text
    assert risultato["modalita"] == "llm"
    assert risultato["target_parole"] == 100


def test_migliora_completezza_non_incolla_titolo_e_prima_frase():
    articolo = crea_articolo(
        "Riforma scuola approvata",
        fonte="ANSA",
        categoria="italia",
        sommario=(
            "Il 20 novembre 2026 il governo ha approvato a Roma la riforma "
            "della scuola. La riforma potrebbe aumentare i costi per le famiglie."
        ),
    )
    selezione = NotiziaSelezionata(crea_cluster([articolo]), True, 1, 100)
    materiale = prepara_materiale([selezione])
    copione = {
        "testo": (
            "Il governo ha approvato la riforma della scuola.\n\n"
            "Per oggi è tutto. A domani."
        ),
        "notizie": [
            {
                "posizione": 1,
                "titolo": "Il governo approva la riforma della scuola",
                "categoria": "Italia",
                "fonti": ["ANSA"],
                "testo": "Il governo ha approvato la riforma della scuola.",
                "paragrafi": ["Il governo ha approvato la riforma della scuola."],
            }
        ],
        "target_parole": 100,
        "divario_parole": 90,
    }
    risultato = migliora_completezza(copione, [selezione], materiale, LOGGER)
    paragrafi = risultato["notizie"][0]["paragrafi"]
    assert any(p.startswith("Il 20 novembre 2026") for p in paragrafi)
    assert all("Riforma scuola approvata Il" not in p for p in paragrafi)
    assert risultato["qualita"]["aggiunte"] == 2
