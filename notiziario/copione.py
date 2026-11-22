"""Generazione del copione italiano: Gemini con fallback deterministico."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any

import requests

from .categorie import CATEGORIE_IDS, label_categoria
from .selezione import NotiziaSelezionata
from .stile import semplifica_slop
from .testi import (
    conta_parole,
    data_in_italiano,
    elenco_naturale,
    estrai_frasi,
    normalizza_per_tts,
    pulisci_html,
    pulisci_testo,
    normalizza_titolo,
    pulisci_titolo,
    spezza_frasi_lunghe,
    tronca_a_frase,
)


class LlmError(Exception):
    """Errore della chiamata al modello: si passa al fallback."""


def _redigi(messaggio: Any) -> str:
    testo = str(messaggio or "")
    testo = re.sub(r"(key=)[^&\s]+", r"\1***", testo, flags=re.IGNORECASE)
    testo = re.sub(r"AIza[0-9A-Za-z_\-]{10,}", "***", testo)
    return testo[:300]


def prepara_materiale(selezioni: list[NotiziaSelezionata]) -> list[dict[str, Any]]:
    materiale = []
    for selezione in selezioni:
        articoli = []
        for articolo in selezione.cluster.ordina_articoli():
            articoli.append(
                {
                    "fonte": articolo.fonte,
                    "titolo": articolo.titolo,
                    "sommario": articolo.sommario,
                    "testo": articolo.contenuto or articolo.sommario,
                    "arricchito": bool(articolo.contenuto),
                    "contenuto_parziale": articolo.contenuto_parziale,
                    "pubblicato": articolo.pubblicato.isoformat(),
                    "link": articolo.link,
                }
            )
        materiale.append(
            {
                "posizione": selezione.ordine,
                "copertina": selezione.copertina,
                "blocco": selezione.blocco,
                "categoria": label_categoria(selezione.categoria),
                "fonti": selezione.fonti,
                "parole_target": selezione.parole_target,
                "articoli": articoli,
            }
        )
    return materiale


def _system_prompt() -> str:
    return (
        "Sei un autore di notiziari radiofonici italiani. Scrivi testi da leggere "
        "ad alta voce, chiari e naturali. Il testo inizia direttamente con la "
        "prima notizia: non scrivere saluti, incipit, 'Buongiorno', 'Ecco le "
        "notizie' o 'Apriamo con'. Il saluto verrà aggiunto dal programma. "
        "Usa soltanto i fatti presenti nel materiale fornito: non inventare "
        "nomi, numeri, cause, conseguenze o citazioni e non aggiungere opinioni. "
        "Se il materiale non basta, scrivi meno parole invece di riempire. Per "
        "le notizie di copertina cita le testate indicate. Le notizie del blocco "
        "'Buone notizie' vanno alla fine, dopo tutte le altre e prima "
        "dell'ultima frase. Non usare markdown, elenchi, parentesi, link, emoji "
        "o simboli grafici. Varia le transizioni, evita frasi fatte e scrivi "
        "frasi di lunghezza variabile, massimo 35 parole. Rispondi soltanto con "
        "JSON valido."
    )


def _prompt_utente(
    materiale: list[dict[str, Any]],
    data_riferimento: datetime,
    impostazioni: dict[str, Any],
) -> tuple[str, int]:
    budget = sum(int(m["parole_target"]) for m in materiale) + 60
    data = data_in_italiano(data_riferimento)
    schema = {
        "titolo_episodio": "string",
        "descrizione": "string",
        "testo": "string",
        "notizie": [
            {
                "titolo": "string",
                "categoria": "string",
                "fonti": ["string"],
                "testo": "string",
            }
        ],
    }
    istruzioni = f"""
Data dell'episodio: {data}.
Budget totale: circa {budget} parole. È un obiettivo massimo: se il materiale
non basta, scrivi meno parole e non inventare nulla. Il programma misurerà il
divario dal budget.
{costruisci_budget(materiale)}.

Struttura richiesta:
- Il testo inizia direttamente con la prima notizia di copertina, senza saluto,
  senza incipit e senza frase di apertura.
- Poi le notizie secondarie, raggruppate per categoria.
- Il blocco "Buone notizie" va in chiusura, dopo tutte le altre categorie e
  prima dell'ultima frase. Se non ci sono voci positive, non inventarle.
- Chiusura breve.
- Il campo "testo" contiene il copione senza saluto, con i paragrafi separati
  da una riga vuota. Il saluto/incipit viene aggiunto dal programma.
- Il campo "notizie" contiene una voce per ogni notizia, nello stesso ordine
  del copione.
- Ogni voce di "notizie" ha titolo, categoria, fonti e un testo breve (1-2 frasi)
  della sola notizia, non l'intero paragrafo già presente in "testo".

