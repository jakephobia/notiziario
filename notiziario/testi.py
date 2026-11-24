"""Pulizia dei testi RSS, similarità tra titoli e normalizzazione per il TTS."""

from __future__ import annotations

import html as html_module
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


MESI = (
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
)

GIORNI = (
    "lunedì",
    "martedì",
    "mercoledì",
    "giovedì",
    "venerdì",
    "sabato",
    "domenica",
)

STOPWORD = {
    "a",
    "ad",
    "al",
    "alla",
    "alle",
    "allo",
    "all",
    "agli",
    "ai",
    "anche",
    "che",
    "chi",
    "ci",
    "come",
    "con",
    "contro",
    "cui",
    "da",
    "dagli",
    "dai",
    "dal",
    "dalla",
    "dalle",
    "dallo",
    "dei",
    "del",
    "dell",
    "della",
    "delle",
    "dello",
    "di",
    "dopo",
    "e",
    "ed",
    "è",
    "era",
    "essere",
    "fra",
    "gli",
    "ha",
    "hanno",
    "i",
    "il",
    "in",
    "io",
    "la",
    "le",
    "lei",
    "lo",
    "loro",
    "lui",
    "ma",
    "mi",
    "ne",
    "nei",
    "nel",
    "nell",
    "nella",
    "nelle",
    "nello",
    "non",
    "o",
    "od",
    "on",
    "per",
    "più",
    "prima",
    "quale",
    "quella",
    "quelle",
    "quelli",
    "quello",
    "questa",
    "queste",
    "questi",
    "questo",
    "sarà",
    "si",
    "sono",
    "su",
    "sua",
    "sue",
    "sugli",
    "sui",
    "sul",
    "sull",
    "sulla",
    "sulle",
    "sullo",
    "suo",
    "suoi",
    "the",
    "tra",
    "tu",
    "un",
    "una",
    "uno",
    "vi",
    "voi",
}

_RIGHE_BOILERPLATE = (
    r"\bleggi\s+(?:tutto|tutta|la\s+notizia|di\s+più|anche|qui|il\s+seguito)\b[^\n]*",
    r"\bcontinua\s+a\s+leggere\b[^\n]*",
    r"\bscopri\s+di\s+più\b[^\n]*",
    r"\bclicca\s+qui\b[^\n]*",
    r"\bvai\s+all['’]articolo\b[^\n]*",
    r"\barticolo\s+originale\b[^\n]*",
    r"\briproduzione\s+riservata\b",
    r"©\s*[^\n]{0,160}",
    r"\bfoto\s*:[^\n.]{0,160}",
    r"\bha\s+collaborato\s+[^\n.]{0,160}",
    r"\b\d+['’]\s*di\s+lettura\b",
    r"\b\d+\s+minuti\s+di\s+lettura\b",
    r"\[\s*(?:foto|video|live|aggiornamento)\s*\]",
)

