"""Download parallelo dei feed RSS e costruzione degli articoli."""

from __future__ import annotations

import calendar
import concurrent.futures
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests

from .categorie import normalizza_testo, trova_categoria
from .config import Fonte
from .sicurezza import (
    FetchHttpError,
    UrlRifiutato,
    fetch_con_limite,
    valida_url_pubblica,
)
from .tempo import ROMA
from .testi import (
    categoria_da_url as categoria_da_url_articolo,
    e_promozionale,
    pulisci_testo,
    pulisci_titolo,
    tronca_a_frase,
)


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
    "Cache-Control": "no-cache",
}

_ALIAS_TAG: dict[str, str] = {
    "calcio": "sport",
    "serie a": "sport",
    "motori": "sport",
    "formula 1": "sport",
    "f1": "sport",
    "motogp": "sport",
    "tennis": "sport",
    "basket": "sport",
    "volley": "sport",
    "ciclismo": "sport",
    "olimpiadi": "sport",
    "finanza": "economia",
    "mercati": "economia",
    "borsa": "economia",
    "lavoro": "economia",
    "imprese": "economia",
    "business": "economia",
    "tech": "tecnologia",
    "digitale": "tecnologia",
    "internet": "tecnologia",
    "intelligenza artificiale": "tecnologia",
    "spettacoli": "cultura",
    "cinema": "cultura",
    "musica": "cultura",
    "libri": "cultura",
    "arte": "cultura",
    "teatro": "cultura",
    "esteri": "mondo",
    "internazionale": "mondo",
    "geopolitica": "mondo",
    "politica": "italia",
    "cronaca": "italia",
    "salute": "scienza-salute",
    "scienza": "scienza-salute",
    "scienze": "scienza-salute",
    "medicina": "scienza-salute",
    "ricerca": "scienza-salute",
    "clima": "ambiente",
    "green": "ambiente",
    "ecologia": "ambiente",
    "sostenibilita": "ambiente",
    "buone notizie": "buone-notizie",
}

_SEGMENTI_CATEGORIA: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sport", ("sport", "calcio", "motori", "formula-1", "motogp", "tennis", "basket", "volley", "ciclismo")),
    ("economia", ("economia", "finanza", "mercati", "borsa", "business", "lavoro")),
    ("tecnologia", ("tecnologia", "tech", "digitale", "innovazione")),
    ("cultura", ("cultura", "spettacoli", "cinema", "musica", "libri", "arte", "teatro")),
    ("scienza-salute", ("scienza", "scienze", "salute", "medicina", "sanita", "ricerca")),
    ("ambiente", ("ambiente", "green", "clima", "ecologia", "sostenibilita")),
    ("mondo", ("esteri", "mondo", "internazionale")),
    ("italia", ("politica", "cronaca", "italia")),
)


def categoria_da_tag(entry) -> str | None:
    for tag in entry.get("tags") or []:
        valore = str(tag.get("term") or tag.get("label") or "").strip()
        if not valore:
            continue
        trovata = trova_categoria(valore)
        if trovata:
            return trovata
        alias = _ALIAS_TAG.get(normalizza_testo(valore))
        if alias:
            return alias
    return None


def categoria_da_url(link: str) -> str | None:
    path = urlsplit(link or "").path.casefold()
    segmenti = {segmento for segmento in path.split("/") if segmento}
    for categoria, marcatori in _SEGMENTI_CATEGORIA:
        if segmenti.intersection(marcatori):
            return categoria
    return None


def inferisci_categoria(entry, link: str, categoria_fonte: str) -> str:
    """Tag RSS, poi path URL, infine categoria della fonte. Mai il titolo."""
    return categoria_da_tag(entry) or categoria_da_url(link) or categoria_fonte


_PARAMETRI_TRACCIANTI = re.compile(
    r"^(utm_|fbclid$|gclid$|mc_cid$|mc_eid$|ref$|source$|rss$|output$|"
    r"campaign$|cmp$|intcmp$|refresh$)",
    re.IGNORECASE,
)


MAX_FEED_BYTES = 10 * 1024 * 1024

class FetchError(Exception):
    """Errore di un singolo feed: non deve fermare gli altri."""

