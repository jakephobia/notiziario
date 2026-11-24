"""Revisione finale del copione: pulizia deterministica e revisione LLM.

Il layer non deve mai bloccare la generazione: ogni errore viene loggato e il
copione pulito deterministicamente viene restituito comunque.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
from typing import Any

from .testi import conta_parole, rimuovi_pubblicita


MODELLO_REVISIONE_DEFAULT = "gemini-2.5-flash"
TEMPERATURA_REVISIONE_DEFAULT = 0.15
MAX_OUTPUT_TOKENS_REVISIONE_DEFAULT = 8192

# Rapporto ammesso tra parole revisionate e parole originali: evita sia la
# perdita di contenuti sia l'aggiunta di fatti.
RAPPORTO_MINIMO = 0.70
RAPPORTO_MASSIMO = 1.15

_TERMINALI = ".!?»\"”"

# Parole funzionali che, in coda a un paragrafo, indicano una frase troncata.
_STOPWORD_CODA = {
    "di", "a", "in", "con", "per", "che", "e", "o", "il", "lo", "la",
    "i", "gli", "le", "un", "uno", "una", "del", "dello", "della", "dei",
    "degli", "delle", "al", "allo", "alla", "ai", "agli", "alle", "dal",
    "dallo", "dalla", "dai", "dagli", "dalle", "nel", "nello", "nella",
    "nei", "negli", "nelle", "sul", "sullo", "sulla", "sui", "sugli",
    "sulle", "tra", "fra", "come", "più", "meno", "molto", "poco", "dopo",
    "prima", "secondo", "senza", "sopra", "sotto", "verso", "presso",
    "durante", "contro", "oltre", "entro", "fino",
}

_PLACEHOLDER_RE = re.compile(
    r"non\s+ci\s+sono\s+notizie\s+disponibili\s+per\s+la\s+categoria\b"
    r"[^.!?]*[.!?]?",
    re.IGNORECASE,
)

# Marcatori di fonte, boilerplate o pubblicità riconosciuti come residui.
_MARCATORI = (
    r"proviene\s+da\b",
    r"leggi\s+anche\b",
    r"articolo\s+correlato\b",
    r"riproduzione\s+riservata\b",
    r"tutti\s+i\s+diritti\s+riservati\b",
    r"fonte\s*:",
    r"©",
)
_MARCATORE_RE = re.compile("|".join(_MARCATORI), re.IGNORECASE)
# In pulizia deterministica tagliamo solo le clausole che *iniziano* con un
# marcatore: "proviene da" o "Leggi anche" a metà frase possono essere testo
# legittimo e restano al revisore LLM.
_MARCATORE_INIZIO_RE = re.compile(
    r"^(?:" + "|".join(_MARCATORI) + r")",
    re.IGNORECASE,
)

# Frammento breve rimasto dopo un marcatore (es. "It." di "BuoneNotizie. It.").
_FRAMMENTO_FONTE_RE = re.compile(
    r"^(?:[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ0-9&'’.-]*\.?"
    r"(?:\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ0-9&'’.-]*\.?){0,2})$"
)

_CLAUSOLA_RE = re.compile(r"(?<=[.!?»])\s+")
_ABBREVIAZIONE_CODA_RE = re.compile(
    r"(?:^|[\s,;:–—-])([^\s,;:–—-]*artt?\.)[\s,;:–—-]*$",
    re.IGNORECASE,
)
_ULTIMA_PAROLA_RE = re.compile(
    r"(?:^|[\s,;:–—-])([A-Za-zÀ-ÖØ-öø-ÿ]+)[\s,;:–—-]*$"
)
_PAROLA_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’][A-Za-zÀ-ÖØ-öø-ÿ]+)?")

_SCHEMA = {
    "chiusura": "string",
    "notizie": [{"posizione": 1, "paragrafi": ["...", "..."]}],
}

_SYSTEM_REVISIONE = (
    "Sei un revisore editoriale italiano. Correggi solo la forma del testo. "
    "Rispondi soltanto con JSON valido."
)


class _RevisioneError(Exception):
    """Risposta del revisore non utilizzabile: il copione resta pulito."""


def _chiave_api() -> str:
    return os.environ.get("GEMINI_API_KEY", "").strip()


def _chiama_gemini(
    prompt: str,
    system: str,
    impostazioni: dict[str, Any],
    api_key: str,
    logger: logging.Logger,
    *,
    modello: str | None = None,
    temperatura: float | None = None,
    max_output_tokens: int | None = None,
) -> str:
    """Wrapper pattchabile nei test: inoltra alla chiamata di ``copione``."""
    from .copione import _chiama_gemini as chiama

    return chiama(
        prompt,
        system,
        impostazioni,
        api_key,
        logger,
        modello=modello,
        temperatura=temperatura,
        max_output_tokens=max_output_tokens,
    )


def _estrai_json(testo: str) -> dict[str, Any]:
    from .copione import _estrai_json as estrai

    return estrai(testo)


def _frasi_con_inglese(testo: str) -> list[str]:
    from .copione import _frasi_con_inglese as frasi

    return frasi(testo)


def _redigi(messaggio: Any) -> str:
    from .copione import _redigi as redigi

    return redigi(messaggio)


def _config_revisione(
    impostazioni: dict[str, Any],
) -> tuple[str, float, int]:
    config = (
        impostazioni.get("llm_revisione") if isinstance(impostazioni, dict) else None
    )
    if not isinstance(config, dict):
        config = {}
    modello = str(config.get("modello") or MODELLO_REVISIONE_DEFAULT).strip()
    if not modello:
        modello = MODELLO_REVISIONE_DEFAULT
    try:
        temperatura = float(config.get("temperatura", TEMPERATURA_REVISIONE_DEFAULT))
    except (TypeError, ValueError):
        temperatura = TEMPERATURA_REVISIONE_DEFAULT
    try:
        massimo = int(
            config.get("max_output_tokens", MAX_OUTPUT_TOKENS_REVISIONE_DEFAULT)
        )
    except (TypeError, ValueError):
        massimo = MAX_OUTPUT_TOKENS_REVISIONE_DEFAULT
    return modello, temperatura, massimo


def _chiudi(testo: str) -> str:
    """Chiude una frase con il punto se manca la punteggiatura finale."""
    testo = testo.strip().rstrip(" \t,;:–—-")
    if not testo:
        return ""
    if testo[-1] not in _TERMINALI:
        testo += "."
    return testo


def _rimuovi_placeholder(testo: str) -> str:
    sostituito = _PLACEHOLDER_RE.sub(" ", testo)
    sostituito = re.sub(r"\s+", " ", sostituito).strip()
    if not re.search(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]", sostituito):
        return ""
    return sostituito


def _rimuovi_boilerplate(testo: str) -> str:
    clausole = [c.strip() for c in _CLAUSOLA_RE.split(testo) if c.strip()]
    if not clausole:
        return ""
    if len(clausole) == 1:
        if _MARCATORE_INIZIO_RE.match(clausole[0]):
            return ""
        return clausole[0]
    tenute: list[str] = []
    rimuovi_frammento = False
    for clausola in clausole:
        if _MARCATORE_INIZIO_RE.match(clausola):
            rimuovi_frammento = True
            continue
        if rimuovi_frammento and _FRAMMENTO_FONTE_RE.match(clausola):
            # Coda di una testata spezzata dal boilerplate (es. "It.").
            continue
        rimuovi_frammento = False
        tenute.append(clausola)
    return " ".join(tenute).strip()


def _taglia_coda_sospesa(testo: str) -> str:
    testo = testo.strip()
    if not testo:
        return ""
    # Abbreviazioni come "art." e "artt." in coda sono sempre troncamenti:
    # una frase italiana completa non finisce con l'abbreviazione da sola
    # (finirebbe con il numero, es. "dall'art. 5.").
    abbreviazione = _ABBREVIAZIONE_CODA_RE.search(testo)
    if abbreviazione:
        return _chiudi(testo[: abbreviazione.start()])
    if testo[-1] in _TERMINALI:
        return testo
    ultima = _ULTIMA_PAROLA_RE.search(testo)
    if not ultima or ultima.group(1).casefold() not in _STOPWORD_CODA:
        return testo
    clausole = [c.strip() for c in _CLAUSOLA_RE.split(testo) if c.strip()]
    if len(clausole) >= 2:
        # Il paragrafo prosegue con frasi complete: elimino solo l'ultima.
        return " ".join(clausole[:-1])
    tagliato = testo[: ultima.start(1)].rstrip(" \t,;:–—-")
    if len(_PAROLA_RE.findall(tagliato)) < 2:
        return ""
    # Frammento unico: tolgo solo la coda e lascio al revisore il resto.
    return _chiudi(tagliato)


def pulisci_residui(testo: str) -> str:
    """Pulizia deterministica e prudente di un paragrafo del copione.

    Rimuove placeholder di categoria vuota, code di fonte/boilerplate e frasi
    troncate che terminano con una parola funzionale sospesa. Non riscrive il
    testo: se un residuo non è riconoscibile con sicurezza, lo lascia al
    revisore LLM.
    """
    if not isinstance(testo, str):
        return ""
    pulito = re.sub(r"\s+", " ", testo).strip()
    if not pulito:
        return ""
    pulito = _rimuovi_placeholder(pulito)
    if not pulito:
        return ""
    pulito = _rimuovi_boilerplate(pulito)
    if not pulito:
        return ""
    pulito = _taglia_coda_sospesa(pulito)
    pulito = re.sub(r"\s+", " ", pulito).strip()
    pulito = re.sub(r"\s+([,.;:!?])", r"\1", pulito)
    return pulito


def _paragrafi_copione(copione: dict[str, Any]) -> list[str]:
    testo = copione.get("testo")
    if not isinstance(testo, str):
        return []
    return [p.strip() for p in re.split(r"\n\s*\n", testo) if p.strip()]


def _posizione(voce: dict[str, Any], indice: int) -> int:
    try:
        return int(voce.get("posizione"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return indice


def _corpo_e_chiusura(copione: dict[str, Any]) -> tuple[list[str], str]:
    """Corpo pulito del testo e chiusura finale, con default se assente."""
    from .copione import _CHIUSURA_DEFAULT, _separa_chiusura

    paragrafi = [pulisci_residui(p) for p in _paragrafi_copione(copione)]
    paragrafi = [p for p in paragrafi if p]
    if not paragrafi:
        return [], _CHIUSURA_DEFAULT
    corpo, chiusura = _separa_chiusura(paragrafi)
    chiusura = pulisci_residui(chiusura) if chiusura else ""
    if not chiusura:
        return paragrafi, _CHIUSURA_DEFAULT
    return corpo, chiusura


def _notizie_pulite(copione: dict[str, Any]) -> list[dict[str, Any]]:
    """Copia delle notizie con i paragrafi puliti deterministicamente."""
    notizie: list[dict[str, Any]] = []
    for indice, voce in enumerate(copione.get("notizie") or [], start=1):
        if not isinstance(voce, dict):
            continue
        paragrafi: list[str] = []
        grezzi = voce.get("paragrafi")
        if isinstance(grezzi, list):
            for grezzo in grezzi:
                pulito = pulisci_residui(str(grezzo or ""))
                if pulito:
                    paragrafi.append(pulito)
        if not paragrafi:
            breve = pulisci_residui(str(voce.get("testo") or ""))
            if breve:
                paragrafi = [breve]
        nuova = copy.deepcopy(voce)
        nuova["posizione"] = _posizione(voce, indice)
        nuova["paragrafi"] = paragrafi
        notizie.append(nuova)
    return notizie


def _prompt_revisione(
    notizie: list[dict[str, Any]], chiusura: str
) -> str:
    contenuto = {
        "chiusura": chiusura,
        "notizie": [
            {
                "posizione": voce["posizione"],
                "titolo": voce.get("titolo", ""),
                "paragrafi": list(voce.get("paragrafi") or []),
            }
            for voce in notizie
        ],
    }
    return (
        "Sei il revisore finale di un notiziario radiofonico italiano. "
        "Ricevi un copione già scritto e lo ripulisci senza riscriverlo.\n\n"
        "Correggi soltanto:\n"
        "- forma, punteggiatura e grammaticale;\n"
        "- frasi troncate o non finite;\n"
        "- ripetizioni inutili;\n"
        "- numeri scritti male;\n"
        "- residui di fonte, pubblicità o boilerplate.\n\n"
        "Regole vincolanti:\n"
        "- NON aggiungere fatti, nomi, numeri, cause, conseguenze o citazioni.\n"
        "- NON cambiare i titoli, le fonti, le categorie o l'ordine delle notizie.\n"
        "- NON inventare nulla: se una frase è irrecuperabile, rimuovila.\n"
        "- Mantieni una voce radiofonica naturale e una lunghezza simile "
        "all'originale.\n"
        "- Ogni paragrafo deve essere una frase compiuta e terminare con "
        "'.', '!' oppure '?'.\n"
        "- Scrivi solo in italiano: nessuna parola o frase inglese.\n"
        "- Non usare placeholder come 'Non ci sono notizie disponibili per la "
        "categoria...', né 'proviene da', 'Leggi anche', 'Fonte:', '©' o "
        "riferimenti pubblicitari.\n"
        "- Restituisci una voce per ogni posizione, una sola volta, nello "
        "stesso ordine.\n"
        "- La chiusura deve essere non vuota e terminare con punteggiatura.\n"
        "- Rispondi SOLO con un oggetto JSON conforme allo schema, senza testo "
        "fuori dal JSON.\n\n"
        f"Schema:\n{json.dumps(_SCHEMA, ensure_ascii=False)}\n\n"
        f"Copione da rivedere:\n{json.dumps(contenuto, ensure_ascii=False, indent=2)}"
    )


def _paragrafo_validato(testo: Any) -> str:
    if not isinstance(testo, str):
        raise _RevisioneError("paragrafo non testuale")
    pulito = re.sub(r"\s+", " ", testo).strip()
    if not pulito:
        raise _RevisioneError("paragrafo vuoto")
    if _PLACEHOLDER_RE.search(pulito):
        raise _RevisioneError("placeholder nel testo")
    if _MARCATORE_RE.search(pulito):
        raise _RevisioneError("residuo di fonte o boilerplate")
    if re.sub(r"\s+", " ", rimuovi_pubblicita(pulito)).strip() != pulito:
        raise _RevisioneError("contenuto pubblicitario")
    if _frasi_con_inglese(pulito):
        raise _RevisioneError("frase in inglese")
    if pulito[-1] not in _TERMINALI:
        ultima = _ULTIMA_PAROLA_RE.search(pulito)
        if not ultima or ultima.group(1).casefold() in _STOPWORD_CODA:
            raise _RevisioneError("frase troncata o non chiusa")
        # Testo chiaramente completo: aggiungo solo il punto mancante.
        pulito += "."
    if len(_PAROLA_RE.findall(pulito)) < 2:
        raise _RevisioneError("paragrafo troppo breve")
    return pulito


def _valida_revisione(
    dati: dict[str, Any],
    notizie: list[dict[str, Any]],
    parole_originali: int,
) -> tuple[dict[int, list[str]], str]:
    """Valida la risposta del revisore; solleva ``_RevisioneError`` se invalida."""
    notizie_risposta = dati.get("notizie")
    if not isinstance(notizie_risposta, list) or not notizie_risposta:
        raise _RevisioneError("notizie mancanti nella risposta")

    attese = [voce["posizione"] for voce in notizie]
    mappa: dict[int, list[str]] = {}
    for voce in notizie_risposta:
        if not isinstance(voce, dict):
            raise _RevisioneError("notizia non è un oggetto")
        posizione = _posizione(voce, 0)
        if posizione in mappa:
            raise _RevisioneError(f"posizione duplicata ({posizione})")
        paragrafi = voce.get("paragrafi")
        if not isinstance(paragrafi, list) or not paragrafi:
            raise _RevisioneError(f"posizione {posizione}: paragrafi mancanti")
        mappa[posizione] = [_paragrafo_validato(p) for p in paragrafi]

    if sorted(mappa) != sorted(attese):
        raise _RevisioneError("posizioni mancanti o diverse dall'originale")

    chiusura_validata = _paragrafo_validato(dati.get("chiusura"))

    parole_nuove = sum(
        conta_parole(p) for paragrafi in mappa.values() for p in paragrafi
    ) + conta_parole(chiusura_validata)
    if parole_originali > 0:
        rapporto = parole_nuove / parole_originali
        if not RAPPORTO_MINIMO <= rapporto <= RAPPORTO_MASSIMO:
            raise _RevisioneError(
                f"lunghezza fuori intervallo ({parole_nuove} parole su "
                f"{parole_originali}, rapporto {rapporto:.2f})"
            )
    return mappa, chiusura_validata


def _esegui_revisione(
    notizie: list[dict[str, Any]],
    chiusura: str,
    parole_originali: int,
    impostazioni: dict[str, Any],
    logger: logging.Logger,
) -> tuple[dict[int, list[str]] | None, str | None, str | None, str]:
    """Prova il modello di revisione e poi la riserva.

    Restituisce ``(mappa, chiusura, modello, motivo)``. ``mappa`` è ``None``
    se nessun modello ha prodotto una revisione valida.
    """
    modello, temperatura, massimo = _config_revisione(impostazioni)
    riserva = ""
    if isinstance(impostazioni, dict):
        riserva = str(impostazioni.get("llm_modello_riserva", "") or "").strip()
    modelli = [modello]
    if riserva and riserva != modello:
        modelli.append(riserva)
    prompt = _prompt_revisione(notizie, chiusura)
    ultimo_motivo = "nessun modello disponibile"
    for nome in modelli:
        try:
            risposta = _chiama_gemini(
                prompt,
                _SYSTEM_REVISIONE,
                impostazioni,
                _chiave_api(),
                logger,
                modello=nome,
                temperatura=temperatura,
                max_output_tokens=massimo,
            )
            dati = _estrai_json(risposta)
            if not isinstance(dati, dict):
                raise _RevisioneError("la risposta non è un oggetto JSON")
            mappa, nuova_chiusura = _valida_revisione(
                dati, notizie, parole_originali
            )
            return mappa, nuova_chiusura, nome, ""
        except Exception as exc:  # la revisione non deve mai bloccare
            ultimo_motivo = _redigi(f"{type(exc).__name__}: {exc}")
            logger.warning(
                "Revisione copione: modello %s non riuscito (%s).",
                nome,
                ultimo_motivo,
            )
    return None, None, modelli[-1] if modelli else None, ultimo_motivo


def _aggiorna_contatori(copione: dict[str, Any], parole: int) -> None:
    try:
        target = int(copione.get("target_parole") or 0)
    except (TypeError, ValueError):
        target = 0
    if target:
        copione["divario_parole"] = max(0, target - parole)
    if "parole" in copione:
        copione["parole"] = parole


def _esito(
    applicata: bool,
    modello: str | None,
    motivo: str,
    parole_prima: int,
    parole_dopo: int,
) -> dict[str, Any]:
    return {
        "applicata": applicata,
        "modello": modello,
        "motivo": motivo,
        "parole_prima": parole_prima,
        "parole_dopo": parole_dopo,
    }


def _rifinisci(
    copione: dict[str, Any],
    impostazioni: dict[str, Any],
    logger: logging.Logger,
    usa_llm: bool,
) -> dict[str, Any]:
    if not isinstance(copione, dict):
        return copione

    lavoro = copy.deepcopy(copione)
    parole_prima = conta_parole(str(copione.get("testo") or ""))
    notizie = _notizie_pulite(lavoro)
    corpo, chiusura = _corpo_e_chiusura(lavoro)

    if not notizie:
        lavoro["revisione"] = _esito(
            False, None, "nessuna notizia da revisionare", parole_prima, parole_prima
        )
        return lavoro

    lavoro["notizie"] = notizie
    lavoro["testo"] = "\n\n".join(corpo + [chiusura])
    _aggiorna_contatori(lavoro, conta_parole(lavoro["testo"]))
    parole_pulite = conta_parole(lavoro["testo"])

    if not usa_llm:
        lavoro["revisione"] = _esito(
            False, None, "revisione LLM disattivata", parole_prima, parole_pulite
        )
        return lavoro
    if not _chiave_api():
        lavoro["revisione"] = _esito(
            False, None, "GEMINI_API_KEY non impostata", parole_prima, parole_pulite
        )
        return lavoro

    mappa, nuova_chiusura, modello, motivo = _esegui_revisione(
        notizie, chiusura, parole_pulite, impostazioni, logger
    )
    if mappa is None or nuova_chiusura is None:
        logger.warning(
            "Revisione copione non applicata: %s. Resta il copione pulito.",
            motivo or "nessuna risposta valida",
        )
        lavoro["revisione"] = _esito(
            False,
            modello,
            motivo or "nessuna risposta valida",
            parole_prima,
            parole_pulite,
        )
        return lavoro

    for indice, voce in enumerate(lavoro["notizie"], start=1):
        posizione = _posizione(voce, indice)
        if posizione in mappa:
            voce["paragrafi"] = list(mappa[posizione])

    blocchi = [
        paragrafo
        for voce in lavoro["notizie"]
        for paragrafo in (voce.get("paragrafi") or [])
    ]
    blocchi.append(nuova_chiusura)
    lavoro["testo"] = "\n\n".join(blocchi)
    parole_dopo = conta_parole(lavoro["testo"])
    _aggiorna_contatori(lavoro, parole_dopo)
    lavoro["revisione"] = _esito(
        True, modello, "revisione applicata", parole_prima, parole_dopo
    )
    logger.info(
        "Revisione copione applicata con %s: %d -> %d parole.",
        modello,
        parole_prima,
        parole_dopo,
    )
    return lavoro


def rifinisci_copione(
    copione: dict[str, Any],
    impostazioni: dict[str, Any],
    logger: logging.Logger | None = None,
    *,
    usa_llm: bool = True,
) -> dict[str, Any]:
    """Pulisce il copione e, se possibile, lo fa rivedere da un LLM.

    Applica prima ``pulisci_residui`` a paragrafi e chiusura. Se la revisione
    LLM restituisce un JSON valido sostituisce i paragrafi e ricostruisce
    ``testo``; altrimenti restituisce il copione pulito deterministicamente
    senza modifiche parziali. Non solleva eccezioni.
    """
    logger = logger or logging.getLogger("notiziario")
    try:
        return _rifinisci(copione, impostazioni, logger, usa_llm)
    except Exception as exc:  # pragma: no cover - difesa finale
        logger.warning(
            "Revisione copione non disponibile (%s).", type(exc).__name__
        )
        if isinstance(copione, dict) and "revisione" not in copione:
            parole = conta_parole(str(copione.get("testo") or ""))
            copione["revisione"] = _esito(
                False, None, f"errore interno ({type(exc).__name__})", parole, parole
            )
        return copione
