# Quartieri di Roma 2026

La nuova geografia amministrativa di Roma su una mappa che si apre nel browser: 334 quartieri urbani, 22 rioni, 101 zone funzionali e 15 municipi, come da deliberazione n. 150/2026 dell'Assemblea Capitolina. Si può cercare una via nello stradario, aprire un'area per vedere i servizi al suo interno e calcolare cosa si raggiunge a piedi in circa 15 minuti da un punto. La mappa si vede in 2D (Leaflet) e in 3D inclinata (MapLibre GL).

È un progetto di Urbe Hub con i dati aperti di Roma Capitale. Progetto indipendente: non è un servizio di Roma Capitale. Per i confini ufficiali vale la deliberazione n. 150/2026.

Il risultato del build è una cartella statica: nessun server applicativo, nessun database, nessun cookie e nessun servizio di statistiche.

## Come si costruisce

Serve Python 3.9 o successivo. Il build usa solo la libreria standard.

```bash
python3 build.py
```

Scrive la cartella `dist/`:

- `index.html`: il bundle autoportante (mappa, dati dei confini, Leaflet, font e logo), circa 1 MB, 0,34 MB compressi
- `strade/`: lo stradario, caricato solo quando si cerca una via (circa 4 MB)
- `servizi/servizi.json`: i servizi del focus e dei 15 minuti, un file solo (circa 0,6 MB)
- `rete/`: la rete pedonale in riquadri, caricata solo attorno al punto scelto (circa 20 MB)
- `3d/`: MapLibre GL (con la sua licenza) e il modulo della vista 3D, scaricati solo al primo tocco su "3D"
- `OFL.txt` e `leaflet-LICENSE.txt`: le licenze del font Montserrat e di Leaflet
- `og.png`: l'immagine di anteprima per i social
- `vercel.json`: header di cache e di sicurezza, per chi pubblica su Vercel

Opzioni:

