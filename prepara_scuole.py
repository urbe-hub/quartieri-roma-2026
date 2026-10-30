#!/usr/bin/env python3
"""
Scuole e nidi di Roma per la "citta' dei 15 minuti".

Fonti:
  1. Roma Capitale, GeoRoma (WFS geoportale.comune.roma.it, layer
     DIPSCU:v_servizi_attivi_pubblica), anno 2025/26, gia' con coordinate: tutti i nidi
     (capitolini, convenzionati, privati, aziendali, micronidi, spazi gioco, sezioni
     primavera), le scuole dell'infanzia (capitoline, statali, paritarie), le primarie e
     le secondarie di I grado statali.
  2. Ministero dell'Istruzione e del Merito, anagrafe scuole statali e paritarie a.s.
     2026/27 (dati.istruzione.it/opendata), senza coordinate: le secondarie di II grado
     (licei, tecnici, professionali) statali e paritarie, e primarie, secondarie di I
     grado e infanzia paritarie. Delle statali solo le sedi scolastiche (SEDESCOLASTICA = SI).
  3. I numeri civici ufficiali di Roma Capitale (GeoRoma, DIPCUL:GeoromaCiviciLocator,
     ~558mila), per dare le coordinate alle sedi del Ministero.

Geocodifica: la via si riconosce anche scritta in breve ("V.LE", "G. BRESADOLA" per
"Giacomo Bresadola"), purche' il candidato sia uno solo; poi il civico esatto, oppure il
piu' vicino sulla stessa via entro 10 numeri (qualita' "vicino"). Le sedi che non si
agganciano restano fuori dalla mappa e finiscono in data/scuole-non-trovate.csv.

Pulizia finale (pulisci(), anche da sola su data/scuole.json gia' scritto):
  - doppioni: GeoRoma ha un record per sezione (es. "Principe di Piemonte, Via Ostiense
    263c" 11 volte); per (tipo, nome, indirizzo) resta un solo punto;
  - le infanzie paritarie del Ministero gia' presenti nel layer del Comune (le comunali
    sono paritarie per legge, e stanno anche nell'anagrafe del Ministero): fuori quelle
    entro 80 m da un'infanzia comunale o paritaria del Comune;
  - nidi aziendali, riservati ai dipendenti (Banca d'Italia, ministeri, Pcm, INPS...):
    non sono servizi di quartiere. Quelli in convenzione col Comune restano;
  - scuole in ospedale (sezioni per i ricoverati: "Ospedale Bambin Gesu'", "Policlinico
    Gemelli"): non sono scuole di quartiere. I nidi ospedalieri in convenzione restano;
  - nomi con dentro il titolare persona fisica (NOMI_CON_TITOLARE, elenco esplicito: il
    pattern " di <nome>" non basta, "La Torta in Cielo di Gianni Rodari" e' un titolo).

Dettagli per la scheda (dettagli_scuole(), data/scuole-dettagli.json): per ogni scuola di
data/scuole.json, senza toccarne i punti, un piccolo oggetto con chiavi corte:
  m  codici meccanografici MIM (da GeoRoma o dall'anagrafe del Ministero), deduplicati;
  w  siti web delle scuole (anagrafe del Ministero), normalizzati da sito_web();
  ic istituto di riferimento (solo statali, se il nome e' diverso dalla scuola);
  p  posti (ricettivita') e z sezioni, nidi e infanzie comunali (portale del Comune);
  l  1 se chiuso per lavori.
Il join con le scuole di scuole.json e' per (tipo, nome, indirizzo), come la pulizia dei
doppioni: i record GeoRoma portano il meccanografico (poi anagrafe MIM per sito e istituto)
e, per nidi e infanzie comunali, il codice servizio (mesis) che aggancia le righe del
portale; le sedi del Ministero si agganciano per tipo, nome e civico. Posti e sezioni del
portale sono per scuola (stesso valore su ogni edificio): si contano una volta per mesis.
Niente email, telefoni o nomi di persona: solo codici, siti e numeri.
I siti che farebbero scattare il gate zero-footprint (i termini di check_zero_footprint) si
scartano, e il conteggio va in uscita.

Uso:
    python3 prepara_scuole.py <v_servizi_attivi_pubblica.json> <statali.csv> <paritarie.csv> <civici_*.csv ...>
    python3 prepara_scuole.py --pulisci      # solo la pulizia, su data/scuole.json
    python3 prepara_scuole.py --dettagli <v_servizi_attivi_pubblica.json> <statali.csv> <paritarie.csv> \\
        <mv_portale_nidi_capitolini.json> <mv_portale_infanzia_capitolina.json>
                                             # solo i dettagli, su data/scuole.json gia' scritto
Scrive data/scuole.json (e data/scuole-dettagli.json con --dettagli: farlo dopo ogni nuova
preparazione delle scuole, senza rete).
"""

