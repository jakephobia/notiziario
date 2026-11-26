"""Selezione delle Buone notizie: feed dedicati e filtro AI di positività."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

from .clustering import Cluster
from .copione import LlmError, _chiama_gemini, _estrai_json, _redigi
from .categorie import label_categoria
from .testi import e_promozionale


# Parole che rendono un titolo inadatto al blocco, anche se l'AI sbagliasse.
_NEGATIVI = re.compile(
    r"\b("
    r"mort[oaie]|uccis[oaie]|guerra|conflitto|attacco|attentato|tragedia|"
    r"catastrofe|alluvione|terremoto|incendio|violenza|stupro|arrestat[oaie]|"
    r"indagat[oaie]|condannat[oaie]|crisi|fallimento|fallita|disastro|"
    r"emergenza|allerta|vittime|ferit[oaie]|sfratt|licenziam|disoccupazione|"
    r"carestia|epidemia|pandemia|contagi|prognosi|abusi|corruzione|"
    r"scandalo|protesta|scontro|tensione|minaccia|pericolo|inquinamento"
    r")\b",
    re.IGNORECASE,
)

_NON_POSITIVE = re.compile(
    r"manca\s+consapevolezza|masseria|in\s+puglia|ceo.{0,40}puglia|"
    r"acquisit|acquist|curiosità|sapevi\s+che|ecco\s+perché|gossip|ville|"
    r"vacanza",
    re.IGNORECASE,
)

_IMPORTANZA = re.compile(
    r"\b(?:"
    r"scopert\w*|stud(?:io|i)\b|ricerc\w*|terapi\w*|cur[ae]\b|vaccin\w*|"
    r"farmac\w*|trapiant\w*|genetic\w*|malatti\w*|tumor\w*|alzheimer|"
    r"parkinson|hiv|malaria|tubercolosi|epatite|diabete|obesit\w*|"
    r"prevenzion\w*|diagnos\w*|screening|sopravvivenza|salva\w*|"
    r"povert\w*|istruzion\w*|alfabetizz\w*|scuol\w*|bambin\w*|donne|"
    r"diritt\w*|parit\w*|rinnovabil\w*|solar\w*|eolic\w*|energia|"
    r"emission\w*|clima\w*|carbon\w*|ricicl\w*|rifiut\w*|acqua|potabile|"
    r"siccit\w*|specie|biodivers\w*|conservazion\w*|forest\w*|alber\w*|"
    r"ocean\w*|estinzion\w*|reintrod\w*|rifug\w*|pace|accord\w*|"
    r"trattat\w*|legge|riform\w*|access\w*|inclus\w*|disabilit\w*|"
    r"protes\w*|nobel|oms|onu|banca mondiale|eurostat|istat|iea|"
    r"nature|science|lancet|nejm|riduc\w*|riduzion\w*|aument\w*|"
    r"cresc\w*|calo\b|miglior\w*"
    r")\b",
    re.IGNORECASE,
)

_SCALA = re.compile(
    r"(?:\b\d[\d.,]*\b|\bmilioni?\b|\bmiliardi?\b|\bpercent\w*\b|%|"
    r"\bpaesi\b|\bnazionale\b|\bglobale\b|\bmondiale\b|\beurope\w*\b|"
    r"\binternazionale\b|\bminimi storici\b|\bdimezzat\w*\b|\brecord\b)",
    re.IGNORECASE,
)

_LOCALE = re.compile(
    r"\b(?:quartiere|parco|ragazzi|studenti|volontari|raccolta fondi|"
    r"iniziativa|festa|concerto|mostra d'arte|mostra fotografica|"
    r"sport|squadra|partita|influencer|gossip|ville|vacanza|masseria|"
    r"startup|assum\w*|centro commerciale|gadget|offerta|sconto|"
    r"record di visualizzazioni|evento locale|evento di quartiere|"
    r"evento benefico)\b",
    re.IGNORECASE,
)

_ISTITUZIONI = re.compile(
    r"\b(?:oms|onu|unicef|unesco|ue|commissione europea|banca mondiale|"
    r"eurostat|istat|iea|ocse|fao|nobel|nature|science|lancet|nejm)\b",
    re.IGNORECASE,
)

_SYSTEM = (
    "Sei un selettore editoriale di buone notizie italiane. Scegli solo "
    "notizie di rilievo nazionale o globale: scoperte scientifiche/mediche, "
    "studi clinici, statistiche positive su povertà, salute o istruzione, "
    "progressi ambientali, conservazione, diritti. Escludi cronaca nera, "
    "tragedie, guerre, catastrofi, politica conflittuale e notizie costruite "
    "sul conteggio delle vittime. Escludi storie di quartiere, volontariato "
    "locale, iniziative di ragazzi, PR, prodotti, offerte, anniversari, "
    "autopromozione, gossip, sport, spettacolo, record di visualizzazioni, "
    "assunzioni e startup. Non inventare nulla. Rispondi solo con JSON."
)


@dataclass
class EsitoBuoneNotizie:
    notizie: list[Cluster]
    usato_ai: bool
    motivo: str
    candidati: int = 0
    scartate_negative: int = 0
    scartate_poco_rilevanti: int = 0


def titolo_negativo(titolo: str) -> bool:
    return bool(_NEGATIVI.search(titolo or ""))

def non_positiva(cluster: Cluster) -> bool:
    testo = f"{cluster.titolo} {cluster.sommario}"
    return titolo_negativo(cluster.titolo) or bool(_NON_POSITIVE.search(testo))


def buona_notizia_importante(cluster: Cluster) -> bool:
    """Vero solo per notizie positive di rilievo, non storie locali o PR."""
    testo = f"{cluster.titolo} {cluster.sommario}"
    if non_positiva(cluster):
        return False
    articolo = cluster.ordina_articoli()[0] if cluster.articoli else None
    if articolo is not None and e_promozionale(
        cluster.titolo,
        cluster.sommario,
        "",
        articolo.fonte,
        articolo.link,
    ):
        return False

    importanza = {
        trovato.group(0).casefold()
        for trovato in _IMPORTANZA.finditer(testo)
    }
    scala = bool(_SCALA.search(testo))
    locale = bool(_LOCALE.search(testo))
    istituzione = bool(_ISTITUZIONI.search(testo))

    if locale and not scala and not istituzione:
        return False
    if not importanza:
        return False
    if len(importanza) >= 2:
        return True
    return scala


def _prompt(candidati: list[Cluster]) -> str:
    voci = []
    for indice, cluster in enumerate(candidati):
        voci.append(
            {
                "indice": indice,
                "titolo": cluster.titolo,
                "categoria": label_categoria(cluster.categoria),
                "fonti": cluster.fonti,
                "sommario": cluster.sommario[:400],
            }
        )
    return (
        "Valuta le notizie qui sotto. Rispondi con un oggetto JSON "
        '{"positive": [indici]} che contiene SOLO gli indici delle notizie '
        "con esito positivo o incoraggiante. Se nessuna va bene, usa una lista "
        "vuota. Non aggiungere testo fuori dal JSON.\n\n"
        + json.dumps(voci, ensure_ascii=False, indent=2)
    )


def filtra_buone_notizie(
    clusters: list[Cluster],
    categorie_attive: list[str],
    impostazioni: dict,
    logger: logging.Logger | None = None,
    usa_ai: bool | None = None,
) -> EsitoBuoneNotizie:
    """Restituisce i cluster del blocco finale.

    Senza AI passano solo i feed dedicati ``buone-notizie`` (e solo titoli non
    negativi). Con AI si aggiungono candidati dai feed generalisti attivi.
    """
    logger = logger or logging.getLogger("notiziario")
    attive = set(categorie_attive)
    if "buone-notizie" not in attive:
        return EsitoBuoneNotizie(
            notizie=[],
            usato_ai=False,
            motivo="categoria non attiva",
        )
    dedicate: list[Cluster] = []
    generaliste: list[Cluster] = []
    scartate = 0
    poco_rilevanti = 0
    for cluster in clusters:
        if non_positiva(cluster):
            scartate += 1
            continue
        if not buona_notizia_importante(cluster):
            poco_rilevanti += 1
            continue
        if cluster.categoria == "buone-notizie":
            dedicate.append(cluster)
        elif cluster.categoria in attive and cluster.categoria != "buone-notizie":
            generaliste.append(cluster)

    generaliste.sort(key=lambda c: (-c.numero_fonti, -c.freschezza.timestamp()))
    chiave = os.environ.get("GEMINI_API_KEY", "").strip()
    if usa_ai is None:
        usa_ai = bool(chiave)
    if not usa_ai or not chiave:
        motivo = (
            "solo feed dedicati (AI non disponibile)"
            if dedicate
            else "nessuna notizia positiva nei feed dedicati"
        )
        logger.info(
            "Buone notizie: %s; %d negative, %d poco rilevanti.",
            motivo,
            scartate,
            poco_rilevanti,
        )
        return EsitoBuoneNotizie(
            notizie=dedicate[:3],
            usato_ai=False,
            motivo=motivo,
            candidati=len(dedicate),
            scartate_negative=scartate,
            scartate_poco_rilevanti=poco_rilevanti,
        )

    massimo = int(impostazioni.get("buone_notizie", {}).get("max_candidati", 30))
    pool = dedicate + generaliste[: max(0, massimo - len(dedicate))]
    if not pool:
        return EsitoBuoneNotizie(
            notizie=[],
            usato_ai=True,
            motivo="nessun candidato positivo",
            scartate_negative=scartate,
            scartate_poco_rilevanti=poco_rilevanti,
        )
    try:
        primario = str(impostazioni["llm"]["modello"])
        riserva = str(impostazioni.get("llm_modello_riserva", "")).strip()
        modelli = [primario]
        if riserva and riserva != primario:
            modelli.append(riserva)
        risposta = None
        ultimo_errore: Exception | None = None
        for modello in modelli:
            try:
                risposta = _chiama_gemini(
                    _prompt(pool),
                    _SYSTEM,
                    impostazioni,
                    chiave,
                    logger,
                    modello=modello,
                )
                break
            except Exception as exc:
                ultimo_errore = exc
                logger.warning(
                    "Filtro positività con %s non riuscito: %s",
                    modello,
                    _redigi(exc),
                )
        if risposta is None:
            raise ultimo_errore or LlmError("nessun modello disponibile")
        dati = _estrai_json(risposta)
        indici = dati.get("positive")
        if not isinstance(indici, list):
            raise LlmError("campo positive mancante o non è una lista")
        scelte: list[Cluster] = []
        for indice in indici:
            if not isinstance(indice, int) or not 0 <= indice < len(pool):
                continue
            cluster = pool[indice]
            if not buona_notizia_importante(cluster):
                continue
            if cluster.id not in {c.id for c in scelte}:
                scelte.append(cluster)
        motivo = f"Gemini ha scelto {len(scelte)} notizie su {len(pool)} candidate"
        logger.info("Buone notizie: %s.", motivo)
        return EsitoBuoneNotizie(
            notizie=scelte,
            usato_ai=True,
            motivo=motivo,
            candidati=len(pool),
            scartate_negative=scartate,
            scartate_poco_rilevanti=poco_rilevanti,
        )
    except Exception as exc:
        motivo = f"filtro AI non riuscito ({_redigi(exc)}); uso i feed dedicati"
        logger.warning("Buone notizie: %s", motivo)
        return EsitoBuoneNotizie(
            notizie=dedicate[:3],
            usato_ai=False,
            motivo=motivo,
            candidati=len(dedicate),
            scartate_negative=scartate,
            scartate_poco_rilevanti=poco_rilevanti,
        )
