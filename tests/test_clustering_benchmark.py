from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from helpers import crea_articolo
from notiziario.clustering import clusterizza


def _codice(numero: int) -> str:
    lettere = []
    for _ in range(3):
        lettere.append(chr(97 + numero % 26))
        numero //= 26
    return "".join(lettere)


def _benchmark():
    base = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    articoli = []
    for feed in range(200):
        for posizione in range(10):
            indice = feed * 10 + posizione
            titolo = f"{_codice(indice)} {_codice(indice + 100000)}"
            articoli.append(
                crea_articolo(
                    titolo,
                    fonte=f"Fonte {feed}",
                    categoria="italia",
                    ore_fa=(feed + posizione) / 100,
                )
            )
    inizio = time.perf_counter()
    clusters = clusterizza(articoli, max_per_feed=30, max_totale=3000)
    durata = time.perf_counter() - inizio
    return clusters, durata


def test_benchmark_200_fonti_per_10_articoli():
    clusters, durata = _benchmark()
    print(f"benchmark cluster: {durata:.2f}s")
    assert durata < 30
    assert len(clusters) == 2000


def test_cap_per_feed_e_totale():
    articoli = [
        crea_articolo(f"Titolo {_codice(i)}", fonte="Stessa", ore_fa=i / 10)
        for i in range(40)
    ]
    assert len(clusterizza(articoli, max_per_feed=30, max_totale=100)) == 30
    articoli2 = [
        crea_articolo(f"Titolo {_codice(i)}", fonte=f"Fonte {i}", ore_fa=i / 10)
        for i in range(50)
    ]
    assert len(clusterizza(articoli2, max_per_feed=30, max_totale=25)) == 25
