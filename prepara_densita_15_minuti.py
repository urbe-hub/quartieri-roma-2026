#!/usr/bin/env python3
"""
Densita' dei servizi a 15 minuti: per ogni esagono abitato di data/copertura/copertura.json
quanti servizi attivi si raggiungono a piedi in 15 minuti. E' il dato della mappa di calore
della 2D, dal rosso (pochi servizi) al verde (molti).

Stesso calcolo di prepara_copertura_15_minuti.py (rete, 4,8 km/h, aggancio alla strada piu'
vicina entro 300 m), ma si contano tutti i servizi invece di cercare il piu' vicino per
categoria. Si misura da sette punti dell'esagono (il centro e sei attorno) e si tiene la
mediana: copertura.json non conserva il baricentro degli abitanti, e il centro da solo puo'
cadere su una strada isolata. Per questo calcolo non serve la griglia di popolazione.

Serve numpy, scipy e tifffile (importati da prepara_copertura_15_minuti.py); non sono
dipendenze del build: il dato si rifa' solo quando cambiano rete o servizi.

Uso:
    python3 prepara_densita_15_minuti.py

Scrive data/copertura/densita.json:
  {"esagono": {...}, "soglia": minuti, "classi": [limite inferiore di ogni classe],
   "celle": [q, r, abitanti, servizi, q, r, ...]}
"""

import json
import math

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from prepara_copertura_15_minuti import (
    KX, KY, LATO, RETE_DIR, SCRIPT_DIR, SERVIZI, SOGLIA, VEL,
    Aggancio, centro_esagono, grafo, leggi_rete,
)

COPERTURA = SCRIPT_DIR / "data" / "copertura" / "copertura.json"
OUT = SCRIPT_DIR / "data" / "copertura" / "densita.json"
N_CLASSI = 7
# Il centro e sei punti attorno, in metri: il centro da solo puo' cadere su una strada
# isolata (una rampa, un tratto recintato), da cui si raggiunge pochissima rete.
RAGGIO_CAMPIONI = 0.6 * LATO
CAMPIONI = [(0.0, 0.0)] + [(RAGGIO_CAMPIONI * math.cos(math.radians(60 * k)),
                            RAGGIO_CAMPIONI * math.sin(math.radians(60 * k))) for k in range(6)]


def matrice(archi, ids):
    """Grafo non orientato sugli incroci; degli archi doppi si tiene il piu' corto."""
    n = len(ids)
    da, a_, w = [], [], []
    for a, b, lun, _ in archi:
        ia, ib = ids[a], ids[b]
        da += [ia, ib]
        a_ += [ib, ia]
        w += [lun, lun]
    da, a_, w = np.asarray(da), np.asarray(a_), np.maximum(np.asarray(w, dtype=np.float64), 1e-3)
    ordine = np.lexsort((w, a_, da))
    da, a_, w = da[ordine], a_[ordine], w[ordine]
    primo = np.ones(len(da), dtype=bool)
    primo[1:] = (da[1:] != da[:-1]) | (a_[1:] != a_[:-1])
    return csr_matrix((w[primo], (da[primo], a_[primo])), shape=(n, n))


def classi_da_quantili(conteggi, abitanti, n_classi):
    """Limiti inferiori di classi con circa gli stessi abitanti, senza limiti ripetuti.
    La prima classe parte sempre da 0."""
    ordine = np.argsort(conteggi)
    cum = np.cumsum(abitanti[ordine]) / abitanti.sum()
    limiti = [0]
    for k in range(1, n_classi):
        v = int(conteggi[ordine][np.searchsorted(cum, k / n_classi)])
        if v > limiti[-1]:
            limiti.append(v)
    return limiti