Regole di scrittura:
- Usa solo i fatti del materiale. Se un dettaglio non c'è, non aggiungerlo.
- Non esprimere opinioni, previsioni o giudizi.
- Per le copertine scrivi "Secondo ANSA e Repubblica..." citando le testate.
- Varia le transizioni: non ripetere "Parliamo di", "Passiamo a", "Apriamo con",
  "riguarda un altro fatto" o formule equivalenti.
- Frasi di lunghezza variabile, ritmo naturale, massimo 35 parole.
- Niente parentesi, elenchi, markdown, link, emoji.
- Numeri e date in forma leggibile ad alta voce, per esempio "il 22 novembre",
  "il 3 per cento", "1400 euro".
- Non usare: in un mondo in cui, non solo, ma anche, è importante sottolineare,
  in conclusione, ecco cosa, nel panorama, un mix di, questo evidenzia,
  in questo contesto, al giorno d'oggi, senza dubbio, in sostanza.

Rispondi SOLO con un oggetto JSON conforme a questo schema:
{json.dumps(schema, ensure_ascii=False)}

Materiale:
{json.dumps(materiale, ensure_ascii=False, indent=2)}
""".strip()
    return istruzioni, budget


def costruisci_budget(materiale: list[dict[str, Any]]) -> str:
    righe = []
    for voce in materiale:
        blocco = voce.get("blocco", "")
        if blocco == "copertina" or voce.get("copertina"):
            tipo = "copertina"
        elif blocco == "buone-notizie":
            tipo = "buone notizie, in chiusura"
        else:
            tipo = "secondaria"
        righe.append(
            f"- posizione {voce.get('posizione')}: {tipo}, "
            f"circa {voce.get('parole_target')} parole, "
            f"categoria {voce.get('categoria')}"
        )
    return "\n".join(righe)


def _ripara_json(testo: str) -> str:
    """Ripara newline non escapate e virgole finali nei JSON del modello."""
    risultato: list[str] = []
    in_stringa = False
    escape = False
    for carattere in testo:
        if in_stringa:
            if escape:
                risultato.append(carattere)
                escape = False
            elif carattere == "\\":
                risultato.append(carattere)
                escape = True
            elif carattere == '"':
                risultato.append(carattere)
                in_stringa = False
            elif carattere == "\n":
                risultato.append("\\n")
            elif carattere == "\r":
                risultato.append("\\r")
            elif carattere == "\t":
                risultato.append("\\t")
            else:
                risultato.append(carattere)
        else:
            if carattere == '"':
                in_stringa = True
            risultato.append(carattere)
    riparato = "".join(risultato)
    riparato = re.sub(r",(\s*[}\]])", r"\1", riparato)
    return riparato


def _estrai_json(testo: str) -> dict[str, Any]:
    pulito = (testo or "").strip()
    pulito = re.sub(r"^```(?:json)?\s*", "", pulito, flags=re.IGNORECASE)
    pulito = re.sub(r"\s*```$", "", pulito)
    inizio = pulito.find("{")
    fine = pulito.rfind("}")
    if inizio < 0 or fine <= inizio:
        raise LlmError("la risposta non contiene un oggetto JSON")
    frammento = pulito[inizio : fine + 1]
    try:
        dati = json.loads(frammento)
    except json.JSONDecodeError as exc:
        try:
            dati = json.loads(_ripara_json(frammento))
        except json.JSONDecodeError as exc2:
            raise LlmError(f"JSON non valido: {exc2.msg}") from exc2
    if not isinstance(dati, dict):
        raise LlmError("la risposta JSON non è un oggetto")
    return dati


def _chiama_gemini(
    prompt: str,
    system: str,
    impostazioni: dict[str, Any],
    api_key: str,
    logger: logging.Logger,
    modello: str | None = None,
) -> str:
    configurazione = impostazioni["llm"]
    modello = modello or configurazione["modello"]
    endpoint = configurazione["endpoint"].format(modello=modello)
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(configurazione.get("temperatura", 0.6)),
            "responseMimeType": "application/json",
            "maxOutputTokens": int(configurazione.get("max_output_tokens", 8192)),
        },
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
        "User-Agent": "Notiziario/0.3",
    }
    timeout = int(configurazione.get("timeout", 60))
    for tentativo in range(2):
        try:
            risposta = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            if tentativo == 0:
                logger.warning("Gemini: errore di rete, riprovo una volta.")
                time.sleep(2)
                continue
            raise LlmError(f"errore di rete ({type(exc).__name__})") from exc

        if risposta.status_code in (429, 500, 502, 503, 504) and tentativo == 0:
            logger.warning(
                "Gemini: HTTP %s, riprovo tra due secondi.", risposta.status_code
            )
            time.sleep(2)
            continue
        if risposta.status_code >= 400:
            dettaglio = ""
            try:
                corpo = risposta.json()
                dettaglio = str(corpo.get("error", {}).get("message", ""))
            except ValueError:
                pass
            messaggio = f"HTTP {risposta.status_code}"
            if dettaglio:
                messaggio += f": {_redigi(dettaglio)}"
            raise LlmError(messaggio)

        try:
            dati = risposta.json()
        except ValueError as exc:
            raise LlmError("risposta Gemini non JSON") from exc
        candidate = (dati.get("candidates") or [None])[0]
        if not candidate:
            blocco = dati.get("promptFeedback", {}).get("blockReason")
            raise LlmError(f"nessun candidato nella risposta (blockReason={blocco})")
        parti = candidate.get("content", {}).get("parts", [])
        testo = "".join(
            str(parte.get("text", ""))
            for parte in parti
            if isinstance(parte, dict) and not parte.get("thought")
        ).strip()
        if not testo:
            motivo = candidate.get("finishReason", "sconosciuto")
            raise LlmError(f"risposta Gemini vuota (finishReason={motivo})")
        return testo
    raise LlmError("chiamata Gemini non riuscita")


def _valida_risposta_llm(dati: dict[str, Any], budget: int) -> None:
    for chiave in ("titolo_episodio", "descrizione", "testo", "notizie"):
        if chiave not in dati:
            raise LlmError(f"campo mancante nella risposta: {chiave}")
    if not str(dati["titolo_episodio"]).strip():
        raise LlmError("titolo_episodio vuoto")
    if not str(dati["descrizione"]).strip():
        raise LlmError("descrizione vuota")
    testo = str(dati["testo"]).strip()
    parole = conta_parole(testo)
    # Il budget è un massimo editoriale, non una soglia da riempire con fatti
    # inventati. Rifiutiamo solo un testo vuoto o palesemente abnorme.
    minimo = 60
    massimo = max(1200, int(budget * 2.5))
    if parole < minimo:
        raise LlmError(f"copione troppo corto ({parole} parole, minimo {minimo})")
    if parole > massimo:
        raise LlmError(f"copione troppo lungo ({parole} parole, massimo {massimo})")
    notizie = dati["notizie"]
    if not isinstance(notizie, list) or not notizie:
        raise LlmError("notizie mancanti o vuote")
    for indice, voce in enumerate(notizie, start=1):
        if not isinstance(voce, dict):
            raise LlmError(f"notizia {indice} non è un oggetto")
        for chiave in ("titolo", "categoria", "fonti", "testo"):
            if chiave not in voce:
                raise LlmError(f"notizia {indice}: campo mancante {chiave}")
        if not isinstance(voce["fonti"], list):
            raise LlmError(f"notizia {indice}: fonti deve essere una lista")
        if not str(voce["testo"]).strip():
            raise LlmError(f"notizia {indice}: testo vuoto")


def _normalizza_blocco(testo: str) -> str:
    """Pulisce un paragrafo e lo rende leggibile dal TTS."""
    testo = pulisci_html(testo)
    testo = re.sub(r"[*_#`~]+", " ", testo)
    testo = re.sub(r"^\s*[-–—•]\s+", "", testo, flags=re.MULTILINE)
    testo = re.sub(r"\s+", " ", testo).strip()
    if not testo:
        return ""
    testo = normalizza_per_tts(testo)
    testo = spezza_frasi_lunghe(testo, 35)
    return testo.strip()


def _pulisci_paragrafi(testo: str) -> str:
    paragrafi = [
        _normalizza_blocco(paragrafo)
        for paragrafo in re.split(r"\n\s*\n", testo or "")
        if paragrafo.strip()
    ]
    return "\n\n".join(p for p in paragrafi if p)


_APERTURA_LLM = re.compile(
    r"^(?:buongiorno|buonasera|ciao|ecco|benvenuti|benvenute|"
    r"oggi parliamo|iniziamo|apriamo)[^.!?]*[.!?]\s*",
    re.IGNORECASE,
)


def _rimuovi_apertura(testo: str) -> str:
    """Toglie un eventuale saluto che il modello aggiunge nonostante il prompt."""
    testo = (testo or "").strip()
    paragrafi = [
        p.strip() for p in re.split(r"\n\s*\n", testo) if p.strip()
    ]
    if len(paragrafi) >= 2 and conta_parole(paragrafi[0]) <= 45:
        if _APERTURA_LLM.match(paragrafi[0]) or re.match(
            r"^(?:buongiorno|buonasera|ciao)\b", paragrafi[0], re.IGNORECASE
        ):
            paragrafi = paragrafi[1:]
            return "\n\n".join(paragrafi)
    ripulito = _APERTURA_LLM.sub("", testo, count=1)
    if conta_parole(ripulito) >= 40:
        return ripulito.strip()
    return testo


def _materiale_caratteri(selezioni: list[NotiziaSelezionata]) -> int:
    totale = 0
    for selezione in selezioni:
        for articolo in selezione.cluster.ordina_articoli()[:3]:
            totale += len(articolo.contenuto or articolo.sommario or "")
    return totale


def _lunghezza_ai_adeguata(
    copione: dict[str, Any],
    selezioni: list[NotiziaSelezionata],
    target: int,
) -> bool:
    """Con materiale abbondante, un copione AI troppo corto non è accettabile."""
    materiale = _materiale_caratteri(selezioni)
    if materiale < max(2000, target * 4):
        return True
    return conta_parole(copione["testo"]) >= max(150, int(target * 0.5))


_CHIUSURA_RE = re.compile(
    r"^(queste|per oggi|per il momento|è tutto|e tutto|grazie|a domani|"
    r"buona giornata|il prossimo appuntamento)",
    re.IGNORECASE,
)
_CHIUSURA_DEFAULT = "Per oggi è tutto. A domani."


def _separa_chiusura(paragrafi: list[str]) -> tuple[list[str], str]:
    """Estrae l'ultimo paragrafo di chiusura, anche se non è in fondo."""
    for indice in range(len(paragrafi) - 1, -1, -1):
        paragrafo = paragrafi[indice]
        if len(paragrafo.split()) <= 45 and _CHIUSURA_RE.match(paragrafo):
            return paragrafi[:indice] + paragrafi[indice + 1 :], paragrafo
    return paragrafi, ""


