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


MODELLO_REVISIONE_DEFAULT = "gemini-3.8-flash"
TEMPERATURA_REVISIONE_DEFAULT = 0.15
MAX_OUTPUT_TOKENS_REVISIONE_DEFAULT = 16384

# Rapporto ammesso tra parole revisionate e parole originali: evita sia la
# perdita di contenuti sia l'aggiunta di fatti. È solo diagnostica: la
# protezione vera è il controllo per singola notizia.
RAPPORTO_MINIMO = 0.60
RAPPORTO_MASSIMO = 1.15

# Una singola notizia non può scendere sotto metà delle parole originali
# (con minimo assoluto di una parola).
RAPPORTO_POSIZIONE_MINIMO = 0.50

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
    thinking_budget: int | None = None,
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
        thinking_budget=thinking_budget,
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


def _catena_revisione(
    impostazioni: dict[str, Any],
) -> tuple[list[str], float, int]:
    """Modello di revisione configurato, poi tutta la catena di riserva."""
    from .copione import modelli_llm

    modello, temperatura, massimo = _config_revisione(impostazioni)
    modelli = [modello]
    for nome in modelli_llm(impostazioni):
        if nome and nome not in modelli:
            modelli.append(nome)
    return modelli, temperatura, massimo


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


def _estratto_risposta(testo: Any, massimo: int = 160) -> str:
    """Estratto redatto e breve della risposta, mai il copione intero."""
    redatto = _redigi(str(testo or "")).strip()
    return redatto[:massimo]


def _valida_revisione(
    dati: dict[str, Any],
    notizie: list[dict[str, Any]],
) -> tuple[dict[int, list[str]], str | None, list[int]]:
    """Valida la risposta del revisore con controllo per singola notizia.

    Solleva ``_RevisioneError`` per gli errori globali: risposta non-lista,
    posizioni mancanti/duplicate o nessuna posizione valida. Le posizioni con
    paragrafi vuoti, inglese, placeholder, boilerplate o con meno del 50%
    delle parole originali vengono restituite in ``scartate``: il chiamante
    per quelle tiene il testo originale. La chiusura è ``None`` se non valida.
    """
    notizie_risposta = dati.get("notizie")
    if not isinstance(notizie_risposta, list) or not notizie_risposta:
        raise _RevisioneError("notizie mancanti nella risposta")

    attese = [voce["posizione"] for voce in notizie]
    parole_originali_posizione = {
        voce["posizione"]: sum(
            conta_parole(p) for p in (voce.get("paragrafi") or [])
        )
        for voce in notizie
    }
    viste: set[int] = set()
    mappa: dict[int, list[str]] = {}
    scartate: list[int] = []
    for voce in notizie_risposta:
        if not isinstance(voce, dict):
            raise _RevisioneError("notizia non è un oggetto")
        posizione = _posizione(voce, 0)
        if posizione in viste:
            raise _RevisioneError(f"posizione duplicata ({posizione})")
        viste.add(posizione)
        try:
            paragrafi = voce.get("paragrafi")
            if not isinstance(paragrafi, list) or not paragrafi:
                raise _RevisioneError("paragrafi mancanti")
            validati = [_paragrafo_validato(p) for p in paragrafi]
            originali = parole_originali_posizione.get(posizione, 0)
            minime = max(1.0, originali * RAPPORTO_POSIZIONE_MINIMO)
            revisionate = sum(conta_parole(p) for p in validati)
            if revisionate < minime:
                raise _RevisioneError(
                    f"testo ridotto ({revisionate} parole su {originali})"
                )
        except _RevisioneError:
            scartate.append(posizione)
            continue
        mappa[posizione] = validati

    if sorted(viste) != sorted(attese):
        raise _RevisioneError("posizioni mancanti o diverse dall'originale")
    if not mappa:
        raise _RevisioneError("nessuna posizione valida")

    try:
        chiusura_validata: str | None = _paragrafo_validato(
            dati.get("chiusura")
        )
    except _RevisioneError:
        chiusura_validata = None

    return mappa, chiusura_validata, sorted(scartate)


_ISTRUZIONE_JSON = (
    "\n\nRispondi SOLO con l'oggetto JSON, senza testo prima o dopo."
)


