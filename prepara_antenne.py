#!/usr/bin/env python3
"""
Antenne di telefonia mobile (stazioni radio base) dei Municipi II e V di Roma Capitale.

Fonti: gli elenchi delle pratiche che i Municipi pubblicano ai sensi della Deliberazione
dell'Assemblea Capitolina n. 27 del 27/09/2024 (comune.roma.it):
  - Municipio II: tre pagine HTML (2024, 2025, 2026) con una tabella protocollo | societa' |
    ubicazione e coordinate | tipo di intervento;
  - Municipio V: dieci PDF con testo (blocchi "Cod./Nome Sito ... Lat ... Long ..." a sinistra,
    poi gestore, tipologia, protocollo), letti con "pdftotext -layout".
Sono pratiche presentate, NON un censimento degli impianti attivi.

Le coordinate dichiarate sono scritte in formati misti: decimali (col punto o la virgola),
gradi/minuti/secondi veri e, molto spesso nel II, GRADI DECIMALI SCRITTI COI SIMBOLI DI
GRADI/MINUTI/SECONDI: `41°91'29.62" N 12°50'46.14"` vuol dire 41.912962, 12.504614 (gradi +
"." + minuti a due cifre + cifre dei secondi senza il punto). Il formato si decide sulla COPPIA
(la longitudine mascherata ha "minuti" 47-53, formalmente validi), con questa regola: per ogni
pratica si generano le interpretazioni candidate della coppia (dms, decimale scritto dms,
decimale), si scartano quelle fuori dal Comune e si sceglie quella piu' vicina al civico ufficiale
dell'indirizzo (o, se il civico non si trova, all'asse della via; se nemmeno la via si trova,
quella dentro il municipio dichiarato). I refusi nelle cifre non si indovinano mai: se nessuna
interpretazione e' coerente, le coordinate dichiarate restano com'erano e la posizione viene
dal civico ufficiale.

Civici ufficiali: WFS GeoRoma DIPCUL:GeoromaCiviciLocator (Roma Capitale), uno per municipio.
Si tengono i civici con STATO "UFFICIALE"; i "SEGNALATO" (segnalati dai cittadini/OSM, non
verificati) servono solo come ultima risorsa quando un civico non c'e' fra gli ufficiali.

Uso:
    python3 prepara_antenne.py --scarica   scarica le fonti in fonti-antenne/ (con manifest.json)
    python3 prepara_antenne.py             rielabora dalle fonti gia' scaricate
Scrive data/antenne/antenne.json e data/antenne/civici.json (indice dei civici per la ricerca
per indirizzo). I file scaricati sono dati non fidati: si leggono, non si eseguono mai.
"""

import argparse
import datetime
import hashlib
import json
import math
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # anche con python3 -I

from prepara_scuole import ABBREVIAZIONI_PUNTATE, Vie, chiave, senza_accenti, titolo  # noqa: E402

RADICE = Path(__file__).resolve().parent
DIR_FONTI = RADICE / "fonti-antenne"
OUT_ANTENNE = RADICE / "data" / "antenne" / "antenne.json"
OUT_CIVICI = RADICE / "data" / "antenne" / "civici.json"
MUNICIPI_PATH = RADICE / "data" / "municipi-roma.geojson"
STRADE_PATH = {"II": RADICE / "data" / "strade" / "m2.json", "V": RADICE / "data" / "strade" / "m5.json"}
SERVIZI_PATH = RADICE / "data" / "servizi" / "servizi.json"

USER_AGENT = "Mozilla/5.0 research-client"
PAUSA_SECONDI = 1.0
BASE_PDF = "https://www.comune.roma.it/web-resources/cms/documents/"
BASE_PAGINA = "https://www.comune.roma.it/web/it/bando-concorso.page?contentId="
WFS = ("https://geoportale.comune.roma.it/geoserver/ows?service=WFS&version=2.0.0&request=GetFeature"
       "&typeNames=DIPCUL:GeoromaCiviciLocator&CQL_FILTER=MUNICIPIO%3D{n}&srsName=EPSG:4326"
       "&outputFormat=csv&propertyName=TOPONIMO,NUMERO_CIVICO,LETTERA,ESPONENTE,STATO,MUNICIPIO,ID_CIVICO,GEOMETRIA"
       "&sortBy=ID_CIVICO")
NUMERO_MUNICIPIO = {"II": 2, "V": 5}

RAGGIO_M = 300
SOGLIA_CONFERMATA_M = 150      # dal civico
SOGLIA_CONFERMATA_VIA_M = 60   # dall'asse della via, se manca il civico
SOGLIA_PLAUSIBILE_M = 400
SOGLIA_SITO_M = 35

AVVERTENZA = ("Elenco delle pratiche pubblicate dai Municipi II e V (installazioni, modifiche, adeguamenti, "
              "dismissioni di stazioni radio base): non e' un censimento degli impianti attivi, e una pratica "
              "non dice se l'impianto sia stato poi realizzato. Le posizioni sono ricavate dalle coordinate "
              "dichiarate e dall'indirizzo, e vanno verificate sulla fonte.")

GRUPPI_SENSIBILI = {
    "scuole": ["nido", "infanzia", "primaria", "media", "superiore"],
    "parchi": ["parchi_e_aree_gioco"],
    "sanita": ["pronto_soccorso", "pronto_soccorso_pediatrico", "pronto_soccorso_specialistico", "sanita",
               "casa_comunita"],
    "anziani": ["centri_anziani"],
}

# Fonti: id, municipio, titolo, url, file scaricato, tipo, anno della tabella (II)
FONTI = [
    {"id": "ii-2026", "municipio": "II", "titolo": "Municipio II - Installazione, adeguamento e modifiche SRB, anno 2026",
     "url": BASE_PAGINA + "BEC1521424", "file": "ii_2026.html", "tipo": "html", "anno": 2026, "attese": 35},
    {"id": "ii-2025", "municipio": "II", "titolo": "Municipio II - Installazione, adeguamento e modifiche SRB, anno 2025",
     "url": BASE_PAGINA + "BEC1313463", "file": "ii_2025.html", "tipo": "html", "anno": 2025, "attese": 57},
    {"id": "ii-2024", "municipio": "II", "titolo": "Municipio II - Installazione e adeguamento SRB, anno 2024",
     "url": BASE_PAGINA + "BEC1125664", "file": "ii_2024.html", "tipo": "html", "anno": 2024, "attese": 73},
]
for _id, _nome, _titolo, _attese in [
    ("v-2025-giu-set", "GIU_LUG__AGO_SETTTabella_SRB", "Municipio V - Elenco interventi 2025, giugno-settembre", 9),
    ("v-2025-ott-dic", "OTT_NOV_DICTabella_SRB", "Municipio V - Elenco interventi 2025, ottobre-dicembre", 11),
    ("v-2025-2026-dic-gen", "elencointerventisrb20252026", "Municipio V - Elenco interventi 2025/2026, dicembre-gennaio", 5),
    ("v-2026-gen-mar", "GENNAIO_2026__FEBBRAIO_2026__MARZO_2026__Copia", "Municipio V - Elenco interventi 2026, gennaio-marzo", 8),
    ("v-2026-apr", "SRB_APRILE_2026", "Municipio V - Elenco interventi 2026, aprile", 5),
    ("v-2026-mag-giu", "SRB_MESE_MAGGIO__GIUGNO_2026_1", "Municipio V - Elenco interventi 2026, maggio-giugno", 5),
    ("v-2026-lug", "Elenco_srb_mese_luglio_2026", "Municipio V - Elenco interventi 2026, luglio", 3),
    ("v-2026-ago", "SRB_AGOSTO_2026__Copia", "Municipio V - Elenco interventi 2026, agosto", 2),
    ("v-2026-set", "Elenco_srb_mese_SETTEMBRE_2026__pubblicit", "Municipio V - Elenco interventi 2026, settembre", 3),
    ("v-2026-ott-nov", "ElencosrbmeseOTTOBRENOV2026", "Municipio V - Elenco interventi 2026, ottobre-novembre", 3),
]:
    FONTI.append({"id": _id, "municipio": "V", "titolo": _titolo, "url": BASE_PDF + _nome + ".pdf",
                  "file": "v_" + _nome + ".pdf", "tipo": "pdf", "anno": None, "attese": _attese})

