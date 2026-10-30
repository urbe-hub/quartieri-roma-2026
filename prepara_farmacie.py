#!/usr/bin/env python3
"""
Farmacie di Roma dall'anagrafe del Ministero della Salute.

Fonte: Ministero della Salute, "Elenco delle farmacie" (dati aperti, dati.salute.gov.it), file
FRM_FARMA_5_<AAAAMMGG>.csv, separato da ";". Si tengono le righe con comune ROMA e
data_fine_validita "-" (cioe' le farmacie attive alla data del file): le righe chiuse
restano nell'anagrafe come storico e non vanno sulla mappa.

Posizione: l'indirizzo ufficiale del Ministero si aggancia ai numeri civici di Roma
Capitale (GeoRoma, DIPCUL:GeoromaCiviciLocator), con lo stesso geocoder delle scuole
(prepara_scuole.geocodifica). Le coordinate del Ministero non bastano da sole: alcune sono
fuori Roma o ripetute uguali su piu' farmacie. Si usano solo quando l'indirizzo non si
aggancia, e solo se cadono dentro un'area di Roma e non sono ripetute.

Il punto mostra "Farmacia" (o "Farmacia comunale", "Dispensario farmaceutico") e
l'indirizzo ufficiale; la ragione sociale non si mostra (spesso contiene nomi di persona).

Uso:
    python3 prepara_farmacie.py <FRM_FARMA_5_AAAAMMGG.csv> <civici_*.csv ...>
Riscrive solo la categoria "farmacie" di data/servizi/servizi.json; le altre restano.
"""

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # anche con python3 -I

from prepara_scuole import carica_civici, geocodifica, senza_accenti, titolo
from importa_servizi import (OUT_PATH, QUARTIERI_PATH, accorpa_doppioni, carica_poligoni,
                             trova_area, trova_area_vicina, scrivi)

CATEGORIA = "farmacie"
# Farmacie comunali di Roma: gestite da Farmacap (Azienda speciale farmacie comunali).
COMUNALE = re.compile(r"FARMACAP|\bCOMUNAL[EI]\b|\bCOM\.\s*LE\b", re.I)


# Vie scritte dal Ministero in modo diverso dai civici di Roma Capitale (via ripulita, in
# maiuscolo e senza accenti -> toponimo dei civici). Solo errori di battitura o nomi con un
# pezzo in piu' o in meno: ogni voce e' stata controllata a mano sul file dei civici.
CORREZIONI = {
    "VIALE CARLO MARX": "VIALE MARX",
    "VIA TIBERO IMPERATORE": "VIA TIBERIO IMPERATORE",
    "VIA A. CECHOV": "VIA CECHOV",
    "VIA LUIGI CAFFARO": "VIA CAFFARO",
    "VIA DELLA CORRAZZATA": "VIA DELLA CORAZZATA",
    "PIAZZA A.F.DORIA PAMPHILI": "PIAZZA FILIPPO ANDREA DORIA PAMPHILI",
    "PIAZZA S. PIERDAMIANI": "PIAZZA S. PIER DAMIANI",
    "VIA G. MARCONI": "VIALE GUGLIELMO MARCONI",
    "VIALE COLLI PORETUENSI": "VIALE DEI COLLI PORTUENSI",
    "VIALE COLA DI RIENZO": "VIA COLA DI RIENZO",
    "VIALE RONALDO VIGNALI": "VIALE ROLANDO VIGNALI",
    "VIA GALBANI": "VIALE EGIDIO GALBANI",
    "VIA ABIGAILE ZANETTA": "VIA ABIGAILLE ZANETTA",
    "VIA FONTEBUONO": "VIA FONTE BUONO",
    "VIA TORPIGNATTARA": "VIA DI TOR PIGNATTARA",
    "VIA RENZO BERTAMI": "VIA RENZO BERTANI",
    "VIA ROCCA PRIORA": "VIA ROCCAPRIORA",
    "VIA LEONARDO DA VINCI": "VIALE LEONARDO DA VINCI",
    "VIA IGNAZIO SILONE": "VIALE IGNAZIO SILONE",
    "VIA DI VALLE MELANIA": "VIA DI VALLE MELAINA",
    "CORSO VITTORIO EMANUELE": "CORSO VITTORIO EMANUELE II",
    "VIA G. ALESSI": "VIA GALEAZZO ALESSI",
    "VIA MAZZINI": "VIALE GIUSEPPE MAZZINI",   # CAP 00195, Prati (non Via Maria Drago Mazzini)
}
TOPONIMI_DOPPI = re.compile(r"^(VIA|VIALE)\s+(?=(VIA|VIALE|PIAZZA|PIAZZALE|LARGO|CIRCONVALLAZIONE|LUNGOTEVERE|"
                            r"VICOLO|CORSO|STRADA)\b)", re.I)