def _esegui_revisione(
    notizie: list[dict[str, Any]],
    chiusura: str,
    impostazioni: dict[str, Any],
    logger: logging.Logger,
) -> tuple[
    dict[int, list[str]] | None,
    str | None,
    list[int],
    str | None,
    str,
]:
    """Prova il modello di revisione e poi tutta la catena di riserva.

    Restituisce ``(mappa, chiusura, scartate, modello, motivo)``. ``mappa`` è
    ``None`` se nessun modello ha prodotto una revisione valida. Ogni modello
    ha fino a due tentativi quando la risposta non contiene JSON valido.
    """
    modelli, temperatura, massimo = _catena_revisione(impostazioni)
    prompt = _prompt_revisione(notizie, chiusura)
    ultimo_motivo = "nessun modello disponibile"
    for indice, nome in enumerate(modelli):
        for tentativo in range(2):
            prompt_uso = prompt if tentativo == 0 else prompt + _ISTRUZIONE_JSON
            try:
                risposta = _chiama_gemini(
                    prompt_uso,
                    _SYSTEM_REVISIONE,
                    impostazioni,
                    _chiave_api(),
                    logger,
                    modello=nome,
                    temperatura=temperatura,
                    max_output_tokens=massimo,
                    thinking_budget=0,
                )
            except Exception as exc:  # la revisione non deve mai bloccare
                ultimo_motivo = _redigi(f"{type(exc).__name__}: {exc}")
                logger.warning(
                    "Revisione copione: modello %s non riuscito (%s).",
                    nome,
                    ultimo_motivo,
                )
                if indice < len(modelli) - 1:
                    logger.warning(
                        "Revisione copione: provo il modello successivo %s.",
                        modelli[indice + 1],
                    )
                break
            try:
                dati = _estrai_json(risposta)
            except Exception as exc:
                ultimo_motivo = _redigi(f"{type(exc).__name__}: {exc}")
                estratto = _estratto_risposta(risposta)
                if tentativo == 0:
                    logger.warning(
                        "Revisione copione: modello %s non ha restituito "
                        "JSON (%s), riprovo. Estratto risposta: %s",
                        nome,
                        ultimo_motivo,
                        estratto,
                    )
                    continue
                logger.warning(
                    "Revisione copione: modello %s non ha restituito JSON "
                    "nemmeno al secondo tentativo (%s). Estratto risposta: %s",
                    nome,
                    ultimo_motivo,
                    estratto,
                )
                if indice < len(modelli) - 1:
                    logger.warning(
                        "Revisione copione: provo il modello successivo %s.",
                        modelli[indice + 1],
                    )
                break
            if not isinstance(dati, dict):
                ultimo_motivo = "la risposta non è un oggetto JSON"
                logger.warning(
                    "Revisione copione: modello %s non riuscito (%s).",
                    nome,
                    ultimo_motivo,
                )
                if indice < len(modelli) - 1:
                    logger.warning(
                        "Revisione copione: provo il modello successivo %s.",
                        modelli[indice + 1],
                    )
                break
            try:
                mappa, nuova_chiusura, scartate = _valida_revisione(
                    dati, notizie
                )
            except Exception as exc:
                ultimo_motivo = _redigi(f"{type(exc).__name__}: {exc}")
                logger.warning(
                    "Revisione copione: modello %s non riuscito (%s).",
                    nome,
                    ultimo_motivo,
                )
                if indice < len(modelli) - 1:
                    logger.warning(
                        "Revisione copione: provo il modello successivo %s.",
                        modelli[indice + 1],
                    )
                break
            if scartate:
                logger.warning(
                    "Revisione copione: modello %s, posizioni scartate %s "
                    "(restano le originali).",
                    nome,
                    scartate,
                )
            return mappa, nuova_chiusura, scartate, nome, ""
    return None, None, [], modelli[-1] if modelli else None, ultimo_motivo


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
    *,
    parziale: bool = False,
    posizioni_scartate: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "applicata": applicata,
        "modello": modello,
        "motivo": motivo,
        "parziale": parziale,
        "posizioni_scartate": list(posizioni_scartate or []),
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

    mappa, nuova_chiusura, scartate, modello, motivo = _esegui_revisione(
        notizie, chiusura, impostazioni, logger
    )
    if not mappa:
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

    # La chiusura non valida non blocca: si tiene quella originale pulita.
    chiusura_finale = (
        nuova_chiusura if nuova_chiusura is not None else chiusura
    )
    blocchi = [
        paragrafo
        for voce in lavoro["notizie"]
        for paragrafo in (voce.get("paragrafi") or [])
    ]
    blocchi.append(chiusura_finale)
    lavoro["testo"] = "\n\n".join(blocchi)
    parole_dopo = conta_parole(lavoro["testo"])
    _aggiorna_contatori(lavoro, parole_dopo)

    # Il totale è solo diagnostica: con una revisione parziale può essere
    # sotto il 60% pur avendo posizioni valide, e non va rifiutato.
    rapporto = parole_dopo / parole_pulite if parole_pulite else 1.0
    if not RAPPORTO_MINIMO <= rapporto <= RAPPORTO_MASSIMO:
        logger.warning(
            "Revisione copione: totale %d -> %d parole (rapporto %.2f) fuori "
            "intervallo, mantenuto perché le posizioni applicate sono valide.",
            parole_pulite,
            parole_dopo,
            rapporto,
        )

    parziale = bool(scartate) or nuova_chiusura is None
    if parziale:
        dettagli: list[str] = []
        if scartate:
            dettagli.append(f"posizioni scartate: {scartate}")
        if nuova_chiusura is None:
            dettagli.append("chiusura originale")
        motivo_esito = "revisione parziale applicata (" + "; ".join(dettagli) + ")"
    else:
        motivo_esito = "revisione applicata"
    lavoro["revisione"] = _esito(
        True,
        modello,
        motivo_esito,
        parole_prima,
        parole_dopo,
        parziale=parziale,
        posizioni_scartate=scartate,
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
    ``testo``. Le posizioni scartate dalla validazione per-notizia mantengono
    l'originale pulito (revisione parziale); senza posizioni valide resta il
    copione pulito deterministicamente. Non solleva eccezioni.
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
