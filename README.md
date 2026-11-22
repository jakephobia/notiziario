# Notiziario

Ogni mattina scarica le ultime notizie dai feed RSS, raggruppa gli articoli che
raccontano lo stesso evento, sceglie una scaletta bilanciata e genera un podcast
mp3 in italiano. Il copione può essere scritto da Gemini (free tier) oppure, se
la chiave non c'è o la chiamata fallisce, da un fallback locale deterministico.

Il progetto è pensato per l'uso personale: nessun servizio a pagamento, nessuna
credenziale nel repository, nessuno scraping massivo delle pagine degli articoli.
Legge i feed RSS e, per arricchire solo le notizie selezionate, scarica il testo
completo di massimo 20 articoli rispettando robots.txt. Cita sempre le testate.

## Cosa produce

- `output/notiziario-AAAA-MM-GG.mp3`: l'episodio, voce italiana, loudness da podcast.
- `output/copione-AAAA-MM-GG.md`: copione leggibile con le notizie e i link alle fonti.
- `output/copione-AAAA-MM-GG.txt`: solo il testo letto dal TTS.
- `output/stato-AAAA-MM-GG.json`: categorie, fonti, notizie, durata, incipit, modalità AI, target/divario parole e avvisi.
- `state/visti.json`: rubrica first_seen per i feed senza date (da committare).
- `logs/run-AAAA-MM-GG.log`: log dell'esecuzione.
- `docs/feed.xml`, `docs/index.html`, `docs/storico.json`: feed RSS e player statico.
- `docs/copertina.png`: copertina 1400x1400 per Apple Podcasts.
- `docs/impostazioni.json`: impostazioni effettive lette dalla pagina.
- `docs/robots.txt`: sito non indicizzato (Disallow /).
- `output/provini/provino-isabella.mp3` e `provino-elsa.mp3`: due provini vocali.
- `output/controllo-feed-AAAA-MM-GG.json`: report del controllo anti-block.
- `output/anteprima/`: mp3 brevi di prova voce, non episodi.
- `cache/articoli/`: cache locale degli articoli arricchiti (24h, non committare).

## Requisiti

- Windows 10/11 (il progetto funziona anche su Linux, come in GitHub Actions).
- Python 3.12 o 3.14. Sul computer di prova è stato usato Python 3.14.4.
- `ffmpeg` e `ffprobe` nel PATH. Sul computer di prova è stato usato ffmpeg 8.1.2.
- Connessione internet per feed, edge-tts e Gemini.
- Nessun account o servizio a pagamento.

Le dipendenze sono poche e hanno wheel per Python 3.12 e 3.14: `feedparser`,
`requests`, `beautifulsoup4`, `PyYAML`, `edge-tts`, `tzdata` (per Europe/Rome su
Windows), `trafilatura`, `defusedxml` e `pytest`.

## Installazione (una volta sola)

Apri PowerShell nella cartella del progetto:

```powershell
cd C:\Users\jacop\Desktop\IDEA
powershell -ExecutionPolicy Bypass -File .\scripts\installa.ps1
```

Oppure, a mano:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Il venv è locale alla cartella `.venv`. Non serve attivarlo: gli script usano
direttamente `.venv\Scripts\python.exe`.

## Uso quotidiano

Il comando più semplice:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\esegui.ps1
```

Equivale a:

```powershell
.\.venv\Scripts\python.exe main.py
```

Alla fine stampa un riepilogo con fonti OK/KO, numero di notizie, durata
dell'mp3, percorso del copione e avvisi di stile.

### Opzioni utili

| Comando | Cosa fa |
|---|---|
| `.\scripts\esegui.ps1 --durata svelto` | Episodio breve, circa 4 minuti. |
| `.\scripts\esegui.ps1 --durata standard` | Formato predefinito, circa 7 minuti. |
| `.\scripts\esegui.ps1 --durata completo` | Episodio lungo, circa 12 minuti. |
| `.\scripts\esegui.ps1 --notizie 5` | Massimo 5 notizie, qualunque sia il preset. |
| `.\scripts\esegui.ps1 --ore 12` | Guarda solo le ultime 12 ore (default 24). |
| `.\scripts\esegui.ps1 --senza-audio` | Crea copione e stato, senza TTS. |
| `.\scripts\esegui.ps1 --dry-run` | Fetch e copione sì; niente audio, feed o pubblicazione. |
| `.\scripts\esegui.ps1 --provini` | Genera i due provini vocali e termina. |
| `.\scripts\esegui.ps1 --test-llm` | Prova la chiave Gemini con una richiesta minima. |
| `.\scripts\esegui.ps1 --test-modelli` | Elenca i modelli e prova i candidati testo/TTS. |
| `.\scripts\esegui.ps1 --anteprima-voce --voce Kore` | Solo mp3 breve di anteprima voce. |
| `.\scripts\esegui.ps1 --voce Leda --velocita 1.1` | Override voce/velocità per la run. |
| `.\scripts\esegui.ps1 --tts-motore edge` | Forza edge-tts invece di Gemini TTS. |
| `.\scripts\esegui.ps1 --importa-feed lista.opml` | Importa feed da OPML/TXT/CSV/JSON. |
| `.\scripts\esegui.ps1 --fonti` | Stampa l'elenco numerato delle fonti. |
| `.\scripts\esegui.ps1 --controlla-feed` | Controlla testo, paywall, podcast e inattività. |
| `.\scripts\esegui.ps1 --controlla-feed --disattiva-non-ok` | Come sopra, spegnendo anche le fonti esistenti non OK. |

`--dry-run` è comodo per controllare la scaletta senza aspettare il TTS.
`--senza-audio` è comodo per correggere il copione prima di generare l'mp3.

### Durata e numero di notizie

I preset sono in `config/impostazioni.json`:

| Preset | Minuti indicativi | Copertine | Secondarie | Max notizie |
|---|---:|---:|---:|---:|
| `svelto` | 4 | 1 | 4 | 6 |
| `standard` | 7 | 2 | 6 | 10 |
| `completo` | 12 | 3 | 8 | 14 |

Le copertine restano 1/2/3. Il valore `secondarie` del preset è un limite
effettivo, non decorativo; il massimo notizie comprende anche il blocco
Buone notizie (2/2/3 voci), che riduce le secondarie quando serve spazio.

Il budget è di circa 145 parole al minuto. Le copertine hanno un budget più
alto (circa 220-300 parole), le secondarie circa 90-130. I valori esatti sono
nel file di configurazione e si possono cambiare senza toccare il codice.

## Incipit configurabile

L'apertura è in `config/incipit.txt` (UTF-8). Il default è:

```text
Ciao [NOME UTENTE], ecco le tue notizie del giorno. Oggi è il [DATA].
```

`config/impostazioni.json` contiene `"nome_utente": "Jacopo"`. Marker supportati,
senza distinzione tra maiuscole e minuscole e con spazi tollerati:

| Marker | Risultato al 22 novembre 2026 |
|---|---|
| `[NOME UTENTE]`, `[NOME]` | `Jacopo` |
| `[DATA]` | `22 novembre` |
| `[GIORNO]` | `domenica` |
| `[DATA COMPLETA]` | `domenica 22 novembre 2026` |

Le date usano sempre `Europe/Rome`, anche su GitHub Actions (che gira in UTC).
L'incipit viene risolto **dopo** il corpo e aggiunto in testa: il prompt AI e il
fallback non scrivono saluti o aperture. Se un marker è sconosciuto viene rimosso
e segnalato; se `nome_utente` è vuoto il marker del nome sparisce e resta un
avviso. Nel testo finale non restano parentesi quadre.

Per sovrascrivere l'incipit da GitHub aggiungi alla issue delle categorie:

```markdown
## Incipit

