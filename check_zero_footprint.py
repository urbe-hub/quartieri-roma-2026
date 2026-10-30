#!/usr/bin/env python3
"""Gate a pattern sul bundle pubblico: fallisce se un file contiene uno dei termini vietati.

I termini non stanno in questo script: si leggono da zero_footprint_termini.json, accanto
allo script (o da un altro file, con --termini <file> o con la variabile d'ambiente
ZERO_FOOTPRINT_TERMINI). Il file e' un oggetto JSON con tre liste:
  - "vietate":         espressioni regolari (senza distinzione di maiuscole);
  - "strade_omonime":  stringhe esatte ammesse nei file delle strade (--strade);
  - "servizi_omonimi": stringhe esatte ammesse nei file dei servizi (--servizi).
Se il file non c'e' il gate stampa un avviso (una volta sola) e passa: la build non dipende
dai termini. Il controllo su file non leggibili resta fail-closed.

Il gate e' la rete di sicurezza sul bundle finale; la garanzia strutturale sta nella
whitelist delle properties del builder.

LIMITE NOTO: un gate a pattern su stdlib non intercetta l'offuscamento avanzato (omoglifi
Unicode, payload codificati in base64). Contro questi la difesa resta la whitelist delle
properties, non il pattern matching testuale.
"""
import html
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

TERMINI_PREDEFINITO = Path(__file__).resolve().parent / "zero_footprint_termini.json"

_avvisato = False


def carica_termini(termini_path=None):
    """Legge i termini; None se il file manca (il chiamante avvisa e passa)."""
    if termini_path is None:
        env = os.environ.get("ZERO_FOOTPRINT_TERMINI")
        termini_path = Path(env) if env else TERMINI_PREDEFINITO
    termini_path = Path(termini_path)
    if not termini_path.exists():
        return None
    dati = json.loads(termini_path.read_text(encoding="utf-8"))
    return {
        "vietate": [str(x) for x in dati.get("vietate", [])],
        "strade_omonime": [str(x) for x in dati.get("strade_omonime", [])],
        "servizi_omonimi": [str(x) for x in dati.get("servizi_omonimi", [])],
    }


def normalizza(testo: str) -> str:
    """Neutralizza le tecniche di evasione piu' comuni prima del match:
    entita' HTML (anche doppiamente codificate), forme Unicode equivalenti,
    spazi bianchi multipli o non separabili (es. &nbsp;)."""
    corrente = testo
    precedente = None
    for _ in range(3):
        if corrente == precedente:
            break
        precedente = corrente
        corrente = html.unescape(corrente)
    corrente = unicodedata.normalize("NFKC", corrente)
    corrente = re.sub(r"\s+", " ", corrente)
    return corrente


def check(path: Path, strade: bool = False, servizi: bool = False, termini_path=None) -> int:
    global _avvisato
    path = Path(path)
    if not path.exists():
        print("Errore: file non trovato: " + str(path) + ". Gate fallito (fail-closed).")
        return 1

    raw = path.read_bytes()
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        print(
            "Errore: " + str(path) + " non e' UTF-8 valido (" + str(exc) + "). "
            "Contenuto non decodificabile trattato come sospetto, gate fallito (fail-closed)."
        )
        return 1

    termini = carica_termini(termini_path)
    if termini is None:
        if not _avvisato:
            print("Avviso: nessun file di termini (" + TERMINI_PREDEFINITO.name + "): "
                  "il gate non controlla niente e passa.", file=sys.stderr)
            _avvisato = True
        print(f"OK: nessun termine da cercare in {path}")
        return 0

    if strade:
        for nome in termini["strade_omonime"]:
            txt = txt.replace('"' + nome + '"', '""')
            # Indirizzo con civico (servizi della citta' dei 15 minuti): "Via ... 118"
            txt = re.sub('"' + re.escape(nome) + r' \d+[A-Za-z]?"', '""', txt)
    if servizi:
        for nome in termini["servizi_omonimi"]:
            txt = txt.replace('"' + nome + '"', '""')
    txt = normalizza(txt)

    hits = []
    for pat in termini["vietate"]:
        for m in re.finditer(pat, txt, re.IGNORECASE):
            hits.append((pat, txt[max(0, m.start() - 30):m.start() + 30]))
    if hits:
        print(f"FOOTPRINT TROVATO in {path}:")
        for pat, ctx in hits[:50]:
            print(f"  [{pat}] ...{ctx}...")
        return 1
    print(f"OK: nessun footprint in {path}")
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    termini = None
    if "--termini" in argv:
        i = argv.index("--termini")
        if i + 1 >= len(argv):
            print("Uso: --termini <file>")
            sys.exit(2)
        termini = argv[i + 1]
        del argv[i:i + 2]
    args = [a for a in argv if a not in ("--strade", "--servizi")]
    if len(args) != 1:
        print("Uso: python3 check_zero_footprint.py [--strade] [--servizi] [--termini <file>] <path-al-file>")
        sys.exit(2)
    sys.exit(check(
        Path(args[0]),
        strade="--strade" in argv,
        servizi="--servizi" in argv,
        termini_path=termini,
    ))