QUALITA_ORDINE = {"confermata": 0, "plausibile": 1, "da_indirizzo": 2, "non_localizzata": 3}
FORMATI = ["dms", "decimale", "decimale_scritto_dms", "assente", "illeggibile"]
GESTORI_CANONICI = ["Iliad", "Fastweb", "Vodafone", "TIM", "WindTre", "Inwit", "Cellnex", "FiberCop"]
MESI_IT = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
           "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}

# Refusi di scrittura nei nomi delle vie delle fonti (chiave "senza accenti, maiuscola" -> via corretta).
# Solo errori di battitura evidenti, ognuno controllato sull'elenco dei civici ufficiali.
CORREZIONI_VIE = {
    "VIALE DELL UNIIVERSITA": "VIALE DELL UNIVERSITA",
    "VIA FELICE GROSSI GRONDI": "VIA FELICE GROSSI GONDI",
    "VIA ALFONSO BORRELLI": "VIA ALFONSO BORELLI",
    "PIAZZA RUGGIERO DI SICILIA": "PIAZZA RUGGERO DI SICILIA",
    "VIALE P DE COUBERTAIN": "VIALE PIETRO DE COUBERTIN",
}

# Anomalie viste a mano nelle fonti e non rilevabili per regola: protocollo -> nota.
NOTE_MANUALI = {
    "CB/10769/2024": "numero di protocollo fuori sequenza rispetto a data e righe vicine (CB/101717 il 09/08/2024): "
                     "probabile refuso nella fonte, non corretto",
}


# ---------------------------------------------------------------- scarico

def sha256(path):
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def scarica_file(url, destinazione, tentativi=3):
    """Scarica un URL e lo scrive su disco. Una richiesta alla volta, con User-Agent generico."""
    ultimo = None
    for t in range(tentativi):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=180) as r:
                dati = r.read()
            destinazione.write_bytes(dati)
            return
        except Exception as e:  # noqa: BLE001 - rete: si riprova e poi si segnala
            ultimo = e
            time.sleep(2 * (t + 1))
    raise SystemExit("Scarico fallito: " + url + " (" + str(ultimo) + ")")


def conta_civici_wfs(n):
    url = (WFS.format(n=n).split("&propertyName")[0].replace("&outputFormat=csv", "") + "&resultType=hits")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        testo = r.read().decode("utf-8", "replace")
    m = re.search(r'numberMatched="(\d+)"', testo)
    return int(m.group(1)) if m else None


def scarica():
    DIR_FONTI.mkdir(exist_ok=True)
    manifest = {}
    oggi = datetime.date.today().isoformat()
    lavori = [(f["file"], f["url"]) for f in FONTI]
    for municipio, n in NUMERO_MUNICIPIO.items():
        lavori.append(("civici_" + municipio + ".csv", WFS.format(n=n) + "&count=200000"))
    for nome, url in lavori:
        print("scarico", nome)
        dest = DIR_FONTI / nome
        scarica_file(url, dest)
        manifest[nome] = {"url": url, "scaricato": oggi, "sha256": sha256(dest)}
        time.sleep(PAUSA_SECONDI)
    # I civici arrivano in una sola pagina: si controlla che siano tutti (numberMatched del WFS).
    for municipio, n in NUMERO_MUNICIPIO.items():
        attesi = conta_civici_wfs(n)
        time.sleep(PAUSA_SECONDI)
        letti = len(leggi_csv(DIR_FONTI / ("civici_" + municipio + ".csv")))
        print("civici", municipio, "righe", letti, "attese", attesi)
        if attesi is not None and letti != attesi:
            raise SystemExit("Civici %s incompleti: %d righe su %d" % (municipio, letti, attesi))
    (DIR_FONTI / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                                             encoding="utf-8")


def leggi_csv(path):
    import csv
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- coordinate

def numeri_in(testo):
    """I numeri di una stringa di coordinata, ignorando simboli e lettere ("41°91'29.62\" N" ->
    ["41", "91", "29.62"]). Una virgola decimale vale come punto solo dentro al numero."""
    return re.findall(r"\d+(?:[.,]\d+)?", testo or "")


def interpretazioni_valore(testo):
    """Le letture possibili di UNA coordinata, per formato: {"dms": x, "decimale_scritto_dms": x,
    "decimale": x}. Il formato giusto si sceglie sulla coppia (vedi candidati_coppia)."""
    nums = numeri_in(testo)
    out = {}
    if len(nums) == 1:
        if re.search(r"[.,]", nums[0]):
            out["decimale"] = float(nums[0].replace(",", "."))
    elif len(nums) in (2, 3):
        g, m = nums[0], nums[1]
        s = nums[2] if len(nums) == 3 else "0"
        if g.isdigit():
            mf, sf = float(m.replace(",", ".")), float(s.replace(",", "."))
            if mf < 60 and sf < 60:
                out["dms"] = int(g) + mf / 60 + sf / 3600
            # gradi decimali scritti coi simboli: gradi "." minuti (2 cifre) + cifre dei secondi
            if m.isdigit() and len(m) == 2:
                cifre_sec = re.sub(r"\D", "", s) if len(nums) == 3 else ""
                out["decimale_scritto_dms"] = float(g + "." + m + cifre_sec)
    return out


def candidati_coppia(testo_lat, testo_lon):
    """Interpretazioni candidate della coppia: [(formato, lat, lon)], solo formati leggibili per
    entrambe le coordinate. Non scarta niente per posizione: lo fa chi sceglie."""
    a, b = interpretazioni_valore(testo_lat), interpretazioni_valore(testo_lon)
    return [(f, round(a[f], 6), round(b[f], 6)) for f in ("dms", "decimale_scritto_dms", "decimale")
            if f in a and f in b]


def formato_sintattico(testo_lat, testo_lon):
    """Il formato in cui la coppia e' scritta, anche se le coordinate non tornano: "assente" se non ci
    sono numeri, "illeggibile" se non si legge in nessun formato, altrimenti il primo formato valido."""
    if not numeri_in(testo_lat) and not numeri_in(testo_lon):
        return "assente"
    c = candidati_coppia(testo_lat, testo_lon)
    return c[0][0] if c else "illeggibile"


def separa_lat_long(testo):
    """Da un blocco di testo con le coordinate a (testo lat, testo lon), o (None, None). Accetta
    "Lat ... Long ...", e due righe senza etichette (41°55'33.08"N / 12°30'24.97"E)."""
    t = re.sub(r"\s+", " ", (testo or "").replace("\xa0", " ")).strip()
    if not t:
        return None, None
    m = re.search(r"\bLong(?:itudine)?\b\.?:?|\bLong(?=\d)", t, flags=re.I)
    if m:
        lat = re.sub(r"^.*?\bLat(?:itudine)?\b\.?:?", "", t[:m.start()], flags=re.I).strip()
        return lat, t[m.end():].strip()
    return None, None


# ---------------------------------------------------------------- geometria