Ciao [NOME], buongiorno. Oggi è [DATA COMPLETA].
```

La sezione arriva fino al successivo `##` e può essere anche un blocco di codice.
Priorità: **issue > config/incipit.txt**. Se la issue non è disponibile si usa il
file, senza errori. `--dry-run` stampa l'incipit risolto e non genera audio.

## Voci, velocità e anteprima

Il motore predefinito è **Gemini TTS** con
`gemini-2.5-flash-preview-tts`. L'output è PCM L16 24 kHz mono, convertito in
WAV, velocizzato con `atempo` e poi masterizzato in mp3 con `loudnorm`
(`I=-16`, `TP=-1.5`, `LRA=11`, 44,1 kHz, mono, 96 kbps). La chiave viaggia
nell'header `x-goog-api-key`, mai nella query string.

| Voce | Genere percepito | Etichetta |
|---|---|---|
| `Kore` | F | Kore — femminile, calda |
| `Leda` | F | Leda — femminile, luminosa |
| `Charon` | M | Charon — maschile, profonda |
| `Puck` | M | Puck — maschile, vivace |
| `Orus` | M | Orus — maschile, riserva |

Default: `Kore`, velocità `1.10` (range 0.75-1.25, step 0.05: 0.75, 0.80, ..., 1.25). Un valore fuori griglia viene agganciato allo step più vicino e segnalato; fuori range viene limitato al bordo. La velocità è applicata ai
soli chunk vocali con ffmpeg `atempo`, prima delle pause, quindi i silenzi non
vengono accelerati.

Ogni episodio e ogni anteprima hanno **1 secondo di silenzio iniziale**
(`silenzio_iniziale_ms: 1000`), applicato una sola volta dopo loudnorm con
`adelay`, prima dell'encoding finale. Non viene aggiunto ai singoli chunk. La
durata nel feed include questo secondo; il controllo automatico verifica che i
primi 950 ms siano sotto -60 dB. Il prompt di regia chiede una conduttrice radiofonica
italiana calda e vivace, ritmo vario, e dice di leggere solo il testo: le
istruzioni non devono finire nel podcast.

### Voce dalla issue GitHub

Nella stessa issue delle categorie/incipit puoi aggiungere:

```markdown
## Voce
voce: Kore
velocita: 1.10
motore: gemini
```

Priorità: **issue > config/impostazioni.json**. La voce è validata sulla
whitelist; la velocità è validata tra 0.75 e 1.25, agganciata allo step 0.05. Valori invalidi tornano al
default con un avviso. Se scegli `edge`, la voce Gemini viene mappata su
`it-IT-IsabellaNeural` e l'avviso viene registrato.

### Anteprima veloce

```powershell
# Gemini, voce Kore, frase predefinita
.\scripts\esegui.ps1 --anteprima-voce --voce Kore

# Frase personalizzata e velocità 1.1
.\scripts\esegui.ps1 --anteprima-voce "Ciao, questa è una prova." --voce Puck --velocita 1.1

# Forza edge-tts
.\scripts\esegui.ps1 --anteprima-voce --voce Kore --tts-motore edge
```

L'anteprima non fa fetch, non scrive copione, non crea episodio e **non tocca
`state/visti.json`**. Il file va in
`output/anteprima/anteprima-<voce>-<velocita>.mp3`.

Da GitHub: **Actions → Anteprima voce → Run workflow**, con input `voce`,
`velocita`, `frase`. Il workflow carica solo l'mp3 come artifact scaricabile,
senza release e senza episodio.

### Fallback e quota

Se Gemini TTS risponde 429/quota o va in errore, il programma registra il
messaggio, passa automaticamente a `edge-tts` e riporta in stato
`tts.motore_usato`, `voce`, `velocita` e `motivo_fallback`. Con
`--tts-motore edge` non chiama Gemini. La voce edge predefinita è
`it-IT-IsabellaNeural`.

Configurazione quota: chunk massimo `tts_chunk_max_caratteri` = 4500, pausa
minima tra chiamate `tts.pausa_chiamate` = 3 s, backoff 429 configurato
5/15/30 s; con max 2 retry usa 5 e 15 s. Se un chunk lungo viene rifiutato con HTTP 400,
il limite viene ridotto automaticamente e loggato. Se i retry non bastano,
l'intero episodio passa a edge-tts: nessuna voce mista. `--provini` e le
anteprime rispettano la pausa minima.

La quota free tier Gemini TTS può esaurirsi: nei test reali Kore ha prodotto
un'anteprima valida, poi le chiamate successive hanno restituito 429. La run
standard finale ha quindi usato edge-tts per l'audio; anche il testo è passato
al fallback perché primario 429 e riserva troppo corta. Non viene mai inserita
una chiave nei log o nei file.

I vecchi provini edge-tts restano disponibili con
`.\scripts\esegui.ps1 --provini` in `output/provini/`.

## Suoni di transizione

Tre suoni royalty-free generati con ffmpeg sono in `docs/suoni/`:

| Suono | Durata | Uso |
|---|---:|---|
| `ding.mp3` | 0,50 s | default, nota 880 Hz |
| `chime.mp3` | 0,80 s | due note, 659 e 880 Hz |
| `whoosh.mp3` | 0,60 s | rumore filtrato |