class FeedSenzaNovita(FetchError):
    """Feed senza date, tutti gli item già in rubrica."""


@dataclass
class Article:
    titolo: str
    link: str
    sommario: str
    pubblicato: datetime
    fonte: str
    categoria: str
    feed_url: str = ""
    data_stimata: bool = False
    prima_vista: datetime | None = None
    contenuto: str | None = None
    contenuto_parziale: bool = False
    arricchito: bool = False
    paywall: bool = False

    @property
    def id(self) -> str:
        base = self.link or f"{self.fonte}|{self.titolo}"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


@dataclass
class EsitoFeed:
    fonte: str
    url: str
    categoria: str
    stato: str
    articoli: int = 0
    senza_data: int = 0
    fuori_finestra: int = 0
    errore: str | None = None


@dataclass
class RisultatoFetch:
    articoli: list[Article] = field(default_factory=list)
    esiti: list[EsitoFeed] = field(default_factory=list)

    @property
    def ok(self) -> int:
        return sum(
            1 for e in self.esiti if e.stato in {"ok", "ok-senza-novita"}
        )

    @property
    def senza_novita(self) -> int:
        return sum(1 for e in self.esiti if e.stato == "ok-senza-novita")

    @property
    def ko(self) -> int:
        return sum(
            1
            for e in self.esiti
            if e.stato not in {"ok", "ok-senza-novita"}
        )


def normalizza_url(url: str) -> str:
    """Rimuove frammenti e parametri di tracciamento per deduplicare i link."""
    try:
        parti = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = [
        (chiave, valore)
        for chiave, valore in parse_qsl(parti.query, keep_blank_values=True)
        if not _PARAMETRI_TRACCIANTI.match(chiave)
    ]
    percorso = parti.path.rstrip("/") or "/"
    return urlunsplit(
        (parti.scheme.lower(), parti.netloc.lower(), percorso, urlencode(query), "")
    )


def _scarica_curl(url: str, timeout: int) -> bytes | None:
    """Fallback con TLS browser-like per feed pubblici che rispondono 403."""
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:  # dipendenza opzionale, ma presente in requirements
        return None
    try:
        valida_url_pubblica(url)
        risposta = curl_requests.get(
            url,
            impersonate="chrome",
            timeout=timeout,
            headers=HEADERS,
            allow_redirects=True,
        )
        valida_url_pubblica(risposta.url)
        contenuto = risposta.content
        if risposta.status_code < 400 and len(contenuto) <= MAX_FEED_BYTES:
            return contenuto
    except Exception:
        return None
    return None


def _scarica(
    url: str,
    timeout: int,
    retry: int,
    session: requests.Session | None = None,
) -> bytes:
    """Scarica un feed con redirect rivalidati e limite 10 MB."""
    ultimo_errore: Exception | None = None
    for tentativo in range(retry + 1):
        try:
            contenuto, _, _ = fetch_con_limite(
                url,
                timeout=timeout,
                max_bytes=MAX_FEED_BYTES,
                max_redirect=3,
                headers=HEADERS,
            )
            return contenuto
        except FetchHttpError as exc:
            if exc.status in {401, 403, 406, 429}:
                contenuto = _scarica_curl(url, timeout)
                if contenuto is not None:
                    return contenuto
            if exc.status >= 500 and tentativo < retry:
                ultimo_errore = exc
                time.sleep(1.2 * (tentativo + 1))
                continue
            raise FetchError(f"HTTP {exc.status}") from exc
        except UrlRifiutato as exc:
            raise FetchError(f"errore URL non pubblico: {exc}") from exc
        except requests.RequestException as exc:
            ultimo_errore = exc
            if isinstance(exc, requests.exceptions.SSLError):
                contenuto = _scarica_curl(url, timeout)
                if contenuto is not None:
                    return contenuto
            if isinstance(
                exc,
                (
                    requests.exceptions.MissingSchema,
                    requests.exceptions.InvalidSchema,
                    requests.exceptions.InvalidURL,
                ),
            ):
                break
            if tentativo < retry:
                time.sleep(1.2 * (tentativo + 1))
        except Exception as exc:
            ultimo_errore = exc
            break
    assert ultimo_errore is not None
    raise FetchError(
        f"errore di rete ({type(ultimo_errore).__name__})"
    ) from ultimo_errore

