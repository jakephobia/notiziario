"""Scelta delle notizie per copertina, secondarie e blocco Buone notizie."""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .categorie import CATEGORIE_IDS, label_categoria
from .classificazione import CATEGORIE_OVERLAY_SET
from .clustering import Cluster
from .testi import (
    estrai_nomi_propri,
    normalizza_titolo,
    sequenza_significativa,
    similarita_titoli,
    stesso_nome,
)


@dataclass
class NotiziaSelezionata:
    cluster: Cluster
    copertina: bool
    ordine: int
    parole_target: int
    blocco: str = "secondaria"
    titolo_tradotto: str = ""
    testo_tradotto: str = ""
    categoria_origine: str = ""
    categorie: set[str] = field(default_factory=set)
    notiziabilita: int = 3

    @property
    def titolo(self) -> str:
        return self.titolo_tradotto or self.cluster.titolo

    @property
    def categoria(self) -> str:
        if self.blocco == "buone-notizie":
            return "buone-notizie"
        # L'assorbimento dei duplicati può cambiare la categoria derivata del
        # cluster: resta quella con cui la notizia è stata selezionata.
        return self.categoria_origine or self.cluster.categoria

    @property
    def fonti(self) -> list[str]:
        return self.cluster.fonti


_LIVE_RE = re.compile(
    r"\b(?:live(?:\s*blog)?|in\s+diretta|diretta|as\s+it\s+happened|breaking|"
    r"ultime\s+notizie)\b",
    re.IGNORECASE,
)

_MAX_SOMMARIO_EVENTO = 1200

_PAROLE_GENERICHE = frozenset(
    {
        "governo",
        "italia",
        "italiano",
        "italiana",
        "presidente",
        "ministro",
        "premier",
        "parlamento",
        "legge",
        "partito",
        "elezioni",
        "paese",
        "citta",
        "giorno",
        "anno",
        "anni",
        "oggi",
        "ieri",
        "domani",
        "secondo",
        "dopo",
        "prima",
        "nuovo",
        "nuova",
        "caso",
        "notizia",
        "notizie",
    }
)


def e_live_blog(cluster: Cluster) -> bool:
    """Riconosce live blog e dirette dal titolo o dagli URL del cluster."""
    testi = [cluster.titolo]
    for articolo in cluster.articoli:
        testi.extend([articolo.titolo, articolo.link])
    return any(_LIVE_RE.search(str(testo or "")) for testo in testi)


def _testo_evento(cluster: Cluster) -> str:
    """Titolo del cluster, titoli e sommari degli articoli."""
    parti = [cluster.titolo]
    for articolo in cluster.articoli:
        parti.append(articolo.titolo)
        if articolo.sommario:
            parti.append(articolo.sommario[:_MAX_SOMMARIO_EVENTO])
    # Il separatore punteggiato evita nomi propri nati dalla giunzione.
    return " . ".join(parte for parte in parti if parte)


def _token_contenuto(cluster: Cluster) -> set[str]:
    """Token significativi del testo evento, senza parole generiche."""
    normalizzato = normalizza_titolo(_testo_evento(cluster))
    return {
        token for token in normalizzato.split() if token not in _PAROLE_GENERICHE
    }


def _nomi_forti(cluster: Cluster) -> set[tuple[str, ...]]:
    """Nomi propri ridotti ai soli token significativi.

    Tiene anche i nomi con particella ("De Gennaro"): serve almeno un token
    non generico, anche se la particella viene scartata.
    """
    nomi: set[tuple[str, ...]] = set()
    for nome in estrai_nomi_propri(_testo_evento(cluster)):
        forte = tuple(
            token
            for token in sequenza_significativa(nome)
            if token not in _PAROLE_GENERICHE and len(token) > 1
        )
        if len(nome) >= 2 and forte:
            nomi.add(forte)
    return nomi


def _nomi_in_comune(primo: Cluster, secondo: Cluster) -> set[str]:
    """Token significativi dei nomi che identificano lo stesso nome."""
    nomi_primo = _nomi_forti(primo)
    nomi_secondo = _nomi_forti(secondo)
    comuni: set[str] = set()
    for nome_primo in nomi_primo:
        for nome_secondo in nomi_secondo:
            if stesso_nome(nome_primo, nome_secondo):
                comuni.update(sequenza_significativa(nome_primo))
                comuni.update(sequenza_significativa(nome_secondo))
    return comuni