def metri(a, b):
    """Distanza in metri fra due punti (lat, lon): proiezione locale, piu' che sufficiente a Roma."""
    return math.hypot((a[0] - b[0]) * 111200, (a[1] - b[1]) * 111320 * math.cos(math.radians((a[0] + b[0]) / 2)))


def distanza_polilinea(p, linea):
    """Distanza in metri di un punto (lat, lon) da una polilinea [[lon, lat], ...]."""
    k = 111320 * math.cos(math.radians(p[0]))
    px, py = p[1] * k, p[0] * 111200
    migliore = float("inf")
    pts = [(x * k, y * 111200) for x, y in linea]
    if len(pts) == 1:
        return math.hypot(px - pts[0][0], py - pts[0][1])
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        dx, dy = x2 - x1, y2 - y1
        L = dx * dx + dy * dy
        t = 0 if L == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / L))
        migliore = min(migliore, math.hypot(px - (x1 + t * dx), py - (y1 + t * dy)))
    return migliore


def punto_in_anello(lon, lat, anello):
    dentro = False
    j = len(anello) - 1
    for i in range(len(anello)):
        xi, yi = anello[i]
        xj, yj = anello[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def punto_in_poligono(lon, lat, geom):
    poligoni = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    for rings in poligoni:
        if punto_in_anello(lon, lat, rings[0]) and not any(punto_in_anello(lon, lat, r) for r in rings[1:]):
            return True
    return False


class Municipi:
    def __init__(self, path=MUNICIPI_PATH):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        self.geom = {f["properties"]["romano"]: f["geometry"] for f in d["features"]}

    def nel_comune(self, lat, lon):
        return any(punto_in_poligono(lon, lat, g) for g in self.geom.values())

    def nel_municipio(self, municipio, lat, lon):
        return punto_in_poligono(lon, lat, self.geom[municipio])


# ---------------------------------------------------------------- civici e vie

class VieAntenne(Vie):
    """Vie dei civici ufficiali; trova() dice anche perche' non aggancia ("non trovata" o "ambigua")."""

    def trova_motivo(self, via):
        tipo, tok = chiave(via)
        if not tok:
            return None, "via non riconoscibile"
        cand = []
        for v in self.per_ultimo.get(tok[-1], []):
            ctipo, ctok = self.chiavi[v]
            if not self._compatibili(tok, ctok):
                continue
            if ctipo != tipo and {tipo, ctipo} not in ({"VIA", "VIALE"}, {"PIAZZA", "PIAZZALE"}):
                continue    # "via" e "viale" (o "piazza" e "piazzale") si scambiano nelle fonti; il resto no
            peso = (len(ctok) - len(tok)) + (0 if ctipo == tipo else 2)
            if peso <= 3:
                cand.append((peso, v))
        if not cand:
            return None, "via non trovata fra i civici del municipio"
        cand.sort()
        if len(cand) > 1 and cand[0][0] == cand[1][0]:
            return None, "via ambigua (" + ", ".join(sorted(v for _, v in cand[:3])) + ")"
        return cand[0][1], None


def chiave_testo(s):
    return re.sub(r"[^A-Z0-9]+", " ", senza_accenti(s or "").upper()).strip()


def carica_civici_municipio(path):
    """Civici di un municipio: {toponimo: [(numero, lat, lon, lettera, esponente, stato)]}."""
    per_via = defaultdict(list)
    for r in leggi_csv(path):
        m = re.match(r"POINT \(([\d.]+) ([\d.]+)\)", r.get("GEOMETRIA", ""))
        if not m or not r.get("NUMERO_CIVICO"):
            continue
        a, b = float(m.group(1)), float(m.group(2))
        lat, lon = (a, b) if a > 40 else (b, a)
        per_via[r["TOPONIMO"]].append((int(float(r["NUMERO_CIVICO"])), lat, lon, (r.get("LETTERA") or "").upper(),
                                       (r.get("ESPONENTE") or "").upper(), r.get("STATO") or ""))
    return per_via


def stringa_civico(numero, lettera, esponente):
    s = str(numero) + (lettera or "")
    return s + (" " + esponente.lower() if esponente else "")


def forma_via(toponimo):
    """Nome leggibile di un toponimo ufficiale ("VIA DELL`OMO" -> "Via dell'Omo")."""
    t = titolo(toponimo.replace("`", "'").replace("’", "'"))
    t = re.sub(r"(?<=\s)D\u00e8\b", "de'", t)
    t = re.sub(r"(?<=\s)D'(?=[A-Za-z])", "d'", t)
    return re.sub(r"(?<=\s)(Il|Lo|La|Dello|Della|Delle|Degli|Dei|Del|Di|De|Da)\b", lambda m: m.group(1).lower(), t)


class Strade:
    """Assi delle vie da data/strade: nome via -> polilinee, con lo stesso nome normalizzato dei civici."""

    def __init__(self, path):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        self.per_chiave = defaultdict(list)
        for vie in d["quartieri"].values():
            for nome, _id, linee in vie:
                tipo, tok = chiave(nome)
                self.per_chiave[(tipo, tuple(tok))].extend(linee)

    def linee(self, toponimo):
        tipo, tok = chiave(toponimo)
        return self.per_chiave.get((tipo, tuple(tok)), [])

    def distanza(self, toponimo, punto):
        linee = self.linee(toponimo)
        return min((distanza_polilinea(punto, l) for l in linee), default=None)


# ---------------------------------------------------------------- indirizzi

def ripulisci_indirizzo(grezzo):
    """Indirizzo come scritto -> (testo via, civico int|None, lettera, note)."""
    note = []
    s = re.sub(r"\s+", " ", (grezzo or "").replace("\xa0", " ")).strip()
    s = s.replace("’", "'").replace("`", "'")
    s = re.sub(r"\bc/o\b.*$", "", s, flags=re.I).strip(" ,")
    s = re.sub(r"\(.*?\)", " ", s)
    # due vie ("viale Gorizia / via Bosio 13"): il civico e' quello dell'ultima
    m = re.search(r"/\s*((?:via|viale|v\.le|piazza|p\.zza|p\.za|largo|circ\w*\.?)\b.*)$", s, flags=re.I)
    if m:
        note.append("due vie nell'indirizzo originale: si usa la seconda ('" + m.group(1).strip() + "')")
        s = m.group(1).strip()
    s = re.sub(r"[,\s]+(?:sc\.?|scala|int\.?|interno)\s*\w+\s*$", "", s, flags=re.I)
    s = re.sub(r"\bn(?:r|um)?\.?\s*(?=\d)", "", s, flags=re.I)
    s = re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)
    if re.search(r"\b(?:snc|s\.n\.c\.?|km)\b", s, flags=re.I):
        return re.sub(r"[,\s]+(?:snc|s\.n\.c\.?|km)\b.*$", "", s, flags=re.I).strip(" ,"), None, "", note
    m = re.match(r"^(.*?)[\s,]+(\d+)\s*(?:/\s*\d+)?\s*(?:/\s*)?([A-Za-z])?$", s)
    if not m:
        return s.strip(" ,"), None, "", note
    return m.group(1).strip(" ,"), int(m.group(2)), (m.group(3) or "").upper(), note


def espandi_abbreviazioni(via):
    """Via con le abbreviazioni sciolte per il nome leggibile ("V.le" -> "Viale")."""
    s = via
    for regola, esteso in ABBREVIAZIONI_PUNTATE:
        s = re.sub(regola, esteso.capitalize(), s, flags=re.I)
    s = re.sub(r"^\s*p\.?za\b\.?", "Piazza", s, flags=re.I)
    s = re.sub(r"^\s*circ\.?\b\.?", "Circonvallazione", s, flags=re.I)
    return s


# ---------------------------------------------------------------- normalizzazioni

