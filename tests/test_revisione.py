from __future__ import annotations

import copy
import json
import logging
from datetime import datetime

import pytest

from helpers import crea_articolo, crea_cluster
from notiziario import copione as modulo_copione
from notiziario import revisione as modulo_revisione
from notiziario.config import carica_impostazioni
from notiziario.revisione import pulisci_residui, rifinisci_copione
from notiziario.selezione import NotiziaSelezionata
from notiziario.tempo import ROMA


LOGGER = logging.getLogger("test-revisione")


def impostazioni_revisione() -> dict:
    return {
        "llm_revisione": {
            "modello": "gemini-2.5-flash",
            "temperatura": 0.15,
            "max_output_tokens": 16384,
        },
        "llm_modello_riserva": "gemini-riserva",
    }


def copione_da_rivedere() -> dict:
    return {
        "titolo_episodio": "Notiziario di prova",
        "descrizione": "Le notizie di prova.",
        "descrizione_breve": "24 novembre 2026 - Sarkozy, sorveglianza",
        "testo": (
            "L'ex presidente della Repubblica. Nicolas Sarkozy.\n\n"
            "Resta indietro la tutela contro la sorveglianza, art.\n\n"
            "Per oggi è tutto. A domani."
        ),
        "notizie": [
            {
                "posizione": 1,
                "titolo": "Sarkozy",
                "categoria": "Mondo",
                "fonti": ["ANSA"],
                "testo": "L'ex presidente della Repubblica. Nicolas Sarkozy.",
                "paragrafi": [
                    "L'ex presidente della Repubblica. Nicolas Sarkozy."
                ],
            },
            {
                "posizione": 2,
                "titolo": "Sorveglianza",
                "categoria": "Italia",
                "fonti": ["Repubblica"],
                "testo": "Resta indietro la tutela contro la sorveglianza, art.",
                "paragrafi": [
                    "Resta indietro la tutela contro la sorveglianza, art."
                ],
            },
        ],
        "modalita": "llm",
        "motivo_fallback": None,
        "target_parole": 40,
        "divario_parole": 21,
        "parole": 19,
    }


def risposta_valida() -> str:
    return json.dumps(
        {
            "chiusura": "Per oggi è tutto. A domani.",
            "notizie": [
                {
                    "posizione": 1,
                    "paragrafi": [
                        "L'ex presidente della Repubblica, Nicolas Sarkozy."
                    ],
                },
                {
                    "posizione": 2,
                    "paragrafi": [
                        "Resta indietro la tutela contro la sorveglianza."
                    ],
                },
            ],
        },
        ensure_ascii=False,
    )


def test_pulisci_residui_rimuove_placeholder():
    assert pulisci_residui(
        "Non ci sono notizie disponibili per la categoria Ambiente."
    ) == ""
    assert (
        pulisci_residui(
            "Il governo ha deciso. Non ci sono notizie disponibili per la "
            "categoria Ambiente."
        )
        == "Il governo ha deciso."
    )


def test_pulisci_residui_rimuove_code_di_fonte():
    assert (
        pulisci_residui("Il ministro ha parlato. proviene da BuoneNotizie. It.")
        == "Il ministro ha parlato."
    )
    assert pulisci_residui("Leggi anche: le altre notizie del giorno.") == ""
    assert pulisci_residui("Fonte: ANSA.") == ""
    assert pulisci_residui("© 2026 ANSA. Tutti i diritti riservati.") == ""
    assert pulisci_residui("Riproduzione riservata.") == ""
    assert pulisci_residui("Articolo correlato: il testo sulla manovra.") == ""
    assert (
        pulisci_residui("Il testo utile. Articolo correlato: la manovra.")
        == "Il testo utile."
    )