import csv
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUT = SCRIPT_DIR / "data" / "scuole.json"
OUT_NON_TROVATE = SCRIPT_DIR / "data" / "scuole-non-trovate.csv"
OUT_DETTAGLI = SCRIPT_DIR / "data" / "scuole-dettagli.json"

ABBREVIAZIONI = {
    "V": "VIA", "VLE": "VIALE", "VL": "VIALE", "PZA": "PIAZZA", "PZZA": "PIAZZA", "P": "PIAZZA",
    "PLE": "PIAZZALE", "LGO": "LARGO", "CSO": "CORSO", "CIRCNE": "CIRCONVALLAZIONE",
    "CIRC": "CIRCONVALLAZIONE", "LGT": "LUNGOTEVERE", "LGTEVERE": "LUNGOTEVERE", "VCO": "VICOLO",
    "STR": "STRADA", "PZTA": "PIAZZETTA",
}
TOPONIMI = {"VIA", "VIALE", "PIAZZA", "PIAZZALE", "LARGO", "CORSO", "CIRCONVALLAZIONE", "LUNGOTEVERE",
            "VICOLO", "STRADA", "PIAZZETTA", "SALITA", "CLIVO", "LUNGOMARE", "BORGO", "GALLERIA",
            "PASSEGGIATA", "RAMPA", "SCALINATA", "VIADOTTO", "PONTE", "LOCALITA"}
VUOTE = {"DI", "DEL", "DELLA", "DELLE", "DEI", "DEGLI", "DE", "D", "DELL", "DA", "E", "LA", "LE", "IL",
         "LO", "GLI", "I", "AL", "ALLA", "ALLE", "AI", "N", "NR", "NUM"}


def senza_accenti(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


ABBREVIAZIONI_PUNTATE = [
    (r"\bCIRC\s*[./]\s*NE\b|\bC\.NE\b|\bCNE\b", "CIRCONVALLAZIONE"), (r"\bV\.LE\b", "VIALE"), (r"\bV\.LO\b", "VICOLO"),
    (r"\bP\.\s?Z?ZA\b", "PIAZZA"), (r"\bP\.LE\b", "PIAZZALE"), (r"\bL\.GO\b", "LARGO"), (r"\bC\.SO\b|\bC\.O\b", "CORSO"),
    (r"\bL\.\s?TEVERE\b", "LUNGOTEVERE"), (r"\bL\.\s?MARE\b", "LUNGOMARE"), (r"\bL\.\s?RE\b", "LUNGOTEVERE"),
]
# Vie scritte in modo diverso dal Comune nell'anagrafe del Ministero (chiave_testo della via -> via dei civici).
CORREZIONI_VIE = {
    "VIA GIOCHI ISTMICI": "VIA DEI GIUOCHI ISTMICI",
    "VIA PLACIDO RICCARDI": "LARGO BEATO PLACIDO RICCARDI",
    "VICOLO DEL CASAL LUMBROSO": "VICOLO DEL CASALE LUMBROSO",
    "VIA ROMOLO TRINCHERI": "VIA ROMOLO TRINCHIERI",
}
# Indirizzi del Ministero senza un civico utilizzabile, dove la stessa scuola ha un'altra sede
# con indirizzo preciso nella stessa anagrafe: (nome, indirizzo grezzo) -> indirizzo da geocodificare.
INDIRIZZI_MIM = {
    ("EMILIO SERENI", "VIA PRENESTINA KM.1400"): "VIA PRENESTINA 1395",
}
# Indirizzi sbagliati nel layer del Comune, dove il punto e' giusto: (tipo, nome, indirizzo grezzo
# titolizzato) -> indirizzo da mostrare ("" se non si conosce quello vero).
INDIRIZZI_COMUNE = {
    ("nido", "Il Campo di Fragole", "Via Vittorio Ragusa 100"): "",
}
SOGLIA_VIA_LONTANA_METRI = 1000
SANTI = {"S", "SS", "SAN", "SANTA", "SANTO", "SANT", "SANTI"}
INIZIALE = "#"   # segna le iniziali puntate ("E." in "VIA E. MARTINI"), che non sono congiunzioni


def gettoni(via):
    s = senza_accenti(via).upper().replace("`", "'")
    s = re.sub(r"\(.*?\)", " ", s).replace("°", " ")
    for regola, esteso in ABBREVIAZIONI_PUNTATE:
        s = re.sub(regola, esteso, s)
    s = re.sub(r"\b([A-Z])\.", r" \1" + INIZIALE + " ", s)
    s = re.sub(r"[^A-Z0-9" + INIZIALE + "]", " ", s)
    t = s.split()
    if t and t[0].rstrip(INIZIALE) in ABBREVIAZIONI and (t[0].endswith(INIZIALE) or t[0] != "P"):
        t[0] = ABBREVIAZIONI[t[0].rstrip(INIZIALE)]
    return t


def chiave(via):
    t = gettoni(via)
    tipo = t[0] if t and t[0] in TOPONIMI else "VIA"
    resto = t[1:] if t and t[0] in TOPONIMI else t
    out = []
    for x in resto:
        if x.rstrip(INIZIALE) in SANTI:
            out.append("S" + INIZIALE)          # San, Santa, S.: tutti uguali (i civici scrivono "S.")
        elif x not in VUOTE:
            out.append(x)
    return tipo, out


def separa_civico(indirizzo):
    s = re.sub(r"\s*-\s*SUCCURSALE.*$", "", indirizzo.strip(), flags=re.I).rstrip(".")
    s = re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)          # "VIA ASCREA26" -> "VIA ASCREA 26"
    s = re.sub(r"\bN\.?\s*(?=\d)", "", s, flags=re.I)    # "N.79" -> "79"
    s = re.sub(r"\s*,\s*", " ", s)
    if re.search(r"\bKM\b|\bSNC\b|\bS\.N\.C\b", s, flags=re.I):
        return re.sub(r"\b(KM|SNC|S\.N\.C\.?)\b.*$", "", s, flags=re.I).strip(), None
    m = re.match(r"^(.*?)\s+(\d+)(?!\d).*$", s)
    if not m:
        return s, None
    return m.group(1).strip(), int(m.group(2))


