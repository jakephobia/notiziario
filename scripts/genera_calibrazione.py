"""Genera un tool HTML di calibrazione con 150 articoli da tutte le fonti."""

from __future__ import annotations

import html as html_lib
import json
import logging
import random
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from notiziario.config import carica_fonti_tutte  # noqa: E402
from notiziario.fetch import fetch_fonte  # noqa: E402
USCITA_CONTENUTO = BASE / "docs" / "calibrazione-contenuto.html"
USCITA_INTERESSE = BASE / "docs" / "calibrazione-interesse.html"
USCITA_INDICE = BASE / "docs" / "calibrazione.html"
DATI = BASE / "output" / "calibrazione-articoli.json"
OBIETTIVO = 150
MINIMO_PER_FONTE = 3
ORE = 24 * 365 * 10
LOGGER = logging.getLogger("calibrazione")

CATEGORIE = [
    ("italia", "Italia"),
    ("mondo", "Mondo"),
    ("economia", "Economia"),
    ("tecnologia", "Tecnologia"),
    ("scienza-salute", "Scienza e salute"),
    ("cultura", "Cultura"),
    ("sport", "Sport"),
    ("ambiente", "Ambiente"),
    ("buone-notizie", "Buone notizie"),
    ("cronaca", "Cronaca"),
    ("cronaca-nera", "Cronaca nera"),
    ("approfondimento", "Approfondimento"),
    ("promozione", "Promozione / PR"),
    ("altro", "Altro"),
]
INTERESSI = [("zero", "Zero"), ("poco", "Poco"), ("normale", "Normale"), ("tanto", "Tanto")]
NOTIZIABILITA = [(str(i), str(i)) for i in range(1, 6)]


def _fonti_uniche() -> list:
    viste: set[str] = set()
    fonti = []
    for fonte in carica_fonti_tutte():
        if fonte.url in viste:
            continue
        viste.add(fonte.url)
        fonti.append(fonte)
    return fonti


def _scarica_tutte(fonti: list) -> list:
    """Scarica ogni fonte senza i filtri di categoria/promozione della pipeline."""
    articoli = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(
                fetch_fonte,
                fonte,
                ORE,
                15,
                1,
                None,
                LOGGER,
            ): fonte
            for fonte in fonti
        }
        for future in as_completed(futures):
            try:
                lista, _esito = future.result()
            except Exception as exc:  # pragma: no cover - difesa
                LOGGER.warning("Fonte fallita: %s", type(exc).__name__)
                continue
            articoli.extend(lista)
    visti: set[str] = set()
    unici = []
    for articolo in articoli:
        if articolo.id in visti:
            continue
        visti.add(articolo.id)
        unici.append(articolo)
    return unici


def _scegli_articoli(articoli: list) -> list:
    per_fonte: dict[str, list] = defaultdict(list)
    for articolo in articoli:
        if not articolo.titolo.strip():
            continue
        per_fonte[articolo.feed_url or articolo.fonte].append(articolo)

    fonti_ok = [
        (feed, lista)
        for feed, lista in per_fonte.items()
        if len(lista) >= MINIMO_PER_FONTE
    ]
    random.Random(20261126).shuffle(fonti_ok)

    scelti = []
    usati: set[str] = set()
    fonti_usate: set[str] = set()
    for feed, lista in fonti_ok:
        if len(scelti) + MINIMO_PER_FONTE > OBIETTIVO:
            break
        disponibili = [a for a in lista if a.id not in usati]
        if len(disponibili) < MINIMO_PER_FONTE:
            continue
        campione = random.sample(disponibili, MINIMO_PER_FONTE)
        for articolo in campione:
            usati.add(articolo.id)
            scelti.append(articolo)
        fonti_usate.add(feed)

    if len(scelti) < OBIETTIVO:
        extra = [
            articolo
            for lista in per_fonte.values()
            for articolo in lista
            if articolo.id not in usati
            and (articolo.feed_url or articolo.fonte) in fonti_usate
        ]
        random.shuffle(extra)
        for articolo in extra:
            if len(scelti) >= OBIETTIVO:
                break
            usati.add(articolo.id)
            scelti.append(articolo)

    random.shuffle(scelti)
    LOGGER.info(
        "Articoli scelti: %d da %d fonti (minimo %d per fonte, fonti totali %d).",
        len(scelti),
        len(fonti_usate),
        MINIMO_PER_FONTE,
        len(per_fonte),
    )
    return scelti