def _garantisci_chiusura_finale(testo: str) -> str:
    paragrafi = [p.strip() for p in re.split(r"\n\s*\n", testo) if p.strip()]
    paragrafi, chiusura = _separa_chiusura(paragrafi)
    if not chiusura:
        chiusura = _CHIUSURA_DEFAULT
    return "\n\n".join(paragrafi + [chiusura])


def _riordina_buone_notizie(
    testo: str, selezioni: list[NotiziaSelezionata]
) -> tuple[str, bool]:
    """Sposta le Buone notizie prima dell'outro e l'outro in fondo."""
    titoli = [s.titolo for s in selezioni if s.blocco == "buone-notizie"]
    paragrafi = [p.strip() for p in re.split(r"\n\s*\n", testo) if p.strip()]
    if len(paragrafi) < 2:
        return testo, False
    paragrafi, chiusura = _separa_chiusura(paragrafi)
    if not titoli:
        return "\n\n".join(paragrafi + ([chiusura] if chiusura else [])), False

    def pertinente(paragrafo: str) -> bool:
        token_paragrafo = set(normalizza_titolo(paragrafo).split())
        for titolo in titoli:
            token_titolo = {
                t for t in normalizza_titolo(titolo).split() if len(t) >= 4
            }
            if len(token_titolo) >= 2 and len(token_titolo & token_paragrafo) >= 2:
                return True
        return False

    positive = [p for p in paragrafi if pertinente(p)]
    altre = [p for p in paragrafi if p not in positive]
    risultato = altre + positive + ([chiusura] if chiusura else [])
    return "\n\n".join(risultato), bool(positive)