class Vie:
    def __init__(self, per_via):
        # Due toponimi con la stessa chiave (es. "DELL'" e "DELL`") sono la stessa via: i civici
        # si uniscono sotto il nome con piu' civici, senza renderla ambigua.
        gruppi = defaultdict(list)
        for via in per_via:
            tipo, tok = chiave(via)
            gruppi[(tipo, tuple(tok))].append(via)
        unite = {}
        for vie_gruppo in gruppi.values():
            vie_gruppo.sort(key=lambda v: (-len(per_via[v]), v))
            unite[vie_gruppo[0]] = [p for v in vie_gruppo for p in per_via[v]]
        self.per_via = unite
        self.per_ultimo = defaultdict(list)
        self.chiavi = {}
        for via in unite:
            tipo, tok = chiave(via)
            self.chiavi[via] = (tipo, tok)
            if tok:
                self.per_ultimo[tok[-1]].append(via)

    @staticmethod
    def _compatibili(q, c):
        # Ogni parola cercata deve esserci nel candidato, nello stesso ordine; una
        # lettera sola vale da iniziale ("G" per "GIACOMO", "S" per "SANTA").
        i = 0
        for x in q:
            iniz = x.endswith(INIZIALE) or len(x) == 1
            while i < len(c) and not (c[i] == x or (iniz and c[i].startswith(x[0]))):
                i += 1
            if i == len(c):
                return False
            i += 1
        return True

    def trova(self, via):
        tipo, tok = chiave(via)
        if not tok:
            return None
        cand = []
        for v in self.per_ultimo.get(tok[-1], []):
            ctipo, ctok = self.chiavi[v]
            if not self._compatibili(tok, ctok):
                continue
            # Il tipo diverso ("VIA" scritto per "VIALE") pesa piu' di un nome in piu'.
            peso = (len(ctok) - len(tok)) + (0 if ctipo == tipo else 3)
            if peso <= 3:
                cand.append((peso, v))
        if not cand:
            return None
        cand.sort()
        # Due vie diverse ugualmente plausibili: meglio non indovinare.
        if len(cand) > 1 and cand[0][0] == cand[1][0]:
            return None
        return cand[0][1]


def geocodifica(vie, indirizzo):
    via_testo, num = separa_civico(indirizzo)
    via_testo = CORREZIONI_VIE.get(chiave_testo(via_testo), via_testo)
    via = vie.trova(via_testo)
    if not via:
        return None, "via non trovata"
    if num is None:
        return None, "senza civico"
    punti = vie.per_via[via]
    esatti = [p for p in punti if p[0] == num]
    if esatti:
        return (sum(p[1] for p in esatti) / len(esatti), sum(p[2] for p in esatti) / len(esatti), "esatto"), via
    vicini = sorted(punti, key=lambda p: (abs(p[0] - num), (p[0] - num) % 2))
    if vicini and abs(vicini[0][0] - num) <= 10:
        return (vicini[0][1], vicini[0][2], "vicino"), via
    return None, "civico non trovato su " + via


MAIUSCOLE = {"IC", "IIS", "IS", "LS", "LC", "SMS", "ITIS", "ITC", "ITT", "IPSIA", "IPSSAR", "ITCG", "IPS", "CPIA", "ITI",
             "ITG", "ISIS", "SM", "II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII", "XIII", "XIV", "XV",
             "XX", "XXI", "XXIII", "XXIV", "XXV", "IPSEOA", "ITCS", "ITAS", "LSS", "IPSSS"}
MINUSCOLE = {"di", "de", "del", "della", "delle", "dei", "degli", "da", "e", "in", "a", "al", "alla"}


ARTICOLI_ELISI = {"dell", "dall", "nell", "sull", "all", "coll"}