Sono mono 44,1 kHz, mp3 ~96 kbps, con volume medio intorno a -20 dBFS.
Config: `suono_transizione` = `ding|chime|whoosh|nessuno`, `suono_gain_db` per
il gain controllato. La issue può avere `## Suono` con `suono: ding`.
Il parser delle categorie legge solo `## Categorie`: le checkbox presenti in
`## Fonti` non attivano o disattivano categorie. Se `## Categorie` manca si
usano i default con un avviso.
Il suono viene inserito dopo il mastering della voce, tra le sezioni, con
0,3 s di silenzio prima e dopo; non passa da loudnorm e non viene messo dopo
l'ultima notizia. Con `nessuno` non viene inserito nulla.

Anteprima:

```powershell
.\scripts\esegui.ps1 --anteprima-suono
.\scripts\esegui.ps1 --anteprima-suono ding
```

I file finiscono in `output/anteprima/suono-<nome>.mp3`, senza episodio,
fetch o modifica di stato. La pagina mostra tre player e indica il suono
selezionato.

## Descrizione breve dell'episodio

Formato: `22 novembre 2026 - Manovra approvata, Schettino libero, ...`.
L'AI riceve l'istruzione di produrre `descrizione_breve` con data e 3-8
micro-riassunti di 2-5 parole, massimo 200 caratteri, senza HTML. La
descrizione viene validata: se non inizia con `22 novembre 2026 - `, ripete la
data, contiene "le principali notizie", "e molto altro", "ecc.", supera 200
caratteri o ha meno di 2 micro-riassunti, si usa il fallback deterministico
(data + titoli accorciati). Il fallback usa data + fino a 8 titoli accorciati a
4 parole. La descrizione breve è usata
nell'item del feed (`description` e `itunes:summary`), nel copione `.md` e
nel player, non la descrizione lunga del canale. Titolo e descrizione usano il
mese minuscolo (`22 novembre 2026`), anche quando l'AI lo restituisce
maiuscolo.

## Outro configurabile

`config/outro.txt` contiene il default:

> Queste erano le notizie di oggi. A domani con i principali eventi della giornata!

La issue può sovrascriverlo con `## Outro` (testo o blocco codice); stessi
marker dell'incipit. Se è vuoto si usa il default. L'AI non deve scrivere
l'outro: il programma rimuove le chiusure generate e appende una sola volta
l'outro configurato, sempre in fondo dopo le Buone notizie.

## Categorie

Le categorie sono fisse:

| Id | Etichetta |
|---|---|
| `italia` | Italia |
| `mondo` | Mondo |
| `economia` | Economia |
| `tecnologia` | Tecnologia |
| `scienza-salute` | Scienza e salute |
| `cultura` | Cultura |
| `sport` | Sport |
| `ambiente` | Ambiente |
| `buone-notizie` | Buone notizie |

Di default sono attive tutte tranne `sport`, compresa `buone-notizie`. La
categoria è decisa **per articolo**: prima i tag RSS riconducibili alle
categorie note, poi il path dell'URL (`/sport/`, `/economia/`, `/tecnologia/`,
`/cultura/`, `/esteri/` o `/mondo/`, `/politica/`, `/cronaca/`, `/salute/`,
`/ambiente/`, `/scienze/`), infine la categoria della fonte. Non si usano le
parole del titolo. Le copertine e le secondarie rispettano le categorie attive:
con `sport` spento un articolo `/sport/` di un feed generalista viene escluso,
anche se la fonte è categorizzata Italia. Il blocco Buone notizie è fisso in
chiusura.

### Con una issue GitHub (consigliato per il cloud)

Crea una issue nel repository, per esempio intitolata "Categorie del notiziario",
con dentro righe come queste:

```markdown
- [x] italia
- [x] mondo
- [ ] sport
- [x] economia
- [x] tecnologia
- [x] scienza-salute
- [x] cultura
- [x] ambiente
- [x] buone-notizie
```

Poi imposta il numero della issue in uno dei due modi:

- variabile del repository `GITHUB_ISSUE_CATEGORIE` (Settings → Secrets and
  variables → Actions → Variables), usata dal workflow;
- `github.issue_categorie` in `config/impostazioni.json`, per l'uso locale.

Il programma legge il corpo della issue con l'API GitHub. Servono
`GITHUB_TOKEN` (fornito da GitHub Actions) e `GITHUB_REPOSITORY` (anch'esso
fornito da Actions). In locale puoi creare un token fine-grained con permesso
"Issues: read" e impostare:

```powershell
$env:GITHUB_TOKEN = "il-tuo-token"
$env:GITHUB_REPOSITORY = "tuonome/tuorepo"
$env:GITHUB_ISSUE_CATEGORIE = "1"
```

Regole di lettura: `- [x]` attiva, `- [ ]` disattiva, il match non distingue
maiuscole/minuscole e accetta id o etichetta. Una categoria non citata mantiene
il default. Se la issue non è disponibile, il programma usa i default e lo scrive
nel log.

## Buone notizie

`buone-notizie` è una categoria attiva di default. Il blocco va sempre in
chiusura, dopo tutte le altre categorie e prima dell'ultima frase, con 2-3
notizie da circa 90-130 parole. Se manca spazio si riducono le secondarie, mai
le copertine. Se la categoria è attiva ma non ci sono notizie positive, il
blocco viene saltato e il log lo dice: il notiziario non si rompe.

Due feed italiani dedicati sono stati verificati davvero e sono in
`config/fonti.yaml`:

- `https://www.buonenotizie.it/feed/` (Buone Notizie);
- `https://www.italiachecambia.org/feed/` (Italia Che Cambia).

Funzionamento:

- **con AI**: Gemini valuta un pool di candidate dai feed generalisti attivi e
  seleziona solo esiti positivi o incoraggianti (scoperte, progressi concreti,
  soluzioni, comunità, diritti, ambiente che migliora). Sono esclusi cronaca
  nera, tragedie, guerre, catastrofi, politica conflittuale e notizie costruite
  sul conteggio delle vittime. Un prefiltro di parole negative resta attivo
  anche se il modello sbaglia.
- **senza AI**: passano solo i feed dedicati `buone-notizie`, sempre filtrati
  per titoli negativi. Se non ci sono articoli recenti, il blocco è vuoto.
- **categoria spenta**: nessun blocco e nessuna chiamata AI per la positività.

## Fonti RSS