def _finalizza_llm(
    dati: dict[str, Any],
    selezioni: list[NotiziaSelezionata],
    data_riferimento: datetime,
    target_parole: int = 0,
    modello_usato: str | None = None,
    motivo_modello: str | None = None,
) -> dict[str, Any]:
    titolo = pulisci_titolo(str(dati["titolo_episodio"]))
    if not titolo:
        titolo = f"Notiziario di {data_in_italiano(data_riferimento)}"
    descrizione = pulisci_testo(str(dati["descrizione"]))
    descrizione = tronca_a_frase(descrizione, 300)
    testo = _pulisci_paragrafi(_rimuovi_apertura(str(dati["testo"])))
    testo = semplifica_slop(testo)
    testo = _pulisci_paragrafi(testo)
    if not testo:
        raise LlmError("copione vuoto dopo la pulizia")

    notizie = []
    for voce in dati["notizie"]:
        notizie.append(
            {
                "titolo": pulisci_titolo(str(voce["titolo"])),
                "categoria": str(voce["categoria"]).strip()
                or label_categoria(selezioni[0].categoria),
                "fonti": [str(f).strip() for f in voce["fonti"] if str(f).strip()],
                "testo": semplifica_slop(
                    _normalizza_blocco(str(voce["testo"]))
                ),
            }
        )
    testo, trovate = _riordina_buone_notizie(testo, selezioni)
    if not trovate:
        positive_texts = [
            v["testo"]
            for v in notizie
            if "buone" in str(v.get("categoria", "")).casefold()
            and v.get("testo")
            and str(v["testo"]).casefold() not in testo.casefold()
        ]
        if positive_texts:
            paragrafi = [p for p in re.split(r"\n\s*\n", testo) if p.strip()]
            if paragrafi and re.match(
                r"^(queste|per oggi|è tutto|e tutto|grazie|a domani|buona)",
                paragrafi[-1].casefold(),
            ):
                chiusura = paragrafi.pop()
                testo = "\n\n".join(paragrafi + positive_texts + [chiusura])
            else:
                testo = "\n\n".join(paragrafi + positive_texts)
    testo = _garantisci_chiusura_finale(testo)
    if not descrizione:
        descrizione = "Le notizie del giorno lette in italiano."
    parole = conta_parole(testo)
    return {
        "titolo_episodio": titolo,
        "descrizione": descrizione,
        "testo": testo,
        "notizie": notizie,
        "modalita": "llm",
        "motivo_fallback": None,
        "target_parole": target_parole,
        "divario_parole": max(0, target_parole - parole),
        "modello_usato": modello_usato,
        "motivo_modello": motivo_modello,
    }