def titolo(s):
    # "Via Altiero Spinelli,20" -> "Via Altiero Spinelli 20"; la virgola decimale ("Km 13,5") resta.
    s = re.sub(r"(?<=[A-Za-z]),\s*(?=\d)", " ", s or "")
    parole = []
    for p in s.replace('"', "").split():
        # "Dell' Osteria" -> "Dell'Osteria"
        if parole and parole[-1].endswith("'") and parole[-1][:-1].lower() in ARTICOLI_ELISI:
            parole[-1] += p
        else:
            parole.append(p)
    out = []
    for i, p in enumerate(parole):
        if p.upper().strip(".,") in MAIUSCOLE:
            out.append(p.upper())
        elif i and p.lower() in MINUSCOLE:
            out.append(p.lower())
        elif i and "'" in p and p.lower().split("'")[0] in ARTICOLI_ELISI:
            out.append(p.lower())          # "Via dell'Idroscalo": l'articolo elisio non e' maiuscolo
        else:
            out.append(p[:1].upper() + p[1:].lower())
    t = " ".join(out)
    t = re.sub(r"(['\-.(/])(\w)", lambda m: m.group(1) + m.group(2).upper(), t)
    # Accento scritto come apostrofo in fondo alla parola: "CITTA'" -> "Città"
    return re.sub(r"(\w)([aeiou])'(?=\s|$|,)", lambda m: m.group(1) + {"a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù"}[m.group(2)], t)


# Comune: tipo di servizio -> (categoria, dettaglio)
TIPI_COMUNE = {
    "nido capitolino": ("nido", "Nido comunale"),
    "micronido capitolino": ("nido", "Micronido comunale"),
    "nido in convenzione": ("nido", "Nido in convenzione"),
    "nido in appalto": ("nido", "Nido comunale in appalto"),
    "nido project financing": ("nido", "Nido comunale (project financing)"),
    "nido privato": ("nido", "Nido privato"),
    "micronido privato": ("nido", "Micronido privato"),
    "nido aziendale": ("nido", "Nido aziendale"),
    "sezione primavera privata": ("nido", "Sezione primavera privata"),
    "spazio gioco privato": ("nido", "Spazio gioco privato"),
    "infanzia capitolina": ("infanzia", "Scuola dell'infanzia comunale"),
    "infanzia statale": ("infanzia", "Scuola dell'infanzia statale"),
    "infanzia paritaria": ("infanzia", "Scuola dell'infanzia paritaria"),
    "primaria": ("primaria", "Scuola primaria statale"),
    "secondaria I grado": ("media", "Scuola secondaria di I grado statale"),
}
PARITARIE = {
    "SCUOLA INFANZIA NON STATALE": ("infanzia", "Scuola dell'infanzia paritaria"),
    "SCUOLA PRIMARIA NON STATALE": ("primaria", "Scuola primaria paritaria"),
    "SCUOLA SEC. PRIMO GRADO NON STATALE": ("media", "Scuola secondaria di I grado paritaria"),
    "SCUOLA SEC. SECONDO GRADO NON STATALE": ("superiore", "Scuola secondaria di II grado paritaria"),
}


def superiore_statale(g):
    if g.startswith(("LICEO", "ISTITUTO TECNICO", "IST TEC", "IST PROF", "ISTITUTO PROFESSIONALE",
                     "ISTITUTO MAGISTRALE", "ISTITUTO D'ARTE", "SCUOLA MAGISTRALE")):
        d = g.replace("IST PROF", "ISTITUTO PROFESSIONALE").replace("IST TEC", "ISTITUTO TECNICO")
        return d[:1] + d[1:].lower() + " statale"
    return None


def leggi_csv(path, **kw):
    return list(csv.DictReader(open(path, encoding="utf-8", errors="replace"), **kw))


def metri(a, b):
    return math.hypot((a[0] - b[0]) * 110540, (a[1] - b[1]) * 111320 * 0.745)


def carica_civici(files):
    per_via = defaultdict(list)
    for f in files:
        for r in leggi_csv(f):
            m = re.match(r"POINT \(([\d.]+) ([\d.]+)\)", r.get("GEOMETRIA", ""))
            if not m or not r.get("NUMERO_CIVICO"):
                continue
            # GeoServer serve il WKT in EPSG:4326 come "lat lon" o "lon lat": lo riconosco dai valori.
            a, b = float(m.group(1)), float(m.group(2))
            lat, lon = (a, b) if a > 40 else (b, a)
            per_via[r["TOPONIMO"]].append((int(float(r["NUMERO_CIVICO"])), lat, lon))
    print("Civici di Roma Capitale:", sum(len(v) for v in per_via.values()), "su", len(per_via), "vie")
    return Vie(per_via)


def indirizzo_comune(tipo, nome, indirizzo):
    """Indirizzo titolizzato di un record del Comune, con le correzioni note (INDIRIZZI_COMUNE)."""
    ind = titolo(indirizzo)
    return INDIRIZZI_COMUNE.get((tipo, nome, ind), ind)