def _data_entry(entry) -> datetime | None:
    for chiave in ("published_parsed", "updated_parsed"):
        strutturata = entry.get(chiave)
        if strutturata:
            try:
                return datetime.fromtimestamp(
                    calendar.timegm(strutturata), tz=timezone.utc
                )
            except (OverflowError, ValueError, TypeError):
                continue
    return None


def _summary_entry(entry) -> str:
    """Preferisce il summary; se il feed offre un content molto più ricco, lo usa.

    Restiamo sempre dentro il feed RSS: non scarichiamo la pagina dell'articolo.
    """
    sommario = str(entry.get("summary") or entry.get("description") or "")
    contenuto = ""
    if entry.get("content"):
        pezzi = []
        for voce in entry["content"]:
            valore = voce.get("value") if hasattr(voce, "get") else None
            if valore:
                pezzi.append(str(valore))
        contenuto = " ".join(pezzi)
    if contenuto and len(contenuto) > max(500, len(sommario) * 2):
        return contenuto
    return sommario or contenuto


def _parse_feed(
    contenuto: bytes,
    fonte: Fonte,
    adesso: datetime,
    ore: int,
    logger: logging.Logger,
    visti=None,
) -> tuple[list[Article], int, int, int]:
    """Restituisce articoli validi, senza data, fuori finestra, totale entry.

    Per i feed senza date usa la rubrica ``Visti``: il primo passaggio (cold
    start) prende solo i primi 5 item; poi entrano solo gli articoli mai visti.
    """
    parsed = feedparser.parse(contenuto)
    entries = list(parsed.entries or [])
    if not entries:
        raise FetchError("feed senza articoli (o non è un RSS valido)")

    limite = adesso - timedelta(hours=ore)
    limite_futuro = adesso + timedelta(hours=3)
    articoli: list[Article] = []
    senza_data = 0
    fuori_finestra = 0
    gia_visti = 0
    visti_url: set[str] = set()
    date_entries = [_data_entry(entry) for entry in entries]
    feed_senza_date = all(data is None for data in date_entries)
    cold_start = bool(
        visti is not None
        and not visti.ha_visti_feed(fonte.url)
        and not visti.ha_visti_feed(fonte.nome)
    )
    if feed_senza_date and visti is not None and cold_start:
        logger.info(
            "Feed %s senza date: cold start, valuto solo i primi 5 item.",
            fonte.nome,
        )
    da_valutare = entries[:5] if feed_senza_date and visti is not None and cold_start else entries

    for entry in da_valutare:
        titolo = pulisci_titolo(entry.get("title"))
        link = str(entry.get("link") or "").strip()
        if not titolo or not link.startswith(("http://", "https://")):
            continue
        data = _data_entry(entry)
        data_stimata = False
        prima_vista = None
        if data is None:
            senza_data += 1
            if not feed_senza_date or visti is None:
                continue
            chiave = visti.chiave_entry(entry)
            visto_il = visti.first_seen(chiave)
            oggi = adesso.astimezone(ROMA).date()
            stesso_giorno = bool(
                visto_il is not None and visto_il.astimezone(ROMA).date() == oggi
            )
            if visto_il is not None and not stesso_giorno:
                # Già in rubrica in un giorno precedente: non va ripetuto.
                gia_visti += 1
                continue
            if visto_il is not None:
                # Stessa giornata: una rigenerazione può riusare le stesse notizie.
                data = visto_il
            else:
                data = visti.registra(
                    chiave,
                    fonte.nome,
                    titolo,
                    adesso=adesso,
                    feed_url=fonte.url,
                )
            data_stimata = True
            prima_vista = data
        elif data > limite_futuro:
            logger.warning(
                "Feed %s: data futura per %r, la normalizzo a ora.",
                fonte.nome,
                titolo[:60],
            )
            data = adesso
            data_stimata = True
            prima_vista = data
        elif data < limite:
            fuori_finestra += 1
            continue

        link_norm = normalizza_url(link)
        if link_norm in visti_url:
            continue
        visti_url.add(link_norm)
        sommario = tronca_a_frase(pulisci_testo(_summary_entry(entry)), 1200)
        articoli.append(
            Article(
                titolo=titolo,
                link=link,
                sommario=sommario,
                pubblicato=data,
                fonte=fonte.nome,
                categoria=inferisci_categoria(entry, link, fonte.categoria),
                feed_url=fonte.url,
                data_stimata=data_stimata,
                prima_vista=prima_vista,
            )
        )

    if senza_data:
        if visti is not None and feed_senza_date:
            logger.info(
                "Feed %s: %d articoli senza data gestiti con first_seen.",
                fonte.nome,
                senza_data,
            )
        else:
            logger.warning(
                "Feed %s: %d articoli senza data scartati per prudenza.",
                fonte.nome,
                senza_data,
            )
    if fuori_finestra:
        logger.info(
            "Feed %s: %d articoli fuori dalle ultime %d ore.",
            fonte.nome,
            fuori_finestra,
            ore,
        )
    if gia_visti:
        logger.info(
            "Feed %s: %d articoli già in rubrica (senza data).",
            fonte.nome,
            gia_visti,
        )
    if not articoli:
        if feed_senza_date and visti is not None and gia_visti > 0:
            raise FeedSenzaNovita(
                f"nessuna novità: {gia_visti} articoli già in rubrica"
            )
        dettagli = []
        if senza_data:
            dettagli.append(f"{senza_data} senza data")
        if fuori_finestra:
            dettagli.append(f"{fuori_finestra} troppo vecchi")
        if gia_visti:
            dettagli.append(f"{gia_visti} già visti")
        motivo = "nessun articolo valido"
        if dettagli:
            motivo += " (" + ", ".join(dettagli) + ")"
        raise FetchError(motivo)
    return articoli, senza_data, fuori_finestra, len(entries)


