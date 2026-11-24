"""Genera una prova before/after del layer di revisione sull'ultima puntata."""

from __future__ import annotations

import copy
import json
import logging
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from notiziario.config import carica_impostazioni  # noqa: E402
from notiziario.revisione import rifinisci_copione  # noqa: E402


LOGGER = logging.getLogger("demo-revisione")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

NOTIZIA_1 = [
    (
        "Secondo ANSA e Repubblica, l'ex presidente francese Nicolas Sarkozy "
        "e sua moglie Carla Bruni andranno a processo nel 2027. Saranno "
        "giudicati insieme ad altre undici persone, inclusa la cosiddetta "
        "papessa dei paparazzi Mimi Marchand."
    ),
    (
        "L'inchiesta riguarda i presunti tentativi di manipolare "
        "l'intermediario Ziad Takieddine. Takieddine era un testimone chiave "
        "nello scandalo del finanziamento libico della campagna presidenziale "
        "di Sarkozy del 2007."
    ),
    (
        "L'obiettivo, secondo gli inquirenti, era ottenere la sua "
        "ritrattazione in cambio di un possibile compenso economico. Il "
        "processo è provvisoriamente fissato dal tre novembre al due dicembre "
        "duemilaventisette."
    ),
    (
        "La coppia sarà processata l'anno prossimo nell'ambito di un'inchiesta "
        "sui presunti tentativi di manipolare il faccendiere franco-libanese "
        "Ziad Takieddine, uno dei principali testimoni dell'accusa nello "
        "scandalo della campagna presidenziale del 2007 L'ex presidente della "
        "Repubblica. Nicolas Sarkozy."
    ),
]

NOTIZIA_2 = [
    (
        "Spostandoci sui mercati finanziari, le borse europee registrano un "
        "calo, con Milano che segna il ribasso maggiore. Secondo ANSA e Il "
        "Sole 24 Ore, l'indice Stoxx seicento scende dello zero virgola cinque "
        "per cento."
    ),
    (
        "Milano perde l'uno per cento, mentre Francoforte scende dello zero "
        "virgola otto per cento, Madrid dello zero virgola sette per cento e "
        "Londra dello zero virgola due per cento. Parigi è poco mossa, con un "
        "calo dello zero virgola zero uno per cento."
    ),
    (
        "I mercati si interrogano sulla tenuta degli investimenti per "
        "l'intelligenza artificiale, dopo l'iniziale euforia per il ritorno di "
        "Jensen Huang alla guida di Nvidia. Le tensioni geopolitiche, come la "
        "guerra tra Russia e Ucraina e il conflitto in Medio Oriente, "
        "continuano a influenzare i listini."
    ),
    (
        "Il comparto tecnologico è in calo del due virgola cinque per cento, e "
        "l'energia dello zero virgola sei per cento, in linea con il prezzo del "
        "petrolio. Il Wti scende dello zero virgola uno per cento a ottanta "
        "virgola zero cinque dollari, e il Brent si attesta a ottantanove "
        "virgola trentaquattro dollari."
    ),
]

CHIUSURA = "Queste erano le notizie di oggi. A domani con i principali eventi della giornata!"


def costruisci_copione() -> dict:
    paragrafi = NOTIZIA_1 + NOTIZIA_2
    return {
        "titolo_episodio": "Notiziario Radiofonico del 24 novembre 2026",
        "descrizione": "Prova di revisione delle prime due notizie.",
        "target_parole": 420,
        "testo": "\n\n".join(paragrafi + [CHIUSURA]),
        "notizie": [
            {
                "posizione": 1,
                "titolo": "Francia, Sarkozy e Carla Bruni andranno a processo per il caso dei fondi libici",
                "categoria": "Mondo",
                "fonti": ["ANSA", "Il Fatto Quotidiano", "Il Sole 24 Ore", "Repubblica"],
                "paragrafi": copy.deepcopy(NOTIZIA_1),
            },
            {
                "posizione": 2,
                "titolo": "Borsa: l'Europa negativa attende Wall Street, Milano -1%",
                "categoria": "Mondo",
                "fonti": ["ANSA", "Il Sole 24 Ore", "Repubblica"],
                "paragrafi": copy.deepcopy(NOTIZIA_2),
            },
        ],
    }


def markdown(prima: dict, dopo: dict) -> str:
    righe = ["# Prova revisione LLM — ultima puntata", ""]
    for indice, notizia in enumerate(prima["notizie"]):
        posizione = notizia["posizione"]
        righe.append(f"## PRIMA — Notizia {posizione}: {notizia['titolo']}")
        righe.append("")
        righe.extend(f"- {p}" for p in notizia["paragrafi"])
        righe.append("")
        righe.append(f"## DOPO — Notizia {posizione}: {notizia['titolo']}")
        righe.append("")
        righe.extend(f"- {p}" for p in dopo["notizie"][indice]["paragrafi"])
        righe.append("")
    revisione = dopo.get("revisione", {})
    righe.append("## Diagnostica")
    righe.append("")
    righe.append(f"- applicata: {revisione.get('applicata')}")
    righe.append(f"- modello: {revisione.get('modello', '')}")
    righe.append(f"- motivo: {revisione.get('motivo', '')}")
    righe.append(f"- parole prima: {revisione.get('parole_prima')}")
    righe.append(f"- parole dopo: {revisione.get('parole_dopo')}")
    righe.append("")
    return "\n".join(righe)


def main() -> int:
    prima = costruisci_copione()
    impostazioni = carica_impostazioni()
    dopo = rifinisci_copione(copy.deepcopy(prima), impostazioni, LOGGER)
    output = BASE / "output"
    output.mkdir(exist_ok=True)
    (output / "revisione-demo.json").write_text(
        json.dumps({"prima": prima, "dopo": dopo}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    testo = markdown(prima, dopo)
    (output / "revisione-demo.md").write_text(testo, encoding="utf-8")
    print(testo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
