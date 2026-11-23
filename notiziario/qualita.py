"""Verifica della completezza giornalistica delle notizie del copione.

Il modulo non chiama servizi esterni: guarda il materiale selezionato e il
testo prodotto, stabilisce quali domande giornalistiche sono applicabili e
restituisce, quando serve, una frase del materiale per coprire una mancanza.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .testi import (
    MESI,
    conta_parole,
    estrai_frasi,
    estrai_nomi_propri,
    normalizza_dedup,
    rimuovi_pubblicita,
    similarita_testi,
)

ESIGENZE = ("cosa", "chi", "quando", "dove", "perche", "conseguenze")

_ETICHETTE_ESIGENZA = {
    "cosa": "cosa è successo",
    "chi": "chi o cosa è coinvolto",
    "quando": "quando",
    "dove": "dove",
    "perche": "perché",
    "conseguenze": "conseguenze o effetti",
}


@dataclass
class EsitoCompletezza:
    posizione: int
    titolo: str
    mancanti: list[str]
    applicabili: list[str]


def _normalizza(testo: str) -> str:
    """Minuscole, senza accenti, spazi compattati. Numeri e punteggiatura restano."""
    normale = unicodedata.normalize("NFKD", str(testo or ""))
    senza_accenti = "".join(
        carattere for carattere in normale if not unicodedata.combining(carattere)
    )
    return re.sub(r"\s+", " ", senza_accenti.casefold()).strip()


_MESI_NORMALIZZATI = tuple(_normalizza(mese) for mese in MESI)
_GIORNI_NORMALIZZATI = (
    "lunedi",
    "martedi",
    "mercoledi",
    "giovedi",
    "venerdi",
    "sabato",
    "domenica",
)

_TEMPO_RE = re.compile(
    r"(?:"
    r"\b(?:oggi|ieri|domani|stamattina|stamani|stasera|stanotte|adesso|"
    + "|".join(_GIORNI_NORMALIZZATI + _MESI_NORMALIZZATI)
    + r")\b|"
    r"\b\d{1,2}\s+(?:" + "|".join(_MESI_NORMALIZZATI) + r")\b|"
    r"\b(?:19|20)\d{2}\b|"
    r"\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b|"
    r"\b\d{1,2}[:.]\d{2}\b|"
    r"\b(?:alle|ore|dalle|entro|fino\s+al|dal)\s+\d{1,2}\b|"
    r"\b(?:quest[' ]?anno|quest[' ]?estate|quest[' ]?inverno|"
    r"settimana\s+scorsa|scorsa\s+settimana|settimana\s+prossima|"
    r"prossima\s+settimana|mese\s+scorso|scorso\s+mese|mese\s+prossimo|"
    r"prossimo\s+mese|anno\s+scorso|scorso\s+anno|anno\s+prossimo|"
    r"prossimo\s+anno|fine\s+settimana|weekend|"
    r"(?:questa|ieri|domani)\s+(?:mattina|sera|notte|pomeriggio)|"
    r"(?:prossim[oi]|scors[oi])\s+(?:ore|giorni|settimane|mesi|anni)|"
    r"(?:di|in|nel|nella|durante|verso)\s+(?:mattina|pomeriggio|sera|notte)|"
    r"(?:un|due|tre|quattro|cinque|sei|sette|otto|nove|dieci|pochi|"
    r"alcuni|molti|qualche)\s+(?:giorni|ore|mesi|anni|settimane)\s+fa)\b"
    r")"
)

_LUOGHI_NOTI = (
    "italia",
    "roma",
    "milano",
    "napoli",
    "torino",
    "palermo",
    "genova",
    "bologna",
    "firenze",
    "bari",
    "catania",
    "venezia",
    "verona",
    "messina",
    "padova",
    "trieste",
    "brescia",
    "parma",
    "prato",
    "modena",
    "reggio calabria",
    "reggio emilia",
    "perugia",
    "livorno",
    "ravenna",
    "cagliari",
    "foggia",
    "rimini",
    "salerno",
    "ferrara",
    "sassari",
    "latina",
    "giugliano",
    "monza",
    "siracusa",
    "pescara",
    "bergamo",
    "forli",
    "trento",
    "vicenza",
    "terni",
    "bolzano",
    "novara",
    "piacenza",
    "ancona",
    "andria",
    "arezzo",
    "udine",
    "cesena",
    "lecce",
    "pesaro",
    "barletta",
    "alessandria",
    "pisa",
    "catanzaro",
    "pistoia",
    "lucca",
    "brindisi",
    "treviso",
    "busto arsizio",
    "como",
    "marsala",
    "grosseto",
    "sesto san giovanni",
    "varese",
    "fiumicino",
    "casoria",
    "asti",
    "caserta",
    "cinisello balsamo",
    "gela",
    "aprilia",
    "ragusa",
    "pavia",
    "cremona",
    "carpi",
    "lamezia terme",
    "altamura",
    "imola",
    "l'aquila",
    "massa",
    "trapani",
    "viterbo",
    "cosenza",
    "potenza",
    "afragola",
    "vittoria",
    "crotone",
    "matera",
    "molfetta",
    "bitonto",
    "faenza",
    "sanremo",
    "aosta",
    "cuneo",
    "savona",
    "imperia",
    "la spezia",
    "belluno",
    "rovigo",
    "sondrio",
    "lecco",
    "lodi",
    "mantova",
    "pordenone",
    "gorizia",
    "siena",
    "rieti",
    "frosinone",
    "isernia",
    "campobasso",
    "chieti",
    "teramo",
    "ascoli piceno",
    "macerata",
    "fermo",
    "urbino",
    "europa",
    "unione europea",
    "stati uniti",
    "usa",
    "america",
    "regno unito",
    "gran bretagna",
    "inghilterra",
    "scozia",
    "irlanda",
    "francia",
    "germania",
    "spagna",
    "portogallo",
    "svizzera",
    "austria",
    "belgio",
    "olanda",
    "paesi bassi",
    "danimarca",
    "svezia",
    "norvegia",
    "finlandia",
    "polonia",
    "repubblica ceca",
    "slovacchia",
    "ungheria",
    "romania",
    "bulgaria",
    "grecia",
    "turchia",
    "russia",
    "ucraina",
    "bielorussia",
    "georgia",
    "armenia",
    "azerbaigian",
    "kazakistan",
    "cina",
    "giappone",
    "corea del sud",
    "corea del nord",
    "india",
    "pakistan",
    "afghanistan",
    "iran",
    "iraq",
    "siria",
    "libano",
    "israele",
    "palestina",
    "gaza",
    "cisgiordania",
    "egitto",
    "libia",
    "tunisia",
    "algeria",
    "marocco",
    "sudan",
    "etiopia",
    "somalia",
    "kenya",
    "nigeria",
    "sudafrica",
    "brasile",
    "argentina",
    "cile",
    "colombia",
    "venezuela",
    "peru",
    "messico",
    "canada",
    "australia",
    "nuova zelanda",
    "arabia saudita",
    "emirati arabi uniti",
    "qatar",
    "kuwait",
    "giordania",
    "yemen",
    "oman",
    "bahrein",
    "bruxelles",
    "strasburgo",
    "washington",
    "new york",
    "londra",
    "parigi",
    "berlino",
    "madrid",
    "mosca",
    "kiev",
    "kyiv",
    "pechino",
    "tokyo",
    "teheran",
    "il cairo",
    "ginevra",
    "vienna",
    "varsavia",
    "praga",
    "budapest",
    "lussemburgo",
    "amsterdam",
    "copenaghen",
    "oslo",
    "stoccolma",
    "helsinki",
    "dublino",
    "lisbona",
    "medio oriente",
    "africa",
    "asia",
    "america latina",
    "balcani",
    "mediterraneo",
    "mar nero",
    "mar rosso",
    "atlantico",
    "pacifico",
)

_LUOGHI_RE = re.compile(
    r"(?<![\w])(?:"
    + "|".join(re.escape(lungo) for lungo in sorted(_LUOGHI_NOTI, key=len, reverse=True))
    + r")(?![\w])"
)

_NOMI_LUOGO_GENERICI = (
    "citta",
    "paese",
    "capitale",
    "comune",
    "provincia",
    "regione",
    "quartiere",
    "frazione",
    "zona",
    "area",
    "localita",
    "centro storico",
    "piazza",
    "via",
    "viale",
    "strada",
    "corso",
    "porto",
    "aeroporto",
    "stazione",
    "ospedale",
    "tribunale",
    "carcere",
    "prigione",
    "scuola",
    "universita",
    "parco",
    "stadio",
    "teatro",
    "museo",
    "chiesa",
    "duomo",
    "basilica",
    "palazzo",
    "sede",
    "confine",
    "frontiera",
    "centro",
    "periferia",
    "campagna",
    "montagna",
    "mare",
    "fiume",
    "lago",
    "valle",
    "collina",
    "spiaggia",
    "bosco",
    "foresta",
    "deserto",
    "isola",
    "penisola",
    "base militare",
    "casa",
    "ufficio",
    "lavoro",
    "azienda",
    "fabbrica",
    "negozio",
    "ristorante",
    "hotel",
    "albergo",
    "mondo",
    "estero",
)

_PREPOSIZIONI_LUOGO = (
    "a",
    "ad",
    "in",
    "nel",
    "nello",
    "nella",
    "nei",
    "negli",
    "nelle",
    "al",
    "allo",
    "alla",
    "ai",
    "agli",
    "alle",
    "da",
    "dal",
    "dallo",
    "dalla",
    "dai",
    "dagli",
    "dalle",
    "presso",
    "verso",
    "tra",
    "fra",
    "su",
    "sul",
    "sullo",
    "sulla",
    "sui",
    "sugli",
    "sulle",
)

_LUOGO_GENERICO_RE = re.compile(
    r"\b(?:"
    + "|".join(_PREPOSIZIONI_LUOGO)
    + r")\s+(?:(?:il|la|lo|l|i|gli|le|un|uno|una)\s+)?(?:"
    + "|".join(re.escape(nome) for nome in _NOMI_LUOGO_GENERICI)
    + r")\b|"
    r"\b(?:all|nell|dall|sull)['’](?:"
    + "|".join(re.escape(nome) for nome in _NOMI_LUOGO_GENERICI)
    + r")\b"
)

_LUOGO_MAIUSCOLO_RE = re.compile(
    r"\b(?:"
    + "|".join(_PREPOSIZIONI_LUOGO)
    + r")\s+([A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ'’.-]+)"
)

_NON_LUOGHI = frozenset(
    {
        "ansa",
        "adnkronos",
        "reuters",
        "afp",
        "ap",
        "governo",
        "parlamento",
        "camera",
        "senato",
        "consiglio",
        "commissione",
        "unione",
        "banca",
        "corte",
        "procura",
        "polizia",
        "carabinieri",
        "ministero",
        "presidenza",
        "partito",
        "sindacato",
        "confindustria",
        "gennaio",
        "febbraio",
        "marzo",
        "aprile",
        "maggio",
        "giugno",
        "luglio",
        "agosto",
        "settembre",
        "ottobre",
        "novembre",
        "dicembre",
        "lunedi",
        "martedi",
        "mercoledi",
        "giovedi",
        "venerdi",
        "sabato",
        "domenica",
    }
)

_CAUSA_RE = re.compile(
    r"(?:perch[eè]|poich[eè]|a\s+causa|a\s+seguito|in\s+seguito|"
    r"in\s+conseguenza|dopo\s+(?:che|la|il|lo|i|gli|le|l['’])|"
    r"indagat[oi]\s+per|accusat[oi]\s+di|accusa\s+di|"
    r"con\s+l['’]?obiettivo|per\s+evitare|per\s+ridurre|per\s+contrastare|"
    r"per\s+fermare|per\s+sostenere|per\s+garantire|per\s+tutelare|"
    r"per\s+punire|per\s+far\s+fronte|per\s+via|grazie\s+a|grazie\s+all['’]?|"
    r"motivo|ragione|scopo|spint[oi]\s+da|in\s+relazione\s+a|"
    r"nell['’]?ambito\s+di|per\s+questo|quindi|per\s+cui|"
    r"dal\s+momento\s+che|visto\s+che|dato\s+che|cos[iì]\s+che|"
    r"dopo)"
)

_CONSEGUENZE_RE = re.compile(
    r"(?:conseguenz\w*|effett\w*|impatt\w*|rischi\w*|rischia\w*|"
    r"potrebbe\w*|potrebbero\w*|ha\s+portato|hanno\s+portato|portando|"
    r"dann\w*|reazion\w*|indagin\w*|sequestr\w*|aument\w*|calo|"
    r"sanzion\w*|condann\w*|provvediment\w*|decision\w*|"
    r"tagli\w*|riduzion\w*|cresc\w*|perdit\w*|feriti|morti|vittime|"
    r"evacuat\w*|chius\w*|riapert\w*|sospes\w*|revocat\w*|"
    r"dimission\w*|arrest\w*|multa|ammend\w*|obblig\w*|diviet\w*|"
    r"stop|blocc\w*|viet\w*|limitazion\w*|restrizion\w*|"
    r"protest\w*|scioper\w*|ferm\w*|interrott\w*|crisi|allarme|"
    r"emergenz\w*|alluvion\w*|incendi\w*|terremot\w*|attacch\w*|"
    r"uccis\w*|salvat\w*|via\s+libera|accord\w*|intes\w*|ratific\w*|"
    r"entrata\s+in\s+vigore|entra\s+in\s+vigore|entrera\s+in\s+vigore|"
    r"coster\w*|pagher\w*|risarc\w*|bonus|incentiv\w*|contribut\w*|"
    r"diminuisc\w*|diminuir\w*|croll\w*|miglior\w*|peggior\w*)"
)

_AZIONE_RE = re.compile(
    r"(?:\b(?:ha|hanno|aveva|avevano|e|sono|era|erano|sara|saranno|"
    r"viene|vengono|venne|vennero|fu|furono)\s+"
    r"\w+(?:ato|ata|ati|ate|ito|ita|iti|ite|uto|uta|uti|ute|"
    r"esso|essa|essi|esse|atto|atta|atti|atte)\b|"
    r"\b(?:approva|approvano|annuncia|annunciano|decide|decidono|"
    r"presenta|presentano|conferma|confermano|negozia|negoziano|"
    r"discute|discutono|vota|votano|attacca|attaccano|uccide|uccidono|"
    r"ferisce|feriscono|arresta|arrestano|indaga|indagano|"
    r"aumenta|aumentano|cresce|crescono|cala|calano|vince|vincono|"
    r"perde|perdono|firma|firmano|accorda|accordano|blocca|bloccano|"
    r"chiude|chiudono|apre|aprono|scoppia|scoppiano|esplode|esplodono|"
    r"ruba|rubano|condanna|condannano|assolve|assolvono|nomina|nominano|"
    r"elegge|eleggono|protesta|protestano|sciopera|scioperano|"
    r"viaggia|viaggiano|incontra|incontrano|visita|visitano|"
    r"annulla|annullano|revoca|revocano|sospende|sospendono|"
    r"sequestra|sequestrano|pubblica|pubblicano|prevede|prevedono|"
    r"introduce|introducono|taglia|tagliano|riduce|riducono|"
    r"investe|investono|finanzia|finanziano|costruisce|costruiscono|"
    r"inaugura|inaugurano|lancia|lanciano|dichiara|dichiarano|"
    r"spiega|spiegano|sostiene|sostengono|riferisce|riferiscono|"
    r"riporta|riportano|vara|varano|boccia|bocciano|respinge|"
    r"respingono|rinvia|rinviano|licenzia|licenziano|studia|studiano|"
    r"valuta|valutano|esamina|esaminano|promuove|promuovono)\b)"
)

_ATTORI_ISTITUZIONALI = (
    "governo",
    "esecutivo",
    "consiglio",
    "consiglio dei ministri",
    "parlamento",
    "camera",
    "senato",
    "presidente del consiglio",
    "presidente della repubblica",
    "capo dello stato",
    "premier",
    "ministro",
    "ministra",
    "ministri",
    "unione europea",
    "commissione",
    "commissione europea",
    "banca centrale europea",
    "bce",
    "corte",
    "tribunale",
    "procura",
    "polizia",
    "carabinieri",
    "guardia di finanza",
    "vigili del fuoco",
    "sindaco",
    "comune",
    "regione",
    "provincia",
    "asl",
    "onu",
    "nato",
    "fmi",
    "ocse",
    "oms",
    "croce rossa",
    "protezione civile",
    "magistratura",
    "giudice",
    "pm",
    "avvocato",
    "difesa",
    "opposizione",
    "maggioranza",
    "sindacato",
    "confindustria",
    "banca d'italia",
    "consob",
    "agenzia",
    "autorita",
    "museo",
    "universita",
    "scuola",
    "ospedale",
    "societa",
    "azienda",
    "impresa",
    "partito",
    "coalizione",
    "associazione",
    "comitato",
    "fondazione",
    "ong",
    "chiesa",
    "vaticano",
    "santa sede",
)

_ATTORI_RE = re.compile(
    r"(?<![\w])(?:"
    + "|".join(re.escape(attore) for attore in sorted(_ATTORI_ISTITUZIONALI, key=len, reverse=True))
    + r")(?![\w])"
)

_PAROLE_NON_NOMI = frozenset(
    {
        "il",
        "lo",
        "la",
        "i",
        "gli",
        "le",
        "un",
        "uno",
        "una",
        "e",
        "ed",
        "ma",
        "o",
        "od",
        "anche",
        "inoltre",
        "intanto",
        "nel",
        "nello",
        "nella",
        "nei",
        "negli",
        "nelle",
        "sul",
        "sullo",
        "sulla",
        "sui",
        "sugli",
        "sulle",
        "dal",
        "dallo",
        "dalla",
        "dai",
        "dagli",
        "dalle",
        "al",
        "allo",
        "alla",
        "ai",
        "agli",
        "alle",
        "con",
        "per",
        "tra",
        "fra",
        "dopo",
        "prima",
        "durante",
        "mentre",
        "quando",
        "dove",
        "perche",
        "come",
        "secondo",
        "oggi",
        "ieri",
        "domani",
        "questa",
        "questo",
        "queste",
        "questi",
        "sono",
        "ha",
        "hanno",
        "era",
        "erano",
        "sara",
        "saranno",
        "viene",
        "vengono",
        "nuovo",
        "nuova",
        "nuovi",
        "nuove",
        "primo",
        "prima",
        "secondo",
        "seconda",
        "ultimo",
        "ultima",
        "altro",
        "altra",
        "altri",
        "altre",
        "buono",
        "buona",
        "buone",
        "notizia",
        "notizie",
        "ecco",
        "cresce",
        "crescono",
        "arriva",
        "arrivano",
        "vince",
        "vincono",
        "perde",
        "perdono",
        "parliamo",
        "passiamo",
        "apriamo",
        "lunedi",
        "martedi",
        "mercoledi",
        "giovedi",
        "venerdi",
        "sabato",
        "domenica",
    }
    | set(_MESI_NORMALIZZATI)
)

_BOILERPLATE_RE = re.compile(
    r"(?:\bleggi\s+(?:anche|tutto|tutta|di\s+piu|di\s+più|qui|il\s+seguito)\b|"
    r"\bcontinua\s+a\s+leggere\b|\bscopri\s+di\s+piu\b|\bscopri\s+di\s+più\b|"
    r"\bclicca\s+qui\b|\barticolo\s+originale\b|"
    r"\briproduzione\s+riservata\b|\biscriviti\s+alla\s+newsletter\b|"
    r"\babbonati\b|\bacquista\s+ora\b|\bcompra\s+ora\b|"
    r"\bofferta\s+limitata\b|\bcodice\s+sconto\b|\bspedizione\s+gratuita\b|"
    r"\bpromosso\s+da\b|\bin\s+collaborazione\s+con\b|"
    r"\bcontenut[oi]\s+sponsorizzat[oi]\b|\blink\s+di\s+affiliazione\b|"
    r"\bpotremmo\s+ricevere\s+una\s+commissione\b)",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def _token(testo: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", _normalizza(testo))
        if token
    }


def _attori_materiale(testo: str) -> tuple[set[str], set[str]]:
    """Frasi e token che indicano persone o attori istituzionali nel materiale."""
    originale = str(testo or "")
    normalizzato = _normalizza(originale)
    frasi: set[str] = set()
    token: set[str] = set()

    for trovato in _ATTORI_RE.finditer(normalizzato):
        attore = re.sub(r"\s+", " ", trovato.group(0)).strip()
        if not attore:
            continue
        frasi.add(attore)
        token.update(parte for parte in attore.split() if len(parte) >= 3)

    for nome in estrai_nomi_propri(originale):
        attore = " ".join(nome)
        if attore:
            frasi.add(attore)
            token.update(
                parte
                for parte in nome
                if len(parte) >= 3 and parte not in _PAROLE_NON_NOMI
            )

    for trovato in re.finditer(
        r"\b[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ'’.-]*\b", originale
    ):
        parola = trovato.group(0).strip(".-")
        base = parola.casefold()
        if len(parola) < 3 or base in _PAROLE_NON_NOMI:
            continue
        if parola.isupper() and len(parola) <= 2:
            continue
        frasi.add(base)
        token.add(base)

    return frasi, token


def _frase_contiene_attori(
    frase: str, attori_frasi: set[str], attori_token: set[str]
) -> bool:
    normalizzato = _normalizza(frase)
    if not normalizzato:
        return False
    token_frase = _token(frase)
    for attore in attori_frasi:
        if not attore:
            continue
        if " " in attore:
            if attore in normalizzato:
                return True
        elif attore in token_frase:
            return True
    return any(
        attore in token_frase for attore in attori_token if len(attore) >= 3
    )


def _contiene_cosa(testo: str) -> bool:
    normalizzato = _normalizza(testo)
    if conta_parole(normalizzato) < 3:
        return False
    return bool(_AZIONE_RE.search(normalizzato))


def _contiene_chi(testo: str, materiale: str) -> bool:
    attori_frasi, attori_token = _attori_materiale(materiale)
    if not attori_frasi and not attori_token:
        return False
    return _frase_contiene_attori(testo, attori_frasi, attori_token)


def _chi_applicabile(materiale: str) -> bool:
    frasi, token = _attori_materiale(materiale)
    return bool(frasi or token)


def _contiene_quando(testo: str) -> bool:
    return bool(_TEMPO_RE.search(_normalizza(testo)))


def _contiene_dove(testo: str) -> bool:
    normale = _normalizza(testo)
    if _LUOGHI_RE.search(normale) or _LUOGO_GENERICO_RE.search(normale):
        return True
    for trovato in _LUOGO_MAIUSCOLO_RE.finditer(str(testo or "")):
        parola = trovato.group(1)
        base = parola.casefold()
        if base in _NON_LUOGHI:
            continue
        if parola.isupper() and len(parola) > 3:
            continue
        return True
    return False


def _contiene_perche(testo: str) -> bool:
    return bool(_CAUSA_RE.search(_normalizza(testo)))


def _contiene_conseguenze(testo: str) -> bool:
    return bool(_CONSEGUENZE_RE.search(_normalizza(testo)))


def _soddisfatta(testo: str, materiale: str, esigenza: str) -> bool:
    if esigenza == "cosa":
        return _contiene_cosa(testo)
    if esigenza == "chi":
        return _contiene_chi(testo, materiale)
    if esigenza == "quando":
        return _contiene_quando(testo)
    if esigenza == "dove":
        return _contiene_dove(testo)
    if esigenza == "perche":
        return _contiene_perche(testo)
    if esigenza == "conseguenze":
        return _contiene_conseguenze(testo)
    return True


def verifica_completezza(
    testo: str,
    materiale: str,
    titolo: str = "",
    posizione: int = 0,
) -> EsitoCompletezza:
    """Confronta una notizia con il materiale e indica le domande scoperte.

    L'applicabilità è decisa solo dal materiale: una domanda che il materiale
    non può coprire non viene mai segnalata come mancante.
    """
    materiale = str(materiale or "")
    testo_completo = " ".join(
        parte for parte in (str(titolo or ""), str(testo or "")) if parte.strip()
    )

    applicabili = ["cosa"]
    if _chi_applicabile(materiale):
        applicabili.append("chi")
    if _contiene_quando(materiale):
        applicabili.append("quando")
    if _contiene_dove(materiale):
        applicabili.append("dove")
    if _contiene_perche(materiale):
        applicabili.append("perche")
    if _contiene_conseguenze(materiale):
        applicabili.append("conseguenze")

    mancanti = [
        esigenza
        for esigenza in ESIGENZE
        if esigenza in applicabili
        and not _soddisfatta(testo_completo, materiale, esigenza)
    ]
    return EsitoCompletezza(
        posizione=int(posizione or 0),
        titolo=str(titolo or "").strip(),
        mancanti=mancanti,
        applicabili=applicabili,
    )


def _punteggio_frase(
    frase: str,
    esigenza: str,
    attori_frasi: set[str],
    attori_token: set[str],
) -> int:
    normale = _normalizza(frase)
    if esigenza == "cosa":
        return 1 + (2 if _AZIONE_RE.search(normale) else 0)
    if esigenza == "chi":
        return 1 if _frase_contiene_attori(frase, attori_frasi, attori_token) else 0
    if esigenza == "quando":
        return len(_TEMPO_RE.findall(normale))
    if esigenza == "dove":
        punteggio = len(_LUOGO_MAIUSCOLO_RE.findall(frase))
        if _LUOGHI_RE.search(normale):
            punteggio += 2
        if _LUOGO_GENERICO_RE.search(normale):
            punteggio += 1
        return punteggio
    if esigenza == "perche":
        return len(_CAUSA_RE.findall(normale))
    if esigenza == "conseguenze":
        return len(_CONSEGUENZE_RE.findall(normale))
    return 0


def _frase_pulita(frase: str) -> str:
    frase = re.sub(r"\s+", " ", str(frase or "")).strip().strip('"“”')
    if not frase:
        return ""
    if frase[0].islower():
        frase = frase[0].upper() + frase[1:]
    if frase[-1] not in ".!?":
        frase += "."
    return frase


def frase_per_esigenza(
    materiale: str,
    esigenza: str,
    testo_esistente: str = "",
) -> str | None:
    """Sceglie una frase del materiale che copra una domanda, se esiste.

    La frase non deve essere già presente nel testo della notizia (confronto
    normalizzato e per similarità) e non deve essere pubblicità o boilerplate.
    """
    if esigenza not in ESIGENZE:
        return None
    pulito = rimuovi_pubblicita(str(materiale or ""))
    if not pulito:
        return None

    frasi_esistenti = estrai_frasi(str(testo_esistente or ""))
    testo_esistente_norm = normalizza_dedup(testo_esistente or "")
    attori_frasi, attori_token = _attori_materiale(pulito)

    migliore: str | None = None
    migliore_chiave: tuple[int, int, int] | None = None
    for indice, grezza in enumerate(estrai_frasi(pulito)):
        frase = re.sub(r"\s+", " ", grezza).strip().strip('"“”')
        if not frase or _BOILERPLATE_RE.search(frase) or _URL_RE.search(frase):
            continue
        parole = conta_parole(frase)
        if parole < 6 or parole > 80:
            continue
        normalizzata = normalizza_dedup(frase)
        if not normalizzata:
            continue
        if normalizzata in testo_esistente_norm:
            continue
        if any(
            similarita_testi(frase, esistente) >= 0.75
            for esistente in frasi_esistenti
        ):
            continue

        punteggio = _punteggio_frase(
            frase, esigenza, attori_frasi, attori_token
        )
        if esigenza != "cosa" and punteggio <= 0:
            continue
        lunghezza_ideale = 1 if 15 <= parole <= 70 else 0
        chiave = (punteggio, lunghezza_ideale, -indice)
        if migliore_chiave is None or chiave > migliore_chiave:
            migliore = frase
            migliore_chiave = chiave

    return _frase_pulita(migliore) if migliore else None


def istruzioni_retry(esiti: list[EsitoCompletezza]) -> str:
    """Messaggio compatto da aggiungere al prompt quando restano mancanze."""
    righe: list[str] = []
    for esito in esiti:
        if not esito.mancanti:
            continue
        etichetta = f"posizione {esito.posizione}"
        if esito.titolo:
            etichetta += f' "{esito.titolo}"'
        domande = ", ".join(
            _ETICHETTE_ESIGENZA[esigenza] for esigenza in esito.mancanti
        )
        righe.append(f"- {etichetta}: {domande}")
    if not righe:
        return ""
    return (
        "COMPLETEZZA DELLE NOTIZIE: per ogni voce aggiungi, solo se il "
        "materiale lo consente, le informazioni mancanti indicate qui sotto. "
        "Non inventare fatti e non ripetere frasi già presenti.\n"
        + "\n".join(righe)
    )