Le fonti sono in `config/fonti.yaml`, con commenti in italiano. Ogni voce ha
`nome` (la testata da pronunciare), `url` (il feed, non la pagina del sito) e
`categoria`.

### Fonti verificate

Il 22 novembre 2026 sono state provate con richieste reali. Queste **31 URL**
rispondevano e restituivano date valide. Il controllo anti-block ha dato
**25 OK, 5 `testo-breve` e 1 `campione-insufficiente`** (ANSA con summary corti o 4 item).
Nella run AI 22 feed avevano articoli nelle ultime 24 ore; 9 sezioni erano
semplicemente ferme, comprese le due Buone notizie, e vengono saltate senza
errore quando non hanno notizie fresche. Restano configurate perché si
aggiornano nel corso della giornata.

| Testata | Categoria | Feed |
|---|---|---|
| ANSA | italia | `https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml` |
| ANSA | italia | `https://www.ansa.it/sito/notizie/cronaca/cronaca_rss.xml` |
| ANSA | mondo | `https://www.ansa.it/sito/notizie/mondo/mondo_rss.xml` |
| ANSA | economia | `https://www.ansa.it/sito/notizie/economia/economia_rss.xml` |
| ANSA | sport | `https://www.ansa.it/sito/notizie/sport/sport_rss.xml` |
| ANSA | cultura | `https://www.ansa.it/sito/notizie/cultura/cultura_rss.xml` |
| Repubblica | italia | `https://www.repubblica.it/rss/homepage/rss2.0.xml` |
| Repubblica | italia | `https://www.repubblica.it/rss/politica/rss2.0.xml` |
| Repubblica | italia | `https://www.repubblica.it/rss/cronaca/rss2.0.xml` |
| Repubblica | mondo | `https://www.repubblica.it/rss/esteri/rss2.0.xml` |
| Repubblica | economia | `https://www.repubblica.it/rss/economia/rss2.0.xml` |
| Repubblica | cultura | `https://www.repubblica.it/rss/cultura/rss2.0.xml` |
| Repubblica | tecnologia | `https://www.repubblica.it/rss/tecnologia/rss2.0.xml` |
| Repubblica | ambiente | `https://www.repubblica.it/rss/ambiente/rss2.0.xml` |
| Repubblica | scienza-salute | `https://www.repubblica.it/rss/salute/rss2.0.xml` |
| Il Post | italia | `https://www.ilpost.it/italia/feed/` |
| Il Post | mondo | `https://www.ilpost.it/mondo/feed/` |
| Il Post | economia | `https://www.ilpost.it/economia/feed/` |
| Il Post | tecnologia | `https://www.ilpost.it/tecnologia/feed/` |
| Il Post | scienza-salute | `https://www.ilpost.it/scienza/feed/` |
| Il Post | cultura | `https://www.ilpost.it/cultura/feed/` |
| Il Post | sport | `https://www.ilpost.it/sport/feed/` |
| Il Sole 24 Ore | italia | `https://www.ilsole24ore.com/rss/italia.xml` |
| Il Sole 24 Ore | mondo | `https://www.ilsole24ore.com/rss/mondo.xml` |
| Il Sole 24 Ore | economia | `https://www.ilsole24ore.com/rss/economia.xml` |
| Il Sole 24 Ore | tecnologia | `https://www.ilsole24ore.com/rss/tecnologia.xml` |
| Il Sole 24 Ore | cultura | `https://www.ilsole24ore.com/rss/cultura.xml` |
| Il Sole 24 Ore | scienza-salute | `https://www.ilsole24ore.com/rss/salute.xml` |
| HDblog | tecnologia | `https://www.hdblog.it/rss/` |
| Buone Notizie | buone-notizie | `https://www.buonenotizie.it/feed/` |
| Italia Che Cambia | buone-notizie | `https://www.italiachecambia.org/feed/` |

### Fonti scartate dopo la verifica

- **Corriere della Sera**: i feed rispondono ma le date più recenti erano del
  2024/2025. Non entrerebbero mai nelle ultime 24 ore.
- **Wired Italia** (`https://www.wired.it/feed/rss/`): ultima data luglio 2026.
- **ANSA Tecnologia** e **ANSA Ambiente** (URL `/sito/notizie/...`): date ferme
  al 2023.
- **Il Post homepage**: risponde 403; le sezioni singole funzionano.
- **Repubblica Sport**, **Il Sole 24 Ore Sport**, **ANSA Italia**,
  **Corriere Italia**: URL 404 o non aggiornati.
- **HDblog** con `/feed/` in HTTPS dà errore SSL; funziona `/rss/`.

I feed cambiano nel tempo. Dopo una modifica, o una volta al mese, controlla:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verifica-fonti.ps1
```

Lo script mostra HTTP, numero di articoli, articoli nelle ultime 24 ore e ultima
data. Con `--strict` esce con errore se una fonte è KO o ferma.

### Aggiungere o togliere una fonte

Apri `config/fonti.yaml` e copia/cancella un blocco:

```yaml
  - nome: La Mia Testata
    url: https://www.example.com/feed.xml
    categoria: italia
```

Poi esegui `python -m notiziario.verifica_fonti` e una prova:

```powershell
.\scripts\esegui.ps1 --dry-run --durata svelto
```

Se una fonte è rotta, la pipeline continua con le altre e la segnala nel log.

## Importare liste RSS

`--importa-feed` accetta OPML, TXT, CSV e JSON. Auto-detect dal contenuto o
dall'estensione. Esempi:

```powershell
.\scripts\esegui.ps1 --importa-feed miei-feed.opml
.\scripts\esegui.ps1 --fonti
.\scripts\esegui.ps1 --importa-feed miei-feed.csv --categoria tecnologia --attiva-tutte
.\scripts\esegui.ps1 --importa-feed miei-feed.json --attiva-fonti 3,7
```

- OPML: anche outline annidati; titolo da `title`/`text`, URL da `xmlUrl`.
- TXT: una URL per riga, righe vuote e `#` ignorate.
- CSV: header `url,titolo,categoria` (case-insensitive) oppure prima colonna URL.
- JSON: lista o oggetto con lista; campi `url`/`url_feed`/`feed`,
  `titolo`/`title`/`name`, `categoria`/`category`.

