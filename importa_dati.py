#!/usr/bin/env python3
"""
Importa in data/ la geografia della delibera n. 150 del 2026 (334 quartieri,
22 rioni, 101 zone funzionali) e lo stradario, da una cartella di input con i
file gia' pronti (quartieri-2026.geojson, quartieri-2026.simplified.geojson,
strade/).

Cosa entra, e solo questo (whitelist, come nel builder):
  - data/quartieri-2026.simplified.geojson: geometria semplificata + campi
    geografici, con la classe di funzionalita' presa dal layer grezzo;
  - data/strade/indice.json: una riga per via, [nome, [codici delle aree]];
  - data/strade/m<N>.json: per municipio, area -> [nome, metri, tracciati].

Fonti ufficiali a monte: WFS DIPCUL:vst_nuove_localita (aree) e
DIPPC:stradario_municipio (vie) del Geoportale di Roma Capitale, open data.

Uso:
    python3 importa_dati.py <cartella di input>
"""

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA = SCRIPT_DIR / "data"

CAMPI_AREA = ("denominazione", "tipo", "municipio", "municipio_num_arabo", "codice",
              "superficie_kmq", "classe_funzionalita")

# Il WFS tronca la classe a 50 caratteri e perde le lettere accentate ("?").
CLASSI_RIPARATE = {
    "Servizi di pubblica utilit? e servizi amministrati": "Servizi di pubblica utilità e servizi amministrativi",
    "Impianti per la produzione industriali e di energi": "Impianti per la produzione industriale e di energia",
    "Turismo e attivit? ludico ricreative": "Turismo e attività ludico-ricreative",
    "Comprensorio Militare - Luoghi di interesse cultur": "Comprensorio militare e luoghi di interesse culturale",
    "Comprensorio Militare": "Comprensorio militare",
}

# Accenti scritti come apostrofo nel layer grezzo ("CINECITTA'"): correzione solo su
# questi nomi interi, gli apostrofi legittimi (DE', DELL', SANT') restano intatti.
DENOMINAZIONI_ACCENTI = {
    "CINECITTA'": "CINECITTÀ",
    "CINECITTA' EST": "CINECITTÀ EST",
    "CITTA' MILITARE DELLA CECCHIGNOLA": "CITTÀ MILITARE DELLA CECCHIGNOLA",
    "LAMARO - CINECITTA'": "LAMARO - CINECITTÀ",
    "SANTA MARIA DELLA PIETA'": "SANTA MARIA DELLA PIETÀ",
    "SAPIENZA UNIVERSITA'": "SAPIENZA UNIVERSITÀ",
    "TOR VERGATA UNIVERSITA'": "TOR VERGATA UNIVERSITÀ",
}

# Nomi di via corrotti nello stradario di origine: nome sbagliato -> nome giusto. Se il nome
# giusto c'e' gia' (stessa via nello stesso quartiere), le due voci si fondono.
CORREZIONI_NOMI = {
    "Largo Fratelli Lumiãˆre": "Largo Fratelli Lumiere",
    "Via Promãˆteo": "Via Prometeo",
}


def json_compatto(dati):
    return json.dumps(dati, ensure_ascii=False, separators=(",", ":"))


def unisci_aree(a, b):
    return a + [x for x in b if x not in a]


def correggi_indice(righe):
    """Applica CORREZIONI_NOMI all'indice [nome, aree]: le voci con lo stesso nome si fondono
    (aree unite, ordine del primo incontro)."""
    out, posizione = [], {}
    for nome, aree in righe:
        nome = CORREZIONI_NOMI.get(nome, nome)
        if nome in posizione:
            riga = out[posizione[nome]]
            riga[1] = unisci_aree(riga[1], aree)
        else:
            posizione[nome] = len(out)
            out.append([nome, list(aree)])
    return out


def correggi_quartiere(righe):
    """Applica CORREZIONI_NOMI alle righe [nome, metri, tracciati] di un'area: due righe con
    lo stesso nome si fondono (metri sommati, tracciati accodati)."""
    out, posizione = [], {}
    for nome, metri, tracciati in righe:
        nome = CORREZIONI_NOMI.get(nome, nome)
        if nome in posizione:
            riga = out[posizione[nome]]
            riga[1] += metri
            riga[2] = riga[2] + tracciati
        else:
            posizione[nome] = len(out)
            out.append([nome, metri, list(tracciati)])
    return out


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python3 importa_dati.py <cartella di input>")
    src = Path(sys.argv[1]).expanduser().resolve()

    # Tutto si valida in memoria; i file in data/ si toccano solo alla fine, a controlli passati.
    grezzo = json.loads((src / "quartieri-2026.geojson").read_text(encoding="utf-8"))
    classe = {f["properties"]["codice"]: f["properties"].get("classe_funzionalita")
              for f in grezzo["features"]}
    semplice = json.loads((src / "quartieri-2026.simplified.geojson").read_text(encoding="utf-8"))

    features = []
    for f in semplice["features"]:
        p = dict(f["properties"])
        c = classe.get(p["codice"])
        p["classe_funzionalita"] = CLASSI_RIPARATE.get(c, c)
        if p.get("denominazione") in DENOMINAZIONI_ACCENTI:
            p["denominazione"] = DENOMINAZIONI_ACCENTI[p["denominazione"]]
        props = {k: p[k] for k in CAMPI_AREA if p.get(k) is not None}
        features.append({"type": "Feature", "properties": props, "geometry": f["geometry"]})
    if len(features) != len(classe):
        raise SystemExit("Errore: " + str(len(features)) + " aree semplificate contro "
                         + str(len(classe)) + " grezze.")

    codici = set(classe)
    indice = json.loads((src / "strade" / "indice.json").read_text(encoding="utf-8"))
    vie = []
    for nome, aree, _bbox in indice["vie"]:
        if not set(aree) <= codici:
            raise SystemExit("Errore: la via " + nome + " cita aree fuori dalla geografia.")
        vie.append([nome, aree])
    vie = correggi_indice(vie)

    per_municipio = {}
    for f in sorted((src / "strade").glob("m*.json")):
        dati = json.loads(f.read_text(encoding="utf-8"))
        quartieri = {}
        for cod, righe in dati["quartieri"].items():
            if cod not in codici:
                raise SystemExit("Errore: " + f.name + " cita l'area sconosciuta " + cod + ".")
            quartieri[cod] = correggi_quartiere([[r[0], r[1], r[2]] for r in righe])
        per_municipio[f.name] = {"quartieri": quartieri}

    # Scrittura.
    (DATA / "quartieri-2026.simplified.geojson").write_text(
        json_compatto({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    print("aree: " + str(len(features)))
    out_strade = DATA / "strade"
    out_strade.mkdir(exist_ok=True)
    for vecchio in out_strade.glob("*.json"):
        vecchio.unlink()
    (out_strade / "indice.json").write_text(json_compatto({"vie": vie}), encoding="utf-8")
    for nome_file, dati in per_municipio.items():
        (out_strade / nome_file).write_text(json_compatto(dati), encoding="utf-8")
    print("vie: " + str(len(vie)) + ", file per municipio: " + str(len(per_municipio)))


if __name__ == "__main__":
    main()