def gestori_da_testo(testo):
    """Da una cella con una o piu' societa' -> (lista di nomi canonici, nomi non riconosciuti)."""
    t = re.sub(r"\s+", " ", (testo or "").replace("\xa0", " ")).strip()
    regole = [("Iliad", r"\bil+iad\b"), ("Fastweb", r"\bfast\s*web\b|\bfatweb\b"), ("Vodafone", r"\bvo[df]afone\b"),
              ("TIM", r"\btim\b|\btelecom\b"), ("WindTre", r"\bwind(?:\s*tre)?\b"), ("Inwit", r"\binwit\b"),
              ("Cellnex", r"\bcellnex\b"), ("FiberCop", r"\bfi[bg]er\s*cop\b")]
    trovati = []
    resto = t
    for nome, rx in regole:
        for m in re.finditer(rx, t, flags=re.I):
            trovati.append((m.start(), nome))
        resto = re.sub(rx, " | ", resto, flags=re.I)
    resto = re.sub(r"\b(?:italia|s\.?\s?p\.?\s?a\.?|spa|s\.?\s?r\.?\s?l\.?|e)\b\.?", " ", resto, flags=re.I)
    altri = []
    for pezzo in re.split(r"[|+/,;\-]", resto):
        p = re.sub(r"\s+", " ", pezzo).strip(" .")
        if re.search(r"[A-Za-z]{3}", p):
            altri.append(p)
    ordine = []
    for _, n in sorted(trovati):
        if n not in ordine:
            ordine.append(n)
    return ordine + altri, altri


def tipologia_da_testo(testo):
    t = re.sub(r"\s+", " ", (testo or "").lower()).strip()
    if "dismission" in t:
        return "dismissione"
    if re.search(r"adeg|modific|riconfigur", t):
        return "adeguamento" if t.startswith("adeg") and "modific" not in t else "modifica"
    if "install" in t or "nuova stazione" in t:
        return "installazione_su_esistente" if re.search(r"su (?:infrastruttura|struttura) esistente|esistente di", t) else "installazione"
    return "altro"


def parse_data_it(testo):
    """Data da "26/01/2024", "2 settembre 2024", "14/012026" (barra mancante) -> (iso|None, nota|None)."""
    t = re.sub(r"\s+", " ", testo or "").strip().lower()
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    nota = None
    if not m:
        m = re.search(r"\b(\d{2})/(\d{2})(\d{4})\b", t)
        if m:
            nota = "data scritta senza una barra ('" + m.group(0) + "'): letta come " + "%s/%s/%s" % m.groups()
    if not m:
        m2 = re.search(r"\b(\d{1,2})\s+([a-z]+)\s+(\d{4})\b", t)
        if m2 and m2.group(2) in MESI_IT:
            m = re.match(r"(\d+),(\d+),(\d+)", "%s,%d,%s" % (m2.group(1), MESI_IT[m2.group(2)], m2.group(3)))
    if not m:
        return None, ("data non interpretabile ('" + t + "')") if t else None
    try:
        return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat(), nota
    except ValueError:
        return None, "data non valida ('" + m.group(0) + "')"


# ---------------------------------------------------------------- lettura Municipio II (HTML)