def _come_frase(testo: str) -> str:
    testo = (testo or "").strip()
    if testo and testo[-1] in ",;:":
        return testo
    if testo and testo[-1] not in ".!?":
        testo += "."
    return testo


_PAROLE_MINUSCOLE_DOPO_VERBO = {
    "a",
    "ad",
    "adesso",
    "agli",
    "ai",
    "al",
    "alla",
    "alle",
    "allo",
    "anche",
    "ancora",
    "annuncia",
    "annunciano",
    "arriva",
    "arrivano",
    "all",
    "circa",
    "con",
    "cosa",
    "cresce",
    "crescono",
    "cronaca",
    "c",
    "d",
    "da",
    "dai",
    "dal",
    "dall",
    "dalla",
    "dalle",
    "dallo",
    "dei",
    "del",
    "dell",
    "della",
    "delle",
    "dello",
    "di",
    "dopo",
    "dove",
    "durante",
    "e",
    "è",
    "fra",
    "già",
    "gli",
    "ha",
    "hanno",
    "i",
    "ieri",
    "il",
    "in",
    "inoltre",
    "intanto",
    "l",
    "la",
    "le",
    "lo",
    "ma",
    "mentre",
    "nasce",
    "nascono",
    "negli",
    "nei",
    "nel",
    "nell",
    "nell",
    "nella",
    "nelle",
    "nello",
    "non",
    "oggi",
    "oltre",
    "ora",
    "parte",
    "partono",
    "per",
    "perché",
    "perde",
    "perdono",
    "poi",
    "prima",
    "prosegue",
    "proseguono",
    "quando",
    "quasi",
    "quest",
    "questa",
    "queste",
    "questi",
    "questo",
    "resta",
    "restano",
    "ricorda",
    "ricordano",
    "sale",
    "salgono",
    "scende",
    "scendono",
    "soccorso",
    "solo",
    "sono",
    "sostiene",
    "sostengono",
    "spiega",
    "spiegano",
    "su",
    "sua",
    "sue",
    "sugli",
    "sui",
    "sul",
    "sull",
    "sull",
    "sulla",
    "sulle",
    "sullo",
    "suo",
    "suoi",
    "torna",
    "tornano",
    "tra",
    "tuttavia",
    "un",
    "una",
    "uno",
    "vince",
    "vincono",
}


def _minuscola_dopo_secondo(testo: str) -> str:
    """Dopo "Secondo X," l'italiano vuole di norma l'iniziale minuscola.

    La applico solo a parole funzionali comuni, per non rovinare nomi propri
    o sigle (Meloni, ANSA, Ue, GTA restano invariati).
    """
    if not testo or not testo[0].isupper():
        return testo
    prima = re.match(r"[A-Za-zÀ-ÖØ-öø-ÿ']+", testo)
    if not prima:
        return testo
    parola = prima.group(0)
    base = parola.split("'", 1)[0].casefold()
    if base in _PAROLE_MINUSCOLE_DOPO_VERBO:
        return testo[0].lower() + testo[1:]
    return testo


def _frasi_cluster(cluster, visti: set[str] | None = None):
    """Frasi dei summary del cluster, con la fonte di provenienza."""
    visti = visti if visti is not None else set()
    titolo_norm = normalizza_titolo(cluster.titolo)
    risultati: list[tuple[str, str]] = []
    for articolo in cluster.ordina_articoli():
        testo_fonte = articolo.contenuto or articolo.sommario
        for frase in estrai_frasi(testo_fonte):
            frase = re.sub(r"\s+", " ", frase).strip().strip('"“”')
            if len(frase.split()) < 5:
                continue
            ultima_parola = re.sub(r"[^\wÀ-ÖØ-öø-ÿ']", "", frase.split()[-1]).casefold()
            if ultima_parola in {
                "degli",
                "delle",
                "dei",
                "del",
                "della",
                "per",
                "con",
                "nel",
                "nella",
                "a",
                "da",
                "e",
                "o",
                "ma",
            }:
                continue
            if normalizza_titolo(frase) == titolo_norm:
                continue
            chiave = re.sub(r"\W+", " ", frase.casefold()).strip()
            if not chiave or chiave in visti:
                continue
            visti.add(chiave)
            if frase[0].islower():
                frase = frase[0].upper() + frase[1:]
            risultati.append((_come_frase(frase), articolo.fonte))
    return risultati