Le nuove fonti sono **spente di default**. Vengono verificate davvero (timeout
15 s, User-Agent browser); i feed podcast con enclosure audio sono scartati, i
feed KO restano spenti. `--attiva-tutte` attiva solo `ok` e `testo-breve`;
`solo-titoli` e `campione-insufficiente` restano spenti con avviso.
`--attiva-fonti 1,3,5` usa gli indici dell'elenco stampato e applica la
stessa policy.
`--categoria X` vale per le nuove senza categoria. Categorie mancanti o
sconosciute diventano `da-assegnare` e la fonte resta esclusa con un avviso.
Limiti: 200 feed per file, file massimo 5 MB, solo `http://` e `https://`.
Un titolo OPML fatto di soli spazi cade sul dominio (es. `ilpost.it`) e non
produce un nome vuoto. Le fonti `da-assegnare` restano spente anche con
`--attiva-tutte` o `--attiva-fonti`, con avviso esplicito nel report.
Il report finisce in `output/importa-feed-AAAA-MM-GG.json` con importati,
duplicati, scartati e motivi. L'import riscrive `config/fonti.yaml`: i commenti
personalizzati vengono rigenerati con l'intestazione standard.

## Controllo anti-block dei feed

```powershell
.\scripts\esegui.ps1 --controlla-feed
.\scripts\esegui.ps1 --controlla-feed --disattiva-non-ok
```

Esiti possibili: `ok`, `testo-breve`, `errore`, `vuoto`, `solo-titoli`,
`paywall`, `podcast`, `inattivo`, `data-assente`, `campione-insufficiente`.
Soglie in `config/impostazioni.json` (`controllo_feed`): testo utile minimo 40
caratteri, almeno 50% di item con testo, paywall massimo 25%, almeno 5 item
valutati, inattività 180 giorni. Il paywall scatta solo su testi corti: un
articolo lungo che parla di abbonamenti non viene segnalato.

`solo-titoli` è riservato ai summary vuoti o identici al titolo. `testo-breve`
indica summary reali ma corti (media sotto 80 caratteri): è un avviso e
`--disattiva-non-ok` **non** spegne `testo-breve` né `campione-insufficiente`.
Spegne solo `errore`, `vuoto`, `paywall`, `inattivo` e `solo-titoli`.
Un XML malformato dà `errore`, non `vuoto`. Anche `--attiva-tutte` non
attiva nuove fonti `solo-titoli` o `campione-insufficiente`.

Per i feed esistenti il controllo aggiorna `controllo` e `ultimo_controllo` ma
non cambia `attivo`, a meno di `--disattiva-non-ok`. Le fonti spente vengono
escluse dalla run; i feed KO vengono saltati senza modificare la configurazione.
Il report è `output/controllo-feed-AAAA-MM-GG.json`; la tabella viene stampata
in console. Nella calibrazione reale ANSA risulta `testo-breve` (5 feed) e
`campione-insufficiente` (economia, 4 item), non `solo-titoli`.

## Feed senza data e first_seen

`state/visti.json` è la rubrica persistente:

```json
{
  "visti": {
    "url:https://esempio.test/articolo": {
      "first_seen": "2026-11-22T13:00:00+01:00",
      "fonte": "Esempio",
      "feed_url": "https://esempio.test/feed.xml",
      "titolo": "Titolo"
    }
  },
  "feed_last_seen": {
    "https://esempio.test/feed.xml": "2026-11-22T13:00:00+01:00"
  }
}
```

- chiave = guid/link normalizzato, altrimenti hash del titolo normalizzato;
- per un feed senza date la data effettiva è `first_seen`;
- cold start: al primo incontro si prendono solo i primi 5 item e si marca
  `data_stimata: true`; gli altri verranno recuperati al passaggio successivo;
- un articolo già in rubrica è vecchio e non viene ripetuto; uno mai visto è
  nuovo ed entra;
- pruning a 60 giorni; `feed_last_seen` resta per l'inattività a 180 giorni;
- date future normalizzate a ora;
- se tutti gli item sono già in rubrica lo stato del feed è
  `ok-senza-novita` (0 nuovi), non un errore; se tutte le fonti sono così la
  run termina con un messaggio chiaro senza crash;
- `state/visti.json` viene salvato anche con `--senza-audio`; `--dry-run` non
  scrive stato e non marca gli articoli come visti;
- `state/visti.json` **non è in `.gitignore`** e il workflow lo committa.

## Arricchimento dei contenuti