def _duplicato_di(
    candidato: Cluster, scelti: list[Cluster], soglia: float = 0.8
) -> Cluster | None:
    """Restituisce il cluster già scelto che racconta lo stesso evento."""
    for scelto in scelti:
        if candidato.id == scelto.id:
            return scelto
        similarita = similarita_titoli(candidato.titolo, scelto.titolo)
        if similarita >= soglia:
            return scelto
        nomi_comuni = _nomi_in_comune(candidato, scelto)
        if not nomi_comuni:
            continue
        contenuto_comune = _token_contenuto(candidato) & _token_contenuto(scelto)
        if len(contenuto_comune - nomi_comuni) >= 3 or similarita >= 0.5:
            return scelto
    return None


def _compatibile(candidato: Cluster, scelti: list[Cluster], soglia: float = 0.8) -> bool:
    """Evita due notizie quasi identiche o sullo stesso evento."""
    return _duplicato_di(candidato, scelti, soglia) is None


def _assorbi(destinazione: Cluster, sorgente: Cluster) -> int:
    """Aggiunge alla destinazione gli articoli della sorgente non già presenti."""
    if destinazione is sorgente:
        return 0
    visti = {articolo.id for articolo in destinazione.articoli}
    aggiunti = 0
    for articolo in sorgente.articoli:
        if articolo.id in visti:
            continue
        destinazione.articoli.append(articolo)
        visti.add(articolo.id)
        aggiunti += 1
    return aggiunti


def _assorbi_duplicati(
    scelto: Cluster,
    candidati: list[Cluster],
    scelti: list[Cluster],
    consumati: set[str],
    soglia: float,
) -> int:
    """Usa i duplicati del cluster scelto come fonti aggiuntive."""
    ids_scelti = {cluster.id for cluster in scelti}
    assorbiti = 0
    for candidato in candidati:
        if candidato is scelto or candidato.id in consumati:
            continue
        if candidato.id in ids_scelti:
            continue
        if _duplicato_di(candidato, [scelto], soglia) is None:
            continue
        if _assorbi(scelto, candidato):
            assorbiti += 1
        consumati.add(candidato.id)
    return assorbiti


def _cluster_ammesso(
    base: str,
    etichette: set[str],
    attive: set[str],
    basi_ammesse: set[str] | None = None,
) -> bool:
    """Base attiva e nessuna etichetta sovrapposta disattivata."""
    if base not in attive:
        return False
    if basi_ammesse is not None and base not in basi_ammesse:
        return False
    overlay = etichette & CATEGORIE_OVERLAY_SET
    return overlay <= attive