def _aggiungi_frasi(
    parti: list[str],
    frasi: list[tuple[str, str]],
    target: int,
) -> None:
    """Aggiunge frasi fino al budget, citando le fonti aggiuntive."""
    usate = sum(conta_parole(p) for p in parti)
    for frase, fonte in frasi:
        if usate >= target:
            break
        parole = conta_parole(frase)
        if usate + parole > target + 30 and usate > target * 0.75:
            break
        # La fonte è già citata nell'attacco ("Secondo ANSA e Repubblica");
        # qui aggiungo solo il fatto, senza frasi di raccordo ripetute.
        parti.append(frase)
        usate += parole


_TRANSIZIONI_CATEGORIA: dict[str, tuple[str, ...]] = {
    "italia": ("In Italia,", "Sul fronte italiano,", "Dal Paese,", "Intanto, in Italia,"),
    "mondo": ("Dall'estero,", "Nel mondo,", "Sul fronte internazionale,", "Oltre confine,"),
    "economia": ("Sull'economia,", "Sul fronte economico,", "Intanto, sui conti pubblici,"),
    "tecnologia": ("Nel campo della tecnologia,", "Sul fronte digitale,", "Dalla tecnologia,"),
    "scienza-salute": ("Sul fronte della salute,", "Dalla ricerca,", "In ambito scientifico,"),
    "cultura": ("Nel mondo della cultura,", "Sul fronte culturale,", "Dalla cultura,"),
    "sport": ("Nello sport,", "Sul fronte sportivo,", "Dagli stadi,"),
    "ambiente": ("Sull'ambiente,", "Sul fronte ambientale,", "Dal clima,"),
}

_TEMA_COPERTINA = {
    "italia": "italiano",
    "mondo": "internazionale",
    "economia": "economico",
    "tecnologia": "tecnologico",
    "scienza-salute": "scientifico",
    "cultura": "culturale",
    "sport": "sportivo",
    "ambiente": "ambientale",
}

_TRANSIZIONI_BUONE = (
    "Chiudiamo con una buona notizia.",
    "Un'altra notizia positiva.",
    "Infine, una buona notizia.",
)


def _transizione_copertina(selezione: NotiziaSelezionata, indice: int) -> str:
    if indice == 0:
        return ""
    tema = _TEMA_COPERTINA.get(selezione.categoria, "delle notizie")
    pool = ("Intanto,", "Nel frattempo,", f"Sul fronte {tema},")
    return pool[(indice - 1) % len(pool)]


def _transizione_secondaria(selezione: NotiziaSelezionata, indice_categoria: int) -> str:
    pool = _TRANSIZIONI_CATEGORIA.get(
        selezione.categoria, ("Intanto,", "Nel frattempo,", "Da segnalare,")
    )
    return pool[indice_categoria % len(pool)]


def _attribuzione(fonti: list[str], indice: int) -> str:
    elenco = elenco_naturale(fonti)
    plurale = len(fonti) > 1
    pool = (
        f"Secondo {elenco},",
        f"Come {'riportano' if plurale else 'riporta'} {elenco},",
        f"Dalla ricostruzione di {elenco},",
        f"Lo {'riportano' if plurale else 'riporta'} {elenco},",
        f"Ne {'parlano' if plurale else 'parla'} {elenco},",
    )
    return pool[indice % len(pool)]


def _paragrafo_notizia(
    selezione: NotiziaSelezionata,
    transizione: str,
) -> str:
    fonti = elenco_naturale(selezione.fonti)
    parti = []
    if transizione:
        parti.append(_come_frase(transizione))
    titolo = _come_frase(selezione.titolo)
    if transizione:
        titolo = _minuscola_dopo_secondo(titolo)
    parti.append(titolo)
    frasi = _frasi_cluster(selezione.cluster)
    if frasi:
        prima = _minuscola_dopo_secondo(frasi[0][0])
        parti.append(f"{_attribuzione(selezione.fonti, selezione.ordine)} {prima}")
        _aggiungi_frasi(parti, frasi[1:], selezione.parole_target)
    else:
        parti.append(f"La notizia è riportata da {fonti}.")
    return " ".join(p for p in parti if p).strip()


def _paragrafo_copertina(selezione: NotiziaSelezionata, indice: int) -> str:
    return _paragrafo_notizia(selezione, _transizione_copertina(selezione, indice))


def _paragrafo_secondaria(
    selezione: NotiziaSelezionata, indice_categoria: int
) -> str:
    return _paragrafo_notizia(
        selezione, _transizione_secondaria(selezione, indice_categoria)
    )


def _paragrafo_buona(selezione: NotiziaSelezionata, indice: int) -> str:
    transizione = _TRANSIZIONI_BUONE[indice % len(_TRANSIZIONI_BUONE)]
    return _paragrafo_notizia(selezione, transizione)


def _raggruppa_secondarie(
    selezioni: list[NotiziaSelezionata],
) -> list[NotiziaSelezionata]:
    return [
        s
        for s in selezioni
        if not s.copertina and s.blocco != "buone-notizie"
    ]