class TabelleHTML(HTMLParser):
    """Estrae le tabelle: [[cella, ...]] con ogni cella = lista di righe di testo; link in <<url>>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tabelle, self.riga, self.cella = [], None, None
        self.paragrafi, self._p, self._fuori = [], None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.tabelle.append([])
        elif tag == "tr" and self.tabelle:
            self.riga = []
            self.tabelle[-1].append(self.riga)
        elif tag in ("td", "th") and self.riga is not None:
            self.cella = [""]
            self.riga.append(self.cella)
        elif tag in ("br", "p") and self.cella is not None:
            self.cella.append("")
        elif tag == "a" and self.cella is not None and a.get("href"):
            self.cella[-1] += "<<" + a["href"] + ">>"
        if tag == "p" and self.cella is None:
            self._p = ""

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.cella = None
        elif tag == "tr":
            self.riga = None
        elif tag == "p" and self._p is not None:
            self.paragrafi.append(re.sub(r"\s+", " ", self._p).strip())
            self._p = None

    def handle_data(self, d):
        if self.cella is not None:
            self.cella[-1] += d
        elif self._p is not None:
            self._p += d


def righe_cella(cella):
    out = []
    for r in cella:
        for pezzo in r.split("\n"):
            p = re.sub(r"\s+", " ", pezzo.replace("\xa0", " ")).strip()
            if p:
                out.append(p)
    return out


RX_PROT_II = re.compile(r"CB\s*/\s*(\d+)(?:\s*/\s*(\d{4}))?")
RX_RIGA_COORD = re.compile(r"^(?:Lat\b|Long\b)|\d\s*°|^\d{2}[.,]\d{3,}", re.I)


def leggi_municipio_ii(fonte, testo_html):
    p = TabelleHTML()
    p.feed(testo_html)
    tab = p.tabelle[-1]    # nel 2024 la prima tabella e' l'indice d'archivio 2020-2023
    info = {"aggiornata": None, "pubblicata": None, "asterisco": None}
    for par in p.paragrafi:
        m = re.search(r"data di aggiornamento:\s*(\d{2}/\d{2}/\d{4})", par)
        if m:
            info["aggiornata"] = parse_data_it(m.group(1))[0]
        m = re.search(r"data di pubblicazione:\s*(\d{2}/\d{2}/\d{4})", par)
        if m:
            info["pubblicata"] = parse_data_it(m.group(1))[0]
        if par.startswith("*"):
            info["asterisco"] = par
    pratiche, contate = [], 0
    for riga in tab:
        if len(riga) < 4:
            continue
        righe_prot = righe_cella(riga[0])
        prot_testo = " ".join(righe_prot)
        m = RX_PROT_II.search(prot_testo)
        if not m:
            continue
        contate += 1
        note = []
        data_iso, nota_data = parse_data_it(prot_testo[m.end():].replace("*", ""))
        if nota_data:
            note.append(nota_data)
        anno = int(m.group(2)) if m.group(2) else (int(data_iso[:4]) if data_iso else fonte["anno"])
        protocollo = "CB/%s/%d" % (m.group(1), anno)
        if "*" in prot_testo:
            note.append("protocollo con asterisco: " + (info["asterisco"] or "*prot richiesta parere"))
        gest_orig = " ".join(righe_cella(riga[1]))
        righe_ubic = righe_cella(riga[2])
        i_coord = next((i for i, r in enumerate(righe_ubic) if RX_RIGA_COORD.search(r)), len(righe_ubic))
        righe_ind, righe_c = righe_ubic[:i_coord], righe_ubic[i_coord:]
        ind_orig = " ".join(righe_ind)
        if len(righe_ind) > 1:
            # "Parcheggio Quick Roma" + "Via Tripoli 140": la descrizione del luogo non e' l'indirizzo.
            # Un "n.160" o un civico andato a capo restano invece parte dell'indirizzo.
            con_via = [r for r in righe_ind if re.match(r"(?:via|viale|v\.le|piazza|p\.zza|p\.za|largo|circ|lungotevere|corso)\b", r, re.I)]
            if len(con_via) == 1 and any(not re.match(r"(?:n\.?\s*)?\d", r, re.I) and r != con_via[0] for r in righe_ind):
                note.append("ubicazione con piu' righe ('" + ind_orig + "'): si usa '" + con_via[0] + "'")
                righe_ind = [con_via[0]]
        coord_testo = " ".join(righe_c)
        if len(righe_c) == 2 and not re.search(r"\bLong", coord_testo, re.I):
            lat_t, lon_t = righe_c
        else:
            lat_t, lon_t = separa_lat_long(coord_testo)
        doc = None
        if len(riga) > 4:
            m_doc = re.search(r"<<([^>]+)>>", " ".join(righe_cella(riga[4])))
            doc = m_doc.group(1) if m_doc else None
        pratiche.append({
            "fonte_id": fonte["id"], "municipio": "II", "protocollo": protocollo, "numero_protocollo": int(m.group(1)),
            "data_protocollo": data_iso, "anno": anno, "gestore_originale": gest_orig,
            "tipologia_originale": " ".join(righe_cella(riga[3])),
            "indirizzo_originale": ind_orig, "indirizzo_per_aggancio": " ".join(righe_ind),
            "coord_testo": coord_testo, "lat_testo": lat_t, "lon_testo": lon_t, "documento": doc, "note": note,
        })
    return pratiche, contate, info


# ---------------------------------------------------------------- lettura Municipio V (PDF)

RX_PROT_V = re.compile(r"CF/(\d{4})/(\d+)")
RX_TIP_V = re.compile(r"\b(INSTALLAZIONE|Installazione|NUOVA|MODIFICA|ADEGUAMENTO|DISMISSIONE|RICONFIGURAZIONE)\b")
RX_INIZIO_INDIRIZZO = re.compile(r"^(?:Via|Viale|Piazza|Largo|Circonvallazione|Lungotevere|G\.R\.A\.|Strada|Vicolo|Corso)(?![A-Za-z])")


def testo_pdf(path):
    r = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True)
    return r.stdout


def contate_pdf(testo):
    return len(re.findall(r"CF/20\d\d/", testo))


def leggi_municipio_v(fonte, testo):
    righe = testo.replace("\f", "\n").split("\n")
    idx = [i for i, l in enumerate(righe) if RX_PROT_V.search(l)]
    if not idx:
        return [], 0
    fine = next((i for i in range(idx[-1], len(righe)) if re.match(r"\s*(Il Responsabile|La Direttrice|Il Direttore)", righe[i])),
                len(righe))
    blocchi = [righe[a:b] for a, b in zip(idx, idx[1:] + [fine])]
    # colonna dei gestori: la piu' a sinistra fra quelle che compaiono sulla prima riga dei blocchi
    c1 = min(len(m.group(1)) for b in blocchi if (m := re.match(r"^(\s*\S.*?\s{2,})(?=\S)", b[0]))) - 2
    pratiche = []
    for b in blocchi:
        prima = b[0]
        pp = RX_PROT_V.search(prima).start()
        t = RX_TIP_V.search(prima, c1)
        if not t:
            raise SystemExit("Tipologia non trovata in " + fonte["id"] + ": " + prima.strip())
        c2 = t.start()
        sinistra, gest, tip, dest = [], [], [prima[c2:pp].strip()], [prima[pp:]]
        for l, fine_l in [(prima, c2)] + [(x, len(x)) for x in b[1:]]:
            riga_sx = []
            for m in re.finditer(r"\S+(?: \S+)*", l[:fine_l]):
                testo_m = m.group(0)
                if m.start() < c1:
                    riga_sx.append(testo_m)
                elif l is prima:
                    gest.append(testo_m)
                else:
                    # a volte la data del protocollo e' separata dalla tipologia da un solo spazio
                    mdata = re.match(r"^(.*?)\s+(\d{1,2}/\d{1,2}/\d{4})$", testo_m)
                    if mdata and m.start() < pp - 3:
                        testo_m = mdata.group(1)
                        dest.append(mdata.group(2))
                    dest_o_tip = dest if m.start() >= pp - 3 else tip if m.start() >= c2 - 5 else gest
                    dest_o_tip.append(testo_m)
            sinistra.append(" ".join(riga_sx))
        sx = [s.strip() for s in sinistra if s.strip()]
        pratiche.append(_pratica_v(fonte, sx, gest, tip, dest))
    return pratiche, len(idx)


def _pratica_v(fonte, sx, gest, tip, dest):
    note = []
    dest_t = " ".join(d for d in dest if d)
    m = RX_PROT_V.search(dest_t)
    anno, numero = int(m.group(1)), int(m.group(2))
    data_iso, nota_data = parse_data_it(dest_t[m.end():].replace("del", " "))
    if nota_data:
        note.append(nota_data)
    if data_iso and int(data_iso[:4]) != anno:
        note.append("l'anno della data (%s) e' diverso da quello del protocollo (%d)" % (data_iso, anno))
    i_ind = next((i for i, r in enumerate(sx) if i and RX_INIZIO_INDIRIZZO.match(r)), None)
    i_lat = next((i for i, r in enumerate(sx) if re.match(r"Lat\b", r)), None)
    if i_ind is None:
        raise SystemExit("Indirizzo non trovato in " + fonte["id"] + " / " + dest_t)
    i_cat = next((i for i, r in enumerate(sx) if i > i_ind and re.match(r"(?:N\.?C\.?E\.?U|Foglio)", r)), None)
    fine_ind = i_cat if i_cat is not None else (i_lat if i_lat is not None else len(sx))
    ind_orig = re.sub(r"\s+", " ", " ".join(sx[i_ind:fine_ind])).strip()
    nome_grezzo = " ".join(sx[:i_ind])
    codici, nomi = [], []
    for blocco in re.split(r"Cod\./Nome\s*Sito", nome_grezzo)[1:]:
        blocco = re.sub(r"^\s*[^:]{0,22}:", "", blocco).strip()
        if blocco:
            codici.append(re.split(r"\s+", blocco)[0].strip("_-–\"“”"))
            nomi.append(blocco)
    catasto = None
    if i_cat is not None:
        tc = " ".join(sx[i_cat:i_lat if i_lat is not None else len(sx)])
        mf = re.search(r"Foglio\s+(\d+(?:\s?[A-Z]\b)?)", tc)
        mp = re.search(r"(?:P\.lla|Mapp\.?)\s*(?:n\.\s*)?(\d+)", tc)
        if mf and mp:
            catasto = {"foglio": mf.group(1), "particella": mp.group(1)}
        else:
            note.append("dati catastali non leggibili: '" + tc + "'")
    coord_testo = " ".join(sx[i_lat:]) if i_lat is not None else ""
    lat_t, lon_t = separa_lat_long(coord_testo)
    return {
        "fonte_id": fonte["id"], "municipio": "V", "protocollo": "CF/%d/%d" % (anno, numero), "numero_protocollo": numero,
        "data_protocollo": data_iso, "anno": anno, "gestore_originale": re.sub(r"\s+", " ", " ".join(g for g in gest if g)).strip(),
        "tipologia_originale": re.sub(r"\s+", " ", " ".join(x for x in tip if x)).strip(),
        "indirizzo_originale": ind_orig, "indirizzo_per_aggancio": ind_orig,
        "coord_testo": coord_testo, "lat_testo": lat_t, "lon_testo": lon_t, "documento": None, "note": note,
        "codice_sito": codici[0] if codici else None, "codici_sito": codici,
        "nome_sito": " / ".join(nomi) if nomi else None, "catasto": catasto,
    }


# ---------------------------------------------------------------- localizzazione

def scegli_posizione(p, vie, strade, municipi):
    """Completa la pratica con indirizzo agganciato, formato, qualita' e posizione (vedi la regola
    in testa al file). Cambia p sul posto."""
    mun = p["municipio"]
    via_t, num, lettera, nota_ind = ripulisci_indirizzo(p["indirizzo_per_aggancio"])
    p["note"].extend(nota_ind)
    via_t = CORREZIONI_VIE.get(chiave_testo(via_t), via_t)
    toponimo, motivo = vie.trova_motivo(via_t)
    punti_civico, civico_str, nota_civ = [], None, None
    if toponimo:
        punti = vie.per_via[toponimo]
        if num is not None:
            esatti = [q for q in punti if q[0] == num]
            if lettera and any(q[3] == lettera for q in esatti):
                esatti = [q for q in esatti if q[3] == lettera]
            uff = [q for q in esatti if q[5] == "UFFICIALE"]
            if uff:
                punti_civico = uff
            elif esatti:
                punti_civico, nota_civ = esatti, "civico presente solo fra quelli segnalati (non ufficiali)"
            else:
                motivo = "civico %d non presente su %s" % (num, forma_via(toponimo))
            if punti_civico:
                q0 = sorted(punti_civico, key=lambda q: (q[3], q[4]))[0]
                civico_str = str(num) + (lettera if lettera and any(q[3] == lettera for q in punti_civico) else "")
        else:
            motivo = "indirizzo senza numero civico"
    p["_motivo_aggancio"] = None if punti_civico else motivo
    p["_aggancio"] = "civico" if punti_civico else "via" if toponimo else "nessuno"
    if nota_civ:
        p["note"].append(nota_civ)
    # indirizzo leggibile
    if toponimo:
        p["toponimo_ufficiale"] = forma_via(toponimo)
        p["civico"] = civico_str
        p["indirizzo"] = p["toponimo_ufficiale"] + (" " + civico_str if civico_str else
                                                    (" " + str(num) + lettera if num is not None else ""))
    else:
        p["toponimo_ufficiale"] = None
        p["civico"] = None
        base = titolo(espandi_abbreviazioni(via_t)) if via_t else titolo(p["indirizzo_originale"])
        p["indirizzo"] = base + (" " + str(num) + lettera if num is not None else "")
    punto_civico = None
    if punti_civico:
        punto_civico = (sum(q[1] for q in punti_civico) / len(punti_civico), sum(q[2] for q in punti_civico) / len(punti_civico))

    # candidati dichiarati
    lat_t, lon_t = p["lat_testo"], p["lon_testo"]
    p["formato_originale"] = formato_sintattico(lat_t, lon_t) if (lat_t is not None and lon_t is not None) else "assente"
    cands = [c for c in (candidati_coppia(lat_t, lon_t) if p["formato_originale"] not in ("assente", "illeggibile") else [])
             if municipi.nel_comune(c[1], c[2])]
    p["coord_dichiarate"] = {"testo": p["coord_testo"] or None, "lat": None, "lon": None, "nel_municipio": None}

    def dist_civico(c):
        return min(metri((c[1], c[2]), (q[1], q[2])) for q in punti_civico) if punti_civico else None

    def dist_via(c):
        return strade.distanza(toponimo, (c[1], c[2])) if toponimo else None

    ref_civico = bool(punti_civico)
    ref_via = (not ref_civico) and bool(toponimo)
    if cands:
        if ref_civico:
            scelto = min(cands, key=dist_civico)
        elif ref_via:
            scelto = min(cands, key=lambda c: (dist_via(c) if dist_via(c) is not None else 1e9))
        else:
            scelto = sorted(cands, key=lambda c: (not municipi.nel_municipio(mun, c[1], c[2]), c[0]))[0]
    else:
        scelto = None
    if scelto:
        p["formato_originale"] = scelto[0]
        p["coord_dichiarate"].update(lat=round(scelto[1], 5), lon=round(scelto[2], 5))
        dc, dv = dist_civico(scelto), dist_via(scelto)
        p["distanza_civico_m"] = None if dc is None else int(round(dc))
        p["distanza_via_m"] = None if dv is None else int(round(dv))
        p["nel_municipio"] = municipi.nel_municipio(mun, scelto[1], scelto[2])
        p["coord_dichiarate"]["nel_municipio"] = p["nel_municipio"]
        if not p["nel_municipio"]:
            p["note"].append("coordinate dichiarate fuori dal Municipio " + mun)
    else:
        p["distanza_civico_m"] = p["distanza_via_m"] = None
        p["nel_municipio"] = False
        if p["formato_originale"] not in ("assente",) and p["coord_testo"]:
            tutte_le_letture = candidati_coppia(lat_t, lon_t)
            p["note"].append("nessuna lettura delle coordinate dichiarate cade nel Comune (%s): non corrette"
                             % ("; ".join("%s %.5f %.5f" % c for c in tutte_le_letture) if tutte_le_letture else "illeggibili"))

    def da_civico(motivo_nota):
        p["qualita"] = "da_indirizzo"
        p["lat"], p["lon"] = round(punto_civico[0], 5), round(punto_civico[1], 5)
        p["nel_municipio"] = municipi.nel_municipio(mun, *punto_civico)
        p["note"].append(motivo_nota)

    if scelto and ref_civico:
        d = p["distanza_civico_m"]
        if d <= SOGLIA_CONFERMATA_M:
            p["qualita"] = "confermata"
        elif d <= SOGLIA_PLAUSIBILE_M and p["nel_municipio"]:
            p["qualita"] = "plausibile"
        else:
            da_civico("coordinate dichiarate a %d m dal civico ufficiale%s: posizione presa dal civico"
                      % (d, "" if p["nel_municipio"] else " e fuori dal municipio"))
        if p["qualita"] != "da_indirizzo":
            p["lat"], p["lon"] = round(scelto[1], 5), round(scelto[2], 5)
    elif scelto and ref_via:
        d = p["distanza_via_m"]
        p["note"].append("civico non verificabile (" + str(motivo) + "): controllo sull'asse della via")
        if d is not None and d <= SOGLIA_CONFERMATA_VIA_M and p["nel_municipio"]:
            p["qualita"] = "confermata"
        elif d is not None and d <= SOGLIA_PLAUSIBILE_M and p["nel_municipio"]:
            p["qualita"] = "plausibile"
        else:
            p["qualita"] = "non_localizzata"
            p["note"].append("coordinate a %s m dall'asse della via e nessun civico ufficiale: non localizzata" % d)
        if p["qualita"] != "non_localizzata":
            p["lat"], p["lon"] = round(scelto[1], 5), round(scelto[2], 5)
    elif scelto:
        if p["nel_municipio"]:
            p["qualita"] = "plausibile"
            p["lat"], p["lon"] = round(scelto[1], 5), round(scelto[2], 5)
            p["note"].append("indirizzo non agganciato (" + str(motivo) + "): posizione solo dalle coordinate dichiarate")
        else:
            p["qualita"] = "non_localizzata"
            p["note"].append("indirizzo non agganciato (" + str(motivo) + ") e coordinate fuori dal municipio")
    elif ref_civico:
        da_civico("coordinate dichiarate assenti o incoerenti: posizione presa dal civico ufficiale")
    else:
        p["qualita"] = "non_localizzata"
        p["note"].append("nessuna coordinata valida e nessun civico ufficiale agganciato (" + str(motivo) + ")")
    if p["qualita"] == "non_localizzata":
        p["lat"] = p["lon"] = None
        p["nel_municipio"] = False
    return p


# ---------------------------------------------------------------- siti

def chiave_ordine(p):
    return (p["anno"], p["numero_protocollo"])


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", senza_accenti(s).lower().replace("'", "-"))
    return s.strip("-")


class UnioneInsiemi:
    def __init__(self, n):
        self.p = list(range(n))

    def trova(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def unisci(self, a, b):
        self.p[self.trova(b)] = self.trova(a)


def costruisci_siti(pratiche):
    """Raggruppa le pratiche localizzate: stesso civico agganciato, oppure entro SOGLIA_SITO_M."""
    posizionate = [p for p in pratiche if p["lat"] is not None]
    u = UnioneInsiemi(len(posizionate))
    per_civico = {}
    for i, p in enumerate(posizionate):
        if p["civico"]:
            k = (p["municipio"], p["toponimo_ufficiale"], re.match(r"\d+", p["civico"]).group(0))
            if k in per_civico:
                u.unisci(per_civico[k], i)
            else:
                per_civico[k] = i
    for i in range(len(posizionate)):
        for j in range(i + 1, len(posizionate)):
            a, b = posizionate[i], posizionate[j]
            if a["municipio"] == b["municipio"] and metri((a["lat"], a["lon"]), (b["lat"], b["lon"])) <= SOGLIA_SITO_M:
                u.unisci(i, j)
    gruppi = defaultdict(list)
    for i, p in enumerate(posizionate):
        gruppi[u.trova(i)].append(p)
    elenco = []
    for g in gruppi.values():
        g.sort(key=chiave_ordine, reverse=True)
        elenco.append(g)
    elenco.sort(key=lambda g: (g[0]["municipio"], g[0]["indirizzo"].lower(), g[0]["id"]))
    siti, usati = [], Counter()
    for g in elenco:
        mun = g[0]["municipio"]
        migliore = min(QUALITA_ORDINE[p["qualita"]] for p in g)
        qual = [k for k, v in QUALITA_ORDINE.items() if v == migliore][0]
        buoni = [p for p in g if p["qualita"] == qual]
        lat = sorted(p["lat"] for p in buoni)[(len(buoni) - 1) // 2] if len(buoni) % 2 else \
            (sorted(p["lat"] for p in buoni)[len(buoni) // 2 - 1] + sorted(p["lat"] for p in buoni)[len(buoni) // 2]) / 2
        lon = sorted(p["lon"] for p in buoni)[(len(buoni) - 1) // 2] if len(buoni) % 2 else \
            (sorted(p["lon"] for p in buoni)[len(buoni) // 2 - 1] + sorted(p["lon"] for p in buoni)[len(buoni) // 2]) / 2
        base = mun.lower() + "-" + slug(g[0]["indirizzo"])
        usati[base] += 1
        sid = base if usati[base] == 1 else base + "-" + str(usati[base])
        gest = []
        for p in g:
            for x in p["gestori"]:
                if x not in gest:
                    gest.append(x)
        gest.sort(key=lambda x: (GESTORI_CANONICI.index(x) if x in GESTORI_CANONICI else 99, x))
        date = sorted(p["data_protocollo"] for p in g if p["data_protocollo"])
        tipi = [p["tipologia"] for p in g]
        if g[0]["tipologia"] == "dismissione":
            stato = "dismissione_richiesta"
        elif any(t in ("modifica", "adeguamento", "installazione_su_esistente") for t in tipi):
            stato = "esistente"
        else:
            stato = "nuova_richiesta"
        sito = {"id": sid, "municipio": mun, "indirizzo": g[0]["indirizzo"], "lat": round(lat, 5), "lon": round(lon, 5),
                "nel_municipio": None, "qualita": qual, "gestori": gest, "pratiche": [p["id"] for p in g],
                "prima_data": date[0] if date else None, "ultima_data": date[-1] if date else None,
                "primo_anno": min(p["anno"] for p in g), "ultimo_anno": max(p["anno"] for p in g), "stato": stato}
        for p in g:
            p["sito"] = sid
        siti.append(sito)
    return siti


def carica_servizi():
    d = json.loads(SERVIZI_PATH.read_text(encoding="utf-8"))
    gruppo_di = {c: g for g, cats in GRUPPI_SENSIBILI.items() for c in cats}
    voci = []
    for r in d["p"]:
        cat = d["c"][r[0]]
        if cat in gruppo_di:
            voci.append({"g": gruppo_di[cat], "c": cat, "n": r[1], "i": r[6] if len(r) > 6 else "", "lat": r[4], "lon": r[5]})
    return voci


def aggiungi_vicini(siti, voci):
    for s in siti:
        v = []
        for x in voci:
            if abs(x["lat"] - s["lat"]) > 0.0035 or abs(x["lon"] - s["lon"]) > 0.0048:
                continue
            m = metri((s["lat"], s["lon"]), (x["lat"], x["lon"]))
            if m <= RAGGIO_M:
                v.append(dict(x, m=int(round(m))))
        v.sort(key=lambda x: (x["m"], x["g"], x["c"], x["n"]))
        s["vicini"] = v
        s["n_vicini"] = len(v)
        s["vicino_min_m"] = v[0]["m"] if v else None


# ---------------------------------------------------------------- civici.json

def costruisci_indice_civici(civici_per_mun, oggi):
    vie = []
    for mun, per_via in civici_per_mun.items():
        raggruppate = defaultdict(set)
        for top, punti in per_via.items():
            nome = forma_via(top)
            for n, lat, lon, lett, esp, stato in punti:
                if stato == "UFFICIALE":
                    raggruppate[nome].add((n, lett, esp, round(lat, 5), round(lon, 5)))
        for nome, punti in raggruppate.items():
            elenco = [[stringa_civico(n, l, e), la, lo] for n, l, e, la, lo in sorted(punti)]
            vie.append([nome, mun, elenco])
    vie.sort(key=lambda v: (senza_accenti(v[0]).lower(), v[1]))
    return {"fonte": "Roma Capitale, GeoRoma, numeri civici (scaricati %s)" % oggi, "vie": vie}


def relativizza(indice):
    """Variante piu' leggera (--civici-relativi): per ogni via un'origine [lat, lon] in unita' di 1e-5 gradi
    e i civici come [civico, dlat, dlon] interi relativi all'origine."""
    vie = []
    for nome, mun, elenco in indice["vie"]:
        la0, lo0 = min(round(c[1] * 1e5) for c in elenco), min(round(c[2] * 1e5) for c in elenco)
        vie.append([nome, mun, [la0, lo0], [[c[0], round(c[1] * 1e5) - la0, round(c[2] * 1e5) - lo0] for c in elenco]])
    return {"fonte": indice["fonte"], "formato": "relativo: origine [lat, lon] in 1e-5 gradi, civici [civico, dlat, dlon] in 1e-5 gradi",
            "vie": vie}