_BOILERPLATE_RE = re.compile("|".join(_RIGHE_BOILERPLATE), re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b\S+@\S+\.\S+\b")
_SPAZI_RE = re.compile(r"[ \t\u00a0\u200b\ufeff]+")
_RIGA_VUOTA_RE = re.compile(r"\n{3,}")
_HTML_RE = re.compile(r"<[a-zA-Z!/][^>]*>")

# Token di classi e id che indicano contenitori pubblicitari. Il confronto è
# per token intero: "ad-container" sì, "header", "read-more", "loading" no.
_TOKENS_PUBBLICITARI = (
    "advertisement",
    "advertising",
    "sponsorizzato",
    "affiliazione",
    "promozionale",
    "google-ads",
    "googleads",
    "sponsored",
    "promozione",
    "advertorial",
    "advert",
    "sponsor",
    "adsense",
    "taboola",
    "outbrain",
    "affiliate",
    "banner",
    "promo",
    "adv",
    "ads",
    "dfp",
    "ad",
)
_TOKEN_PUBBLICITARIO_RE = re.compile(
    r"(?<![a-z0-9])(?:"
    + "|".join(re.escape(token) for token in _TOKENS_PUBBLICITARI)
    + r")(?![a-z0-9])",
    re.IGNORECASE,
)

_ETICHETTE_PUB = re.compile(
    r"^(?:pubblicità|pubblicita|adv|advertisement|advertorial|sponsor|"
    r"sponsorizzato|contenuto\s+sponsorizzato|articolo\s+sponsorizzato)$",
    re.IGNORECASE,
)
_PROMOSSO_DA_RE = re.compile(r"^promosso\s+da\b", re.IGNORECASE)
_COLLABORAZIONE_RE = re.compile(r"^in\s+collaborazione\s+con\b", re.IGNORECASE)
_CONTINUA_PUB_RE = re.compile(
    r"\b(?:l['’]articolo\s+)?continua\s+(?:a\s+leggere\s+)?(?:dopo|sotto)\s+"
    r"(?:la\s+|il\s+|l['’])?"
    r"(?:pubblicità|pubblicita|video|articolo|galleria|gallery|immagini|contenuto)\b",
    re.IGNORECASE,
)
_RIGHE_PUB = (
    r"\bcontenut[oi]\s+sponsorizzat[oi]\b",
    r"\barticol[oi]\s+sponsorizzat[oi]\b",
    r"\badvertorial\b",
    r"\blink\s+di\s+affiliazione\b",
    r"\blink\s+affiliat[oi]\b",
    r"\bse\s+acquisti\s+tramite\b",
    r"\bpotremmo\s+ricevere\s+una\s+commissione\b",
    r"\bacquista\s+ora\b",
    r"\bcompra\s+ora\b",
    r"\bscopri\s+l['’]offerta\b",
    r"\bapprofitta\s+dell['’]offerta\b",
    # Queste formule restano pubblicitarie solo quando aprono la frase:
    # "Gli abbonati a Netflix..." o "Il governo taglia gli sconti del 20 per
    # cento" sono notizie e non vanno scartate.
    r"^offerta\s+limitata\b",
    r"\bcodice\s+sconto\b",
    r"^sconti?\s+del\s+\d+(?:[.,]\d+)?\s*(?:%|per\s+cento)\b",
    r"\bspedizione\s+gratuita\b",
    r"\bprenota\s+ora\b",
    r"\biscriviti\s+alla\s+newsletter\b",
    r"^abbonati\s+a\b",
    r"\bsostieni\s+il\s+nostro\s+giornalismo\b",
)
_FRASI_PUB_RE = re.compile("|".join(_RIGHE_PUB), re.IGNORECASE)


def rimuovi_elementi_pubblicitari(soup: BeautifulSoup) -> None:
    """Decompone i tag con classi o id che indicano pubblicità."""
    for tag in list(soup.find_all(True)):
        if getattr(tag, "decomposed", False):
            continue
        valori: list[str] = []
        classi = tag.get("class")
        if isinstance(classi, (list, tuple)):
            valori.extend(str(classe) for classe in classi)
        elif classi:
            valori.append(str(classi))
        identificativo = tag.get("id")
        if identificativo:
            valori.append(str(identificativo))
        if any(_TOKEN_PUBBLICITARIO_RE.search(valore) for valore in valori):
            tag.decompose()


def _e_etichetta_pubblicitaria(blocco: str) -> bool:
    testo = _SPAZI_RE.sub(" ", str(blocco or "")).strip()
    if not testo:
        return False
    nucleo = testo.strip(" \t\r\n.:;!?-–—|")
    if _ETICHETTE_PUB.match(nucleo):
        return True
    if conta_parole(nucleo) <= 8 and (
        _PROMOSSO_DA_RE.match(nucleo) or _COLLABORAZIONE_RE.match(nucleo)
    ):
        return True
    return False


def _e_riga_pubblicitaria(riga: str) -> bool:
    """Riga che *è* un'etichetta o un invito a continuare dopo l'annuncio."""
    if _e_etichetta_pubblicitaria(riga):
        return True
    nucleo = _SPAZI_RE.sub(" ", str(riga or "")).strip(" \t\r\n.:;!?-–—|")
    return bool(_CONTINUA_PUB_RE.fullmatch(nucleo))


def _blocco_pubblicitario_da_saltare(blocco: str) -> bool:
    """Blocco brevissimo dopo un'etichetta ad: CTA, prezzo o prodotto."""
    testo = str(blocco or "").strip()
    if not testo or conta_parole(testo) > 45:
        return False
    basso = testo.casefold()
    indicatori = (
        "offert",
        "sconto",
        "prodotto",
        "prodotta",
        "acquista",
        "compra",
        "ordina",
        "spedizione",
        "gratis",
        "gratuit",
        "codice",
        "promo",
        "abbonat",
        "iscriviti",
        "clicca",
        "visita",
        "scopri",
    )
    if any(indicatore in basso for indicatore in indicatori):
        return True
    # Prezzi espliciti sì; "il prezzo del gas aumenta" o "l'euro si rafforza"
    # sono notizie e non vanno scartati.
    if re.search(r"\d+(?:[.,]\d+)?\s*(?:€|euro|dollari|dollaro)", basso):
        return True
    return bool(re.search(r"\bprezzo\b\s*[:=]?\s*\d", basso))


def rimuovi_pubblicita(testo: str) -> str:
    """Toglie etichette, disclosure e inviti all'acquisto da testo semplice.

    Lavora su paragrafi, righe e frasi. Una frase che parla di pubblicità in
    modo informativo (per esempio "La pubblicità online cresce del 5 per
    cento") resta: vengono rimossi solo etichette isolate e formule esplicite.
    """
    if not testo:
        return ""
    normalizzato = str(testo).replace("\r\n", "\n").replace("\r", "\n")
    risultato: list[str] = []
    salta_successivo = False
    for paragrafo in re.split(r"\n\s*\n", normalizzato):
        righe = [riga.strip() for riga in paragrafo.split("\n") if riga.strip()]
        if not righe:
            continue
        blocco_etichetta = all(_e_riga_pubblicitaria(riga) for riga in righe)
        tenute: list[str] = []
        for riga in righe:
            if _e_riga_pubblicitaria(riga):
                continue
            frasi = [
                frase
                for frase in estrai_frasi(riga)
                if not _e_etichetta_pubblicitaria(frase)
                and not _CONTINUA_PUB_RE.search(frase)
                and not _FRASI_PUB_RE.search(frase)
            ]
            if frasi:
                tenute.append(" ".join(frasi))
        nuovo = " ".join(tenute).strip()
        if salta_successivo:
            salta_successivo = False
            if _blocco_pubblicitario_da_saltare(nuovo):
                continue
        if not nuovo:
            if blocco_etichetta:
                salta_successivo = True
            continue
        risultato.append(nuovo)
    return "\n\n".join(risultato).strip()


def pulisci_html(valore: str | None, *, rimuovi_titoli: bool = False) -> str:
    """Toglie tag, script e contenitori pubblicitari, mantenendo il testo."""
    if not valore:
        return ""
    soup = BeautifulSoup(str(valore), "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "form"]):
        tag.decompose()
    if rimuovi_titoli:
        for tag in soup(["h1", "h2", "h3", "h4", "h5", "h6"]):
            tag.decompose()
    rimuovi_elementi_pubblicitari(soup)
    testo = soup.get_text(" ")
    testo = html_module.unescape(testo)
    return _SPAZI_RE.sub(" ", testo).strip()


def pulisci_testo(valore: str | None) -> str:
    """Pulisce un summary RSS: HTML, pubblicità, boilerplate, link e spazi."""
    if not valore:
        return ""
    grezzo = str(valore)
    if _HTML_RE.search(grezzo):
        testo = pulisci_html(grezzo, rimuovi_titoli=True)
        testo = rimuovi_pubblicita(testo)
    else:
        testo = rimuovi_pubblicita(grezzo)
        testo = pulisci_html(testo, rimuovi_titoli=True)
        testo = rimuovi_pubblicita(testo)
    testo = _URL_RE.sub(" ", testo)
    testo = _EMAIL_RE.sub(" ", testo)
    testo = _BOILERPLATE_RE.sub(" ", testo)
    testo = testo.replace("\u00ad", "").replace("\u200b", "")
    testo = re.sub(r"\[\s*\.\.\.\s*\]", " ", testo)
    testo = re.sub(r"\.{3,}", ".", testo)
    testo = _SPAZI_RE.sub(" ", testo)
    testo = re.sub(r"\s+([,.;:!?])", r"\1", testo)
    testo = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", testo)
    testo = re.sub(r"\s*\n\s*", " ", testo)
    return testo.strip(" \t\n\r-–—|")


def pulisci_titolo(valore: str | None) -> str:
    """Titolo leggibile, senza HTML, markdown o suffisso della testata."""
    if not valore:
        return ""
    testo = pulisci_html(valore)
    testo = re.sub(r"[*_#`~]+", " ", testo)
    testo = re.sub(
        r"\s*[-–—|]\s*(?:ANSA|Repubblica|Corriere(?: della Sera)?|"
        r"Il Post|Il Sole 24 Ore|HDblog)(?:\.it)?\s*$",
        "",
        testo,
        flags=re.IGNORECASE,
    )
    testo = _SPAZI_RE.sub(" ", testo).strip(" \t\n\r-–—|")
    if len(testo) > 300:
        testo = tronca_a_frase(testo, 300)
    return testo


def tronca_a_frase(testo: str, max_caratteri: int) -> str:
    """Tronca a fine frase (o a fine parola) senza lasciare frasi monche."""
    testo = (testo or "").strip()
    if len(testo) <= max_caratteri:
        return testo
    taglio = testo[:max_caratteri]
    confini = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", taglio)]
    if confini:
        taglio = taglio[: confini[-1]]
    else:
        spazio = taglio.rfind(" ")
        if spazio > max_caratteri * 0.5:
            taglio = taglio[:spazio]
        taglio = taglio.rstrip(" ,;:-–—")
        if not taglio.endswith((".", "!", "?")):
            taglio += "."
    return taglio.strip()


def estrai_frasi(testo: str) -> list[str]:
    """Divide in frasi mantenendo la punteggiatura finale."""
    testo = re.sub(r"\s+", " ", (testo or "").strip())
    if not testo:
        return []
    parti = re.split(r"(?<=[.!?])\s+", testo)
    return [p.strip() for p in parti if p.strip()]


def conta_parole(testo: str) -> int:
    return len(re.findall(r"[\wÀ-ÖØ-öø-ÿ]+(?:['’][\wÀ-ÖØ-öø-ÿ]+)?", testo or ""))


def _senza_accenti(testo: str) -> str:
    normale = unicodedata.normalize("NFKD", testo or "")
    return "".join(ch for ch in normale if not unicodedata.combining(ch))


def normalizza_titolo(titolo: str) -> str:
    """Minuscole, senza accenti, numeri, punteggiatura e stopword minime."""
    testo = _senza_accenti(titolo).casefold()
    testo = re.sub(r"[’']", " ", testo)
    testo = re.sub(r"\b\d+\b", " ", testo)
    testo = re.sub(r"[^a-z\s]", " ", testo)
    parole = [
        parola
        for parola in testo.split()
        if len(parola) >= 3 and parola not in STOPWORD
    ]
    return " ".join(parole)


def token_significativi(titolo: str) -> set[str]:
    normalizzato = normalizza_titolo(titolo)
    return set(normalizzato.split()) if normalizzato else set()


_PAROLA_NOME_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
_APOSTROFO_RE = re.compile(r"['’]")

PARTICELLE_NOME = frozenset(
    {
        "de",
        "di",
        "da",
        "del",
        "della",
        "dello",
        "dei",
        "degli",
        "delle",
        "van",
        "von",
        "bin",
        "al",
        "el",
        "la",
        "le",
        "du",
        "des",
        "d",
        "l",
        "il",
        "lo",
        "i",
        "gli",
        "un",
        "una",
        "uno",
    }
)


def sequenza_significativa(nome: tuple[str, ...]) -> tuple[str, ...]:
    """Token del nome senza particelle e articoli."""
    return tuple(token for token in nome if token not in PARTICELLE_NOME)


def estrai_nomi_propri(testo: str) -> set[tuple[str, ...]]:
    """Nomi di almeno due parole con iniziale maiuscola, normalizzati.

    Apostrofi e punteggiatura spezzano i token; numeri e simboli interrompono
    la sequenza. I token sono minuscoli e senza accenti.
    """
    testo = str(testo or "")
    if not testo:
        return set()

    nomi: set[tuple[str, ...]] = set()
    corrente: list[str] = []
    fine_precedente: int | None = None

    def chiudi() -> None:
        nonlocal corrente
        if len(corrente) >= 2:
            nomi.add(tuple(corrente))
        corrente = []

    for trovato in _PAROLA_NOME_RE.finditer(testo):
        if fine_precedente is not None and testo[fine_precedente : trovato.start()].strip():
            chiudi()
        fine_precedente = trovato.end()
        for pezzo in _APOSTROFO_RE.split(trovato.group(0)):
            if not pezzo:
                continue
            if pezzo[0].isupper():
                corrente.append(_senza_accenti(pezzo).casefold())
            else:
                chiudi()
    chiudi()
    return nomi


def stesso_nome(primo: tuple[str, ...], secondo: tuple[str, ...]) -> bool:
    """Vero se le sequenze senza particelle coincidono o una è suffisso.

    "De Gennaro" (``gennaro``) combacia con "Gianni De Gennaro"
    (``gianni``, ``gennaro``). Non combacia invece con "Gennaro De Luca"
    (``gennaro``, ``luca``), perché ``gennaro`` è un prefisso, non un
    suffisso. Così due persone diverse con lo stesso cognome non si
    confondono, mentre il cognome citato da solo resta riconoscibile.
    """
    sequenza_primo = sequenza_significativa(tuple(primo))
    sequenza_secondo = sequenza_significativa(tuple(secondo))
    if not sequenza_primo or not sequenza_secondo:
        return False
    if sequenza_primo == sequenza_secondo:
        return True
    if len(sequenza_primo) <= len(sequenza_secondo):
        corta, lunga = sequenza_primo, sequenza_secondo
    else:
        corta, lunga = sequenza_secondo, sequenza_primo
    return len(corta) < len(lunga) and lunga[-len(corta) :] == corta


def normalizza_dedup(testo: str) -> str:
    """Minuscole, senza accenti, punteggiatura o spazi multipli."""
    testo = _senza_accenti(str(testo or "")).casefold()
    testo = re.sub(r"[^a-z0-9\s]", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()


_ATTRIBUZIONE_RE = re.compile(
    r"^(?:come riporta|secondo|lo riporta|ne parla|dalla ricostruzione di)\s+[^,]+,\s*",
    re.IGNORECASE,
)


def _senza_attribuzione(testo: str) -> str:
    return _ATTRIBUZIONE_RE.sub("", str(testo or ""), count=1)


def _normalizza_confronto(testo: str) -> str:
    return normalizza_dedup(_senza_attribuzione(testo))


def similarita_testi(a: str, b: str, soglia: float = 0.85) -> float:
    """Similarità prudente per paragrafi/frasi: sequenza + token comuni."""
    na, nb = _normalizza_confronto(a), _normalizza_confronto(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    sequenza = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    unione = ta | tb
    jaccard = len(ta & tb) / len(unione) if unione else 0.0
    return 0.55 * sequenza + 0.45 * jaccard


def deduplica_unita(unita: list[str], soglia: float = 0.85) -> list[str]:
    """Mantiene la prima occorrenza e scarta unità quasi identiche."""
    tenute: list[str] = []
    for voce in unita:
        testo = str(voce or "").strip()
        if not testo:
            continue
        if any(similarita_testi(testo, altra, soglia) >= soglia for altra in tenute):
            continue
        tenute.append(testo)
    return tenute


def deduplica_frasi(testo: str, soglia: float = 0.85) -> str:
    """Deduplica le frasi mantenendo l'ordine e la prima occorrenza."""
    return " ".join(deduplica_unita(estrai_frasi(testo), soglia)).strip()


def deduplica_paragrafi(testo: str, soglia: float = 0.85) -> str:
    """Deduplica paragrafi e frasi, anche se la ripetizione è in un altro paragrafo."""
    paragrafi = [
        p.strip() for p in re.split(r"\n\s*\n", testo or "") if p.strip()
    ]
    frasi_viste: list[str] = []
    puliti: list[str] = []
    for paragrafo in paragrafi:
        frasi: list[str] = []
        for frase in estrai_frasi(paragrafo):
            if any(similarita_testi(frase, vista, soglia) >= soglia for vista in frasi_viste):
                continue
            frasi_viste.append(frase)
            frasi.append(frase)
        if frasi:
            puliti.append(" ".join(frasi))
    return "\n\n".join(deduplica_unita(puliti, soglia))


def rimuovi_titoli_ripetuti(testo: str, titoli: list[str]) -> str:
    """Rimuove le occorrenze successive dello stesso titolo, lasciando la prima."""
    risultato = testo or ""
    for titolo in sorted({t.strip() for t in titoli if t and len(t.split()) >= 3}, key=len, reverse=True):
        pattern = re.compile(re.escape(titolo), re.IGNORECASE)
        occorrenze = list(pattern.finditer(risultato))
        for trovata in reversed(occorrenze[1:]):
            risultato = risultato[: trovata.start()] + risultato[trovata.end() :]
    risultato = re.sub(r"[ \t]{2,}", " ", risultato)
    risultato = re.sub(r"\s+([,.;:!?])", r"\1", risultato)
    risultato = re.sub(r"([,;:])\s*[,;:]+", r"\1", risultato)
    risultato = re.sub(r",\s*([.!?])", r"\1", risultato)
    risultato = re.sub(r"\n{3,}", "\n\n", risultato)
    return risultato.strip(" \t\n,;:")


def _chiave_senza_titoli(testo: str, titoli: list[str]) -> str:
    chiave = normalizza_dedup(_senza_attribuzione(testo))
    for titolo in titoli:
        norm = normalizza_dedup(titolo)
        if len(norm.split()) >= 3:
            chiave = chiave.replace(norm, " ")
    return re.sub(r"\s+", " ", chiave).strip()


def deduplica_testo_finale(testo: str, titoli: list[str] | None = None, soglia: float = 0.85) -> str:
    """Deduplica il copione mantenendo ordine, incipit e outro."""
    if titoli:
        testo = rimuovi_titoli_ripetuti(testo, titoli)
    paragrafi = [
        p.strip() for p in re.split(r"\n\s*\n", testo or "") if p.strip()
    ]
    chiavi_viste: list[str] = []
    paragrafi_tenuti: list[str] = []
    for paragrafo in paragrafi:
        frasi_tenute: list[str] = []
        for frase in estrai_frasi(paragrafo):
            chiave = _chiave_senza_titoli(frase, titoli or [])
            if any(similarita_testi(chiave, vista, soglia) >= soglia for vista in chiavi_viste):
                continue
            chiavi_viste.append(chiave)
            frasi_tenute.append(frase)
        if frasi_tenute:
            paragrafi_tenuti.append(" ".join(frasi_tenute))
    return "\n\n".join(paragrafi_tenuti).strip()

def similarita_normalizzate(a: str, b: str) -> float:
    """Similarità combinata su titoli già normalizzati."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    sequenza = SequenceMatcher(None, a, b).ratio()
    insieme_a, insieme_b = set(a.split()), set(b.split())
    unione = insieme_a | insieme_b
    jaccard = len(insieme_a & insieme_b) / len(unione) if unione else 0.0
    return 0.55 * sequenza + 0.45 * jaccard


def similarita_titoli(primo: str, secondo: str) -> float:
    """Similarità combinata: 55% SequenceMatcher, 45% Jaccard sui token."""
    return similarita_normalizzate(
        normalizza_titolo(primo), normalizza_titolo(secondo)
    )


def _data_italiana(giorno: int, mese: int, anno: int) -> str | None:
    if not (1 <= mese <= 12 and 1 <= giorno <= 31):
        return None
    return f"{giorno} {MESI[mese - 1]} {anno}"


def _converti_data_italiana(match: re.Match[str]) -> str:
    giorno, mese, anno = (int(match.group(i)) for i in (1, 2, 3))
    convertita = _data_italiana(giorno, mese, anno)
    return convertita or match.group(0)


def _converti_data_iso(match: re.Match[str]) -> str:
    anno, mese, giorno = (int(match.group(i)) for i in (1, 2, 3))
    convertita = _data_italiana(giorno, mese, anno)
    return convertita or match.group(0)


def _migliaia(match: re.Match[str]) -> str:
    return match.group(0).replace(".", "")


def normalizza_per_tts(testo: str) -> str:
    """Rende il testo adatto alla lettura ad alta voce.

    Non riscrive i fatti: cambia solo la forma di date, percentuali, simboli,
    parentesi, markdown e separatori delle migliaia.
    """
    if not testo:
        return ""
    t = html_module.unescape(str(testo))
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")

    # URL ed email non vanno letti.
    t = _URL_RE.sub(" ", t)
    t = _EMAIL_RE.sub(" ", t)

    # Date prima dei separatori delle migliaia.
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", _converti_data_italiana, t)
    t = re.sub(r"\b(\d{1,2})[-.](\d{1,2})[-.](\d{4})\b", _converti_data_italiana, t)
    t = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", _converti_data_iso, t)

    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", r"\1 per cento", t)
    t = t.replace("€", " euro ").replace("$", " dollari ").replace("£", " sterline ")
    t = re.sub(r"\b\d{1,3}(?:\.\d{3})+\b", _migliaia, t)

    # Markdown ed elenchi.
    t = re.sub(r"[*_#`~]+", " ", t)
    t = re.sub(r"^\s*[-–—•]\s+", "", t, flags=re.MULTILINE)
    t = re.sub(r"^\s*>\s*", "", t, flags=re.MULTILINE)

    # Parentesi e virgolette: meglio una pausa che una lettura strana.
    t = t.replace("(", ", ").replace(")", ", ")
    t = t.replace("[", ", ").replace("]", ", ")
    for carattere in ("\u201c", "\u201d", "\u201e", "\u00ab", "\u00bb", '"'):
        t = t.replace(carattere, "")
    t = t.replace("\u2019", "'")

    # Simboli e punteggiatura.
    t = t.replace("&", " e ")
    t = t.replace("+", " più ")
    t = t.replace("=", " uguale a ")
    t = t.replace("@", " chiocciola ")
    t = t.replace("§", " paragrafo ")
    t = t.replace("°", " gradi ")
    t = t.replace("→", " verso ")
    t = t.replace("≈", " circa ").replace("~", " circa ")
    t = t.replace("<", " minore di ").replace(">", " maggiore di ")
    t = t.replace("±", " più o meno ").replace("×", " per ").replace("÷", " diviso ")
    t = t.replace("‰", " per mille ")
    t = t.replace("•", " ")
    t = t.replace("|", " ").replace("\\", " ").replace("{", " ").replace("}", " ")
    t = re.sub(r"[®™©]", "", t)
    t = t.replace("…", ".")
    t = t.replace(";", ".")
    t = t.replace("/", " ")
    t = re.sub(r":(?!\d)", ",", t)
    t = t.replace("–", ",").replace("—", ",")
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", " ", t)
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", t)

    # Spazi e punteggiatura ripetuta.
    t = re.sub(r"\.{2,}", ".", t)
    t = re.sub(r"([,.;!?])(?:\s*[,.;!?])+", r"\1", t)
    t = re.sub(r"\s+([,.;!?])", r"\1", t)
    t = re.sub(r"([,.;!?])(?=[A-Za-zÀ-ÖØ-öø-ÿ])", r"\1 ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = t.strip(" \t\n,;:")
    if t and t[-1] not in ".!?":
        t += "."
    return t


def spezza_frasi_lunghe(testo: str, max_parole: int = 35) -> str:
    """Spezza le frasi troppo lunghe a una virgola o a un confine di parole."""
    if not testo:
        return ""
    paragrafi: list[str] = []
    for paragrafo in testo.split("\n"):
        if not paragrafo.strip():
            paragrafi.append("")
            continue
        nuove: list[str] = []
        for frase in estrai_frasi(paragrafo):
            parole = frase.split()
            if len(parole) <= max_parole:
                nuove.append(frase)
                continue
            pezzi: list[str] = []
            resto = parole
            while len(resto) > max_parole:
                punto = None
                for indice in range(max_parole, max(7, int(max_parole * 0.55)) - 1, -1):
                    if resto[indice - 1].endswith((",", ";", ":")):
                        punto = indice
                        break
                if punto is None:
                    punto = max_parole
                pezzo = " ".join(resto[:punto]).rstrip(" ,;:")
                if pezzo and pezzo[-1] not in ".!?":
                    pezzo += "."
                pezzi.append(pezzo)
                resto = resto[punto:]
            if resto:
                ultimo = " ".join(resto).strip()
                if ultimo:
                    if ultimo[0].islower():
                        ultimo = ultimo[0].upper() + ultimo[1:]
                    if ultimo[-1] not in ".!?":
                        ultimo += "."
                    pezzi.append(ultimo)
            for pezzo in pezzi:
                if pezzo and pezzo[0].islower():
                    pezzo = pezzo[0].upper() + pezzo[1:]
                nuove.append(pezzo)
        paragrafi.append(" ".join(nuove))
    return "\n".join(paragrafi)


def normalizza_mesi(testo: str) -> str:
    """Scrive i nomi dei mesi in minuscolo (22 Novembre -> 22 novembre)."""
    risultato = testo or ""
    for mese in MESI:
        risultato = re.sub(
            rf"\b{re.escape(mese)}\b",
            mese,
            risultato,
            flags=re.IGNORECASE,
        )
    return risultato

def data_in_italiano(data: datetime, con_giorno: bool = True) -> str:
    base = f"{data.day} {MESI[data.month - 1]} {data.year}"
    if con_giorno:
        return f"{GIORNI[data.weekday()]} {base}"
    return base


def elenco_naturale(elementi: list[str]) -> str:
    elementi = [e for e in elementi if e]
    if not elementi:
        return ""
    if len(elementi) == 1:
        return elementi[0]
    if len(elementi) == 2:
        return f"{elementi[0]} e {elementi[1]}"
    return f"{', '.join(elementi[:-1])} e {elementi[-1]}"


def formatta_durata(secondi: float | int | None) -> str:
    """Formato iTunes HH:MM:SS."""
    if secondi is None:
        return "00:00:00"
    totale = max(0, int(round(float(secondi))))
    ore, resto = divmod(totale, 3600)
    minuti, sec = divmod(resto, 60)
    return f"{ore:02d}:{minuti:02d}:{sec:02d}"


def durata_umana(secondi: float | int | None) -> str:
    if secondi is None:
        return "durata sconosciuta"
    totale = max(0, int(round(float(secondi))))
    minuti, sec = divmod(totale, 60)
    return f"{minuti} min {sec} s"


# ---------------------------------------------------------------------------
# Categoria dedotta dall'URL e contenuti promozionali.
# ---------------------------------------------------------------------------

# Marcatori di categoria nel path dell'articolo. L'ordine conta quando un
# path contiene più marcatori: vince il primo riconosciuto.
_CATEGORIE_DA_URL: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sport", ("sport",)),
    ("cultura", ("cultura", "spettacoli", "spettacolo")),
    ("economia", ("economia", "economia-e-finanza", "finanza", "mercati")),
    ("tecnologia", ("tecnologia", "tech")),
    ("scienza-salute", ("salute", "scienze", "scienza", "medicina")),
    ("ambiente", ("ambiente", "green", "clima")),
    ("mondo", ("mondo", "esteri", "world")),
    ("italia", ("italia", "politica", "cronaca")),
)


def categoria_da_url(url: str) -> str | None:
    """Deduce la categoria dal path dell'articolo; None se non riconosce.

    Guarda solo i segmenti interi del path: ``/sport/`` sì,
    ``/sport-e-business/`` no. Un articolo ``/cultura/...`` pubblicato sul
    feed generale ANSA viene quindi ricondotto a ``cultura``.
    """
    if not url:
        return None
    try:
        path = urlsplit(str(url)).path.casefold()
    except ValueError:
        return None
    segmenti = {segmento for segmento in path.split("/") if segmento}
    for categoria, marcatori in _CATEGORIE_DA_URL:
        if segmenti.intersection(marcatori):
            return categoria
    return None


# Segnali forti: da soli bastano a scartare l'articolo. I marcatori URL
# valgono solo come segmento intero del path, non come sottostringa.
_PROMO_PATH_FORTI = frozenset(
    {
        "advertorial",
        "comunicati-stampa",
        "press-release",
        "sponsor",
        "promo",
        "partner",
    }
)

_PROMO_FRASI_FORTI = (
    r"\bcontenut[oi]\s+sponsorizzat[oi]\b",
    r"\barticol[oi]\s+sponsorizzat[oi]\b",
    r"\badvertorial\b",
    r"\bcomunicato\s+stampa\b",
    r"\bufficio\s+stampa\b",
    r"\bpartner\s+ufficiale\b",
    r"\bleader\s+del\s+settore\b",
    r"\beccellenza\s+italiana\b",
    r"\bsoluzione\s+innovativa\b",
)
_PROMO_FRASI_DEBOLI = (r"\bin\s+collaborazione\s+con\b",)
_PROMO_FRASI_FORTI_RE = re.compile("|".join(_PROMO_FRASI_FORTI), re.IGNORECASE)

_PROMO_TITOLO_FORTI = (
    r"\bsponsorizzat[oi]\b",
    r"\badvertorial\b",
    r"\bcodice\s+sconto\b",
    r"\bporta\s+le\s+aziende\b",
    r"\bpresenta\s+il\s+nuovo\b",
    r"\blancia\s+il\s+nuovo\b",
)
_PROMO_TITOLO_DEBOLI = (
    r"\bpromozione\b",
    r"\bsconto\b",
    # "offerta" singolare: "offerte di lavoro" non è promozionale.
    r"\bofferta\b",
    r"\bacquista\b",
    r"\babbonati\b",
    r"\bconcorso\b",
    r"\bregalo\b",
    r"\bgadget\b",
)
_PROMO_TITOLO_FORTI_RE = re.compile("|".join(_PROMO_TITOLO_FORTI), re.IGNORECASE)
_PROMO_TITOLO_DEBOLI_RES = tuple(
    re.compile(pattern, re.IGNORECASE) for pattern in _PROMO_TITOLO_DEBOLI
)
_PROMO_FRASI_DEBOLI_RES = tuple(
    re.compile(pattern, re.IGNORECASE) for pattern in _PROMO_FRASI_DEBOLI
)

# Parole che, insieme al nome della testata nel titolo, indicano
# autopromozione (anniversari, storie della testata, festeggiamenti).
_AUTOPROMO_PAROLE_RE = re.compile(
    r"\b(?:anni|anniversari\w*|compleann\w*|stori[ae]|si\s+racconta|"
    r"ideator[ei]|fest[ae]|celebr\w*|festeggi\w*)\b",
    re.IGNORECASE,
)

# Parole troppo comuni per valere come "token forte" del nome della testata.
_TOKEN_FONTE_GENERICI = frozenset(
    {
        "il",
        "lo",
        "la",
        "i",
        "gli",
        "le",
        "di",
        "del",
        "della",
        "dei",
        "delle",
        "notizie",
        "news",
        "post",
        "sole",
        "ore",
        "oggi",
        "domani",
        "italia",
        "quotidiano",
        "giornale",
        "web",
        "online",
        "tv",
        "radio",
        "magazine",
        "open",
        "left",
        "fatto",
        "buone",
    }
)
_ARTICOLI_INIZIALI = frozenset({"il", "lo", "la", "i", "gli", "le"})


def _normalizza_promo(testo: str) -> str:
    """Minuscolo, senza accenti, con la punteggiatura ridotta a spazi."""
    normalizzato = _senza_accenti(str(testo or "")).casefold()
    normalizzato = re.sub(r"[^a-z0-9]+", " ", normalizzato)
    return re.sub(r"\s+", " ", normalizzato).strip()


def _frasi_fonte(fonte: str) -> list[str]:
    """Nomi con cui una testata può comparire nel titolo.

    Il nome intero vale sempre; se inizia con un articolo, vale anche la
    variante senza articolo ("Il Sole 24 Ore" -> "sole 24 ore"). I nomi di
    una sola parola valgono solo se distintivi: evita che "post" faccia
    scattare l'autopromozione su un titolo qualsiasi.
    """
    nome = _normalizza_promo(fonte)
    if not nome:
        return []
    parole = nome.split()
    if len(parole) == 1:
        if len(nome) >= 4 and nome not in _TOKEN_FONTE_GENERICI:
            return [nome]
        return []
    frasi = [nome]
    if len(parole) > 2 and parole[0] in _ARTICOLI_INIZIALI:
        frasi.append(" ".join(parole[1:]))
    return frasi


def _titolo_autopromozionale(titolo: str, fonte: str) -> bool:
    """Nome della testata + parola da anniversario/autopresentazione."""
    if not titolo or not fonte:
        return False
    titolo_norm = _normalizza_promo(titolo)
    if not _AUTOPROMO_PAROLE_RE.search(titolo_norm):
        return False
    riempito = f" {titolo_norm} "
    return any(f" {frase} " in riempito for frase in _frasi_fonte(fonte))


def e_promozionale(
    titolo: str,
    sommario: str = "",
    contenuto: str = "",
    fonte: str = "",
    link: str = "",
) -> bool:
    """Vero per contenuti promozionali, PR o autopromozionali.

    Regola prudente: un segnale forte basta, altrimenti servono almeno due
    segnali deboli. Una singola parola ambigua ("offerta", "sconto",
    "promozione") non esclude la notizia.
    """
    titolo = str(titolo or "")
    titolo_norm = _senza_accenti(titolo).casefold()
    testo_norm = _senza_accenti(
        " ".join(str(parte or "") for parte in (titolo, sommario, contenuto))
    ).casefold()

    segmenti: set[str] = set()
    if link:
        try:
            path = urlsplit(str(link)).path.casefold()
        except ValueError:
            path = ""
        segmenti = {segmento for segmento in path.split("/") if segmento}
    if segmenti & _PROMO_PATH_FORTI:
        return True

    deboli = 0
    if _PROMO_FRASI_FORTI_RE.search(testo_norm):
        return True
    deboli += sum(
        1 for regex in _PROMO_FRASI_DEBOLI_RES if regex.search(testo_norm)
    )
    if _PROMO_TITOLO_FORTI_RE.search(titolo_norm):
        return True
    deboli += sum(
        1 for regex in _PROMO_TITOLO_DEBOLI_RES if regex.search(titolo_norm)
    )
    if _titolo_autopromozionale(titolo, fonte):
        return True
    return deboli >= 2