def test_pulisci_residui_taglia_le_code_sospese():
    assert (
        pulisci_residui("Resta indietro la tutela contro la sorveglianza, art.")
        == "Resta indietro la tutela contro la sorveglianza."
    )
    assert (
        pulisci_residui("Il termine è previsto dall'art.")
        == "Il termine è previsto."
    )
    assert (
        pulisci_residui("Il governo ha approvato il piano e")
        == "Il governo ha approvato il piano."
    )
    assert (
        pulisci_residui("Il governo ha approvato il piano e,")
        == "Il governo ha approvato il piano."
    )
    assert (
        pulisci_residui("Prima frase completa. La seconda frase si interrompe di")
        == "Prima frase completa."
    )


def test_pulisci_residui_non_tocca_art_legittimo():
    # Una frase completa finisce con il numero, non con l'abbreviazione:
    # "dall'art. 5." resta intatta, mentre "…, art." è un troncamento.
    testo = "L'obbligo è previsto dall'art. 5."
    assert pulisci_residui(testo) == testo
    assert pulisci_residui("Il termine è fissato al 5 dicembre.") == (
        "Il termine è fissato al 5 dicembre."
    )


def test_rifinisci_copione_applica_la_revisione_valida(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    chiamate: list[dict] = []

    def finta(prompt, system, impostazioni, api_key, logger, **kwargs):
        chiamate.append(kwargs)
        return risposta_valida()

    monkeypatch.setattr(modulo_revisione, "_chiama_gemini", finta)
    originale = copione_da_rivedere()
    risultato = rifinisci_copione(
        originale, impostazioni_revisione(), LOGGER
    )

    assert risultato["revisione"]["applicata"] is True
    assert risultato["revisione"]["modello"] == "gemini-2.5-flash"
    assert risultato["revisione"]["parole_prima"] == 20
    assert risultato["revisione"]["parole_dopo"] == 19
    assert risultato["notizie"][0]["paragrafi"] == [
        "L'ex presidente della Repubblica, Nicolas Sarkozy."
    ]
    assert risultato["notizie"][1]["paragrafi"] == [
        "Resta indietro la tutela contro la sorveglianza."
    ]
    # Titoli, fonti e ordine restano quelli originali.
    assert [n["titolo"] for n in risultato["notizie"]] == ["Sarkozy", "Sorveglianza"]
    assert [n["fonti"] for n in risultato["notizie"]] == [["ANSA"], ["Repubblica"]]
    assert risultato["testo"] == (
        "L'ex presidente della Repubblica, Nicolas Sarkozy.\n\n"
        "Resta indietro la tutela contro la sorveglianza.\n\n"
        "Per oggi è tutto. A domani."
    )
    assert risultato["divario_parole"] == 21
    assert risultato["parole"] == 19
    assert risultato["titolo_episodio"] == originale["titolo_episodio"]
    assert risultato["descrizione"] == originale["descrizione"]
    assert risultato["revisione"]["parziale"] is False
    assert risultato["revisione"]["posizioni_scartate"] == []
    # La revisione usa il modello e i parametri dedicati.
    assert chiamate[0]["modello"] == "gemini-2.5-flash"
    assert chiamate[0]["temperatura"] == 0.15
    assert chiamate[0]["max_output_tokens"] == 16384
    assert chiamate[0]["thinking_budget"] == 0


def _risposta_non_valida(tipo: str) -> str:
    base = {
        "chiusura": "Per oggi è tutto. A domani.",
        "notizie": [
            {
                "posizione": 1,
                "paragrafi": [
                    "L'ex presidente della Repubblica, Nicolas Sarkozy."
                ],
            },
            {
                "posizione": 2,
                "paragrafi": [
                    "Resta indietro la tutela contro la sorveglianza."
                ],
            },
        ],
    }
    if tipo == "posizione_mancante":
        base["notizie"] = base["notizie"][:1]
    elif tipo == "posizione_duplicata":
        base["notizie"][1]["posizione"] = 1
    elif tipo == "paragrafo_vuoto":
        base["notizie"][0]["paragrafi"] = [""]
    elif tipo == "inglese":
        base["notizie"][0]["paragrafi"] = ["The president said."]
    elif tipo == "placeholder":
        base["notizie"][0]["paragrafi"] = [
            "Non ci sono notizie disponibili per la categoria Ambiente."
        ]
    elif tipo == "troppo_corta":
        base["notizie"] = [
            {"posizione": 1, "paragrafi": ["Nicolas Sarkozy."]},
            {"posizione": 2, "paragrafi": ["Tutela ridotta."]},
        ]
    elif tipo == "chiusura_vuota":
        base["chiusura"] = ""
    return json.dumps(base, ensure_ascii=False)


def _risposta_finta(tipo):
    return lambda prompt, system, impostazioni, api_key, logger, **kwargs: (
        _risposta_non_valida(tipo)
    )


@pytest.mark.parametrize(
    "tipo,atteso",
    [
        ("posizione_mancante", "posizioni"),
        ("posizione_duplicata", "duplicata"),
        ("troppo_corta", "nessuna posizione valida"),
    ],
)
def test_rifinisci_copione_scarta_errori_globali(monkeypatch, tipo, atteso):
    # Posizioni mancanti/duplicate e nessuna posizione valida sono errori
    # globali: non si applica nulla e resta il copione pulito.
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    monkeypatch.setattr(
        modulo_revisione,
        "_chiama_gemini",
        _risposta_finta(tipo),
    )
    originale = copione_da_rivedere()
    risultato = rifinisci_copione(
        originale, impostazioni_revisione(), LOGGER
    )

    assert risultato["revisione"]["applicata"] is False
    assert risultato["revisione"]["parziale"] is False
    assert risultato["revisione"]["posizioni_scartate"] == []
    assert atteso.casefold() in risultato["revisione"]["motivo"].casefold()
    # Nessuna modifica parziale: resta il copione pulito deterministicamente.
    assert risultato["notizie"][1]["paragrafi"] == [
        "Resta indietro la tutela contro la sorveglianza."
    ]
    assert risultato["testo"].rstrip().endswith("Per oggi è tutto. A domani.")
    assert [n["titolo"] for n in risultato["notizie"]] == ["Sarkozy", "Sorveglianza"]
    assert [n["fonti"] for n in risultato["notizie"]] == [["ANSA"], ["Repubblica"]]
    assert originale["notizie"][1]["paragrafi"] == [
        "Resta indietro la tutela contro la sorveglianza, art."
    ]


@pytest.mark.parametrize("tipo", ["paragrafo_vuoto", "inglese", "placeholder"])
def test_rifinisci_copione_applica_le_posizioni_valide(monkeypatch, tipo):
    # Una posizione invalida viene scartata, l'altra viene applicata.
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    monkeypatch.setattr(
        modulo_revisione,
        "_chiama_gemini",
        _risposta_finta(tipo),
    )
    risultato = rifinisci_copione(
        copione_da_rivedere(), impostazioni_revisione(), LOGGER
    )

    assert risultato["revisione"]["applicata"] is True
    assert risultato["revisione"]["parziale"] is True
    assert risultato["revisione"]["posizioni_scartate"] == [1]
    assert risultato["notizie"][0]["paragrafi"] == [
        "L'ex presidente della Repubblica. Nicolas Sarkozy."
    ]
    assert risultato["notizie"][1]["paragrafi"] == [
        "Resta indietro la tutela contro la sorveglianza."
    ]
    assert risultato["testo"] == (
        "L'ex presidente della Repubblica. Nicolas Sarkozy.\n\n"
        "Resta indietro la tutela contro la sorveglianza.\n\n"
        "Per oggi è tutto. A domani."
    )
    assert [n["titolo"] for n in risultato["notizie"]] == ["Sarkozy", "Sorveglianza"]


def test_rifinisci_copione_chiusura_invalida_tiene_l_originale(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    monkeypatch.setattr(
        modulo_revisione,
        "_chiama_gemini",
        _risposta_finta("chiusura_vuota"),
    )
    risultato = rifinisci_copione(
        copione_da_rivedere(), impostazioni_revisione(), LOGGER
    )

    assert risultato["revisione"]["applicata"] is True
    assert risultato["revisione"]["parziale"] is True
    assert risultato["revisione"]["posizioni_scartate"] == []
    assert "chiusura originale" in risultato["revisione"]["motivo"]
    assert risultato["testo"].rstrip().endswith("Per oggi è tutto. A domani.")


def test_rifinisci_copione_accetta_taglio_al_70_percento(monkeypatch):
    # Totale al 68% (sotto la vecchia soglia 0.70) ma ogni notizia resta
    # sopra il 50%: la revisione va applicata, non scartata.
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    risposta = json.dumps(
        {
            "chiusura": "Per oggi è tutto. A domani.",
            "notizie": [
                {"posizione": 1, "paragrafi": ["Nicolas Sarkozy assolto."]},
                {"posizione": 2, "paragrafi": ["La sorveglianza resta limitata."]},
            ],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        modulo_revisione,
        "_chiama_gemini",
        lambda *args, **kwargs: risposta,
    )
    risultato = rifinisci_copione(
        copione_da_rivedere(), impostazioni_revisione(), LOGGER
    )

    assert risultato["revisione"]["applicata"] is True
    assert risultato["revisione"]["parziale"] is False
    assert risultato["revisione"]["posizioni_scartate"] == []
    assert risultato["notizie"][0]["paragrafi"] == ["Nicolas Sarkozy assolto."]
    assert risultato["notizie"][1]["paragrafi"] == ["La sorveglianza resta limitata."]
    # 3 + 4 + 6 = 13 parole su 19 pulite.
    assert risultato["revisione"]["parole_dopo"] == 13


def test_rifinisci_copione_scarta_solo_la_notizia_dimezzata(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    risposta = json.dumps(
        {
            "chiusura": "Per oggi è tutto. A domani.",
            "notizie": [
                {
                    "posizione": 1,
                    "paragrafi": ["L'ex presidente della Repubblica, Sarkozy."],
                },
                {"posizione": 2, "paragrafi": ["Tutela ridotta."]},
            ],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        modulo_revisione,
        "_chiama_gemini",
        lambda *args, **kwargs: risposta,
    )
    originale = copione_da_rivedere()
    risultato = rifinisci_copione(
        originale, impostazioni_revisione(), LOGGER
    )

    assert risultato["revisione"]["applicata"] is True
    assert risultato["revisione"]["parziale"] is True
    assert risultato["revisione"]["posizioni_scartate"] == [2]
    assert risultato["notizie"][0]["paragrafi"] == [
        "L'ex presidente della Repubblica, Sarkozy."
    ]
    # La notizia scartata resta identica all'originale pulito.
    assert risultato["notizie"][1]["paragrafi"] == [
        "Resta indietro la tutela contro la sorveglianza."
    ]
    assert risultato["testo"] == (
        "L'ex presidente della Repubblica, Sarkozy.\n\n"
        "Resta indietro la tutela contro la sorveglianza.\n\n"
        "Per oggi è tutto. A domani."
    )
    # L'originale in ingresso non viene mutato.
    assert originale["notizie"][1]["paragrafi"] == [
        "Resta indietro la tutela contro la sorveglianza, art."
    ]


def test_rifinisci_copione_ritenta_se_manca_il_json(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    prompt_usati: list[str] = []

    def finta(prompt, system, impostazioni, api_key, logger, **kwargs):
        prompt_usati.append(prompt)
        if len(prompt_usati) == 1:
            return "Ecco la revisione: nessun JSON qui."
        return risposta_valida()

    monkeypatch.setattr(modulo_revisione, "_chiama_gemini", finta)
    risultato = rifinisci_copione(
        copione_da_rivedere(), impostazioni_revisione(), LOGGER
    )

    assert len(prompt_usati) == 2
    assert "Rispondi SOLO con l'oggetto JSON" in prompt_usati[1]
    assert "Rispondi SOLO con l'oggetto JSON" not in prompt_usati[0]
    assert risultato["revisione"]["applicata"] is True
    assert risultato["revisione"]["modello"] == "gemini-2.5-flash"


def test_rifinisci_copione_prova_la_riserva(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    modelli: list[str] = []

    def finta(prompt, system, impostazioni, api_key, logger, *, modello=None, **kwargs):
        modelli.append(modello)
        if modello == "gemini-2.5-flash":
            raise modulo_copione.LlmError("HTTP 429 quota")
        return risposta_valida()

    monkeypatch.setattr(modulo_revisione, "_chiama_gemini", finta)
    risultato = rifinisci_copione(
        copione_da_rivedere(), impostazioni_revisione(), LOGGER
    )

    assert modelli == ["gemini-2.5-flash", "gemini-riserva"]
    assert risultato["revisione"]["applicata"] is True
    assert risultato["revisione"]["modello"] == "gemini-riserva"


def test_rifinisci_copione_prova_tutta_la_catena_di_riserva(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    impostazioni = {
        "llm": {"modello": "gemini-3.1-flash-lite"},
        "llm_modelli_riserva": [
            "gemini-3.8-flash",
            "gemini-3.6-flash",
            "gemini-3-flash",
            "gemini-2.5-flash",
        ],
        "llm_modello_riserva": "gemini-3.8-flash",
        "llm_revisione": {
            "modello": "gemini-3.8-flash",
            "temperatura": 0.15,
            "max_output_tokens": 16384,
        },
    }
    modelli: list[str] = []
    falliti = {
        "gemini-3.8-flash",
        "gemini-3.1-flash-lite",
        "gemini-3.6-flash",
    }

    def finta(prompt, system, impostazioni, api_key, logger, *, modello=None, **kwargs):
        modelli.append(modello)
        if modello in falliti:
            raise modulo_copione.LlmError("HTTP 429 quota")
        return risposta_valida()

    monkeypatch.setattr(modulo_revisione, "_chiama_gemini", finta)
    risultato = rifinisci_copione(
        copione_da_rivedere(), impostazioni, LOGGER
    )

    assert modelli == [
        "gemini-3.8-flash",
        "gemini-3.1-flash-lite",
        "gemini-3.6-flash",
        "gemini-3-flash",
    ]
    assert len(modelli) == len(set(modelli))
    assert risultato["revisione"]["applicata"] is True
    assert risultato["revisione"]["modello"] == "gemini-3-flash"


def test_rifinisci_copione_non_solleva_se_tutti_i_modelli_falliscono(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")

    def finta(*args, **kwargs):
        raise RuntimeError("quota esaurita")

    monkeypatch.setattr(modulo_revisione, "_chiama_gemini", finta)
    originale = copione_da_rivedere()
    risultato = rifinisci_copione(
        originale, impostazioni_revisione(), LOGGER
    )

    assert risultato["revisione"]["applicata"] is False
    assert "RuntimeError" in risultato["revisione"]["motivo"]
    assert risultato["notizie"][1]["paragrafi"] == [
        "Resta indietro la tutela contro la sorveglianza."
    ]
    assert risultato["testo"].rstrip().endswith("Per oggi è tutto. A domani.")


def test_rifinisci_copione_non_chiama_llm_senza_notizie(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    chiamate = {"n": 0}

    def finta(*args, **kwargs):
        chiamate["n"] += 1
        return risposta_valida()

    monkeypatch.setattr(modulo_revisione, "_chiama_gemini", finta)
    copione = {
        "testo": "Per oggi è tutto. A domani.",
        "notizie": [],
        "target_parole": 10,
        "divario_parole": 4,
    }
    risultato = rifinisci_copione(
        copione, impostazioni_revisione(), LOGGER
    )
    assert chiamate["n"] == 0
    assert risultato["revisione"]["applicata"] is False
    assert "nessuna notizia" in risultato["revisione"]["motivo"]


def test_rifinisci_copione_rispetta_usa_llm_false(monkeypatch):
    # Rete mai usata nei test: con l'LLM disattivato il revisore non parte.
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    chiamate = {"n": 0}

    def finta(*args, **kwargs):
        chiamate["n"] += 1
        return risposta_valida()

    monkeypatch.setattr(modulo_revisione, "_chiama_gemini", finta)
    risultato = rifinisci_copione(
        copione_da_rivedere(), impostazioni_revisione(), LOGGER, usa_llm=False
    )
    assert chiamate["n"] == 0
    assert risultato["revisione"]["applicata"] is False
    assert "disattivata" in risultato["revisione"]["motivo"]
    assert risultato["notizie"][1]["paragrafi"] == [
        "Resta indietro la tutela contro la sorveglianza."
    ]


def test_rifinisci_copione_senza_chiave_non_chiama_llm(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        modulo_revisione,
        "_chiama_gemini",
        lambda *args, **kwargs: pytest.fail("il revisore non deve partire"),
    )
    risultato = rifinisci_copione(
        copione_da_rivedere(), impostazioni_revisione(), LOGGER
    )
    assert risultato["revisione"]["applicata"] is False
    assert "GEMINI_API_KEY" in risultato["revisione"]["motivo"]


def test_genera_copione_integra_la_revisione(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-di-prova")
    selezione = NotiziaSelezionata(
        crea_cluster(
            [
                crea_articolo(
                    "Il governo approva il piano per la scuola",
                    sommario=(
                        "Il consiglio dei ministri ha approvato il piano. "
                        "Sono previsti fondi per i laboratori."
                    ),
                )
            ]
        ),
        copertina=True,
        ordine=1,
        parole_target=120,
    )
    testo = " ".join(
        ["Il governo ha approvato il piano per la scuola."] * 12
    )
    generazione = json.dumps(
        {
            "titolo_episodio": "Notiziario di prova",
            "descrizione": "Le notizie di prova.",
            "descrizione_breve": "22 novembre 2026 - Scuola, manovra",
            "testo": testo,
            "notizie": [
                {
                    "titolo": "Il governo approva il piano per la scuola",
                    "categoria": "Italia",
                    "fonti": ["ANSA"],
                    "testo": "Il governo ha approvato il piano per la scuola.",
                }
            ],
        },
        ensure_ascii=False,
    )
    chiamate = {"generazione": 0, "revisione": 0}

    def finta(prompt, system, impostazioni, api_key, logger, **kwargs):
        if "Copione da rivedere:" in prompt:
            chiamate["revisione"] += 1
            dati = json.loads(prompt.split("Copione da rivedere:", 1)[1])
            return json.dumps(
                {
                    "chiusura": dati["chiusura"],
                    "notizie": [
                        {
                            "posizione": voce["posizione"],
                            "paragrafi": voce["paragrafi"],
                        }
                        for voce in dati["notizie"]
                    ],
                },
                ensure_ascii=False,
            )
        chiamate["generazione"] += 1
        return generazione

    monkeypatch.setattr(modulo_copione, "_chiama_gemini", finta)
    copione = modulo_copione.genera_copione(
        [selezione],
        carica_impostazioni(),
        datetime(2026, 11, 22, 7, 0, tzinfo=ROMA),
        logger=LOGGER,
    )

    assert chiamate == {"generazione": 1, "revisione": 1}
    assert copione["modalita"] == "llm"
    assert copione["revisione"]["applicata"] is True
    assert copione["notizie"][0]["titolo"] == (
        "Il governo approva il piano per la scuola"
    )
    assert copione["notizie"][0]["fonti"] == ["ANSA"]
    assert copione["target_parole"] > 0
    # Il testo ricostruito contiene i paragrafi della notizia e la chiusura.
    for paragrafo in copione["notizie"][0]["paragrafi"]:
        assert paragrafo in copione["testo"]
    assert copione["testo"].rstrip().endswith("A domani.")


def test_chiama_gemini_usa_temperatura_e_token_di_revisione(monkeypatch):
    catturato: dict = {}

    class Risposta:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": '{"ok": true}'}]}}
                ]
            }

    def finto_post(url, json=None, headers=None, timeout=None, **kwargs):
        catturato["payload"] = json
        return Risposta()

    monkeypatch.setattr(modulo_copione.requests, "post", finto_post)
    testo = modulo_copione._chiama_gemini(
        "prompt",
        "system",
        carica_impostazioni(),
        "chiave-di-prova",
        LOGGER,
        modello="gemini-2.5-flash",
        temperatura=0.15,
        max_output_tokens=4096,
    )
    assert testo == '{"ok": true}'
    configurazione = catturato["payload"]["generationConfig"]
    assert configurazione["temperature"] == 0.15
    assert configurazione["maxOutputTokens"] == 4096


def _risposta_gemini(testo: str, status_code: int = 200):
    class Risposta:
        pass

    risposta = Risposta()
    risposta.status_code = status_code
    risposta.json = lambda: {
        "candidates": [{"content": {"parts": [{"text": testo}]}}]
    }
    return risposta


def _risposta_http_400(messaggio: str):
    class Risposta:
        status_code = 400

        def json(self):
            return {"error": {"message": messaggio}}

    return Risposta()


def test_chiama_gemini_ritenta_senza_thinking_config_su_http_400(monkeypatch):
    payloads: list[dict] = []

    def finto_post(url, json=None, headers=None, timeout=None, **kwargs):
        # Il payload viene mutato al retry: salvo una copia per ogni chiamata.
        payloads.append(copy.deepcopy(json))
        if len(payloads) == 1:
            return _risposta_http_400("thinkingConfig non supportato")
        return _risposta_gemini('{"ok": true}')

    monkeypatch.setattr(modulo_copione.requests, "post", finto_post)
    testo = modulo_copione._chiama_gemini(
        "prompt",
        "system",
        carica_impostazioni(),
        "chiave-di-prova",
        LOGGER,
        max_output_tokens=16384,
        thinking_budget=0,
    )

    assert testo == '{"ok": true}'
    assert len(payloads) == 2
    assert payloads[0]["generationConfig"]["thinkingConfig"] == {
        "thinkingBudget": 0
    }
    assert "thinkingConfig" not in payloads[1]["generationConfig"]


def test_chiama_gemini_http_400_conserva_l_errore_con_thinking(monkeypatch):
    payloads: list[dict] = []

    def finto_post(url, json=None, headers=None, timeout=None, **kwargs):
        payloads.append(json)
        return _risposta_http_400("thinkingConfig non supportato")

    monkeypatch.setattr(modulo_copione.requests, "post", finto_post)
    with pytest.raises(modulo_copione.LlmError) as errore:
        modulo_copione._chiama_gemini(
            "prompt",
            "system",
            carica_impostazioni(),
            "chiave-di-prova",
            LOGGER,
            thinking_budget=0,
        )

    assert len(payloads) == 2
    assert "HTTP 400" in str(errore.value)
    assert "thinkingConfig" in str(errore.value)


def test_chiama_gemini_default_invariati(monkeypatch):
    catturato: dict = {}

    class Risposta:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": '{"ok": true}'}]}}
                ]
            }

    def finto_post(url, json=None, headers=None, timeout=None, **kwargs):
        catturato["payload"] = json
        return Risposta()

    monkeypatch.setattr(modulo_copione.requests, "post", finto_post)
    impostazioni = carica_impostazioni()
    modulo_copione._chiama_gemini(
        "prompt",
        "system",
        impostazioni,
        "chiave-di-prova",
        LOGGER,
    )
    configurazione = catturato["payload"]["generationConfig"]
    assert configurazione["temperature"] == impostazioni["llm"]["temperatura"]
    assert (
        configurazione["maxOutputTokens"]
        == impostazioni["llm"]["max_output_tokens"]
    )