def scrivi_indice_civici(indice, relativi=False):
    if relativi:
        indice = relativizza(indice)
    righe = [json.dumps(v, ensure_ascii=False, separators=(",", ":")) for v in indice["vie"]]
    extra = (',"formato":' + json.dumps(indice["formato"], ensure_ascii=False)) if relativi else ""
    testo = ('{"fonte":' + json.dumps(indice["fonte"], ensure_ascii=False) + extra + ',"vie":[\n' + ",\n".join(righe) + "\n]}\n")
    OUT_CIVICI.parent.mkdir(parents=True, exist_ok=True)
    OUT_CIVICI.write_text(testo, encoding="utf-8")
    return len(testo.encode("utf-8"))


# ---------------------------------------------------------------- main

def elabora(oggi):
    manifest = json.loads((DIR_FONTI / "manifest.json").read_text(encoding="utf-8")) if (DIR_FONTI / "manifest.json").exists() else {}
    municipi = Municipi()
    civici = {m: carica_civici_municipio(DIR_FONTI / ("civici_" + m + ".csv")) for m in NUMERO_MUNICIPIO}
    vie = {m: VieAntenne(civici[m]) for m in civici}
    strade = {m: Strade(STRADE_PATH[m]) for m in STRADE_PATH}

    tutte, fonti_out, problemi = [], [], []
    for f in FONTI:
        path = DIR_FONTI / f["file"]
        if f["tipo"] == "html":
            pr, contate, info = leggi_municipio_ii(f, path.read_text(encoding="utf-8", errors="replace"))
        else:
            testo = testo_pdf(path)
            pr, contate = leggi_municipio_v(f, testo)
            info = {}
        if not (len(pr) == contate == f["attese"]):
            problemi.append("%s: attese %d, contate nella fonte %d, estratte %d" % (f["id"], f["attese"], contate, len(pr)))
        man = manifest.get(f["file"], {})
        voce = {"id": f["id"], "municipio": f["municipio"], "titolo": f["titolo"], "url": f["url"],
                "scaricata": man.get("scaricato"), "pratiche": len(pr)}
        if info.get("aggiornata"):
            voce["aggiornata"] = info["aggiornata"]
        if info.get("pubblicata"):
            voce["pubblicata"] = info["pubblicata"]
        fonti_out.append(voce)
        tutte.extend(pr)
    if problemi:
        raise SystemExit("Conteggi che non tornano:\n  " + "\n  ".join(problemi))

    visti = Counter()
    ripetuti = defaultdict(list)
    for p in tutte:
        chiave_p = (p["municipio"], p["protocollo"])
        visti[chiave_p] += 1
        ripetuti[chiave_p].append(p)
    for p in tutte:
        base = p["municipio"].lower() + "-" + p["protocollo"].lower().replace("/", "-")
        n = [q for q in ripetuti[(p["municipio"], p["protocollo"])]].index(p) + 1
        p["id"] = base if n == 1 else base + "-" + str(n)
        if visti[(p["municipio"], p["protocollo"])] > 1:
            p["note"].append("protocollo ripetuto nella fonte (%d righe con %s)" % (visti[(p["municipio"], p["protocollo"])], p["protocollo"]))
        if p["protocollo"] in NOTE_MANUALI:
            p["note"].append(NOTE_MANUALI[p["protocollo"]])
        gest, altri = gestori_da_testo(p["gestore_originale"])
        p["gestori"] = gest
        if not gest:
            p["note"].append("societa' non indicata nella fonte")
        if altri:
            p["note"].append("societa' non fra quelle note: " + ", ".join(altri))
        p["tipologia"] = tipologia_da_testo(p["tipologia_originale"])
        if "/" in p["tipologia_originale"] and re.search(r"modific", p["tipologia_originale"], re.I) and re.search(r"adeg", p["tipologia_originale"], re.I):
            p["note"].append("tipologia doppia nella fonte ('%s'): classificata come modifica" % p["tipologia_originale"])
        if p["tipologia"] == "altro":
            p["note"].append("tipologia non classificabile")
        scegli_posizione(p, vie[p["municipio"]], strade[p["municipio"]], municipi)

    siti = costruisci_siti(tutte)
    for s in siti:
        s["nel_municipio"] = municipi.nel_municipio(s["municipio"], s["lat"], s["lon"])
    aggiungi_vicini(siti, carica_servizi())
    return tutte, siti, fonti_out, civici


