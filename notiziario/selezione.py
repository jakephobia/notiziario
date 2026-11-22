"""Scelta delle notizie per copertina, secondarie e blocco Buone notizie."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .categorie import CATEGORIE_IDS, label_categoria
from .clustering import Cluster
from .testi import similarita_titoli


@dataclass
class NotiziaSelezionata:
    cluster: Cluster
    copertina: bool
    ordine: int
    parole_target: int
    blocco: str = "secondaria"
    titolo_tradotto: str = ""
    testo_tradotto: str = ""

    @property
    def titolo(self) -> str:
        return self.titolo_tradotto or self.cluster.titolo

    @property
    def categoria(self) -> str:
        if self.blocco == "buone-notizie":
            return "buone-notizie"
        return self.cluster.categoria

    @property
    def fonti(self) -> list[str]:
        return self.cluster.fonti


_LIVE_RE = re.compile(
    r"\b(?:live(?:\s*blog)?|in\s+diretta|diretta|as\s+it\s+happened|breaking|"
    r"ultime\s+notizie)\b",
    re.IGNORECASE,
)


def e_live_blog(cluster: Cluster) -> bool:
    """Riconosce live blog e dirette dal titolo o dagli URL del cluster."""
    testi = [cluster.titolo]
    for articolo in cluster.articoli:
        testi.extend([articolo.titolo, articolo.link])
    return any(_LIVE_RE.search(str(testo or "")) for testo in testi)


def _compatibile(candidato: Cluster, scelti: list[Cluster], soglia: float = 0.8) -> bool:
    """Evita due notizie quasi identiche nella stessa scaletta."""
    for scelto in scelti:
        if candidato.id == scelto.id:
            return False
        if similarita_titoli(candidato.titolo, scelto.titolo) >= soglia:
            return False
    return True


def _seleziona_copertine(
    clusters: list[Cluster],
    categorie_attive: list[str],
    quante: int,
    soglia: float,
) -> list[Cluster]:
    """Copertine solo da categorie attive, multi-fonte prima, poi freschezza."""
    multi = [
        c for c in clusters if c.multi_fonte and c.categoria in categorie_attive
    ]
    singoli = sorted(
        (
            c
            for c in clusters
            if not c.multi_fonte and c.categoria in categorie_attive
        ),
        key=lambda c: c.freschezza,
        reverse=True,
    )
    copertine: list[Cluster] = []
    for cluster in multi + singoli:
        if len(copertine) >= quante:
            break
        if _compatibile(cluster, copertine, soglia):
            copertine.append(cluster)
    return copertine


def seleziona(
    clusters: list[Cluster],
    preset: dict,
    categorie_attive: list[str],
    max_notizie: int | None = None,
    logger: logging.Logger | None = None,
    soglia_duplicati: float = 0.8,
    buone_notizie: list[Cluster] | None = None,
) -> list[NotiziaSelezionata]:
    """Sceglie la scaletta.

    - copertine solo dalle categorie attive;
    - secondarie bilanciate a rotazione tra le categorie attive;
    - blocco Buone notizie fisso in chiusura, dopo le secondarie;
    - se manca spazio si riducono le secondarie, non le copertine.
    """
    logger = logger or logging.getLogger("notiziario")
    if not clusters and not buone_notizie:
        return []

    esclusi_live = [c for c in clusters if e_live_blog(c)]
    if esclusi_live:
        logger.info("Live blog esclusi dalla selezione: %d.", len(esclusi_live))
    clusters = [c for c in clusters if not e_live_blog(c)]
    if buone_notizie:
        buone_notizie = [c for c in buone_notizie if not e_live_blog(c)]
    if not clusters and not buone_notizie:
        return []

    limite = int(max_notizie if max_notizie is not None else preset["max_notizie"])
    limite = max(1, limite)
    attive = [c for c in CATEGORIE_IDS if c in set(categorie_attive)]
    generali = [c for c in attive if c != "buone-notizie"]

    copertine_desiderate = min(int(preset["copertine"]), limite)
    copertine = _seleziona_copertine(
        clusters, generali, copertine_desiderate, soglia_duplicati
    )
    scelti: list[Cluster] = list(copertine)

    positive: list[Cluster] = []
    if "buone-notizie" in attive and buone_notizie:
        posti = max(0, limite - len(copertine))
        quante = min(int(preset.get("buone_notizie", 2)), posti)
        for cluster in buone_notizie:
            if len(positive) >= quante:
                break
            if _compatibile(cluster, scelti, soglia_duplicati):
                positive.append(cluster)
                scelti.append(cluster)

    ids_copertine = {c.id for c in copertine}
    ids_positive = {c.id for c in positive}
    per_categoria: dict[str, list[Cluster]] = {c: [] for c in generali}
    for cluster in clusters:
        if cluster.id in ids_copertine or cluster.id in ids_positive:
            continue
        if cluster.categoria in per_categoria:
            per_categoria[cluster.categoria].append(cluster)

    posti_secondarie = max(0, limite - len(copertine) - len(positive))
    posti_secondarie = min(posti_secondarie, int(preset["secondarie"]))
    secondarie: list[Cluster] = []
    while len(secondarie) < posti_secondarie:
        progresso = False
        for categoria in generali:
            if len(secondarie) >= posti_secondarie:
                break
            lista = per_categoria[categoria]
            while lista:
                candidato = lista.pop(0)
                if _compatibile(candidato, scelti, soglia_duplicati):
                    secondarie.append(candidato)
                    scelti.append(candidato)
                    progresso = True
                    break
        if not progresso:
            break

    selezionate: list[NotiziaSelezionata] = []
    for indice, cluster in enumerate(copertine, start=1):
        selezionate.append(
            NotiziaSelezionata(
                cluster=cluster,
                copertina=True,
                ordine=indice,
                parole_target=int(preset["parole_copertina"]),
                blocco="copertina",
            )
        )
    for cluster in secondarie:
        selezionate.append(
            NotiziaSelezionata(
                cluster=cluster,
                copertina=False,
                ordine=len(selezionate) + 1,
                parole_target=int(preset["parole_secondaria"]),
                blocco="secondaria",
            )
        )
    for cluster in positive:
        selezionate.append(
            NotiziaSelezionata(
                cluster=cluster,
                copertina=False,
                ordine=len(selezionate) + 1,
                parole_target=int(preset.get("parole_buona_notizia", 100)),
                blocco="buone-notizie",
            )
        )

    logger.info(
        "Selezione: %d copertine, %d secondarie, %d buone notizie; categorie attive: %s.",
        len(copertine),
        len(secondarie),
        len(positive),
        ", ".join(label_categoria(c) for c in attive) or "nessuna",
    )
    if len(copertine) < copertine_desiderate:
        logger.warning(
            "Copertine disponibili %d su %d richieste (categorie attive).",
            len(copertine),
            copertine_desiderate,
        )
    if "buone-notizie" in attive and not positive:
        logger.warning(
            "Buone notizie attive ma nessuna notizia positiva: blocco saltato."
        )
    return selezionate
