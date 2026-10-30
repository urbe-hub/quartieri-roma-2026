#!/usr/bin/env python3
"""
Servizi della "citta' dei 15 minuti": i punti che la mappa cerca attorno a un indirizzo.

Prima versione: sanita'.
  - Case della Comunita' di Roma (AGENAS, monitoraggio PNRR, rilevazione al
    2025-12-31), attive e previste; restano fuori Centrali operative (COT) e
    Ospedali di comunita', che non sono servizi a cui si va a piedi.
  - Ospedali con pronto soccorso di Roma (elenco della Regione Lazio, coordinate
    abbinate su OpenStreetMap).

Poi scuole e nidi, se c'e' data/scuole.json (prepara_scuole.py).

Le fonti sono tre file JSON (case_comunita.json, cdc_agenas_tutte.json e
hospitals.json) in una cartella di input, indicata col primo argomento o con la
variabile d'ambiente MAPPA_FONTI. Uso:
    python3 prepara_servizi_15_minuti.py <cartella fonti> [civici_*.csv ...]
    MAPPA_FONTI=<cartella fonti> python3 prepara_servizi_15_minuti.py [civici_*.csv ...]
Con i civici di Roma Capitale (vedi prepara_scuole.py) le case della comunita' con
coordinate AGENAS sbagliate si riposizionano sull'indirizzo.
Scrive data/servizi-15-minuti.json: solo nome, tipo, stato, indirizzo, dettaglio, coordinate.
"""

import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# Cartella delle fonti: valorizzata in main() dall'argomento o da MAPPA_FONTI.
FONTI = None
OUT = SCRIPT_DIR / "data" / "servizi-15-minuti.json"
SCUOLE = SCRIPT_DIR / "data" / "scuole.json"

# Case della Comunita' con la posizione AGENAS sbagliata, per CUP: indirizzo e coordinate
# dell'elenco della Regione Lazio (verificati: la posizione AGENAS cade a 9 km dalla strada).
CORREZIONI_CDC = {
    "C89J22001100001": {"i": "Viale Camillo Sabatini", "lat": 41.820808, "lon": 12.443076},
}
# Una casa senza civico deve stare entro questa distanza dalla casa piu' vicina dell'elenco
# della Regione: oltre, la posizione AGENAS e' sospetta e lo script si ferma.
SOGLIA_REGIONE_METRI = 1000

# Nomi del pronto soccorso come li dice chi ci va, non come li abbrevia l'elenco.
NOMI_OSPEDALI = {
    "Bambino Gesu'": "Ospedale Pediatrico Bambino Gesù",
    "C.T.O. Andrea Alesini": "CTO Andrea Alesini",
    "Campus Biomedico": "Policlinico Campus Bio-Medico",
    "Cristo Re": "Ospedale Cristo Re",
    "FBF-Gemelli Isola Tiberina": "Fatebenefratelli Isola Tiberina",
    "G. Battista Grassi": "Ospedale G. B. Grassi",
    "Madre G. Vannini": "Ospedale Madre Giuseppina Vannini",
    "Oftalmico": "Ospedale Oftalmico",
    "Pol. Univ. A. Gemelli": "Policlinico Gemelli",
    "Pol. Univ. Tor Vergata": "Policlinico Tor Vergata",
    "Pol. Univ. Umberto I": "Policlinico Umberto I",
    "San Camillo-Forlanini": "Ospedale San Camillo",
    "San Carlo di Nancy": "Ospedale San Carlo di Nancy",
    "San Filippo Neri": "Ospedale San Filippo Neri",
    "San Giovanni Addolorata": "Ospedale San Giovanni Addolorata",
    "San Pietro-FBF": "Ospedale San Pietro Fatebenefratelli",
    "Sandro Pertini": "Ospedale Sandro Pertini",
    "Sant'Andrea": "Ospedale Sant'Andrea",
    "Sant'Eugenio": "Ospedale Sant'Eugenio",
    "Santo Spirito": "Ospedale Santo Spirito",
}
DETTAGLIO_PS = {
    "DEA II": "Pronto soccorso, DEA di II livello",
    "DEA I": "Pronto soccorso, DEA di I livello",
    "PS": "Pronto soccorso",
    "PS SPEC.": "Pronto soccorso specialistico",
}
# Pronto soccorso che non sono quello di riferimento per chi abita vicino: si mostrano,
# ma con l'etichetta, e la mappa non li propone come "il piu' vicino" (campo "x").
PS_SPECIALISTICI = {"PS SPEC.": "specialistico"}
PS_PEDIATRICI = {"Bambino Gesu'"}