def controlli(tutte, siti, fonti_out):
    out = {}
    for mun in ("II", "V"):
        pr = [p for p in tutte if p["municipio"] == mun]
        out[mun] = {
            "pratiche": len(pr),
            "siti": sum(1 for s in siti if s["municipio"] == mun),
            "per_qualita": {k: sum(1 for p in pr if p["qualita"] == k) for k in QUALITA_ORDINE},
            "per_formato_originale": {k: sum(1 for p in pr if p["formato_originale"] == k) for k in FORMATI},
            "protocolli_ripetuti": sorted({p["protocollo"] for p in pr if any("protocollo ripetuto" in n for n in p["note"])}),
            "indirizzi_non_agganciati": [{"pratica": p["id"], "indirizzo": p["indirizzo_originale"], "motivo": p["_motivo_aggancio"]}
                                         for p in pr if p["_aggancio"] == "nessuno"],
            "agganciati_solo_alla_via": [{"pratica": p["id"], "indirizzo": p["indirizzo_originale"], "motivo": p["_motivo_aggancio"]}
                                         for p in pr if p["_aggancio"] == "via"],
            "casi_incoerenti": [{"pratica": p["id"], "indirizzo": p["indirizzo"], "qualita": p["qualita"],
                                 "coord_dichiarate": p["coord_dichiarate"]["testo"],
                                 "distanza_civico_m": p["distanza_civico_m"], "distanza_via_m": p["distanza_via_m"]}
                                for p in pr if p["qualita"] in ("da_indirizzo", "non_localizzata")],
        }
    return out