NUMERALI = {"I": "PRIMO", "II": "DUE", "III": "TRE", "IV": "QUATTRO", "V": "CINQUE", "VI": "SEI",
            "VII": "SETTE", "VIII": "OTTO", "IX": "NOVE", "X": "DIECI", "XI": "UNDICI", "XII": "DODICI",
            "XIII": "TREDICI", "XIV": "QUATTORDICI", "XV": "QUINDICI", "XVI": "SEDICI",
            "XVII": "DICIASSETTE", "XVIII": "DICIOTTO", "XIX": "DICIANNOVE", "XX": "VENTI",
            "XXI": "VENTUNO", "XXII": "VENTIDUE", "XXIII": "VENTITRE", "XXIV": "VENTIQUATTRO",
            "XXV": "VENTICINQUE", "XXVI": "VENTISEI", "XXVII": "VENTISETTE", "XXVIII": "VENTOTTO",
            "XXIX": "VENTINOVE", "XXX": "TRENTA", "XXXI": "TRENTUNO"}
MESI = "GENNAIO|FEBBRAIO|MARZO|APRILE|MAGGIO|GIUGNO|LUGLIO|AGOSTO|SETTEMBRE|OTTOBRE|NOVEMBRE|DICEMBRE"


def senza_mojibake(s):
    """Il CSV del Ministero ha alcune lettere accentate codificate due volte ("BarzanÃ²")."""
    for _ in range(3):
        try:
            nuovo = s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
        if nuovo == s:
            return s
        s = nuovo
    return s


def pulisci_indirizzo(grezzo):
    """Indirizzo del Ministero pronto per il geocoder: senza note tra parentesi e senza
    "angolo ...", senza toponimo ripetuto ("Via Via ..."), date in lettere come nei civici
    ("Via XX Settembre" -> "VIA VENTI SETTEMBRE"), con le correzioni note."""
    s = senza_mojibake(grezzo)
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\s+(ANG\.|ANGOLO\b|-\s+[A-Z]{2,}).*$", "", s, flags=re.I)
    s = re.sub(r"\bNN?\.\s*(?=\d)", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" ,")
    for _ in range(2):
        s = TOPONIMI_DOPPI.sub("", s)
    s = re.sub(r"\b([IVX]+)\s+(?=(" + MESI + r")\b)", lambda m: NUMERALI.get(m.group(1).upper(), m.group(1)) + " ",
               s, flags=re.I)
    m = re.match(r"^(.*?)([\s,]+(?:\d|KM|SNC).*)?$", s, flags=re.I)
    via, resto = m.group(1).strip(" ,"), (m.group(2) or "")
    chiave = senza_accenti(via).upper()
    return CORREZIONI.get(chiave, via) + resto


def numero_float(s):
    try:
        return float(s.replace(",", "."))
    except (AttributeError, ValueError):
        return None