def avvisa_via_lontana(vie, s):
    """Stampa un avviso se il punto di un record del Comune sta a piu' di SOGLIA_VIA_LONTANA_METRI
    da tutti i civici della via del suo indirizzo (indirizzo sbagliato o punto sbagliato)."""
    if not s["i"]:
        return
    via = vie.trova(separa_civico(s["i"])[0])
    if via and min(metri((s["lat"], s["lon"]), (p[1], p[2])) for p in vie.per_via[via]) > SOGLIA_VIA_LONTANA_METRI:
        print("  Avviso: %s (%s) sta a piu' di %d m dalla via %s" % (s["n"], s["i"], SOGLIA_VIA_LONTANA_METRI, via))


def chiave_testo(s):
    return re.sub(r"[^A-Z0-9]+", " ", senza_accenti(s or "").upper()).strip()


# Prima il record che il Comune gestisce o convenziona, poi statale, poi il resto: fra
# doppioni con lo stesso nome e indirizzo resta quello piu' aperto al pubblico.
def priorita(s):
    d = s["d"]
    if "comunal" in d or "convenzione" in d:
        return 0
    if "statale" in d:
        return 1
    if "aziendale" in d:
        return 3
    return 2


# Nidi dei datori di lavoro, che il dato del Comune segna "privato" o "aziendale".
NIDI_AZIENDALI = re.compile(
    r"\bAZIENDAL|BANCA D ?ITALIA|\bMINISTER|\bPCM\b|\bINPS\b|\bI N P S\b|\bINAIL\b|\bPOSTE\b|"
    r"\bATAC\b|\bENI\b|CITTA UNIVERSITARIA")


SCUOLE_IN_OSPEDALE = re.compile(r"\bOSPEDAL|\bPOLICLINIC")
NOMI_CON_TITOLARE = {
    "Dall'Ape alla Zebra di Rita Lucchesi": "Dall'Ape alla Zebra",
}


def pulisci(servizi):
    conta = defaultdict(lambda: defaultdict(int))
    gruppi = defaultdict(list)
    for s in servizi:
        gruppi[(s["t"], chiave_testo(s["n"]), chiave_testo(s["i"]))].append(s)
    unici = []
    for k in sorted(gruppi):
        g = sorted(gruppi[k], key=lambda s: (priorita(s), s.get("q") != "comune", s["lat"], s["lon"]))
        unici.append(g[0])
        conta[k[0]]["doppioni"] += len(g) - 1
    # Le statali non sono nell'anagrafe delle paritarie: il confronto vale con le comunali
    # (paritarie per legge) e le paritarie del layer del Comune.
    infanzia_comune = [(s["lat"], s["lon"]) for s in unici
                       if s["t"] == "infanzia" and s.get("q") == "comune" and "statale" not in s["d"]]
    tenuti = []
    for s in unici:
        if (s.get("q") != "comune" and s["d"] == "Scuola dell'infanzia paritaria"
                and any(metri((s["lat"], s["lon"]), c) < 80 for c in infanzia_comune)):
            conta["infanzia"]["gia' nel Comune"] += 1
            continue
        if s["t"] == "nido" and "convenzione" not in s["d"] and "comunal" not in s["d"] and (
                s["d"] == "Nido aziendale" or NIDI_AZIENDALI.search(chiave_testo(s["n"]))):
            conta["nido"]["aziendali"] += 1
            continue
        if s["t"] != "nido" and SCUOLE_IN_OSPEDALE.search(chiave_testo(s["n"])):
            conta[s["t"]]["in ospedale"] += 1
            continue
        if s["n"] in NOMI_CON_TITOLARE:
            s = dict(s, n=NOMI_CON_TITOLARE[s["n"]])
        tenuti.append(s)
    tenuti.sort(key=lambda s: (s["t"], s["n"], s["lat"], s["lon"]))
    for t in ("nido", "infanzia", "primaria", "media", "superiore"):
        prima = sum(1 for s in servizi if s["t"] == t)
        dopo = sum(1 for s in tenuti if s["t"] == t)
        print("  pulizia %-10s %4d -> %4d  (%s)" % (t, prima, dopo, ", ".join(
            "%s %d" % kv for kv in conta[t].items()) or "nessuno scarto"))
    return tenuti


def scrivi(servizi):
    OUT.write_text(json.dumps({
        "fonti": {
            "scuole": "Roma Capitale (GeoRoma, servizi educativi 2025/26) e Ministero dell'Istruzione e del Merito "
                      "(anagrafe scuole a.s. 2026/27, posizioni dai civici di Roma Capitale)",
        },
        "servizi": servizi,
    }, ensure_ascii=False, indent=1), encoding="utf-8")



# ---------------------------------------------------------------------------
# Dettagli per la scheda: codici, sito, istituto, posti (vedi docstring del file)
# ---------------------------------------------------------------------------