def _ripara_testo(testo: str) -> str:
    """Ripara entità HTML e i casi più comuni di doppia codifica UTF-8."""
    testo = html_lib.unescape(str(testo or ""))
    if any(marcatore in testo for marcatore in ("\u00c3", "\u00e2\u20ac", "\u00c2")):
        try:
            testo = testo.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return testo


def _articoli_json(articoli: list) -> list[dict]:
    risultato = []
    for indice, articolo in enumerate(articoli, start=1):
        sommario = (articolo.sommario or articolo.contenuto or "").strip()
        risultato.append(
            {
                "id": f"a{indice}",
                "titolo": _ripara_testo(articolo.titolo),
                "fonte": _ripara_testo(articolo.fonte),
                "categoria_base": _ripara_testo(articolo.categoria),
                "sommario": _ripara_testo(sommario[:900]),
                "link": articolo.link,
                "pubblicato": articolo.pubblicato.isoformat(),
            }
        )
    return risultato


def _indice() -> str:
    return """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Calibrazione - Notiziario</title>
<style>
  :root { --bg:#0f1318; --card:#181f27; --testo:#eef3f8; --tenue:#a8b5c2; --bordo:#2c3946; --accento:#7cc4ff; }
  * { box-sizing:border-box; }
  body { margin:0; padding:24px; background:var(--bg); color:var(--testo); font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
  main { max-width:760px; margin:0 auto; }
  h1 { font-size:1.45rem; margin:0 0 6px; }
  p { color:var(--tenue); margin:0 0 18px; }
  .card { display:block; text-decoration:none; color:var(--testo); background:var(--card); border:1px solid var(--bordo); border-radius:16px; padding:18px; margin:0 0 14px; }
  .card:hover { border-color:var(--accento); }
  .card h2 { margin:0 0 4px; font-size:1.15rem; }
  .card small { color:var(--tenue); display:block; }
  .stato { color:var(--accento); margin-top:8px; font-size:.9rem; }
  .nota { border-top:1px solid var(--bordo); margin-top:22px; padding-top:16px; font-size:.9rem; color:var(--tenue); }
</style>
</head>
<body>
<main>
  <h1>Calibrazione</h1>
  <p>Prima calibra il contenuto, poi personalizza l'interesse. Le risposte restano nel browser e si esportano alla fine di ogni pagina.</p>
  <a class="card" href="calibrazione-contenuto.html">
    <h2>1. Contenuto</h2>
    <small>Categorie (anche più di una), notiziabilità 1–5 e flag PR/promozione.</small>
    <div class="stato" id="stato-contenuto">0 risposte</div>
  </a>
  <a class="card" href="calibrazione-interesse.html">
    <h2>2. Interesse</h2>
    <small>Quanto ti interessa: zero, poco, normale, tanto.</small>
    <div class="stato" id="stato-interesse">0 risposte</div>
  </a>
  <p class="nota">Alla fine di ogni pagina trovi Esporta JSON e Esporta CSV.</p>
</main>
<script>
function conta(chiave) {
  try {
    const dati = JSON.parse(localStorage.getItem(chiave) || "null");
    return dati && dati.risposte ? Object.keys(dati.risposte).length : 0;
  } catch (e) { return 0; }
}
document.getElementById("stato-contenuto").textContent = conta("notiziario.calibrazione.contenuto.v2") + " risposte";
document.getElementById("stato-interesse").textContent = conta("notiziario.calibrazione.interesse.v1") + " risposte";
</script>
</body>
</html>
"""


def _html(articoli: list[dict], modo: str = "contenuto") -> str:
    dati = json.dumps(articoli, ensure_ascii=False)
    categorie = json.dumps(CATEGORIE, ensure_ascii=False)
    interessi = json.dumps(INTERESSI, ensure_ascii=False)
    notiziabilita = json.dumps(NOTIZIABILITA, ensure_ascii=False)
    titolo_modo = "Contenuto" if modo == "contenuto" else "Interesse"
    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Calibrazione {titolo_modo} - Notiziario</title>
