"""Raggruppamento degli articoli che raccontano lo stesso evento."""

from __future__ import annotations

import hashlib
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .fetch import Article
from .testi import normalizza_titolo, similarita_normalizzate


@dataclass
class Cluster:
    articoli: list[Article] = field(default_factory=list)

    @property
    def fonti(self) -> list[str]:
        return sorted({a.fonte for a in self.articoli})

    @property
    def numero_fonti(self) -> int:
        return len(self.fonti)

    @property
    def multi_fonte(self) -> bool:
        return self.numero_fonti >= 2

    @property
    def freschezza(self) -> datetime:
        return max(a.pubblicato for a in self.articoli)

    @property
    def titolo(self) -> str:
        """Titolo dell'articolo più fresco; è la voce del cluster."""
        return max(self.articoli, key=lambda a: a.pubblicato).titolo

    @property
    def sommario(self) -> str:
        for articolo in sorted(self.articoli, key=lambda a: a.pubblicato, reverse=True):
            if articolo.sommario:
                return articolo.sommario
        return ""

    @property
    def categoria(self) -> str:
        conteggi = Counter(a.categoria for a in self.articoli)
        massimo = max(conteggi.values())
        candidate = {c for c, n in conteggi.items() if n == massimo}
        if len(candidate) == 1:
            return next(iter(candidate))
        for articolo in sorted(self.articoli, key=lambda a: a.pubblicato, reverse=True):
            if articolo.categoria in candidate:
                return articolo.categoria
        return next(iter(candidate))

    @property
    def id(self) -> str:
        base = "|".join(sorted(a.id for a in self.articoli))
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]

    @property
    def link_principale(self) -> str:
        return max(self.articoli, key=lambda a: a.pubblicato).link

    def ordina_articoli(self) -> list[Article]:
        return sorted(self.articoli, key=lambda a: a.pubblicato, reverse=True)


class _UnionFind:
    def __init__(self, dimensione: int) -> None:
        self._padre = list(range(dimensione))
        self._rango = [0] * dimensione

    def trova(self, nodo: int) -> int:
        while self._padre[nodo] != nodo:
            self._padre[nodo] = self._padre[self._padre[nodo]]
            nodo = self._padre[nodo]
        return nodo

    def unisci(self, primo: int, secondo: int) -> None:
        radice_a = self.trova(primo)
        radice_b = self.trova(secondo)
        if radice_a == radice_b:
            return
        if self._rango[radice_a] < self._rango[radice_b]:
            radice_a, radice_b = radice_b, radice_a
        self._padre[radice_b] = radice_a
        if self._rango[radice_a] == self._rango[radice_b]:
            self._rango[radice_a] += 1


def clusterizza(
    articoli: list[Article],
    soglia: float = 0.58,
    logger: logging.Logger | None = None,
    max_per_feed: int = 30,
    max_totale: int = 3000,
) -> list[Cluster]:
    """Raggruppa per similarità di titolo con union-find.

    Il numero di "fonti distinte" è sempre calcolato sull'insieme dei nomi
    delle testate, quindi più articoli della stessa fonte contano una volta.
    """
    logger = logger or logging.getLogger("notiziario")
    if not articoli:
        return []

    # Cap per feed e totale: la freschezza decide cosa resta.
    ordinati = sorted(articoli, key=lambda a: a.pubblicato, reverse=True)
    contatori: Counter[str] = Counter()
    limitati: list[Article] = []
    for articolo in ordinati:
        if max_per_feed > 0 and contatori[articolo.feed_url or articolo.fonte] >= max_per_feed:
            continue
        limitati.append(articolo)
        contatori[articolo.feed_url or articolo.fonte] += 1
        if len(limitati) >= max_totale:
            break
    if len(limitati) != len(articoli):
        logger.info(
            "Clustering: limito da %d a %d articoli (max %d per feed, %d totali).",
            len(articoli),
            len(limitati),
            max_per_feed,
            max_totale,
        )
    articoli = limitati

    normalizzati = [normalizza_titolo(a.titolo) for a in articoli]
    unione = _UnionFind(len(articoli))

    # Blocking: confrontiamo solo coppie con almeno 2 token significativi
    # condivisi. Evita l'O(n²) su centinaia di fonti mantenendo i risultati
    # sui titoli che raccontano lo stesso evento.
    frequenza: Counter[str] = Counter()
    for titolo in normalizzati:
        frequenza.update(set(titolo.split()))
    soglia_raro = max(50, int(len(normalizzati) * 0.05))
    indice_token: dict[str, list[int]] = defaultdict(list)
    for indice, titolo in enumerate(normalizzati):
        for token in set(titolo.split()):
            if len(token) >= 4 and frequenza[token] <= soglia_raro:
                indice_token[token].append(indice)
    coppie: Counter[tuple[int, int]] = Counter()
    for lista in indice_token.values():
        for posizione, primo in enumerate(lista):
            for secondo in lista[posizione + 1 :]:
                coppie[(primo, secondo)] += 1

    confronti = 0
    for (i, j), token_comuni in coppie.items():
        if token_comuni < 2:
            continue
        if articoli[i].categoria != articoli[j].categoria:
            continue
        confronti += 1
        if similarita_normalizzate(normalizzati[i], normalizzati[j]) >= soglia:
            unione.unisci(i, j)

    gruppi: dict[int, list[Article]] = {}
    for indice, articolo in enumerate(articoli):
        radice = unione.trova(indice)
        gruppi.setdefault(radice, []).append(articolo)

    clusters = []
    for gruppo in gruppi.values():
        gruppo.sort(key=lambda a: a.pubblicato, reverse=True)
        clusters.append(Cluster(articoli=gruppo))

    clusters.sort(key=lambda c: (-c.numero_fonti, -c.freschezza.timestamp(), c.titolo))
    multi = sum(1 for c in clusters if c.multi_fonte)
    logger.info(
        "Clustering: %d articoli, %d confronti, %d notizie, %d con più fonti "
        "(soglia %.2f).",
        len(articoli),
        confronti,
        len(clusters),
        multi,
        soglia,
    )
    return clusters