# Nome proprio della casa quando l'elenco lo ha; altrimenti basta l'indirizzo.
NOMI_CDC_GENERICI = re.compile(r"^(CASA (DELLA|DI) COMUNIT\S*|EX ORATORIO.*|POLIAMBUL\S* .*\d.*)$")
TOPONIMI = ("VIA ", "VIALE ", "PIAZZA ", "LARGO ", "LUNGOMARE ", "PIAZZALE ", "CORSO ")
MINUSCOLE = {"di", "de", "del", "della", "delle", "dei", "degli", "da", "e"}


def titolo(s):
    parole = s.lower().split()
    out = []
    for i, p in enumerate(parole):
        if i and p in MINUSCOLE:
            out.append(p)
        else:
            out.append(p[:1].upper() + p[1:])
    t = " ".join(out)
    t = re.sub(r"(['-])(\w)", lambda m: m.group(1) + m.group(2).upper(), t)
    return t.replace("Comunita'", "Comunità").replace("Niccolo'", "Niccolò").replace("Coppede'", "Coppedè")


def indirizzo_cdc(raw):
    via = raw.split(" - ")[0].replace(", SNC", "").replace(",", "")
    if not via.upper().startswith(TOPONIMI):
        via = "VIA " + via
    return titolo(via)


def nome_cdc(x):
    n = x["nome"].replace("COMINITA'", "COMUNITA'").replace("POLIAMBULTORIO", "POLIAMBULATORIO")
    if n.startswith("CASA DELLA SALUTE LUNGOMARE"):
        return "Casa della Comunità Ostia"
    if NOMI_CDC_GENERICI.match(n):
        return "Casa della Comunità"
    n = re.sub(r"^CASA DELLA (COMUNIT\S*|SALUTE)\s*", "", n)
    n = re.sub(r"^POLIAMBULATORIO\s*", "", n)
    n = re.sub(r"\s*-?\s*VIA .*$|\s+LUNGOMARE .*$|\s+LARGO .*$", "", n)
    return "Casa della Comunità " + titolo(n) if n else "Casa della Comunità"


def correggi_posizioni(servizi, civici_files):
    # Le coordinate AGENAS di alcune case sono lontane dall'indirizzo (fino a 10 km,
    # verificato il 2026-10-27): se l'indirizzo si aggancia ai civici di Roma Capitale
    # e il punto AGENAS sta a piu' di 150 m, vale il civico.
    from prepara_scuole import carica_civici, geocodifica, metri
    vie = carica_civici(civici_files)
    for s in servizi:
        if s["t"] != "cdc":
            continue
        punto, _ = geocodifica(vie, s["i"])
        if punto and punto[2] == "esatto":
            d = metri((s["lat"], s["lon"]), (punto[0], punto[1]))
            if d > 150:
                print("  %s (%s): spostata di %.0f m sul civico" % (s["n"], s["i"], d))
                s["lat"], s["lon"] = round(punto[0], 6), round(punto[1], 6)


def controlla_case_senza_civico(servizi):
    # Le case senza civico non si possono riposizionare sull'indirizzo: per queste la posizione
    # si confronta con l'elenco della Regione Lazio, e se e' lontana lo script si ferma.
    from prepara_scuole import metri
    regione = [(c["lat"], c["lon"]) for c in json.loads((FONTI / "case_comunita.json").read_text(encoding="utf-8"))]
    lontane = []
    for s in servizi:
        if s["t"] != "cdc" or re.search(r"\d", s["i"]):
            continue
        d = min(metri((s["lat"], s["lon"]), r) for r in regione)
        if d > SOGLIA_REGIONE_METRI:
            lontane.append("%s (%s): %.0f m dalla casa piu' vicina dell'elenco della Regione" % (s["n"], s["i"], d))
    if lontane:
        raise SystemExit("Errore: case senza civico lontane dall'elenco della Regione:\n  " + "\n  ".join(lontane))