def _genera_fallback(
    selezioni: list[NotiziaSelezionata],
    data_riferimento: datetime,
    motivo: str,
) -> dict[str, Any]:
    copertine = [s for s in selezioni if s.copertina]
    secondarie = _raggruppa_secondarie(selezioni)
    positive = [s for s in selezioni if s.blocco == "buone-notizie"]

    chiusura = "Per oggi è tutto. A domani."
    blocchi: list[str] = []
    voci: list[dict[str, Any]] = []
    for indice, selezione in enumerate(copertine):
        testo = _paragrafo_copertina(selezione, indice)
        blocchi.append(testo)
        voci.append(
            {
                "titolo": selezione.titolo,
                "categoria": label_categoria(selezione.categoria),
                "fonti": selezione.fonti,
                "testo": testo,
            }
        )

    contatori: dict[str, int] = {}
    for selezione in secondarie:
        indice_categoria = contatori.get(selezione.categoria, 0)
        contatori[selezione.categoria] = indice_categoria + 1
        testo = _paragrafo_secondaria(selezione, indice_categoria)
        blocchi.append(testo)
        voci.append(
            {
                "titolo": selezione.titolo,
                "categoria": label_categoria(selezione.categoria),
                "fonti": selezione.fonti,
                "testo": testo,
            }
        )

    for indice, selezione in enumerate(positive):
        testo = _paragrafo_buona(selezione, indice)
        blocchi.append(testo)
        voci.append(
            {
                "titolo": selezione.titolo,
                "categoria": label_categoria("buone-notizie"),
                "fonti": selezione.fonti,
                "testo": testo,
            }
        )

    chiusura_norm = _normalizza_blocco(chiusura)
    coppie = [
        (voce, semplifica_slop(_normalizza_blocco(blocco)))
        for voce, blocco in zip(voci, blocchi)
    ]
    coppie = [(voce, normale) for voce, normale in coppie if normale]
    voci = [voce for voce, _ in coppie]
    blocchi_norm = [normale for _, normale in coppie]
    for voce, normale in coppie:
        voce["testo"] = normale
    corpo = "\n\n".join(blocchi_norm + [chiusura_norm])
    corpo = semplifica_slop(corpo)

    target = sum(s.parole_target for s in selezioni) + 15
    titoli = [v["titolo"] for v in voci[:3]]
    descrizione = (
        f"Le notizie del {data_in_italiano(data_riferimento, con_giorno=False)}: "
        + "; ".join(titoli)
        + "."
    )
    descrizione = pulisci_testo(descrizione)
    if len(descrizione) > 300:
        descrizione = descrizione[:297].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
    return {
        "titolo_episodio": f"Notiziario di {data_in_italiano(data_riferimento)}",
        "descrizione": descrizione,
        "testo": corpo,
        "notizie": voci,
        "modalita": "fallback",
        "motivo_fallback": motivo,
        "target_parole": target,
        "divario_parole": max(0, target - conta_parole(corpo)),
        "modello_usato": None,
        "motivo_modello": motivo,
    }