Dopo la selezione, `notiziario/arricchisci.py` scarica il testo completo delle
notizie scelte: massimo 20 articoli, massimo 3 per cluster multi-fonte. Usa
`trafilatura` 2.3.1 (compatibile con Python 3.14 tramite wheel lxml; in caso di
problemi c'è il fallback BeautifulSoup sui paragrafi), timeout 15 s, massimo
2 MB per pagina, massimo 3 redirect. Non usa la pagina per fare scraping
selvaggio: legge solo gli articoli selezionati, rispetta `robots.txt` e usa la
cache locale `cache/articoli` con TTL 24h.

Sicurezza: solo HTTP/HTTPS, host risolti e rifiutati se loopback, privati,
link-local o non globali; redirect rivalidati. Se `robots.txt` non è
raggiungibile si **consente** il fetch con un warning esplicito (policy
documentata), mentre un `Disallow` esplicito blocca. Paywall o estratto sotto 300
caratteri → si torna al summary e si marca `contenuto_parziale`.

Config in `config/impostazioni.json` (`arricchimento`):
`attivo`, `max_articoli`, `max_per_cluster`, `timeout`, `max_bytes`,
`min_caratteri_estratto`, `rispetta_robots`, `cache_dir`, `ttl_ore`.
Il testo arricchito entra nel prompt AI e nel fallback, così la run standard si
avvicina ai 6-8 minuti senza inventare fatti. Se il materiale resta insufficiente,
lo stato riporta `target_parole` e `divario_parole`.

`cache/`, `output/qa/` e `docs-qa/` sono in `.gitignore`: non vanno committati.

## Come funziona la pipeline

1. **Fetch parallelo** dei feed (timeout 15 s, 2 retry, User-Agent browser).
2. **Filtro 24 ore**: per i feed senza date si usa `state/visti.json`.
3. **Pulizia**: HTML, link, "Leggi tutto", firme, spazi doppi, troncamento a frase.
4. **Clustering**: normalizzazione dei titoli, similarità SequenceMatcher +
   Jaccard, union-find. Si contano le testate distinte, non gli articoli.
5. **Selezione**: copertine solo da categorie attive, secondarie bilanciate a
   rotazione, blocco Buone notizie in chiusura. Evita notizie quasi identiche.
6. **Arricchimento**: testo completo dei massimo 20 articoli scelti, con robots,
   cache, SSRF e fallback al summary.
7. **Copione**: Gemini con JSON strutturato; se manca la chiave, la quota o la
   risposta non è valida, fallback locale con frasi pulite dai summary. Il
   corpo non contiene saluto: l'incipit viene aggiunto dopo. Le Buone notizie
   vengono riordinate prima dell'outro anche se il modello le mette all'inizio.
8. **Controllo stile**: espressioni fatte, frasi oltre 35 parole, parentesi,
   markdown, ripetizioni. Sono avvisi, non blocchi.
9. **TTS**: Gemini TTS a chunk, `atempo`, pause, concatenazione e mastering
   ffmpeg; fallback automatico a edge-tts su errore/quota.
10. **Feed e player**: `docs/feed.xml` RSS 2.0 con namespace iTunes,
    `docs/index.html` con player mobile, voce, velocità e motore TTS.

## Gemini (facoltativo)

Senza chiave il programma funziona già, in modalità fallback. Per usare Gemini:

1. crea una chiave API gratuita in Google AI Studio;
2. in PowerShell, solo per la sessione corrente:

```powershell
$env:GEMINI_API_KEY = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY','User')
.\.venv\Scripts\python.exe main.py --test-llm
```

La chiave si carica dal registro utente e non viene mai scritta su file.

Se il test risponde, lancia il notiziario normalmente. Il modello predefinito è
`gemini-2.5-flash`, configurabile in `config/impostazioni.json`. La chiamata usa
l'endpoint REST `generativelanguage.googleapis.com` con `requests`, senza SDK
pesanti. La chiave non va mai scritta nel repository o nei file di configurazione.

La riserva testo è `llm_modello_riserva`, oggi `gemini-3.1-flash-lite`: viene
usata **solo** dopo un errore/429 del primario, mai a rotazione. Se anche la
riserva è troppo corta rispetto al materiale arricchito, si passa al fallback
deterministico e lo stato riporta modello e motivo.

Il free tier può avere limiti di quota. Il programma scrive il messaggio esatto
(per esempio `HTTP 429: quota exceeded`) nel log e usa il fallback, senza
bloccare l'episodio. `--test-modelli` elenca i modelli visibili e fa una sola
chiamata minima per candidato testo/TTS, con pausa:

```powershell
.\.venv\Scripts\python.exe main.py --test-modelli
```

Strategia quota: un episodio al giorno richiede poche chiamate testo e, con
chunk 4500, poche chiamate TTS. Se la quota gratuita TTS non basta, l'intero
episodio passa a edge-tts (mai voci miste). In futuro si può valutare un billing
minimo, Azure free tier o un motore open source come Chatterbox, senza assumere
prezzi o disponibilità.

## Feed e player locali

Dopo una run completa vengono aggiornati `docs/feed.xml` e `docs/index.html`.
`feed.sito_url` è `https://jakephobia.github.io/notiziario/` e
`feed.base_url` punta agli asset della release GitHub: nessun placeholder.
`--feed-site-url` sostituisce il sito e normalizza il caso speciale
`owner.github.io/owner.github.io`. Per provare il player con l'mp3 locale:

```powershell
.\scripts\esegui.ps1 --durata svelto --feed-base-url http://localhost:8000/output
.\scripts\anteprima-sito.ps1
```

Poi apri `http://localhost:8000/docs/`. Il server deve partire dalla cartella
del progetto, così `/output/` è raggiungibile. In cloud il workflow sostituisce
`base_url` con gli allegati della release GitHub.

## Interfaccia unica e impostazioni

`docs/index.html` unisce player, elenco episodi e una sezione **Impostazioni**:
categorie attive come chip, incipit, voce, velocità, motore TTS e data
dell'ultimo aggiornamento. La sezione legge `docs/impostazioni.json`; se
manca o è invalido usa i dati del feed e non rompe la pagina. Il pulsante
“Modifica impostazioni” apre la issue configurata in una nuova scheda; senza
issue mostra un link discreto al repository.

`docs/impostazioni.json` è generato a ogni run con i valori effettivi
dell'episodio (categorie, incipit template/risolto, voce, velocità, motore,
outro, suono, nome, motore usato, motore richiesto, numero fonti totali/attive, data, URL
issue/repo). Se Gemini TTS fallisce e si usa edge, il JSON riporta
`motore: edge` e `motore_richiesto: gemini`; la pagina mostra entrambi.
Inizialmente è già
presente con i default, così la pagina funziona subito. Le modifiche si salvano
dalla dashboard GitHub e vengono applicate al run successivo.

## Dashboard GitHub

La issue **#1** del repository è il punto unico di configurazione. Formato:

```markdown
## Nome
nome: Jacopo

## Categorie
- [x] Italia
...
- [ ] Sport

## Incipit
Ciao [NOME UTENTE], ecco le tue notizie del giorno. Oggi è il [DATA].

## Voce
voce: Kore
velocita: 1.1
motore: gemini

## Suono
suono: ding

## Outro
Queste erano le notizie di oggi. A domani con i principali eventi della giornata!

## Fonti
- [x] ANSA (italia) — https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml
- [ ] Corriere (italia) — https://...

## Import feed
Incolla qui un OPML o una URL per riga. Le nuove fonti vengono importate spente.
```

Comandi:

```powershell
# Applica Nome/Fonti/Import/Suono/Outro dalla issue e aggiorna la issue
.\.venv\Scripts\python.exe -m notiziario.dashboard --applica

# Mostra le modifiche senza scrivere né aggiornare la issue
.\.venv\Scripts\python.exe -m notiziario.dashboard --applica --dry-run

# Genera il markdown completo dalla config attuale
.\.venv\Scripts\python.exe -m notiziario.dashboard --genera-corpo --out output/issue-dashboard.md
```

`--applica` richiede `GITHUB_TOKEN`, `GITHUB_REPOSITORY` e
`GITHUB_ISSUE_CATEGORIE`; applica Nome, Fonti, Import, Suono e Outro e il
workflow lo esegue prima di generare l'episodio,
con `issues: write`, e non blocca la run se la issue non è raggiungibile.
Nome e Fonti sono conservativi: le sezioni malformate non vengono toccate.
L'import crea solo fonti nuove, le verifica per un massimo di 20 feed (timeout
10 s, 8 worker), scarta i podcast e sostituisce la sezione con
`Import completato: N aggiunte, M duplicate, K scartate.` per evitare
reimportazioni. Le nuove fonti restano spente e vengono aggiunte in fondo a
`## Fonti`. La sezione Import non viene riscritta se è vuota o solo un
segnaposto.