def main():
    if not (RETE_DIR / "indice.json").exists():
        raise SystemExit("Manca la rete pedonale in " + str(RETE_DIR) + " (prepara_rete_pedonale.py).")
    cop = json.loads(COPERTURA.read_text())
    passo = 3 + len(cop["categorie"])
    celle = np.asarray(cop["celle"]).reshape(-1, passo)[:, :3]

    archi = leggi_rete()
    ids = grafo(archi)
    m = matrice(archi, ids)
    aggancia = Aggancio(archi)
    print("Rete: %d archi, %d incroci" % (len(archi), len(ids)))

    # Sette punti per esagono, agganciati alla rete: il centro e sei attorno.
    n_es = len(celle)
    n_pt = n_es * len(CAMPIONI)
    pa, pb, ps, pr, pd, parco = [np.zeros(n_pt) for _ in range(6)]
    agganciato = np.zeros(n_pt, dtype=bool)
    for i, (q, r, _) in enumerate(celle):
        la, lo = centro_esagono(int(q), int(r))
        for j, (dx, dy) in enumerate(CAMPIONI):
            ag = aggancia(la + dy / KY, lo + dx / KX)
            if ag is None:
                continue
            e, s, d = ag
            a, b, lun, _ = archi[e]
            k = i * len(CAMPIONI) + j
            pa[k], pb[k], ps[k], pr[k], pd[k], parco[k] = ids[a], ids[b], s, lun - s, d, e
            agganciato[k] = True
    pa, pb, parco = pa.astype(np.int64), pb.astype(np.int64), parco.astype(np.int64)
    print("Punti senza strada entro 300 m: %d su %d" % (n_pt - agganciato.sum(), n_pt))

    # Ogni servizio attivo: Dijkstra limitato ai 15 minuti, e +1 ai punti raggiunti.
    sv = json.loads(SERVIZI.read_text())
    # Come il pannello dei 15 minuti, che arrotonda al minuto: 15,49 minuti valgono 15.
    limite = (SOGLIA + 0.5) * VEL
    per_punto = np.zeros(n_pt, dtype=np.int64)
    usati, fuori = 0, 0
    for p in sv["p"]:
        if len(p) > 8 and p[8] == "prevista":
            continue
        ag = aggancia(p[4], p[5])
        if ag is None:
            fuori += 1
            continue
        e, s, d = ag
        a, b, lun, _ = archi[e]
        dist = dijkstra(m, directed=True, indices=[ids[a], ids[b]], limit=limite)
        nodo = np.minimum(dist[0] + s, dist[1] + lun - s) + d
        t = np.minimum(nodo[pa] + ps, nodo[pb] + pr) + pd
        stesso = parco == e
        if stesso.any():      # sullo stesso arco si cammina lungo l'arco, senza passare dagli incroci
            t[stesso] = np.minimum(t[stesso], np.abs(ps[stesso] - s) + pd[stesso] + d)
        per_punto += (t < limite) & agganciato
        usati += 1
    print("Servizi attivi contati: %d (%d senza strada)" % (usati, fuori))

    # La mediana dei punti agganciati: un punto su una strada isolata non conta per tutti.
    valori = np.where(agganciato, per_punto, np.nan).reshape(n_es, len(CAMPIONI)).astype(np.float64)
    senza = np.isnan(valori).all(axis=1)
    valori[senza, 0] = 0
    conta = np.rint(np.nanmedian(valori, axis=1)).astype(np.int64)
    print("Esagoni senza nessuna strada: %d · esagoni a zero: %d" % (senza.sum(), (conta == 0).sum()))

    abitanti = celle[:, 2].astype(np.float64)
    classi = classi_da_quantili(conta, abitanti, N_CLASSI)
    q = np.percentile(conta, [0, 10, 25, 50, 75, 90, 100]).astype(int).tolist()
    print("Servizi per esagono, percentili 0/10/25/50/75/90/100: %s" % q)
    print("Classi (limite inferiore):", classi)
    sup = classi[1:] + [int(conta.max()) + 1]
    for lo_, hi in zip(classi, sup):
        dentro = (conta >= lo_) & (conta < hi)
        print("  %4d-%-4d %5d esagoni  %5.1f%% residenti" % (lo_, hi - 1, dentro.sum(), 100 * abitanti[dentro].sum() / abitanti.sum()))

    flat = []
    for i in range(n_es):
        flat += [int(celle[i, 0]), int(celle[i, 1]), int(celle[i, 2]), int(conta[i])]
    OUT.write_text(json.dumps({
        "esagono": cop["esagono"], "soglia": SOGLIA, "classi": classi, "celle": flat,
    }, separators=(",", ":")))
    print("Scritto %s: %.0f KB" % (OUT.relative_to(SCRIPT_DIR), OUT.stat().st_size / 1024))


if __name__ == "__main__":
    main()
