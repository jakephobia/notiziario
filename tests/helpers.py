from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from notiziario.clustering import Cluster
from notiziario.fetch import Article


def crea_articolo(
    titolo: str,
    fonte: str = "ANSA",
    categoria: str = "italia",
    sommario: str | None = None,
    ore_fa: float = 1,
    link: str | None = None,
) -> Article:
    base = link or f"https://esempio.test/{hashlib.sha1((titolo + fonte).encode()).hexdigest()}"
    return Article(
        titolo=titolo,
        link=base,
        sommario=sommario if sommario is not None else f"Summary di {titolo}.",
        pubblicato=datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
        - timedelta(hours=ore_fa),
        fonte=fonte,
        categoria=categoria,
    )


def crea_cluster(articoli: list[Article]) -> Cluster:
    return Cluster(articoli=articoli)