def fetch_fonte(
    fonte: Fonte,
    ore: int,
    timeout: int,
    retry: int,
    adesso: datetime | None = None,
    logger: logging.Logger | None = None,
    visti=None,
) -> tuple[list[Article], EsitoFeed]:
    """Scarica e interpreta una singola fonte senza mai propagare l'errore."""
    logger = logger or logging.getLogger("notiziario")
    adesso = adesso or datetime.now(timezone.utc)
    esito = EsitoFeed(
        fonte=fonte.nome,
        url=fonte.url,
        categoria=fonte.categoria,
        stato="ko",
    )
    try:
        contenuto = _scarica(fonte.url, timeout=timeout, retry=retry)
        articoli, senza_data, fuori, totale = _parse_feed(
            contenuto, fonte, adesso, ore, logger, visti=visti
        )
    except FeedSenzaNovita as exc:
        esito.stato = "ok-senza-novita"
        esito.errore = str(exc)
        logger.info("Feed senza novità: %s (%s) - %s", fonte.nome, fonte.url, exc)
        return [], esito
    except FetchError as exc:
        esito.errore = str(exc)
        logger.warning("Feed KO: %s (%s) - %s", fonte.nome, fonte.url, exc)
        return [], esito
    except Exception as exc:  # pragma: no cover - difesa finale
        esito.errore = f"errore imprevisto ({type(exc).__name__})"
        logger.warning("Feed KO: %s (%s) - %s", fonte.nome, fonte.url, esito.errore)
        return [], esito

    esito.stato = "ok"
    esito.articoli = len(articoli)
    esito.senza_data = senza_data
    esito.fuori_finestra = fuori
    logger.info(
        "Feed OK: %s [%s] - %d articoli validi su %d",
        fonte.nome,
        fonte.categoria,
        len(articoli),
        totale,
    )
    return articoli, esito


def _nome_fonte_normalizzato(nome: str) -> str:
    return re.sub(r"\s+", " ", str(nome or "").strip().casefold())