`--genera-corpo` è utile per preparare il corpo della issue con
`gh issue edit --body-file`; il file `output/issue-dashboard.md` è un esempio
generato dalla config locale.

## Copertina, feed e robots

`docs/copertina.png` è una PNG quadrata 1400x1400 RGB, con titolo
“NOTIZIARIO” e sottotitolo “Le notizie del giorno”. Il feed include sia
`<image><url>` sia `<itunes:image href>` con URL assoluto
`https://jakephobia.github.io/notiziario/copertina.png`, anche prima del
primo episodio. Titolo podcast: “Il notiziario di Jacopo”.

`docs/robots.txt` contiene `User-agent: *` e `Disallow: /`: il sito non deve
essere indicizzato. `docs/` non contiene URL segnaposto.

## Cloud: GitHub Actions e Pages

Il workflow è `.github/workflows/notiziario.yml`. Non è stato eseguito in questo
ambiente; per attivarlo servono:

1. un account GitHub e un repository con questi file;
2. **Settings → Pages → Source: GitHub Actions**;
3. **Settings → Actions → General → Workflow permissions: Read and write**
   (il workflow dichiara già `contents: write`, ma il repository deve permettere
   il push del bot);
4. il secret **`GEMINI_API_KEY`** (facoltativo: senza, si usa il fallback);
5. la variabile **`GITHUB_ISSUE_CATEGORIE`** con il numero della issue #1.
   La stessa issue contiene Nome, Categorie, Incipit, Voce, Fonti e Import.

Il workflow:

- parte ogni giorno alle **05:30 UTC** (06:30 in Italia con l'ora solare,
  07:30 con l'ora legale) e si può lanciare a mano con `workflow_dispatch`,
  scegliendo `svelto`, `standard` o `completo`;
- installa Python 3.12 e ffmpeg su Ubuntu;
- applica la dashboard (`python -m notiziario.dashboard --applica`) prima di
  generare: se la issue non è raggiungibile, avvisa e prosegue con la config
  esistente;
- esegue `python main.py`;
- crea o aggiorna la release `episodio-AAAA-MM-GG` (data Europe/Rome) e allega
  l'mp3 tramite `notiziario/pubblica.py`; il passo è **bloccante**;
- verifica con una HEAD che l'URL enclosure della release risponda 200; se non
  risponde, la run fallisce e non committa né deploya;
- aggiorna `docs/feed.xml` (storico massimo 60 episodi), `docs/storico.json` e
  `docs/index.html`, con `sito_url` reale derivato da `GITHUB_REPOSITORY`
  (`https://owner.github.io/repo/`, con caso speciale `owner.github.io`), poi
  committa e pusha **`docs/`, `state/visti.json` e `config/`**;
- pubblica `docs/` su GitHub Pages solo dopo release, verifica HEAD e commit.

C'è anche un workflow manuale separato `.github/workflows/anteprima-voce.yml`:
scegli voce, velocità e frase, scarica l'mp3 come artifact, senza episodio.
`.github/workflows/tests.yml` esegue pytest su push e pull request (Python 3.12),
senza segreti.

Permessi usati: `contents: write`, `pages: write`, `id-token: write`,
`issues: write`. La concurrency evita due run sovrapposte. Le action sono
pinnate ai tag major (`@v4`, `@v5`, `@v3`): rischio basso di supply chain,
documentato; non sono stati inventati SHA.

Se un feed è KO o Gemini non risponde, la run continua e produce comunque
l'mp3. Se Gemini TTS è in quota, si passa a edge-tts e lo stato lo dice. Se
falliscono sia Gemini TTS sia edge-tts, o il fetch totale, la run esce con
errore e non pubblica un episodio incompleto. Se tutti i feed senza date sono già in rubrica, anche con altri feed KO per
“nessun articolo valido”, la run termina con `Nessuna novità` e non crea un
episodio.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
```

I test non usano la rete e coprono: categorie, incipit e marker, voce/velocità
dalla issue, TTS Gemini (PCM mock, header, chunk, atempo, fallback 429), edge,
pulizia e normalizzazione TTS, clustering con blocking, selezione con copertine
attive e Buone notizie in chiusura, fallback e AI (mock), controllo stile, feed
XML con sito reale, storico, player, fonte rotta, no-news, first_seen/cold
start/pruning, controllo anti-block con `testo-breve`, arricchimento con robots,
paywall, cache, SSRF e redirect (302 loopback rifiutato), release/verifica HEAD,
silenzio iniziale automatico, copertina 1400x1400, feed con immagine, workflow
blocking, benchmark clustering, policy `--attiva-tutte`/`--disattiva-non-ok`,
import OPML/TXT/CSV/JSON e regressioni QA.

Controllo stile manuale di un copione:

```powershell
.\.venv\Scripts\python.exe -m notiziario.stile output\copione-AAAA-MM-GG.txt
```

## Risultato della verifica locale (22 novembre 2026)

- `pytest`: **211 test passati**.
- `--test-llm`: Gemini 2.5 Flash ha risposto con la chiave letta dal registro
  utente (nessuna chiave scritta su file).
- Run standard finale: 31 fonti attive, 22 feed OK e 9 KO solo per assenza di
  articoli nelle 24 ore; 264 articoli, 246 cluster, 2 multi-fonte.
- **Arricchimento standard: 11 articoli provati, 10 arricchiti, 1 parziale,
  20.025 caratteri.**
- Copione standard: **1040 parole**, target 1295, divario 255; 10 notizie
  (2 copertine, 2 Buone notizie); **0 avvisi di stile**; incipit esatto
  `Ciao Jacopo, ecco le tue notizie del giorno. Oggi è il 22 novembre.`
  Modalità: fallback deterministico arricchito, perché il primario ha dato 429
  e la riserva ha prodotto un testo troppo corto rispetto al materiale.
- Mp3 standard: `output/notiziario-2026-11-22.mp3`, **428,14 s (7 min 8 s)**,
  5.138.435 byte, mp3 44.100 Hz mono ~96 kbps, velocità **1.1**, silenzio
  iniziale 1 s incluso. TTS richiesto Gemini Kore, **usato edge-tts** dopo
  429 per l'intero episodio (nessuna voce mista).
- Run svelto finale: **472 parole**, target 740, divario 268; 6 notizie
  (1 copertina, 2 Buone notizie); **0 avvisi di stile**; testo con modello
  primario `gemini-2.5-flash` (459 parole di corpo); mp3 214,21 s (3 min 34 s),
  2.571.434 byte; arricchimento 6/7, 1 parziale; TTS edge per quota.
- Benchmark clustering: 200 fonti × 10 articoli = 2000 articoli in **0,01 s**;
  cap 30 per feed URL e 3000 totali, blocking su token rari.
- Controllo anti-block: 31 fonti, **25 OK, 5 `testo-breve`, 1
  `campione-insufficiente`**, 0 paywall, 0 podcast, 0 inattivi. ANSA non viene
  spenta da `--disattiva-non-ok` per `testo-breve`.
- Anteprime reali con silenzio iniziale verificato:

| File | Durata | Motore | Primi 950 ms |
|---|---:|---|---|
| `output/anteprima/anteprima-Kore-1.1.mp3` | 14,86 s | edge (quota) | -91 dB |
| `output/anteprima/anteprima-Kore-1.25.mp3` | 13,20 s | edge (quota) | -91 dB |
| `output/anteprima/anteprima-it-IT-IsabellaNeural-0.75.mp3` | 21,32 s | edge forzato | -91 dB |
- `--test-modelli` (65 modelli visibili):

| Tipo | Modello | Esito | Latenza |
|---|---|---|---:|
| testo | `gemini-2.5-flash` | ok | 0,67 s |
| testo | `gemini-3.1-flash-lite` | ok | 0,70 s |
| testo | `gemini-2.5-flash-lite` | HTTP 404 (non più disponibile) | 0,45 s |
| testo | `gemini-3-flash-preview` | ok (risposta vuota col limite 16 token) | 0,97 s |
| TTS | `gemini-2.5-flash-preview-tts` | HTTP 429 quota | 0,42 s |
| TTS | `gemini-2.5-pro-preview-tts` | HTTP 429 quota | 0,45 s |

- Feed iniziale: `docs/feed.xml` valido con **0 episodi**, copertina e titolo;
  dopo una run reale la durata dell'episodio è 00:07:08, con voce, velocità
  1.1 e motore TTS; `docs/index.html` con player, voce e velocità.
- Import OPML reale: titolo whitespace → host `ilpost.it`, categoria mancante
  `da-assegnare`, `--attiva-tutte` non l'ha attivata, avviso nel report.
- Fonte rotta: un URL irraggiungibile produce `Feed KO` e la pipeline termina
  con exit code 0 **solo** quando l'episodio è valido o non ci sono novità; errori
bloccanti escono con codice 1.

Per riprodurre:

```powershell
.\.venv\Scripts\python.exe -m pytest
$env:GEMINI_API_KEY = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY','User')
.\scripts\esegui.ps1 --test-llm
.\scripts\esegui.ps1 --durata standard
.\scripts\esegui.ps1 --durata svelto
.\scripts\esegui.ps1 --controlla-feed
```

## Limiti e uso personale

- Le pagine articolo vengono scaricate solo per i massimo 20 articoli scelti,
  con robots, cache, SSRF e fallback al summary. Non è scraping dell'intero
  sito.
- Con l'arricchimento e velocità 1.1 la run standard finale è risultata di
  **7 min 8 s** (target ~7 min) e la svelto di **3 min 34 s** (target ~4 min),
  silenzio iniziale di 1 s incluso. Il divario dal budget parole è riportato
  nello stato (`target_parole`, `divario_parole`); il programma non riempie
  con fatti inventati.
- Gemini TTS free tier può andare in 429/quota: nei test Kore ha funzionato per
  un'anteprima, poi la run completa ha usato edge-tts. Il motivo esatto è nello
  stato e nel log. Con il fallback l'intero episodio viene rigenerato con edge:
  non ci sono voci miste, anche se Gemini aveva prodotto i primi chunk.
- Il controllo anti-block segnala 5 feed ANSA come `testo-breve` (summary reali
  ma corti) e 1 come `campione-insufficiente`. Non vengono spenti da
  `--disattiva-non-ok` quando sono `testo-breve`.
- Senza AI il blocco Buone notizie usa solo i due feed dedicati: se non hanno
  articoli nelle 24 ore, il blocco viene saltato (non inventato).
- Le due Buone notizie possono restare più brevi del target 90-130 parole perché
  il materiale disponibile è limitato o parziale. Il divario è tracciato, non
  riempito con fatti inventati. Anche la riserva testo può produrre meno del
  budget: in quel caso scatta il fallback deterministico arricchito.
- Il clustering è euristico: può unire due notizie simili o lasciare separati
  due articoli dello stesso evento. La soglia è configurabile.
- Il fallback locale è volutamente prudente: non inventa fatti, quindi può
  risultare più asciutto di Gemini. Anche il testo AI va riletto: il modello
  può aggiungere frasi di raccordo generiche; il controllo stile non verifica
  la verità di ogni dettaglio.
- edge-tts richiede internet e il servizio può cambiare. In caso di errore il
  programma lo dice e non declassa la voce in silenzio.
- Gemini free tier ha quote e limiti; non c'è alcuna garanzia di disponibilità.
- Il podcast è per uso personale. Le notizie restano delle testate citate;
  verifica le condizioni d'uso delle fonti prima di una pubblicazione ampia.
- GitHub Pages rende pubblico il sito e il feed. Non inserire dati personali.

## Sicurezza

- Nessuna chiave o token nel codice, nei test o nella configurazione.
- `GEMINI_API_KEY` si carica dal registro utente con
  `[Environment]::GetEnvironmentVariable('GEMINI_API_KEY','User')`; non va
  scritta nel repository. `GITHUB_TOKEN` arriva da GitHub Actions o da una
  variabile d'ambiente locale.
- Gemini (testo e TTS) usa l'header `x-goog-api-key`, mai la chiave in query.
- Nessun segreto viene scritto nei log; gli errori HTTP di Gemini vengono
  ripuliti prima di essere registrati.
- Le richieste hanno timeout e retry; una fonte rotta non ferma le altre.
- I feed scaricati sono limitati a 10 MB; gli articoli arricchiti a 2 MB,
  massimo 3 redirect, solo HTTP/HTTPS e host pubblici (blocco SSRF di loopback,
  privati e link-local).
- OPML importato con `defusedxml`; il file locale è limitato a 5 MB e 200 feed.
- `cache/`, `output/qa/`, `docs-qa/` non vanno committati.
- Le query all'API GitHub sono parametrizzate e usano HTTPS.