<style>
  :root {{
    --bg:#0f1318; --card:#181f27; --card2:#202a34; --testo:#eef3f8;
    --tenue:#a8b5c2; --bordo:#2c3946; --accento:#7cc4ff; --ok:#7fe0a0;
    --warn:#ffcf7a; --male:#ff9c9c;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; padding:20px; background:var(--bg); color:var(--testo);
    font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;
  }}
  main {{ max-width:900px; margin:0 auto; }}
  header {{ display:flex; gap:12px; align-items:baseline; justify-content:space-between; flex-wrap:wrap; }}
  body[data-modo="contenuto"] .solo-interesse {{ display:none; }}
  body[data-modo="interesse"] .solo-contenuto {{ display:none; }}
  h1 {{ font-size:1.35rem; margin:0; }}
  .tenue {{ color:var(--tenue); }}
  .barra {{ height:8px; background:var(--card2); border-radius:99px; overflow:hidden; margin:14px 0 18px; }}
  .barra span {{ display:block; height:100%; width:0; background:var(--accento); transition:width .2s; }}
  .card {{ background:var(--card); border:1px solid var(--bordo); border-radius:16px; padding:20px; }}
  .meta {{ display:flex; gap:8px; flex-wrap:wrap; color:var(--tenue); font-size:.86rem; margin-bottom:10px; }}
  .badge {{ background:var(--card2); border:1px solid var(--bordo); border-radius:99px; padding:3px 9px; }}
  h2 {{ font-size:1.35rem; line-height:1.25; margin:0 0 12px; }}
  .sommario {{ color:#d7e2ec; white-space:pre-wrap; max-height:260px; overflow:auto; padding-right:4px; }}
  .sommario a {{ color:var(--accento); }}
  .sezione {{ margin-top:18px; }}
  .sezione h3 {{ font-size:.95rem; margin:0 0 8px; color:var(--tenue); text-transform:uppercase; letter-spacing:.04em; }}
  .opzioni {{ display:flex; gap:8px; flex-wrap:wrap; }}
  button {{
    font:inherit; color:var(--testo); background:var(--card2); border:1px solid var(--bordo);
    border-radius:10px; padding:9px 13px; cursor:pointer;
  }}
  button:hover {{ border-color:var(--accento); }}
  button.scelto {{ background:#17354a; border-color:var(--accento); color:#fff; }}
  button.primario {{ background:var(--accento); color:#07121b; border-color:var(--accento); font-weight:650; }}
  button:disabled {{ opacity:.45; cursor:not-allowed; }}
  .interesse button.scelto {{ background:#2b3a28; border-color:var(--ok); }}
  .pr button.scelto {{ background:#3a2d1f; border-color:var(--warn); }}
  .azioni {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:18px; align-items:center; }}
  .azioni .spazio {{ flex:1; }}
  .nota {{ font-size:.86rem; color:var(--tenue); margin-top:12px; }}
  .riepilogo {{ margin-top:14px; display:grid; gap:8px; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); }}
  .riepilogo div {{ background:var(--card2); border:1px solid var(--bordo); border-radius:12px; padding:10px; }}
  .errore {{ color:var(--male); }}
  @media (max-width:600px) {{
    body {{ padding:12px; }}
    .card {{ padding:14px; }}
    h2 {{ font-size:1.18rem; }}
  }}
</style>
</head>
<body data-modo="{modo}">
<main>
  <header>
    <div>
      <h1>Calibrazione {titolo_modo}</h1>
      <div class="tenue" id="sottotitolo">150 articoli da tutte le fonti</div>
    </div>
    <div class="tenue" id="conteggio">0 / 150</div>
  </header>
  <div class="barra"><span id="avanzamento"></span></div>

  <section class="card" id="scheda">
    <div class="meta" id="meta"></div>
    <h2 id="titolo">Caricamento...</h2>
    <div class="sommario" id="sommario"></div>

<div class="sezione solo-contenuto">
      <h3>Categorie (puoi sceglierne più di una)</h3>
      <div class="opzioni" id="categorie"></div>
    </div>

    <div class="sezione solo-contenuto">
      <h3>Notiziabilità (1 = non è una notizia, 5 = apertura)</h3>
      <div class="opzioni meter" id="notiziabilita"></div>
      <div class="nota" id="notiziabilita-label">Scegli un valore da 1 a 5.</div>
    </div>

    <div class="sezione interesse solo-interesse">
      <h3>Quanto ti interessa?</h3>
      <div class="opzioni" id="interessi"></div>
    </div>

    <div class="sezione pr solo-contenuto">
      <h3>È PR / promozione?</h3>
      <div class="opzioni" id="pr"></div>
    </div>

    <div class="azioni">
      <button id="indietro" type="button">Indietro</button>
      <button id="salta" type="button">Salta</button>
      <span class="spazio"></span>
      <button class="primario" id="avanti" type="button">Salva e avanti</button>
    </div>
    <div class="nota" id="stato"></div>
  </section>

  <section class="card" style="margin-top:14px">
    <div class="riepilogo">
      <div><strong id="risposte">0</strong><br><span class="tenue">risposte</span></div>
      <div><strong id="rimaste">150</strong><br><span class="tenue">da categorizzare</span></div>
      <div><strong id="fonti">0</strong><br><span class="tenue">fonti diverse</span></div>
    </div>
    <div class="azioni">
      <button id="esporta-json" type="button">Esporta JSON</button>
      <button id="esporta-csv" type="button">Esporta CSV</button>
      <button id="copia" type="button">Copia JSON</button>
      <span class="spazio"></span>
      <button id="ricomincia" type="button">Ricomincia</button>
    </div>
    <div class="nota">
      Le risposte restano in questo browser. Alla fine esporta il JSON o il CSV e passamelo:
      lo uso per calibrare categorie e livello di interesse.
    </div>
  </section>
</main>
<script>
const ARTICOLI = {dati};
const CATEGORIE = {categorie};
const INTERESSI = {interessi};
const NOTIZIABILITA = {notiziabilita};
const PR = [["no", "No"], ["si", "Sì"]];
const MODO = "{modo}";
const CHIAVE = MODO === "contenuto"
  ? "notiziario.calibrazione.contenuto.v2"
  : "notiziario.calibrazione.interesse.v1";
let stato = {{ indice: 0, risposte: {{}} }};
try {{
  const salvato = JSON.parse(localStorage.getItem(CHIAVE) || "null");
  if (salvato && salvato.risposte) stato = salvato;
}} catch (e) {{}}

const $ = (id) => document.getElementById(id);
const titolo = $("titolo");
const sommario = $("sommario");
const meta = $("meta");
const categorieEl = $("categorie");
const interessiEl = $("interessi");
const notiziabilitaEl = $("notiziabilita");
const notiziabilitaLabel = $("notiziabilita-label");
const prEl = $("pr");
const avanti = $("avanti");
const indietro = $("indietro");
const salta = $("salta");
const statoEl = $("stato");

function salva() {{
  try {{
    localStorage.setItem(CHIAVE, JSON.stringify(stato));
  }} catch (e) {{
    statoEl.textContent = "Impossibile salvare nel browser: " + e.message;
    statoEl.className = "nota errore";
  }}
}}

function risposta(id) {{
  return stato.risposte[id] || {{}};
}}

function aggiornaRiepilogo() {{
  const totale = ARTICOLI.length;
  const risposte = Object.keys(stato.risposte).length;
  $("risposte").textContent = risposte;
  $("rimaste").textContent = Math.max(0, totale - risposte);
  $("fonti").textContent = new Set(ARTICOLI.map(a => a.fonte)).size;
  $("conteggio").textContent = (stato.indice + 1) + " / " + totale;
  $("avanzamento").style.width = (100 * (stato.indice + 1) / totale) + "%";
}}

function creaBottoni(contenitore, voci, valore, suScelta) {{
  contenitore.replaceChildren();
  const scelti = new Set(Array.isArray(valore) ? valore : (valore ? [valore] : []));
  for (const [id, label] of voci) {{
    const bottone = document.createElement("button");
    bottone.type = "button";
    bottone.textContent = label;
    bottone.dataset.valore = id;
    if (scelti.has(id)) bottone.classList.add("scelto");
    bottone.addEventListener("click", () => suScelta(id));
    contenitore.appendChild(bottone);
  }}
}}

function mostra() {{
  const articolo = ARTICOLI[stato.indice];
  if (!articolo) return;
  const r = risposta(articolo.id);
  meta.replaceChildren();
  const fonte = document.createElement("span");
  fonte.className = "badge";
  fonte.textContent = articolo.fonte;
  const categoria = document.createElement("span");
  categoria.className = "badge";
  categoria.textContent = "feed: " + articolo.categoria_base;
  meta.append(fonte, categoria);

  titolo.textContent = articolo.titolo;
  sommario.replaceChildren();
  const testo = document.createElement("span");
  testo.textContent = articolo.sommario || "Nessun sommario disponibile.";
  sommario.appendChild(testo);
  if (articolo.link) {{
    sommario.appendChild(document.createElement("br"));
    const link = document.createElement("a");
    link.href = articolo.link;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Apri articolo";
    sommario.appendChild(link);
  }}

  function scegliCategoria(valore) {{
    const attuali = new Set(
      Array.isArray(risposta(articolo.id).categorie)
        ? risposta(articolo.id).categorie
        : []
    );
    if (attuali.has(valore)) attuali.delete(valore);
    else attuali.add(valore);
    const nuove = [...attuali];
    stato.risposte[articolo.id] = {{ ...risposta(articolo.id), categorie: nuove }};
    salva();
    creaBottoni(categorieEl, CATEGORIE, nuove, scegliCategoria);
    aggiornaRiepilogo();
    aggiornaAvanti();
  }}
  function scegliInteresse(valore) {{
    stato.risposte[articolo.id] = {{ ...risposta(articolo.id), interesse: valore }};
    salva();
    creaBottoni(interessiEl, INTERESSI, valore, scegliInteresse);
    aggiornaRiepilogo();
    aggiornaAvanti();
  }}
  function scegliPr(valore) {{
    stato.risposte[articolo.id] = {{ ...risposta(articolo.id), pr: valore === "si" }};
    salva();
    creaBottoni(prEl, PR, valore, scegliPr);
    aggiornaRiepilogo();
    aggiornaAvanti();
  }}
  function aggiornaLabelNotiziabilita(valore) {{
    const etichette = {{
      1: "Non è una notizia",
      2: "Bassa",
      3: "Media",
      4: "Alta",
      5: "Da apertura",
    }};
    notiziabilitaLabel.textContent =
      "Notiziabilita " + valore + "/5 - " + (etichette[valore] || "");
  }}
  function scegliNotiziabilita(valore) {{
    const numero = Number(valore);
    stato.risposte[articolo.id] = {{
      ...risposta(articolo.id),
      notiziabilita: numero,
    }};
    salva();
    creaBottoni(notiziabilitaEl, NOTIZIABILITA, String(numero), scegliNotiziabilita);
    aggiornaLabelNotiziabilita(numero);
    aggiornaRiepilogo();
    aggiornaAvanti();
  }}
  const prScelto = r.pr === true ? "si" : r.pr === false ? "no" : undefined;
  const categorieScelte = Array.isArray(r.categorie) ? r.categorie : [];
  const notiziabilitaScelta =
    typeof r.notiziabilita === "number" ? String(r.notiziabilita) : undefined;
  creaBottoni(categorieEl, CATEGORIE, categorieScelte, scegliCategoria);
  creaBottoni(interessiEl, INTERESSI, r.interesse, scegliInteresse);
  creaBottoni(notiziabilitaEl, NOTIZIABILITA, notiziabilitaScelta, scegliNotiziabilita);
  creaBottoni(prEl, PR, prScelto, scegliPr);
  if (notiziabilitaScelta) aggiornaLabelNotiziabilita(Number(notiziabilitaScelta));
  else notiziabilitaLabel.textContent = "Scegli un valore da 1 a 5.";

  statoEl.textContent = "";
  statoEl.className = "nota";
  indietro.disabled = stato.indice === 0;
  aggiornaRiepilogo();
  aggiornaAvanti();
}}

function aggiornaAvanti() {{
  const articolo = ARTICOLI[stato.indice];
  const r = risposta(articolo.id);
  avanti.disabled = MODO === "contenuto"
    ? !(Array.isArray(r.categorie) && r.categorie.length > 0
        && typeof r.pr === "boolean"
        && typeof r.notiziabilita === "number")
    : !r.interesse;
}}

function vai(indice) {{
  stato.indice = Math.max(0, Math.min(ARTICOLI.length - 1, indice));
  salva();
  mostra();
}}

avanti.addEventListener("click", () => {{
  if (avanti.disabled) return;
  vai(stato.indice + 1);
}});
indietro.addEventListener("click", () => vai(stato.indice - 1));
salta.addEventListener("click", () => vai(stato.indice + 1));

function esportaJson() {{
  const risposte = ARTICOLI.map((a) => {{
    const r = risposta(a.id);
    return {{
      id: a.id, titolo: a.titolo, fonte: a.fonte,
      categoria_base: a.categoria_base,
      categorie: Array.isArray(r.categorie) ? r.categorie : [],
      notiziabilita: typeof r.notiziabilita === "number" ? r.notiziabilita : "",
      interesse: r.interesse || "",
      pr: r.pr === true ? "si" : r.pr === false ? "no" : "",
      link: a.link, sommario: a.sommario
    }};
  }}).filter(r => MODO === "contenuto"
    ? ((Array.isArray(r.categorie) && r.categorie.length > 0)
        || typeof r.pr === "boolean"
        || typeof r.notiziabilita === "number")
    : r.interesse);
  const dati = {{ generato: new Date().toISOString(), modo: MODO, totale: ARTICOLI.length, risposte }};
  scarica("calibrazione-" + MODO + ".json", JSON.stringify(dati, null, 2), "application/json");
}}

function esportaCsv() {{
  const righe = [["id","titolo","fonte","categoria_base","categorie","notiziabilita","interesse","pr","link"]];
  for (const a of ARTICOLI) {{
    const r = risposta(a.id);
    const pr = r.pr === true ? "si" : r.pr === false ? "no" : "";
    const categorie = Array.isArray(r.categorie) ? r.categorie.join(";") : "";
    const notiziabilita = typeof r.notiziabilita === "number" ? r.notiziabilita : "";
    const valida = MODO === "contenuto"
      ? (categorie || pr || notiziabilita !== "")
      : !!r.interesse;
    if (!valida) continue;
    righe.push([a.id, a.titolo, a.fonte, a.categoria_base, categorie, notiziabilita, r.interesse || "", pr, a.link]);
  }}
  const csv = righe.map(riga => riga.map(v => '"' + String(v ?? "").replaceAll('"','""') + '"').join(",")).join("\\n");
  scarica("calibrazione-" + MODO + ".csv", csv, "text/csv");
}}

function scarica(nome, contenuto, tipo) {{
  const blob = new Blob([contenuto], {{ type: tipo }});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = nome;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}}

$("esporta-json").addEventListener("click", esportaJson);
$("esporta-csv").addEventListener("click", esportaCsv);
$("copia").addEventListener("click", async () => {{
  const risposte = ARTICOLI.map(a => {{
    const r = risposta(a.id);
    const pr = r.pr === true ? "si" : r.pr === false ? "no" : "";
    const categorie = Array.isArray(r.categorie) ? r.categorie : [];
    const notiziabilita = typeof r.notiziabilita === "number" ? r.notiziabilita : "";
    const valida = MODO === "contenuto"
      ? (categorie.length > 0 || pr || notiziabilita !== "")
      : r.interesse;
    return valida ? {{
      id:a.id, titolo:a.titolo, fonte:a.fonte,
      categorie, notiziabilita, interesse:r.interesse||"", pr
    }} : null;
  }}).filter(Boolean);
  await navigator.clipboard.writeText(JSON.stringify({{ risposte }}, null, 2));
  statoEl.textContent = "JSON copiato negli appunti.";
}});
$("ricomincia").addEventListener("click", () => {{
  if (!confirm("Cancellare tutte le risposte salvate?")) return;
  stato = {{ indice: 0, risposte: {{}} }};
  salva(); mostra();
}});

mostra();
</script>
</body>
</html>"""


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    riusa = "--riusa" in sys.argv
    if riusa and DATI.exists():
        dati = json.loads(DATI.read_text(encoding="utf-8"))
        for articolo in dati:
            for chiave in ("titolo", "fonte", "categoria_base", "sommario"):
                articolo[chiave] = _ripara_testo(articolo.get(chiave, ""))
        DATI.write_text(
            json.dumps(dati, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        LOGGER.info("Riuso %d articoli da %s.", len(dati), DATI)
    else:
        fonti = _fonti_uniche()
        LOGGER.info("Scarico %d fonti (anche disattivate), tutte le date.", len(fonti))
        articoli_grezzi = _scarica_tutte(fonti)
        LOGGER.info("Articoli grezzi: %d.", len(articoli_grezzi))
        articoli = _scegli_articoli(articoli_grezzi)
        dati = _articoli_json(articoli)
        DATI.parent.mkdir(parents=True, exist_ok=True)
        DATI.write_text(
            json.dumps(dati, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if len(dati) < OBIETTIVO:
        LOGGER.warning("Ho trovato solo %d articoli su %d.", len(dati), OBIETTIVO)
    USCITA_CONTENUTO.parent.mkdir(parents=True, exist_ok=True)
    USCITA_CONTENUTO.write_text(_html(dati, "contenuto"), encoding="utf-8")
    USCITA_INTERESSE.write_text(_html(dati, "interesse"), encoding="utf-8")
    USCITA_INDICE.write_text(_indice(), encoding="utf-8")
    LOGGER.info(
        "Creati %s e %s con %d articoli.",
        USCITA_CONTENUTO,
        USCITA_INTERESSE,
        len(dati),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