def filtra_articoli(
    articoli: list[Article],
    tutte_fonti: list[Fonte],
    logger: logging.Logger | None = None,
) -> tuple[list[Article], dict[str, int]]:
    """Scarta categorie disattivate per la fonte e contenuti promozionali.

    La mappa ``(fonte, categoria) -> attivo`` parte da ``tutte_fonti``, incluse
    le fonti spente: così un articolo di cultura arrivato dal feed generale
    ANSA viene escluso se *tutti* i feed ANSA di cultura sono disattivati.
    Se la categoria non è mappata per quella fonte, l'articolo resta.
    """
    logger = logger or logging.getLogger("notiziario")

    attive: dict[tuple[str, str], bool] = {}
    for fonte in tutte_fonti or []:
        chiave = (_nome_fonte_normalizzato(fonte.nome), fonte.categoria)
        attive[chiave] = attive.get(chiave, False) or bool(fonte.attivo)

    tenuti: list[Article] = []
    fonti_disattivate = 0
    promozionali = 0
    for articolo in articoli:
        categoria = categoria_da_url_articolo(articolo.link)
        if categoria:
            chiave = (_nome_fonte_normalizzato(articolo.fonte), categoria)
            if chiave in attive and not attive[chiave]:
                fonti_disattivate += 1
                continue
        if e_promozionale(
            articolo.titolo,
            sommario=articolo.sommario,
            contenuto=articolo.contenuto or "",
            fonte=articolo.fonte,
            link=articolo.link,
        ):
            promozionali += 1
            continue
        tenuti.append(articolo)

    contatori = {
        "tenuti": len(tenuti),
        "fonti_disattivate": fonti_disattivate,
        "promozionali": promozionali,
    }
    if fonti_disattivate:
        logger.warning(
            "Filtro fonti disattivate: %d articoli scartati per categoria "
            "spenta sulla fonte.",
            fonti_disattivate,
        )
    if promozionali:
        logger.info(
            "Filtro promozionali: %d articoli scartati.", promozionali
        )
    logger.info(
        "Filtro articoli: %d tenuti, %d categorie disattivate, %d promozionali.",
        contatori["tenuti"],
        fonti_disattivate,
        promozionali,
    )
    return tenuti, contatori


def fetch_all(
    fonti: list[Fonte],
    ore: int,
    timeout: int,
    retry: int,
    max_workers: int,
    logger: logging.Logger | None = None,
    adesso: datetime | None = None,
    visti=None,
    tutte_fonti: list[Fonte] | None = None,
) -> RisultatoFetch:
    """Scarica tutte le fonti in parallelo, deduplica per URL e filtra.

    ``tutte_fonti`` contiene anche le fonti spente; serve al filtro per
    categoria. Se manca, il filtro usa le sole fonti attive (nessuna categoria
    risulta disattivata) ma continua a scartare i contenuti promozionali.
    """
    logger = logger or logging.getLogger("notiziario")
    adesso = adesso or datetime.now(timezone.utc)
    risultato = RisultatoFetch()
    lavoratori = max(1, min(max_workers, max(1, len(fonti))))
    with concurrent.futures.ThreadPoolExecutor(max_workers=lavoratori) as pool:
        futures = [
            pool.submit(
                fetch_fonte,
                fonte,
                ore,
                timeout,
                retry,
                adesso,
                logger,
                visti,
            )
            for fonte in fonti
        ]
        for future in concurrent.futures.as_completed(futures):
            articoli, esito = future.result()
            risultato.articoli.extend(articoli)
            risultato.esiti.append(esito)

    # Ordine stabile per gli esiti, come nel file delle fonti.
    posizione = {fonte.url: indice for indice, fonte in enumerate(fonti)}
    risultato.esiti.sort(key=lambda e: posizione.get(e.url, 9999))

    visti_url: set[str] = set()
    unici: list[Article] = []
    for articolo in sorted(risultato.articoli, key=lambda a: a.pubblicato, reverse=True):
        chiave = normalizza_url(articolo.link)
        if chiave in visti_url:
            continue
        visti_url.add(chiave)
        unici.append(articolo)
    risultato.articoli = unici
    riferimento_fonti = tutte_fonti if tutte_fonti is not None else fonti
    risultato.articoli, contatori = filtra_articoli(
        unici, riferimento_fonti, logger=logger
    )
    logger.info(
        "Fetch completato: %d fonti OK, %d KO, %d articoli unici, "
        "%d tenuti dopo i filtri (%d categorie disattivate, %d promozionali).",
        risultato.ok,
        risultato.ko,
        len(unici),
        contatori["tenuti"],
        contatori["fonti_disattivate"],
        contatori["promozionali"],
    )
    return risultato