SITO_ASSENTE = {"NON DISPONIBILE", "N D", "ND", "NO", "NESSUNO", "NULL", "NON PRESENTE", "ASSENTE"}
CODICE_MIM = re.compile(r"^[A-Z0-9]{10}$")
DOMINIO_SITO = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}$")


def sito_web(valore):
    """Sito della scuola normalizzato: https:// davanti se manca lo schema, dominio in
    minuscolo (il percorso resta com'e'), niente slash finale da solo. None se vuoto,
    "Non Disponibile", con spazi o chiocciola (testo, email) o senza un dominio vero."""
    v = (valore or "").strip()
    if not v or chiave_testo(v) in SITO_ASSENTE or re.search(r"\s|@", v):
        return None
    m = re.match(r"^(?:(https?)://)?([^/?#]+)([/?#].*)?$", v, flags=re.I)
    if not m:
        return None
    host = m.group(2).lower().rstrip(".")
    if ":" in host:                     # porta esplicita: la tolgo se e' quella standard
        host, _, porta = host.partition(":")
        if porta not in ("80", "443"):
            return None
    if not DOMINIO_SITO.match(host):
        return None
    resto = m.group(3) or ""
    return "https://" + host + ("" if resto == "/" else resto)


def sito_vietato(url):
    """True se l'URL farebbe scattare il gate zero-footprint (un'espressione dell'elenco dei
    termini vietati): quel sito non entra nei dettagli. Senza elenco dei termini, nessun sito
    si scarta."""
    import check_zero_footprint as gate
    termini = gate.carica_termini()
    if not termini:
        return False
    testo = gate.normalizza(url)
    return any(re.search(p, testo, re.IGNORECASE) for p in termini["vietate"])


def aggiungi_unico(lista, valore):
    if valore and valore not in lista:
        lista.append(valore)


def dettagli_scuole(comune, statali, paritarie, nidi, infanzia):
    """Dettagli delle scuole di data/scuole.json: dizionario (tipo, nome, indirizzo) -> oggetto
    con le chiavi m, w, ic, p, z, l (solo quelle piene). Non modifica i punti."""
    scuole = json.loads(OUT.read_text(encoding="utf-8"))["servizi"]

    # Anagrafe del Ministero: tutte le righe per codice (sito e istituto), e le sedi di Roma
    # per tipo, nome e civico (per le scuole che il Comune non ha: superiori, paritarie).
    stat_righe = {r["CODICESCUOLA"]: r for r in leggi_csv(statali)}
    par_righe = {r["CODICESCUOLA"]: r for r in leggi_csv(paritarie)}
    sedi = defaultdict(list)       # (tipo, chiave nome, civico) -> [(codice, via grezza)]
    for codice, r in stat_righe.items():
        if r["CODICECOMUNESCUOLA"] != "H501" or r["SEDESCOLASTICA"] != "SI":
            continue
        if r["DESCRIZIONECARATTERISTICASCUOLA"] in ("SPEC. PER CARCERARI", "C/O IST. OSPEDALIERO"):
            continue
        if superiore_statale(r["DESCRIZIONETIPOLOGIAGRADOISTRUZIONESCUOLA"]):
            via, num = separa_civico(r["INDIRIZZOSCUOLA"])
            sedi[("superiore", chiave_testo(titolo(r["DENOMINAZIONESCUOLA"])), num)].append((codice, via))
    for codice, r in par_righe.items():
        if r["CODICECOMUNESCUOLA"] != "H501":
            continue
        t = PARITARIE.get(r["DESCRIZIONETIPOLOGIAGRADOISTRUZIONESCUOLA"], (None, None))[0]
        if t:
            via, num = separa_civico(r["INDIRIZZOSCUOLA"])
            sedi[(t, chiave_testo(titolo(r["DENOMINAZIONESCUOLA"])), num)].append((codice, via))

    # Portale del Comune (nidi e infanzie comunali): una riga per edificio, ma posti e
    # sezioni sono quelli della scuola (stesso valore su ogni edificio del mesis).
    portale = {}
    for f in (nidi, infanzia):
        for x in json.loads(Path(f).read_text(encoding="utf-8"))["features"]:
            p = x["properties"]
            portale[(p["codice_edificio"], p["codice_mesis"])] = p

    # GeoRoma: codici, mesis e portale per (tipo, nome, indirizzo) come la pulizia dei doppioni.
    per_chiave = defaultdict(lambda: {"codici": [], "mesis": {}})
    for f in json.loads(Path(comune).read_text(encoding="utf-8"))["features"]:
        p = f["properties"]
        cat = TIPI_COMUNE.get(p.get("tipo_servizio"))
        if not cat or not f.get("geometry"):
            continue
        nome = NOMI_CON_TITOLARE.get(titolo(p.get("denominazione")), titolo(p.get("denominazione")))
        g = per_chiave[(cat[0], chiave_testo(nome), chiave_testo(indirizzo_comune(cat[0], nome, p.get("indirizzo"))))]
        # "RMMM8FF01G_s": la sezione staccata di una scuola porta il codice della scuola e il suffisso
        cod = re.sub(r"_[A-Za-z]+$", "", (p.get("meccanografico") or "").strip()).upper()
        if CODICE_MIM.match(cod):
            aggiungi_unico(g["codici"], cod)
        riga = portale.get((p.get("codice_edificio"), p.get("mesis")))
        if riga:
            g["mesis"][riga["codice_mesis"]] = riga

    out, scartati = {}, 0
    for s in scuole:
        g = per_chiave.get((s["t"], chiave_testo(s["n"]), chiave_testo(s["i"])))
        codici = list(g["codici"]) if g else []
        if s.get("q") in ("esatto", "vicino"):
            # sede del Ministero: tipo, nome e civico; se il nome e il civico coincidono su vie
            # diverse, vale quella compatibile con l'indirizzo della scuola
            via_s, num_s = separa_civico(s["i"])
            tok_s = chiave(via_s)[1]
            for codice, via in sedi.get((s["t"], chiave_testo(s["n"]), num_s), []):
                if Vie._compatibili(chiave(via)[1], tok_s) or Vie._compatibili(tok_s, chiave(via)[1]):
                    aggiungi_unico(codici, codice)
        d = {}
        if codici:
            d["m"] = codici
        siti, istituti = [], []
        for codice in codici:
            stat = stat_righe.get(codice)
            r = stat or par_righe.get(codice)
            if not r:
                continue
            sito = sito_web(r.get("SITOWEBSCUOLA"))
            if sito and sito_vietato(sito):
                scartati += 1
                sito = None
            aggiungi_unico(siti, sito)
            if stat and stat["CODICEISTITUTORIFERIMENTO"] != codice:
                ic = titolo(stat["DENOMINAZIONEISTITUTORIFERIMENTO"])
                if ic and chiave_testo(ic) != chiave_testo(s["n"]):
                    aggiungi_unico(istituti, ic)
        if siti:
            d["w"] = siti
        if istituti:
            d["ic"] = " · ".join(istituti)
        if g and g["mesis"]:
            righe = list(g["mesis"].values())
            d["p"] = sum(int(r["ricettivita"] or 0) for r in righe)
            d["z"] = sum(int(r["n_sezioni"] or 0) for r in righe)
            if all(r["chiuso_per_lavori"] for r in righe):
                d["l"] = 1
            if not d["p"]:
                del d["p"]
            if not d["z"]:
                del d["z"]
        if d:
            out[(s["t"], s["n"], s["i"])] = d
    return out, scartati