CAMPI_PRATICA = ["id", "municipio", "fonte", "protocollo", "data_protocollo", "anno", "gestori", "gestore_originale",
                 "tipologia", "tipologia_originale", "indirizzo", "indirizzo_originale", "toponimo_ufficiale", "civico",
                 "codice_sito", "codici_sito", "nome_sito", "catasto", "lat", "lon", "qualita", "formato_originale",
                 "coord_dichiarate", "distanza_civico_m", "distanza_via_m", "nel_municipio", "sito", "note"]


def scrivi_antenne(tutte, siti, fonti_out, oggi):
    pr_out = []
    for p in tutte:
        d = {"fonte": {"id": p["fonte_id"]}}
        if p.get("documento"):
            d["fonte"]["documento"] = p["documento"]
        for k in CAMPI_PRATICA:
            if k == "fonte":
                continue
            if k in p:
                d[k] = p[k]
            elif k == "sito":
                d[k] = None
        pr_out.append({k: d[k] for k in CAMPI_PRATICA if k in d})
    doc_testa = {"generato": oggi, "raggio_m": RAGGIO_M, "avvertenza": AVVERTENZA, "gruppi_sensibili": GRUPPI_SENSIBILI,
                 "fonti": fonti_out}
    j = lambda x: json.dumps(x, ensure_ascii=False, separators=(", ", ": "))  # noqa: E731
    parti = ["{"]
    for k, v in doc_testa.items():
        parti.append(json.dumps(k) + ": " + j(v) + ",")
    parti.append('"siti": [\n' + ",\n".join(j(s) for s in siti) + "\n],")
    parti.append('"pratiche": [\n' + ",\n".join(j(p) for p in pr_out) + "\n],")
    parti.append('"controlli": ' + json.dumps(controlli(tutte, siti, fonti_out), ensure_ascii=False, indent=1))
    parti.append("}")
    OUT_ANTENNE.parent.mkdir(parents=True, exist_ok=True)
    OUT_ANTENNE.write_text("\n".join(parti) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Antenne dei Municipi II e V: fonti -> data/antenne/antenne.json")
    ap.add_argument("--scarica", action="store_true", help="scarica le fonti in fonti-antenne/ prima di elaborare")
    ap.add_argument("--civici-relativi", action="store_true",
                    help="civici.json con coordinate intere relative all'origine di ogni via (piu' leggero)")
    args = ap.parse_args()
    if args.scarica:
        scarica()
    if not (DIR_FONTI / "civici_II.csv").exists():
        raise SystemExit("Mancano le fonti: lancia prima  python3 prepara_antenne.py --scarica")
    oggi = datetime.date.today().isoformat()
    tutte, siti, fonti_out, civici = elabora(oggi)
    scrivi_antenne(tutte, siti, fonti_out, oggi)
    manifest = json.loads((DIR_FONTI / "manifest.json").read_text(encoding="utf-8")) if (DIR_FONTI / "manifest.json").exists() else {}
    data_civici = manifest.get("civici_II.csv", {}).get("scaricato", oggi)
    peso = scrivi_indice_civici(costruisci_indice_civici(civici, data_civici), args.civici_relativi)
    print("pratiche %d, siti %d; qualita: %s" % (len(tutte), len(siti), dict(Counter(p["qualita"] for p in tutte))))
    print("civici.json: %d byte" % peso)


if __name__ == "__main__":
    main()
