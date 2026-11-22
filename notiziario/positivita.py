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


# Parole che rendono un titolo inadatto al blocco, anche se l'AI sbagliasse.
_NEGATIVI = re.compile(
    r"\b("
    r"mort[oaie]|uccis[oaie]|guerra|conflitto|attacco|attentato|tragedia|"
    r"catastrofe|alluvione|terremoto|incendio|violenza|stupro|arrestat[oaie]|"
    r"indagat[oaie]|condannat[oaie]|crisi|fallimento|fallita|disastro|"
    r"emergenza|allerta|vittime|ferit[oaie]|sfratt|licenziam|disoccupazione|"
    r"povertà|carestia|epidemia|pandemia|contagi|prognosi|abusi|corruzione|"
    r"scandalo|protesta|scontro|tensione|minaccia|pericolo|inquinamento|"
    r"siccità|carestia"
    r")\b",
    re.IGNORECASE,
)

_NON_POSITIVE = re.compile(
    r"manca\s+consapevolezza|masseria|in\s+puglia|ceo.{0,40}puglia|"
    r"acquisit|acquist|curiosità|sapevi\s+che|ecco\s+perché|gossip|ville|"
    r"vacanza",
    re.IGNORECASE,
)

_SYSTEM = (
    "Sei un selettore editoriale di buone notizie italiane. Scegli solo "
    "notizie con esito positivo o incoraggiante: scoperte, progressi concreti, "
    "soluzioni, comunità, diritti, ambiente che migliora. Escludi cronaca nera, "
    "tragedie, guerre, catastrofi, politica conflittuale e notizie costruite "
    "sul conteggio delle vittime. Escludi curiosità, costume, gossip, acquisti "
    "immobiliari, ville, vacanze e storie su CEO senza impatto positivo "
    "concreto e verificabile. Non inventare nulla. Rispondi solo con JSON."
)


@dataclass
class EsitoBuoneNotizie:
    notizie: list[Cluster]
    usato_ai: bool
    motivo: str
    candidati: int = 0
    scartate_negative: int = 0


def titolo_negativo(titolo: str) -> bool:
    return bool(_NEGATIVI.search(titolo or ""))

def non_positiva(cluster: Cluster) -> bool:
    testo = f"{cluster.titolo} {cluster.sommario}"
    return titolo_negativo(cluster.titolo) or bool(_NON_POSITIVE.search(testo))


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
    for cluster in clusters:
        if non_positiva(cluster):
            scartate += 1
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
        logger.info("Buone notizie: %s; %d scartate per titolo negativo.", motivo, scartate)
        return EsitoBuoneNotizie(
            notizie=dedicate[:3],
            usato_ai=False,
            motivo=motivo,
            candidati=len(dedicate),
            scartate_negative=scartate,
        )

    massimo = int(impostazioni.get("buone_notizie", {}).get("max_candidati", 30))
    pool = dedicate + generaliste[: max(0, massimo - len(dedicate))]
    if not pool:
        return EsitoBuoneNotizie(
            notizie=[],
            usato_ai=True,
            motivo="nessun candidato positivo",
            scartate_negative=scartate,
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
            if non_positiva(cluster):
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
        )
