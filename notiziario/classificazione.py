"""Categorie multi-etichetta e notiziabilità strutturale dei cluster.

La categoria base resta quella del feed/articolo. Questo modulo aggiunge solo
etichette sovrapposte (cronaca, cronaca-nera, approfondimento, promozione) e
calcola un punteggio di notiziabilità senza usare entità specifiche.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .categorie import normalizza_testo
from .testi import e_promozionale

if TYPE_CHECKING:
    from .clustering import Cluster


# Etichette che si sovrappongono alla categoria base.
CATEGORIE_OVERLAY: tuple[str, ...] = (
    "cronaca",
    "cronaca-nera",
    "approfondimento",
    "promozione",
)

CATEGORIE_OVERLAY_SET = frozenset(CATEGORIE_OVERLAY)

_MAX_SOMMARIO = 1200
_MAX_CONTENUTO = 6000


@dataclass(frozen=True)
class _Contesto:
    base: str
    titolo_raw: str
    titolo_norm: str
    testo_breve_norm: str
    testo_norm: str
    testo_raw: str
    promozionale: bool
    fonte_approfondimento: bool
    link_approfondimento: bool


def _parti_cluster(cluster: "Cluster"):
    """Titoli, sommari, contenuti, fonti e link degli articoli del cluster."""
    titoli: list[str] = []
    sommari: list[str] = []
    contenuti: list[str] = []
    fonti: list[str] = []
    link: list[str] = []
    for articolo in getattr(cluster, "articoli", []) or []:
        titolo = str(getattr(articolo, "titolo", "") or "")
        sommario = str(getattr(articolo, "sommario", "") or "")[:_MAX_SOMMARIO]
        contenuto = str(getattr(articolo, "contenuto", "") or "")[:_MAX_CONTENUTO]
        fonte = str(getattr(articolo, "fonte", "") or "")
        indirizzo = str(getattr(articolo, "link", "") or "")
        if titolo:
            titoli.append(titolo)
        if sommario:
            sommari.append(sommario)
        if contenuto:
            contenuti.append(contenuto)
        if fonte:
            fonti.append(fonte)
        if indirizzo:
            link.append(indirizzo)
    if not titoli:
        # Difesa per cluster vuoti o costruiti a mano nei test.
        try:
            titolo = str(cluster.titolo or "")
        except ValueError:
            titolo = ""
        if titolo:
            titoli.append(titolo)
        try:
            sommario = str(cluster.sommario or "")
        except ValueError:
            sommario = ""
        if sommario:
            sommari.append(sommario)
    return titoli, sommari, contenuti, fonti, link


def _contesto(cluster: "Cluster") -> _Contesto:
    titoli, sommari, contenuti, fonti, link = _parti_cluster(cluster)
    titoli_raw = " . ".join(titoli)
    breve_raw = " . ".join(titoli + sommari)
    testo_raw = " . ".join(titoli + sommari + contenuti)
    promozionale = any(
        e_promozionale(
            str(getattr(articolo, "titolo", "") or ""),
            str(getattr(articolo, "sommario", "") or ""),
            str(getattr(articolo, "contenuto", "") or ""),
            str(getattr(articolo, "fonte", "") or ""),
            str(getattr(articolo, "link", "") or ""),
        )
        for articolo in (getattr(cluster, "articoli", []) or [])
    )
    fonti_norm = {normalizza_testo(fonte) for fonte in fonti}
    fonte_approfondimento = any(
        nome in fonte
        for fonte in fonti_norm
        for nome in _FONTI_APPROFONDIMENTO_NORM
    )
    link_approfondimento = any(
        _URL_APPROFONDIMENTO.search(indirizzo) for indirizzo in link
    )
    return _Contesto(
        base=_base_cluster(cluster),
        titolo_raw=titoli_raw,
        titolo_norm=normalizza_testo(titoli_raw),
        testo_breve_norm=normalizza_testo(breve_raw),
        testo_norm=normalizza_testo(testo_raw),
        testo_raw=testo_raw,
        promozionale=promozionale,
        fonte_approfondimento=fonte_approfondimento,
        link_approfondimento=link_approfondimento,
    )


def _base_cluster(cluster: "Cluster") -> str:
    try:
        return str(cluster.categoria or "")
    except ValueError:
        return ""


# --- Cronaca nera ---------------------------------------------------------

# Eventi violenti espliciti. Non basta un processo o un commento.
_NERA_FORTI = re.compile(
    r"\b(?:femminicidio|femminicidi|omicidio|omicidi|omicidi stradali|"
    r"uccis[oei]|uccisione|uccisioni|assassinat\w*|sparatoria|sparatorie|"
    r"accoltellat\w*|ammazzat\w*|cadavere|cadaveri|corpo senza vita|"
    r"gettato dal|gettata dal|investito e ucciso|investita e uccisa|"
    r"omicidio stradale|attacco armato)\b"
)
_NERA_STORAGE = re.compile(r"\b(?:strage|stragi|attentato|attentati)\b")
_NERA_SUICIDIO = re.compile(
    r"\b(?:suicidio|suicidi|suicida|suicidarsi|si e tolto la vita|"
    r"si e tolta la vita)\b"
)
_NERA_ESCLUSIONI = re.compile(
    r"\b(?:processo|processi|udienza|udienze|inchiesta|inchieste|"
    r"indagine|indagini|commento|commenti|reazione|reazioni|"
    r"polemica|polemiche|mistero italiano|editoriale|editoriali|"
    r"opinione|opinioni|analisi|intervista|interviste|reportage|"
    r"saggio|saggi|anniversario|anniversari|commemorazione|"
    r"commemorazioni|dichiarazione|dichiarazioni|retroscena)\b"
)
_SUICIDIO_SEGUITO = re.compile(
    r"\b(?:processo|processi|udienza|udienze|inchiesta|inchieste|"
    r"indagine|indagini|indag\w*|procura|pm|tribunale|sentenza|"
    r"autopsia|sequestrat\w*|commento|commenti|reazione|reazioni|"
    r"polemica|polemiche|mistero italiano|dichiarazione|dichiarazioni|"
    r"editoriale|editoriali|opinione|opinioni|analisi|intervista|"
    r"interviste|reportage|saggio|saggi|anniversario|anniversari|"
    r"commemorazione|commemorazioni)\b"
)
_GUERRA = re.compile(
    r"\b(?:guerra|guerre|conflitt[oi](?!\s+di\s+(?:interessi|attribuzioni))|"
    r"offensiva|offensive|bombardament\w*|genocidio|genocidi|"
    r"invasione(?!\s+di\s+(?:mercato|campo|privacy))|invasioni)\b"
)
_OPERA_CULTURALE = re.compile(
    r"\b(?:libro|libri|romanzo|romanzi|film|spettacolo|spettacoli|"
    r"concerto|concerti|documentario|documentari|podcast|recensione|"
    r"recensioni)\b"
)


def _e_cronaca_nera(titolo_norm: str, testo_norm: str) -> bool:
    """Vero solo per un evento violento/morte, non per seguiti o commenti."""
    forte = bool(_NERA_FORTI.search(testo_norm))
    strage = bool(_NERA_STORAGE.search(testo_norm))
    suicidio = bool(_NERA_SUICIDIO.search(testo_norm))
    if not (forte or strage or suicidio):
        return False
    # Una guerra o una strage di guerra restano mondo/cronaca.
    if _GUERRA.search(testo_norm):
        return False
    # Seguiti giudiziari e commenti non sono cronaca nera.
    if _NERA_ESCLUSIONI.search(testo_norm):
        return False
    # Un libro, un film o una mostra su un delitto non sono il delitto.
    if _OPERA_CULTURALE.search(titolo_norm):
        return False
    # Il suicidio è spesso raccontato come seguito: al primo dubbio, non nera.
    if suicidio and not (forte or strage):
        if _SUICIDIO_SEGUITO.search(testo_norm):
            return False
    return True


# --- Cronaca (hard news) --------------------------------------------------

_CRONACA_NORM = re.compile(
    r"\b(?:guerra|guerre|conflitto|conflitti|attacco|attacchi|offensiva|"
    r"offensive|genocidio|genocidi|tortura|torture|strage|stragi|"
    r"attentat\w*|femminicid\w*|omicid\w*|uccis\w*|assassin\w*|suicid\w*|"
    r"cadaver\w*|corpo senza vita|processo|processi|indagine|indagini|"
    r"indag\w*|procura|tribunale|tribunali|sentenza|sentenze|arrest\w*|"
    r"fermat[oi]|condann\w*|assolt\w*|sequestr\w*|operazione|operazioni|"
    r"vertice|vertici|governo|governi|parlamento|legge|leggi|decreto|"
    r"decreti|riforma|riforme|sanita|sanitar\w*|scuola|scuole|sciopero|"
    r"scioperi|protesta|proteste|emergenza|emergenze|incendio|incendi|"
    r"incidente|incidenti|alluvione|alluvioni|terremoto|terremoti|"
    r"bilancio|bilanci|manovra|manovre|difesa|elezioni|elezione|voto|"
    r"voti|colpo di stato)\b"
)
_CRONACA_ACRONIMI = re.compile(r"\b(?:NATO|UE|Ue|ONU|Onu)\b")


def _e_cronaca(base: str, promozionale: bool, contesto: _Contesto) -> bool:
    """Hard news/attualità, non cultura, sport o promozione."""
    if promozionale or base in {"cultura", "sport"}:
        return False
    return bool(
        _CRONACA_NORM.search(contesto.testo_norm)
        or _CRONACA_ACRONIMI.search(contesto.testo_raw)
    )


# --- Approfondimento ------------------------------------------------------

_FONTI_APPROFONDIMENTO = (
    "Valigia Blu",
    "MicroMega",
    "Jacobin",
    "Le Grand Continent",
    "The Nation",
    "The American Prospect",
    "Foreign Policy",
    "Internazionale",
    "Limes",
    "IRPI",
    "Il Tascabile",
    "doppiozero",
    "Nazione Indiana",
    "Carmilla",
    "La Balena Bianca",
    "Rivista Studio",
    "Lucy",
    "Artribune",
)
_FONTI_APPROFONDIMENTO_NORM = tuple(
    normalizza_testo(fonte) for fonte in _FONTI_APPROFONDIMENTO
)
_URL_APPROFONDIMENTO = re.compile(
    r"/(?:opinioni|editoriali|commenti|analisi|longform|approfondimenti|idee)/",
    re.IGNORECASE,
)
_TITOLI_APPROFONDIMENTO = re.compile(
    r"\b(?:editoriale|editoriali|opinione|opinioni|commento|commenti|"
    r"analisi|il punto|perche|cosa significa|dietro le quinte|ritratto|"
    r"ritratti|intervista|interviste|lezione|lezioni|viaggio dentro|"
    r"inchiesta|inchieste|reportage|saggio|saggi)\b"
)


def _e_approfondimento(contesto: _Contesto) -> bool:
    return bool(
        contesto.fonte_approfondimento
        or contesto.link_approfondimento
        or _TITOLI_APPROFONDIMENTO.search(contesto.titolo_norm)
    )


# --- Promozione / PR ------------------------------------------------------

# Segnali che da soli bastano.
_PROMO_FORTI = re.compile(
    r"\b(?:esce in libreria|presenta il libro|presentazione del libro|"
    r"presentazione del volume|in edicola|abbonati|abbonamento|abbonamenti|"
    r"iscriviti|test drive|gadget|concorso(?!\s+di\s+colpa)|recensione|"
    r"recensioni|prova su strada|nuovo numero della rivista|"
    r"nuovo numero del mensile|trailer|filmato promozionale|"
    r"film biografico|al cinema|esce al cinema|nuovo film|pellicola)\b"
)
# Segnali ambigui: servono due indizi oppure un contesto promozionale.
_PROMO_DEBOLI = re.compile(
    r"\b(?:presentazione|offerta|offerte|sconto|sconti|prezzo|prezzi|"
    r"prova|prove|evento|eventi|festa|feste|anniversario|anniversari|"
    r"celebra|celebrazione|celebrazioni|numero \d+)\b"
)
_PROMO_CONTESTO = re.compile(
    r"\b(?:lettori|clienti|rivista|mensile|settimanale|prodotto|prodotti|"
    r"marchio|azienda|sponsor|ingresso|appuntamento|vi aspettiamo|"
    r"in piazza|organizzato|organizzata|concerto|spettacolo|mostra|"
    r"firma copie|incontro con l autore)\b"
)
# "Numero 12 di Focus" è un numero di rivista; "numero 3 della Costituzione"
# non deve diventare PR. Il nome della testata in maiuscolo aiuta a distinguere.
_PROMO_NUMERO_RAW = re.compile(
    r"\b[Nn]umero\s+\d+\s+(?:di|del)\s+[A-Z]"
)


def _e_promozionale(contesto: _Contesto) -> bool:
    if contesto.promozionale:
        return True
    if _PROMO_NUMERO_RAW.search(contesto.titolo_raw):
        return True
    if _PROMO_FORTI.search(contesto.testo_breve_norm):
        return True
    deboli = {
        trovato.group(0) for trovato in _PROMO_DEBOLI.finditer(contesto.testo_breve_norm)
    }
    if not deboli:
        return False
    if len(deboli) >= 2:
        return True
    return bool(_PROMO_CONTESTO.search(contesto.testo_breve_norm))


# --- API principale categorie --------------------------------------------

def categorie_cluster(cluster: "Cluster") -> set[str]:
    """Categoria base più le etichette sovrapposte pertinenti."""
    return _calcola_categorie(_contesto(cluster))


# --- Notiziabilità strutturale -------------------------------------------

_SIGNAL_GROUPS = (
    re.compile(
        r"\b(?:guerra|guerre|conflitt[oi](?!\s+di\s+(?:interessi|attribuzioni))|"
        r"pace|cessate il fuoco|negoziati di pace|processo di pace|"
        r"accordo di pace|trattato di pace|offensiv\w*|bombardament\w*|"
        r"genocidio|genocidi|tortura|torture|elezion\w*|colpo di stato)\b"
    ),
    re.compile(
        r"\b(?:riforma|riforme|manovra|manovre|bilancio|bilanci|sanita|"
        r"sanitar\w*|servizio sanitario|legge di bilancio)\b"
    ),
    re.compile(
        r"\b(?:scoperta|scoperte|studio clinico|studi clinici|"
        r"sperimentazione|sperimentazioni|vaccino|vaccini|farmaco|farmaci|"
        r"nobel)\b"
    ),
    re.compile(
        r"\b(?:cop\d*|clima|climatic\w*|cambiamento climatico|emission\w*|"
        r"rinnovabil\w*)\b"
    ),
)
_STATISTICHE = re.compile(
    r"\b(?:statistica|statistiche|dati statistici|dati globali|"
    r"dati mondiali|censimento|censimenti)\b"
)
_GLOBALE = re.compile(
    r"\b(?:globale|globali|mondiale|mondiali|internazionale|internazionali)\b"
)
_SCALA = re.compile(r"\b(?:milione|milioni|miliardo|miliardi|record)\b")
_ISTITUZIONI = re.compile(
    r"\b(?:oms|onu|ue|fmi|iea|istat|eurostat|banca mondiale|"
    r"fondo monetario internazionale|nature|science|lancet)\b"
)
_NATO_RAW = re.compile(r"\bNATO\b")
_ECCEZIONALE = re.compile(
    r"\b(?:genocidio|genocidi|guerra mondiale|guerra globale|guerra totale|"
    r"guerra nucleare|invasione(?!\s+di\s+(?:mercato|campo|privacy))|"
    r"invasioni|pace storica|storico accordo di pace|"
    r"accordo di pace storico|trattato di pace storico|record globale|"
    r"record mondiale|record storico|mai registrato)\b"
)
_SEGUITO = re.compile(
    r"\b(?:processo|processi|udienza|udienze|indagine|indagini|indag\w*|"
    r"reazione|reazioni|commento|commenti|polemica|polemiche|retroscena|"
    r"dichiarazione|dichiarazioni)\b"
)
_NUOVO_EVENTO = re.compile(
    r"\b(?:ucciso|uccisa|ferito|ferita|morto|morta|attacco|sparatoria|"
    r"accoltellat\w*|arrestato|arrestata|fermato|fermata|sequestrato|"
    r"sequestrata|esplosione|incendio|alluvione|terremoto|vertice|accordo|"
    r"firmato|approvato|varato|elezione|eletto|colpo di stato|scoperta|"
    r"pubblicato|studio|sentenza|condanna|assolto)\b"
)
_LOCALE = re.compile(
    r"\b(?:quartiere|quartieri|municipio|municipi|consiglio comunale|"
    r"pro loco|festa patronale|parrocchia|parrocchie)\b"
)
_STORICO = re.compile(
    r"\b(?:prima guerra mondiale|seconda guerra mondiale|guerra fredda|"
    r"nel 1914|nel 1918|nel 1939|nel 1945|storia del marchio|"
    r"storia della famiglia|film biografico|film storico)\b"
)

_BASE_3 = {
    "italia",
    "mondo",
    "economia",
    "tecnologia",
    "scienza-salute",
    "ambiente",
    "cronaca",
    "approfondimento",
    "buone-notizie",
}


def _calcola_notiziabilita(contesto: _Contesto, categorie: set[str]) -> int:
    base = contesto.base
    if "promozione" in categorie or base == "promozione":
        return 1
    if base in {"cultura", "sport"}:
        punteggio = 2
    elif "cronaca-nera" in categorie:
        punteggio = 3
    elif base in _BASE_3:
        punteggio = 3
    else:
        punteggio = 2

    storico = bool(_STORICO.search(contesto.testo_norm))
    for indice, segnale in enumerate(_SIGNAL_GROUPS):
        if indice == 0 and storico:
            continue
        if segnale.search(contesto.testo_norm):
            punteggio += 1
    if _STATISTICHE.search(contesto.testo_norm) and _GLOBALE.search(
        contesto.testo_norm
    ):
        punteggio += 1
    if (
        _SCALA.search(contesto.testo_norm)
        or "%" in contesto.testo_raw
        or _ISTITUZIONI.search(contesto.testo_norm)
        or _NATO_RAW.search(contesto.testo_raw)
    ):
        punteggio += 1

    eccezionale = bool(_ECCEZIONALE.search(contesto.testo_norm)) and not storico
    if eccezionale:
        risultato = 5
    elif punteggio >= 4:
        risultato = 4
    elif punteggio >= 2:
        risultato = 3
    elif punteggio >= 0:
        risultato = 2
    else:
        risultato = 1

    # Tetti strutturali: la cultura, lo sport e il localismo non sono aperture.
    if base in {"cultura", "sport"}:
        risultato = min(risultato, 2)
    if _LOCALE.search(contesto.testo_norm) and base != "mondo":
        risultato = min(risultato, 2)
    # Un seguito giudiziario o un commento senza un fatto nuovo non è apertura.
    if _SEGUITO.search(contesto.testo_norm) and not _NUOVO_EVENTO.search(
        contesto.testo_norm
    ):
        risultato = min(risultato, 3)
    return max(1, min(5, risultato))


def notiziabilita_cluster(cluster: "Cluster") -> int:
    """Notiziabilità 1-5 strutturale, calibrata su segnali non nominali."""
    contesto = _contesto(cluster)
    return _calcola_notiziabilita(contesto, _calcola_categorie(contesto))


def _calcola_categorie(contesto: _Contesto) -> set[str]:
    """Variante interna che riusa il contesto già costruito."""
    categorie: set[str] = {contesto.base} if contesto.base else set()
    promozionale = contesto.base == "promozione" or _e_promozionale(contesto)
    if promozionale:
        categorie.add("promozione")
    if not promozionale and _e_cronaca_nera(contesto.titolo_norm, contesto.testo_norm):
        categorie.add("cronaca-nera")
    if _e_approfondimento(contesto):
        categorie.add("approfondimento")
    if _e_cronaca(contesto.base, promozionale, contesto):
        categorie.add("cronaca")
    return categorie