def _seleziona_copertine(
    clusters: list[Cluster],
    basi_ammesse: set[str],
    attive: set[str],
    quante: int,
    soglia: float,
    categorie: dict[int, str],
    etichette: dict[int, set[str]],
    notiziabilita: dict[int, int],
) -> list[Cluster]:
    """Copertine per notiziabilità, poi fonti, poi freschezza."""
    candidati = [
        cluster
        for cluster in clusters
        if _cluster_ammesso(
            categorie.get(id(cluster), cluster.categoria),
            etichette.get(id(cluster), set()),
            attive,
            basi_ammesse,
        )
    ]
    candidati.sort(
        key=lambda cluster: (
            -notiziabilita.get(id(cluster), cluster.notiziabilita),
            -cluster.numero_fonti,
            -cluster.freschezza.timestamp(),
        )
    )
    copertine: list[Cluster] = []
    for cluster in candidati:
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
    parole_per_minuto: int = 145,
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

    # Pool completo: serve per assorbire i duplicati anche se sono nell'altro
    # blocco (per esempio una buona notizia che ripete una notizia generale).
    tutti_candidati = list(clusters)
    visti_identita = {id(cluster) for cluster in tutti_candidati}
    for cluster in buone_notizie or []:
        if id(cluster) not in visti_identita:
            tutti_candidati.append(cluster)
            visti_identita.add(id(cluster))
    consumati: set[str] = set()
    assorbiti = 0
    # Categorie, etichette e notiziabilità vanno lette prima dell'assorbimento:
    # aggiungere articoli può cambiare la categoria derivata del cluster.
    categorie_origine: dict[int, str] = {}
    etichette_origine: dict[int, set[str]] = {}
    notiziabilita_origine: dict[int, int] = {}
    for cluster in tutti_candidati:
        categorie_origine[id(cluster)] = cluster.categoria
        etichette_origine[id(cluster)] = set(cluster.categorie)
        notiziabilita_origine[id(cluster)] = cluster.notiziabilita

    limite = int(max_notizie if max_notizie is not None else preset["max_notizie"])
    limite = max(1, limite)
    parole_copertina = int(preset["parole_copertina"])
    parole_secondaria = int(preset["parole_secondaria"])
    # Le buone notizie durano a metà tra una copertina e una secondaria.
    parole_buona = max(1, (parole_copertina + parole_secondaria) // 2)
    attive = [c for c in CATEGORIE_IDS if c in set(categorie_attive)]
    attive_set = set(attive)
    generali = [c for c in attive if c != "buone-notizie"]
    generali_set = set(generali)

    copertine_desiderate = min(int(preset["copertine"]), limite)
    copertine = _seleziona_copertine(
        clusters,
        generali_set,
        attive_set,
        copertine_desiderate,
        soglia_duplicati,
        categorie_origine,
        etichette_origine,
        notiziabilita_origine,
    )
    scelti: list[Cluster] = list(copertine)
    for cluster in copertine:
        assorbiti += _assorbi_duplicati(
            cluster, tutti_candidati, scelti, consumati, soglia_duplicati
        )

    positive: list[Cluster] = []
    if "buone-notizie" in attive_set and buone_notizie:
        posti = max(0, limite - len(copertine))
        quante = min(int(preset.get("buone_notizie", 2)), posti)
        for cluster in buone_notizie:
            if len(positive) >= quante:
                break
            if cluster.id in consumati:
                continue
            if not _cluster_ammesso(
                categorie_origine.get(id(cluster), cluster.categoria),
                etichette_origine.get(id(cluster), set()),
                attive_set,
            ):
                continue
            duplicato = _duplicato_di(cluster, scelti, soglia_duplicati)
            if duplicato is not None:
                if _assorbi(duplicato, cluster):
                    assorbiti += 1
                consumati.add(cluster.id)
                continue
            positive.append(cluster)
            scelti.append(cluster)
            assorbiti += _assorbi_duplicati(
                cluster, tutti_candidati, scelti, consumati, soglia_duplicati
            )

    ids_copertine = {c.id for c in copertine}
    ids_positive = {c.id for c in positive}
    per_categoria: dict[str, list[Cluster]] = {c: [] for c in generali}
    for cluster in clusters:
        if (
            cluster.id in consumati
            or cluster.id in ids_copertine
            or cluster.id in ids_positive
        ):
            continue
        if not _cluster_ammesso(
            categorie_origine.get(id(cluster), cluster.categoria),
            etichette_origine.get(id(cluster), set()),
            attive_set,
            generali_set,
        ):
            continue
        if notiziabilita_origine.get(id(cluster), cluster.notiziabilita) <= 1:
            continue
        base = categorie_origine.get(id(cluster), cluster.categoria)
        if base in per_categoria:
            per_categoria[base].append(cluster)
    # Per le secondarie meglio partire dalle notizie più rilevanti; il numero
    # di fonti e il materiale disponibile rompono la parità.
    for lista in per_categoria.values():
        lista.sort(
            key=lambda cluster: (
                -notiziabilita_origine.get(id(cluster), cluster.notiziabilita),
                -cluster.numero_fonti,
                -len(cluster.sommario),
            )
        )

    target_parole = int(preset.get("minuti", 0)) * max(1, parole_per_minuto)
    parole_fisse = (
        len(copertine) * parole_copertina
        + len(positive) * parole_buona
        + 60
    )
    restanti = max(0, target_parole - parole_fisse)
    calcolate = (
        math.ceil(restanti / max(1, parole_secondaria))
        if restanti
        else 0
    )
    # Buffer per coprire notizie estere non traducibili e varianza del modello:
    # meglio una notizia in più che una puntata troppo corta.
    minuti = int(preset.get("minuti", 0))
    buffer_secondarie = 8 if minuti >= 15 else 2
    posti = max(0, limite - len(copertine) - len(positive))
    posti_secondarie = min(posti, calcolate + buffer_secondarie)
    if posti_secondarie == 0 and posti > 0 and target_parole > parole_fisse:
        posti_secondarie = 1
    logger.info(
        "Target %d parole (%d minuti): %d copertine, %d secondarie "
        "(calcolate %d + buffer %d), %d buone notizie.",
        target_parole,
        minuti,
        len(copertine),
        posti_secondarie,
        calcolate,
        buffer_secondarie,
        len(positive),
    )
    secondarie: list[Cluster] = []
    while len(secondarie) < posti_secondarie:
        progresso = False
        for categoria in generali:
            if len(secondarie) >= posti_secondarie:
                break
            lista = per_categoria[categoria]
            while lista:
                candidato = lista.pop(0)
                if candidato.id in consumati:
                    continue
                duplicato = _duplicato_di(candidato, scelti, soglia_duplicati)
                if duplicato is not None:
                    if _assorbi(duplicato, candidato):
                        assorbiti += 1
                    consumati.add(candidato.id)
                    continue
                secondarie.append(candidato)
                scelti.append(candidato)
                assorbiti += _assorbi_duplicati(
                    candidato, tutti_candidati, scelti, consumati, soglia_duplicati
                )
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
                categoria_origine=categorie_origine.get(id(cluster), ""),
                categorie=set(etichette_origine.get(id(cluster), set())),
                notiziabilita=notiziabilita_origine.get(
                    id(cluster), cluster.notiziabilita
                ),
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
                categoria_origine=categorie_origine.get(id(cluster), ""),
                categorie=set(etichette_origine.get(id(cluster), set())),
                notiziabilita=notiziabilita_origine.get(
                    id(cluster), cluster.notiziabilita
                ),
            )
        )
    for cluster in positive:
        etichette = set(etichette_origine.get(id(cluster), set()))
        etichette.add("buone-notizie")
        selezionate.append(
            NotiziaSelezionata(
                cluster=cluster,
                copertina=False,
                ordine=len(selezionate) + 1,
                parole_target=parole_buona,
                blocco="buone-notizie",
                categoria_origine=categorie_origine.get(id(cluster), ""),
                categorie=etichette,
                notiziabilita=notiziabilita_origine.get(
                    id(cluster), cluster.notiziabilita
                ),
            )
        )

    logger.info(
        "Selezione: %d copertine, %d secondarie, %d buone notizie; categorie attive: %s.",
        len(copertine),
        len(secondarie),
        len(positive),
        ", ".join(label_categoria(c) for c in attive) or "nessuna",
    )
    conteggi_notiziabilita = Counter(s.notiziabilita for s in selezionate)
    logger.info(
        "Notiziabilità selezionate: %s.",
        ", ".join(
            f"{punteggio}: {conteggi_notiziabilita.get(punteggio, 0)}"
            for punteggio in range(5, 0, -1)
        ),
    )
    conteggi_categorie: Counter[str] = Counter()
    for selezione in selezionate:
        conteggi_categorie.update(selezione.categorie)
    logger.info(
        "Categorie selezionate: %s.",
        ", ".join(
            f"{label_categoria(categoria)}: {numero}"
            for categoria, numero in sorted(
                conteggi_categorie.items(), key=lambda voce: (-voce[1], voce[0])
            )
        )
        or "nessuna",
    )
    if assorbiti:
        logger.info(
            "Dedup eventi: %d notizie duplicate usate come fonti aggiuntive.",
            assorbiti,
        )
    if len(copertine) < copertine_desiderate:
        logger.warning(
            "Copertine disponibili %d su %d richieste (categorie attive).",
            len(copertine),
            copertine_desiderate,
        )
    if "buone-notizie" in attive and not positive:
        logger.warning(
            "Buone notizie attive ma nessuna notizia positiva: blocco saltato "
            "o assorbita in un'altra notizia."
        )
    return selezionate