def genera_copione(
    selezioni: list[NotiziaSelezionata],
    impostazioni: dict[str, Any],
    data_riferimento: datetime,
    logger: logging.Logger | None = None,
    usa_llm: bool = True,
) -> dict[str, Any]:
    """Prova Gemini; se manca la chiave o qualcosa non va, usa il fallback."""
    logger = logger or logging.getLogger("notiziario")
    if not selezioni:
        raise ValueError("Nessuna notizia selezionata per il copione.")

    chiave = os.environ.get("GEMINI_API_KEY", "").strip()
    motivo = ""
    if not usa_llm:
        motivo = "LLM disattivato"
    elif not chiave:
        motivo = "GEMINI_API_KEY non impostata"
    else:
        materiale = prepara_materiale(selezioni)
        prompt, budget = _prompt_utente(materiale, data_riferimento, impostazioni)
        target = sum(s.parole_target for s in selezioni) + 15
        modello_primario = str(impostazioni["llm"]["modello"])
        modello_riserva = str(impostazioni.get("llm_modello_riserva", "")).strip()
        for tentativo in (1, 2):
            try:
                logger.info(
                    "Copione: chiamo Gemini (%s), tentativo %d.",
                    modello_primario,
                    tentativo,
                )
                risposta = _chiama_gemini(
                    prompt,
                    _system_prompt(),
                    impostazioni,
                    chiave,
                    logger,
                    modello=modello_primario,
                )
                dati = _estrai_json(risposta)
                _valida_risposta_llm(dati, budget)
                copione = _finalizza_llm(
                    dati,
                    selezioni,
                    data_riferimento,
                    target_parole=target,
                    modello_usato=modello_primario,
                    motivo_modello="primario",
                )
                if not _lunghezza_ai_adeguata(copione, selezioni, target):
                    raise LlmError(
                        "copione AI troppo corto rispetto al materiale arricchito"
                    )
                logger.info(
                    "Copione generato con Gemini: %d parole (target %d, divario %d).",
                    conta_parole(copione["testo"]),
                    copione["target_parole"],
                    copione["divario_parole"],
                )
                return copione
            except LlmError as exc:
                motivo = _redigi(exc)
                logger.warning(
                    "Gemini tentativo %d non riuscito: %s", tentativo, motivo
                )
                if tentativo == 1:
                    prompt = (
                        prompt
                        + "\n\nATTENZIONE: la risposta precedente non era un JSON "
                        "valido o non rispettava lo schema. Rispondi solo con JSON "
                        "valido e completo, senza testo fuori dal JSON."
                    )
            except Exception as exc:  # pragma: no cover - difesa finale
                motivo = _redigi(f"errore imprevisto ({type(exc).__name__})")
                logger.warning("Gemini tentativo %d non riuscito: %s", tentativo, motivo)
        if modello_riserva and modello_riserva != modello_primario:
            try:
                logger.warning(
                    "Modello primario non disponibile: provo la riserva %s una volta.",
                    modello_riserva,
                )
                risposta = _chiama_gemini(
                    prompt,
                    _system_prompt(),
                    impostazioni,
                    chiave,
                    logger,
                    modello=modello_riserva,
                )
                dati = _estrai_json(risposta)
                _valida_risposta_llm(dati, budget)
                copione = _finalizza_llm(
                    dati,
                    selezioni,
                    data_riferimento,
                    target_parole=target,
                    modello_usato=modello_riserva,
                    motivo_modello="riserva dopo errore primario",
                )
                if not _lunghezza_ai_adeguata(copione, selezioni, target):
                    raise LlmError(
                        "copione AI troppo corto rispetto al materiale arricchito"
                    )
                logger.info(
                    "Copione generato con modello di riserva %s: %d parole.",
                    modello_riserva,
                    conta_parole(copione["testo"]),
                )
                return copione
            except LlmError as exc:
                motivo_riserva = _redigi(exc)
                motivo = f"{motivo}; riserva: {motivo_riserva}"
                logger.warning("Modello di riserva non riuscito: %s", motivo_riserva)
            except Exception as exc:  # pragma: no cover
                motivo = f"{motivo}; riserva: {type(exc).__name__}"
        logger.warning("Passo al copione di fallback deterministico.")

    copione = _genera_fallback(selezioni, data_riferimento, motivo)
    logger.info(
        "Copione di fallback: %d parole (target %d, divario %d; %s).",
        conta_parole(copione["testo"]),
        copione["target_parole"],
        copione["divario_parole"],
        motivo,
    )
    return copione


def prova_llm(
    impostazioni: dict[str, Any], logger: logging.Logger | None = None
) -> tuple[bool, str]:
    """Testa la chiave Gemini con una richiesta minima. Non stampa la chiave."""
    logger = logger or logging.getLogger("notiziario")
    chiave = os.environ.get("GEMINI_API_KEY", "").strip()
    if not chiave:
        return (
            False,
            "GEMINI_API_KEY non impostata. In PowerShell, senza scriverla su file: "
            "$env:GEMINI_API_KEY = [Environment]::GetEnvironmentVariable("
            "'GEMINI_API_KEY','User'); python main.py --test-llm",
        )
    prompt = (
        'Rispondi con un oggetto JSON: {"ok": true, "messaggio": '
        '"collegamento funzionante"}'
    )
    try:
        risposta = _chiama_gemini(
            prompt,
            "Rispondi soltanto con JSON valido.",
            impostazioni,
            chiave,
            logger,
        )
        dati = _estrai_json(risposta)
        if dati.get("ok") is not True:
            return False, f"Risposta inattesa: {_redigi(risposta)}"
        return (
            True,
            f"Gemini risponde. Modello: {impostazioni['llm']['modello']}. "
            f"Risposta: {_redigi(risposta)}",
        )
    except Exception as exc:
        return False, f"Gemini non disponibile: {_redigi(exc)}"


def blocchi_per_tts(testo: str) -> list[str]:
    """Divide il copione in blocchi con pause naturali.

    Se il testo ha già paragrafi separati da riga vuota li usa; altrimenti
    raggruppa le frasi in blocchi da circa 70 parole.
    """
    paragrafi = [
        p.strip()
        for p in re.split(r"\n\s*\n", testo or "")
        if p.strip()
    ]
    if len(paragrafi) >= 2:
        return paragrafi
    frasi = estrai_frasi(testo)
    if not frasi:
        return []
    blocchi: list[str] = []
    corrente: list[str] = []
    parole = 0
    for frase in frasi:
        corrente.append(frase)
        parole += conta_parole(frase)
        if parole >= 70:
            blocchi.append(" ".join(corrente))
            corrente = []
            parole = 0
    if corrente:
        blocchi.append(" ".join(corrente))
    return blocchi