def cartella_fonti(argomenti):
    """(cartella delle fonti, argomenti restanti): la cartella e' il primo argomento se e'
    una directory, altrimenti MAPPA_FONTI; senza nessuna delle due lo script si ferma."""
    if argomenti and Path(argomenti[0]).expanduser().is_dir():
        return Path(argomenti[0]).expanduser().resolve(), argomenti[1:]
    if os.environ.get("MAPPA_FONTI"):
        return Path(os.environ["MAPPA_FONTI"]).expanduser().resolve(), argomenti
    raise SystemExit("Uso: python3 prepara_servizi_15_minuti.py <cartella fonti> [civici_*.csv ...]"
                     " (oppure MAPPA_FONTI=<cartella fonti>)")


def main():
    global FONTI
    FONTI, civici = cartella_fonti(sys.argv[1:])
    servizi = []
    for x in json.loads((FONTI / "cdc_agenas_tutte.json").read_text(encoding="utf-8")):
        if x["comune"] != "Roma" or x["tipo_struttura"] != "CDC":
            continue
        g = x.get("giorni_apertura") or ""
        corr = CORREZIONI_CDC.get(x.get("cup"), {})
        servizi.append({
            "t": "cdc",
            "n": nome_cdc(x),
            "i": corr.get("i") or indirizzo_cdc(x["indirizzo_completo"]),
            "s": "attiva" if x["stato"] == "attiva" else "prevista",
            "d": {"7GG/7": "Aperta 7 giorni su 7", "6GG/7": "Aperta 6 giorni su 7",
                  "MENO DI 6GG/7": "Aperta meno di 6 giorni su 7"}.get(g, ""),
            "lat": round(corr.get("lat", x["lat"]), 6), "lon": round(corr.get("lon", x["lon"]), 6),
        })
    for x in json.loads((FONTI / "hospitals.json").read_text(encoding="utf-8")):
        if x["comune"].lower() != "roma":
            continue
        ps = {
            "t": "ps",
            "n": NOMI_OSPEDALI.get(x["istituto"], x["istituto"]),
            "i": "",
            "s": "attiva",
            "d": DETTAGLIO_PS.get(x["tipo"], "Pronto soccorso"),
            "lat": round(x["lat"], 6), "lon": round(x["lon"], 6),
        }
        if x["istituto"] in PS_PEDIATRICI:
            ps["x"], ps["d"] = "pediatrico", "Pronto soccorso pediatrico"
        elif x["tipo"] in PS_SPECIALISTICI:
            ps["x"] = PS_SPECIALISTICI[x["tipo"]]
        servizi.append(ps)
    if civici:
        correggi_posizioni(servizi, civici)
    controlla_case_senza_civico(servizi)
    fonti = {
        "cdc": "AGENAS, monitoraggio Case della Comunità PNRR, rilevazione al 31/12/2025; posizioni dai civici di Roma Capitale",
        "ps": "Regione Lazio, elenco dei pronto soccorso; posizioni da OpenStreetMap",
    }
    # Scuole e nidi, se prepara_scuole.py li ha gia' preparati.
    if SCUOLE.exists():
        scuole = json.loads(SCUOLE.read_text(encoding="utf-8"))
        servizi += scuole["servizi"]
        fonti.update(scuole["fonti"])
    OUT.write_text(json.dumps({"fonti": fonti, "servizi": servizi}, ensure_ascii=False, indent=1), encoding="utf-8")
    conta = {}
    for s in servizi:
        conta[s["t"]] = conta.get(s["t"], 0) + 1
    print("Servizi:", len(servizi), "·", ", ".join("%s %d" % kv for kv in conta.items()))


if __name__ == "__main__":
    main()