def scrivi_dettagli(dettagli):
    righe = [[t, n, i, d] for (t, n, i), d in sorted(dettagli.items())]
    corpo = ",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in righe)
    OUT_DETTAGLI.write_text(
        '{"fonti":' + json.dumps({
            "dettagli": "Ministero dell'Istruzione e del Merito (anagrafe scuole statali e paritarie a.s. 2026/27: "
                        "codici, siti, istituto di riferimento), Roma Capitale (GeoRoma e portale dei servizi educativi "
                        "2025/26: codici, posti e sezioni di nidi e infanzie comunali)"}, ensure_ascii=False)
        + ',\n"dettagli":[\n' + corpo + "\n]}\n", encoding="utf-8")


def main_dettagli(argomenti):
    if len(argomenti) != 5:
        raise SystemExit(__doc__)
    dettagli, scartati = dettagli_scuole(*argomenti)
    scrivi_dettagli(dettagli)
    tot = len(json.loads(OUT.read_text(encoding="utf-8"))["servizi"])
    print("Dettagli per %d scuole su %d (siti scartati dal gate zero-footprint: %d)" % (len(dettagli), tot, scartati))
    for chiave_d, etichetta in (("m", "codice"), ("w", "sito"), ("ic", "istituto"), ("p", "posti"), ("z", "sezioni"), ("l", "lavori")):
        print("  con %-8s %d" % (etichetta, sum(1 for d in dettagli.values() if chiave_d in d)))


