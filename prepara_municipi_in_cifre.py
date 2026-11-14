#!/usr/bin/env python3
"""
Due cifre per municipio nella scheda d'area: la spesa stanziata per abitante (PEG 2026) e i
progetti PNRR e Giubileo 2025 sul territorio del municipio. Scrive data/municipi-in-cifre.json,
che il build inlina nel bundle (la mappa non scarica niente da altri siti).

Le cifre si ricavano dagli snapshot del sito dei conti dei municipi (data/snapshot/ di quel
progetto), con le stesse regole delle sue pagine, cosi' la scheda e il sito dicono lo stesso:
  - spesa per abitante: spese.competenza_2026 di bilancio_peg_2026.json (PEG 2026-2028,
    Allegato A, DGC 110/2026) diviso popolazione di profilo_annuario.json (residenti al
    31/12/2025, Annuario statistico 2025, Tab. 1.2); posizione fra i 15, 1 = valore piu' alto;
  - progetti: schede di progetti.json con programma "PNRR" o "Giubileo 2025", collocate in un
    solo municipio e con contato_nel_totale; l'importo e' la somma di importo_programma_euro
    (fondi del programma assegnati, non pagamenti). Un importo mancante non vale 0: la scheda
    conta nel numero dei progetti, non nella somma, e si conta a parte (progetti_senza_importo).

Uso:
    python3 prepara_municipi_in_cifre.py <cartella data/snapshot del sito dei conti>
    (o con la variabile d'ambiente MAPPA_CONTI_SNAPSHOT)
"""

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUT = SCRIPT_DIR / "data" / "municipi-in-cifre.json"
ROMANI = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV"]
PROGRAMMI = (("PNRR", "pnrr"), ("Giubileo 2025", "giubileo_2025"))


def data_it(iso):
    a, m, g = iso.split("-")
    return g + "/" + m + "/" + a


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cartella = argv[0] if argv else os.environ.get("MAPPA_CONTI_SNAPSHOT")
    if not cartella:
        raise SystemExit("Uso: python3 prepara_municipi_in_cifre.py <cartella data/snapshot>")
    cartella = Path(cartella)
    leggi = lambda nome: json.loads((cartella / nome).read_text(encoding="utf-8"))
    peg, annuario, progetti = leggi("bilancio_peg_2026.json"), leggi("profilo_annuario.json"), leggi("progetti.json")

    spesa = {}
    for n in range(1, 16):
        stanziato = peg["municipi"][str(n)]["spese"]["competenza_2026"]
        residenti = annuario["municipi"][str(n)]["popolazione"]
        spesa[n] = (stanziato, residenti, stanziato / residenti)
    ordine = sorted(spesa, key=lambda n: -spesa[n][2])
    posizione = {n: i + 1 for i, n in enumerate(ordine)}

    municipi = {}
    for n in range(1, 16):
        stanziato, residenti, per_ab = spesa[n]
        riga = {
            "romano": ROMANI[n],
            "residenti": residenti,
            "stanziamenti_spesa_2026_euro": round(stanziato, 2),
            "spesa_per_abitante_euro": round(per_ab, 2),
            "spesa_per_abitante_posizione": posizione[n],
            "progetti": 0,
            "progetti_senza_importo": 0,
            "progetti_importo_euro": 0.0,
            "per_programma": {},
        }
        for programma, chiave in PROGRAMMI:
            schede = [r for r in progetti["municipi"][str(n)]["progetti"]
                      if r.get("programma") == programma and r.get("contato_nel_totale")]
            importi = [r["importo_programma_euro"] for r in schede if isinstance(r.get("importo_programma_euro"), (int, float))]
            parte = {"progetti": len(schede), "progetti_senza_importo": len(schede) - len(importi),
                     "importo_euro": round(sum(importi), 2)}
            riga["per_programma"][chiave] = parte
            riga["progetti"] += parte["progetti"]
            riga["progetti_senza_importo"] += parte["progetti_senza_importo"]
            riga["progetti_importo_euro"] = round(riga["progetti_importo_euro"] + parte["importo_euro"], 2)
        municipi[str(n)] = riga

    letto_peg, letto_progetti = peg["verificato"], progetti["verificato"]
    out = {
        "titolo": "Il municipio in cifre: spesa stanziata per abitante e progetti PNRR e Giubileo 2025",
        "nota": "Cifre del municipio, non dell'area: la scheda d'area mostra quelle del municipio in cui l'area si trova. "
                "Ricavate con prepara_municipi_in_cifre.py dagli snapshot del sito dei conti dei municipi. "
                "fonte_breve e' la forma corta della fonte, per la riga in fondo alla scheda.",
        "indicatori": {
            "spesa_per_abitante": {
                "etichetta": "Spesa del municipio per abitante",
                "misura": "Stanziamenti di spesa (competenza 2026) che il PEG 2026-2028 assegna alle strutture del municipio, "
                          "divisi per i residenti al 31/12/2025. Posizione fra i 15 municipi: 1 = valore più alto.",
                "non_misura": "Non sono pagamenti né impegni. Non comprende la spesa dei dipartimenti centrali, "
                              "della Polizia Locale e delle società partecipate sul territorio del municipio.",
                "fonte": "Roma Capitale, PEG 2026-2028, DGC 110/2026; residenti: Roma Capitale, Annuario statistico 2025, Tab. 1.2",
                "fonte_breve": "PEG 2026-2028",
                "periodo": "competenza 2026; residenti al 31/12/2025",
                "data_lettura": letto_peg,
                "licenza": peg["fonte"].get("licenza", ""),
            },
            "progetti_pnrr_giubileo": {
                "etichetta": "Progetti PNRR e Giubileo 2025 sul territorio del municipio",
                "misura": "Schede PNRR e Giubileo 2025 collocate in un solo municipio (contato_nel_totale); importo = somma "
                          "dei fondi del programma assegnati (importo_programma_euro). Le schede senza importo contano "
                          "nel numero ma non nella somma.",
                "non_misura": "Non sono pagamenti. Restano fuori i progetti su più municipi, intermunicipali o senza "
                              "municipio indicato. I progetti sono per lo più gestiti dai dipartimenti di Roma Capitale, "
                              "non dal municipio.",
                "fonte": "Roma Capitale, pagine progetti, elenco letto il " + data_it(letto_progetti),
                "fonte_breve": "pagine progetti",
                "periodo": "elenco pubblicato al " + data_it(letto_progetti),
                "data_lettura": letto_progetti,
                "licenza": progetti["fonte"].get("licenza", ""),
            },
        },
        "municipi": municipi,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for n in range(1, 16):
        r = municipi[str(n)]
        print("Municipio %-4s %7.2f euro per abitante (%2d su 15), %3d progetti (%d senza importo), %.1f mln euro"
              % (r["romano"], r["spesa_per_abitante_euro"], r["spesa_per_abitante_posizione"], r["progetti"],
                 r["progetti_senza_importo"], r["progetti_importo_euro"] / 1e6))
    print("Scritto " + str(OUT) + ".")


if __name__ == "__main__":
    main()