def indirizzo_mostrato(grezzo, via_civici):
    """Via col nome dei civici (se agganciata) + i civici come li scrive il Ministero
    ("60/62", "34-35", "225-231"), senza "angolo ...", note, "Roma" o edificio."""
    s = senza_mojibake(grezzo).replace("\\", "/")
    s = re.sub(r",?\s*\bSNC\b", "", s, flags=re.I)   # "senza numero civico"
    s = re.sub(r"\bN[NR]?\.?\s*(?=\d)", "", s, flags=re.I)
    m = re.match(r"^(.*?)[\s,]+(\d.*)$", s.strip())
    via, resto = (m.group(1), m.group(2)) if m else (s, "")
    # Solo il gruppo dei civici iniziale: numeri ("13/A"), lettere singole ("A", "B") ed "e".
    # Fra due numeri va "-" ("225-231"), altrimenti uno spazio ("39/A e B").
    pezzi = []
    for t in re.finditer(r"\s*([,\-/]?)\s*(\d+(?:\s*/\s*(?:\d+|[A-Z]))?[A-Z]?(?![\w.])|[A-Z](?![\w.])|e(?=\s+[A-Z]\b))",
                         resto):
        if t.start() != (pezzi[-1][2] if pezzi else 0):
            break
        pezzi.append((t.group(1), re.sub(r"\s+", "", t.group(2)), t.end()))
    numero = ""
    for i, (sep, val, _) in enumerate(pezzi):
        if i == 0:
            numero = val
        elif val[0].isdigit() and numero[-1].isdigit() or sep in ("-", ","):
            numero += "-" + val
        elif sep == "/":
            numero += "/" + val
        else:
            numero += " " + val
    return (titolo(via_civici or via.strip(" ,")) + (" " + numero if numero else "")).strip()


def tipo_farmacia(r):
    if "dispensario" in r["descrizione_tipologia"].lower():
        return "Dispensario farmaceutico"
    if COMUNALE.search(r["descrizione_farmacia"]):
        return "Farmacia comunale"
    return "Farmacia"


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    righe = list(csv.DictReader(open(sys.argv[1], encoding="latin-1"), delimiter=";"))
    attive = [r for r in righe if r["comune"].strip().upper() == "ROMA"
              and r["data_fine_validita"].strip() == "-"]
    print("Anagrafe Ministero: " + str(len(righe)) + " righe, Roma attive: " + str(len(attive)))
    vie = carica_civici(sys.argv[2:])
    aree = carica_poligoni(QUARTIERI_PATH, ("codice", "denominazione", "tipo", "municipio"))

    coppie = Counter((r["latitudine"].strip(), r["longitudine"].strip()) for r in attive)
    nuove, qualita, scartate = [], Counter(), []
    for r in attive:
        r["indirizzo"] = pulisci_indirizzo(r["indirizzo"])
        pos, via = geocodifica(vie, r["indirizzo"])
        if pos:
            lat, lon, q = pos
            qualita[q] += 1
        else:
            lat, lon = numero_float(r["latitudine"]), numero_float(r["longitudine"])
            ripetuta = coppie[(r["latitudine"].strip(), r["longitudine"].strip())] > 1
            if lat is None or lon is None or ripetuta or not trova_area(lon, lat, aree):
                scartate.append((r["indirizzo"], via))
                continue
            via, q = None, "coordinate Ministero"
            qualita[q] += 1
        area = trova_area(lon, lat, aree) or trova_area_vicina(lon, lat, aree)
        if not area:
            scartate.append((r["indirizzo"], "fuori dalle aree"))
            continue
        nuove.append((CATEGORIA, tipo_farmacia(r), area["codice"], area["municipio"],
                      round(lat, 5), round(lon, 5),
                      (indirizzo_mostrato(r["indirizzo"], via if q != "coordinate Ministero" else None),)))

    d = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    altre = [(d["c"][p[0]], p[1], p[2], p[3], p[4], p[5], tuple(p[6:])) for p in d["p"]
             if d["c"][p[0]] != CATEGORIA]
    prima = sum(1 for p in d["p"] if d["c"][p[0]] == CATEGORIA)
    print("posizione: " + ", ".join(k + " " + str(v) for k, v in sorted(qualita.items())))
    print("scartate (senza posizione affidabile): " + str(len(scartate)))
    for ind, motivo in scartate:
        print("  - " + ind + " (" + str(motivo) + ")")
    print("farmacie: prima " + str(prima) + ", ora " + str(len(nuove))
          + " (" + str(Counter(p[1] for p in nuove)) + ")")
    scrivi(accorpa_doppioni(altre + nuove))


if __name__ == "__main__":
    main()