def main():
    if sys.argv[1:2] == ["--dettagli"]:
        main_dettagli(sys.argv[2:])
        return
    if sys.argv[1:] == ["--pulisci"]:
        servizi = pulisci(json.loads(OUT.read_text(encoding="utf-8"))["servizi"])
        scrivi(servizi)
        print("In mappa:", len(servizi))
        return
    if len(sys.argv) < 5:
        raise SystemExit(__doc__)
    comune, statali, paritarie = sys.argv[1:4]
    vie = carica_civici(sys.argv[4:])

    servizi, mancanti = [], []
    conta = defaultdict(lambda: defaultdict(int))

    # 1. Comune, gia' geolocalizzati
    for f in json.loads(Path(comune).read_text(encoding="utf-8"))["features"]:
        p, g = f["properties"], f.get("geometry")
        cat = TIPI_COMUNE.get(p.get("tipo_servizio"))
        if not cat or not g:
            continue
        lon, lat = g["coordinates"][:2]
        nome = titolo(p.get("denominazione"))
        servizi.append({"t": cat[0], "n": nome, "i": indirizzo_comune(cat[0], nome, p.get("indirizzo")), "s": "attiva",
                        "d": cat[1], "lat": round(lat, 6), "lon": round(lon, 6), "q": "comune"})
        avvisa_via_lontana(vie, servizi[-1])
        conta[cat[0]]["Comune"] += 1

    # 2. Ministero, da geocodificare
    voci = []
    for r in leggi_csv(statali):
        if r["CODICECOMUNESCUOLA"] != "H501" or r["SEDESCOLASTICA"] != "SI":
            continue
        if r["DESCRIZIONECARATTERISTICASCUOLA"] in ("SPEC. PER CARCERARI", "C/O IST. OSPEDALIERO"):
            continue
        d = superiore_statale(r["DESCRIZIONETIPOLOGIAGRADOISTRUZIONESCUOLA"])
        if d:
            voci.append(("superiore", r["DENOMINAZIONESCUOLA"], d, r["INDIRIZZOSCUOLA"], "MIM statali"))
    for r in leggi_csv(paritarie):
        if r["CODICECOMUNESCUOLA"] != "H501":
            continue
        t, d = PARITARIE.get(r["DESCRIZIONETIPOLOGIAGRADOISTRUZIONESCUOLA"], (None, None))
        if t:
            voci.append((t, r["DENOMINAZIONESCUOLA"], d, r["INDIRIZZOSCUOLA"], "MIM paritarie"))

    voci = [(t, nome, d, INDIRIZZI_MIM.get((nome, ind), ind), fonte) for t, nome, d, ind, fonte in voci]
    per_indirizzo = defaultdict(set)
    for t, nome, d, indirizzo, fonte in voci:
        via_n, num_n = separa_civico(indirizzo)
        per_indirizzo[(t, chiave_testo(via_n), num_n)].add(chiave_testo(nome))
    altre_sedi = defaultdict(set)
    for t, nome, d, indirizzo, fonte in voci:
        via_n, num_n = separa_civico(indirizzo)
        k = (t, chiave_testo(via_n), num_n)
        if per_indirizzo[k] - {chiave_testo(nome)}:
            altre_sedi[nome, indirizzo].add(k)

    for t, nome, d, indirizzo, fonte in voci:
        indirizzo = INDIRIZZI_MIM.get((nome, indirizzo), indirizzo)
        # Una "scuola" che si chiama come la sua via e' l'istituto di riferimento registrato
        # allo stesso indirizzo di un'altra sede dello stesso tipo: non e' un luogo in piu'.
        # Se non c'e' un'altra sede a quell'indirizzo, e' una sede vera e resta.
        via_n, num_n = separa_civico(indirizzo)
        if chiave_testo(nome) == chiave_testo(via_n) and (t, chiave_testo(via_n), num_n) in altre_sedi[nome, indirizzo]:
            conta[t]["istituto = via"] += 1
            continue
        punto, via = geocodifica(vie, indirizzo)
        if not punto:
            conta[t]["non trovate"] += 1
            mancanti.append([t, fonte, nome, indirizzo, via])
            continue
        lat, lon, q = punto
        conta[t][q] += 1
        via_txt, num = separa_civico(indirizzo)
        servizi.append({"t": t, "n": titolo(nome), "i": titolo(via) + (" " + str(num) if num else ""), "s": "attiva",
                        "d": d, "lat": round(lat, 6), "lon": round(lon, 6), "q": q})

    servizi = pulisci(servizi)
    scrivi(servizi)
    # Una sede del Ministero che il Comune ha gia' in mappa (stesso tipo e nome) non e' "non trovata".
    in_mappa = {(s["t"], chiave_testo(s["n"])) for s in servizi}
    gia = [m for m in mancanti if (m[0], chiave_testo(titolo(m[2]))) in in_mappa]
    mancanti = [m for m in mancanti if m not in gia]
    with open(OUT_NON_TROVATE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tipo", "fonte", "nome", "indirizzo", "motivo"])
        w.writerows(mancanti)

    print("In mappa:", len(servizi), "· non trovate:", len(mancanti), "(altre %d sono gia' in mappa col nome del Comune)" % len(gia))
    for t in ("nido", "infanzia", "primaria", "media", "superiore"):
        c = conta[t]
        geo = c["esatto"] + c["vicino"] + c["non trovate"]
        print("  %-10s Comune %4d · Ministero: esatto %4d  vicino %3d  non trovate %3d%s" % (
            t, c["Comune"], c["esatto"], c["vicino"], c["non trovate"],
            ("  (%.0f%% agganciate)" % (100 * (c["esatto"] + c["vicino"]) / geo)) if geo else ""))


if __name__ == "__main__":
    main()