- `python3 build.py --produzione`: costruisce la versione indicizzabile (senza meta noindex e senza l'header X-Robots-Tag). Fallisce se manca la rete pedonale.
- `MAPPA_DIST=/percorso/uscita python3 build.py`: scrive in una cartella diversa da `dist/`, senza toccare quella esistente.

Senza opzioni il build produce una versione di anteprima con noindex, adatta a essere provata prima di pubblicare.

### Anteprima in locale

Va servita via HTTP, non aprendo il file:

```bash
cd dist && python3 -m http.server 8731 --bind 127.0.0.1
```

poi si apre `http://localhost:8731/index.html`.

### La città dei 15 minuti

Il pulsante "A piedi in 15 minuti" calcola, da un punto sulla mappa (un tocco, una via cercata, "Dove sono" o un link `#15=lat,lon`), le strade raggiungibili a piedi in circa 15 minuti e i servizi lungo il percorso. Il calcolo gira nel browser, a 4,8 km/h sulla rete pedonale.

La rete pedonale è ricavata da OpenStreetMap e pesa circa 20 MB, per questo non sta nel repository. Per averla:

```bash
pip install osmium
python3 prepara_rete_pedonale.py centro-latest.osm.pbf
```

L'estratto dell'Italia centrale si scarica da `https://download.geofabrik.de/europe/italy/centro-latest.osm.pbf`. Lo script scrive `data/rete/` (circa 1.175 riquadri). Senza quella cartella il build di anteprima non si ferma: avvisa e la mappa esce senza il pulsante dei 15 minuti, mentre un link `#15=` apre la mappa normale con un avviso.

## Test

```bash
pip install -r requirements-dev.txt
python3 -m pytest -q
```

I test unitari verificano il build: il meta noindex e l'header X-Robots-Tag in anteprima e in produzione, gli header di sicurezza, il fallimento del build di produzione senza `data/rete/` e la presenza dei file di licenza. Il controllo sul bundle `check_zero_footprint.py` (termini vietati, eccezioni per gli omonimi, file di termini locale facoltativo) lo esegue il build sul file finale.

## Pubblicare

`dist/` è una cartella statica: va caricata per intero su un hosting statico (Vercel, Netlify, Cloudflare Pages, S3 con CDN e simili). Il bundle carica strade, servizi e rete con un parametro `?v=<hash>`: quei file si possono servire con cache lunga e immutabile, mentre `index.html` va servito con revalidazione. Chi non usa Vercel deve riprodurre a mano gli header di `dist/vercel.json`.

La pagina si può incorporare in un iframe: non è imposto alcun blocco al framing.

## Dati e rigenerazione

I dati sono già pronti in `data/`: confini di quartieri e municipi, stradario, servizi, scuole e presidi. Il build usa solo quei file.

Gli script `importa_dati.py`, `importa_servizi.py`, `prepara_scuole.py`, `prepara_servizi_15_minuti.py` e `prepara_rete_pedonale.py` descrivono come sono stati ottenuti, partendo dai servizi WFS del geoportale di Roma Capitale, dall'anagrafe del Ministero dell'Istruzione e del Merito e dall'estratto OpenStreetMap. Due script prendono la cartella delle fonti da riga di comando: `prepara_servizi_15_minuti.py <cartella fonti> [civici_*.csv ...]` (o con la variabile `MAPPA_FONTI`) e `icone/prepara_icone_app.py [<cartella illustrazioni>]` (o `MAPPA_ILLUSTRAZIONI`). Per le farmacie, `importa_servizi.py --solo-farmacie` porta un file scritto col formato precedente a nome "Farmacia" con l'indirizzo nel campo apposito, senza rete.

Rigenerare i dati dipende da fonti esterne che non sono incluse in questo repository (estratti, elenchi dei civici, file degli enti), quindi non fa parte del normale ciclo di build.

Una nota sullo stradario: in `data/strade/` (14.908 vie) manca Via Cassia Antica, perché lo strato DIPPC:stradario_municipio del geoportale non la contiene (esistono solo Via Cassia e Via Cassia Nuova). Chi la cerca non la trova. Le altre tre vie segnalate sono presenti con grafia diversa da quella del Ministero: Via Romolo Trinchieri, Via Cinigiano e Via Monte Manno. Se il Comune aggiunge Via Cassia Antica, basta rigenerare lo stradario.

Nella fonte GeoRoma sette nomi di quartiere usano l'apostrofo al posto dell'accento (per esempio "LAMARO - CINECITTA'"). Lo script `importa_dati.py` li corregge all'importazione, e il build li corregge anche nel bundle, quindi la mappa mostra i nomi con l'accento.

## Fonti e licenze

Il codice è sotto licenza MIT (vedi `LICENSE`). I dati, le librerie e i font hanno ciascuno la propria licenza, elencata in `THIRD_PARTY.md`: GeoRoma di Roma Capitale, OpenStreetMap (ODbL), Ministero dell'Istruzione e del Merito (IODL 2.0), AGENAS, Regione Lazio, Leaflet, MapLibre GL e il font Montserrat. Il nome e il logo di Urbe Hub non sono coperti dalla licenza MIT.

## Mappa di base

La mappa di base usa le tile di OpenStreetMap (`tile.openstreetmap.org`), con la dicitura © OpenStreetMap contributors. L'indirizzo delle tile compare in due punti: nel template `mappa-quartieri.template.html` per la vista 2D e in `vista-3d/vista-3d.js` per la 3D (che accetta anche un valore in `window.MAPPA_TILE_URL`). Il server pubblico di OpenStreetMap è pensato per un uso leggero: una visita genera decine di richieste (circa 28 in 2D, circa 87 in 3D), quindi se il traffico cresce conviene passare a un fornitore di tile con un piano adatto. Per farlo si cambia l'indirizzo in entrambi i punti e si aggiorna l'elenco degli host consentiti nell'header Content-Security-Policy-Report-Only, che in `build.py` (funzione `config_vercel`) cita `https://tile.openstreetmap.org`.

## Uso su telefono

Sotto i 720 px di larghezza la mappa cambia cornice, e il desktop resta com'è:

- la testata sta in una riga, con i tasti (i) e (?)
- sulla mappa restano la barra con indietro, ricerca (aree e vie) e 2D | 3D, e il tasto posizione
- in basso il cartiglio con Elenco e Livelli
- la scheda d'area è un foglio basso (Servizi, 15 minuti, Condividi) che si tira su per i dettagli
- Servizi e Livelli sono fogli a parte: il foglio Servizi prende il posto della scheda, con le categorie spente di partenza, mentre il foglio Livelli porta legenda e filtri per tipo
- ogni foglio ha una maniglia: un tocco lo alza o lo abbassa, trascinarlo in giù lo abbassa di un gradino

La stessa cornice vale in 3D.

## La scheda del servizio

Un clic o un tocco su un'icona dei servizi, o su una voce dell'elenco di un grappolo, apre la scheda del servizio: su desktop un riquadro ancorato all'icona, su telefono un foglio dal basso. Mostra categoria, nome, indirizzo, area e municipio. Per le scuole aggiunge, quando ci sono, l'istituto di riferimento, i posti e le sezioni dei nidi e delle infanzie comunali, un eventuale avviso di chiusura per lavori, il sito e il collegamento a Scuola in Chiaro. Dalla scheda parte il calcolo dei 15 minuti dal servizio stesso.

## Struttura

```
build.py                         builder: inlina dati, Leaflet, font e logo, esegue il controllo finale
mappa-quartieri.template.html    template unico (veste e logica della mappa)
vista-3d/                        modulo della vista 3D e aggancio alla 2D
vendor/                          Leaflet, MapLibre GL, font Montserrat, con le rispettive licenze
brand/                           logo Urbe Hub (escluso dalla licenza MIT)
icone/                           icone dei servizi (SVG) e lo script che le prepara
data/                            dati pronti per il build
check_zero_footprint.py          controllo sul bundle, eseguito dal build
test_build.py                    test del build
test_zero_footprint.py           test del controllo
importa_dati.py                  confini e stradario, da WFS di Roma Capitale
importa_servizi.py               Piano dei Servizi, unito a scuole e presidi
prepara_scuole.py                scuole e nidi (con --dettagli per le schede)
prepara_servizi_15_minuti.py     case della comunità e pronto soccorso
prepara_rete_pedonale.py         rete pedonale da OpenStreetMap
```

## Contatti

hello@urbe.build
