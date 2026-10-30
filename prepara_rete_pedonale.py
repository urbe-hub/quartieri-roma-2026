#!/usr/bin/env python3
"""
Rete pedonale di Roma per la "citta' dei 15 minuti": dall'estratto OpenStreetMap
(Geofabrik, centro Italia) al grafo delle strade percorribili a piedi, diviso in
riquadri che la mappa carica solo attorno al punto scelto.

Serve pyosmium (pip install osmium), che non e' una dipendenza del build: il grafo
si rifa' solo quando si vuole aggiornare la rete, come importa_dati.py.

Uso:
    python3 prepara_rete_pedonale.py <centro-latest.osm.pbf>

Scrive data/rete/r<riga>_<colonna>.json, uno per riquadro, piu' data/rete/indice.json.
Formato di un riquadro: {"e": [[a, b, metri, [lat0, lon0, dlat1, dlon1, ...]], ...]}
dove a e b sono gli id dei nodi d'incrocio (comuni a tutti i riquadri) e il
tracciato e' in interi da 1e-5 gradi, coordinate delta dopo la prima coppia.
Nessun nome di strada: solo geometria.
"""

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import osmium

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DIR = SCRIPT_DIR / "data" / "rete"

# Comune di Roma con un margine di ~1 km: chi abita sul confine cammina anche fuori.
BBOX = (41.64, 12.22, 42.17, 12.87)   # sud, ovest, nord, est
# Riquadri: 0,015 gradi di latitudine x 0,02 di longitudine, circa 1,7 x 1,7 km.
PASSO_LAT, PASSO_LON = 0.015, 0.02

PEDONALI = {
    "footway", "path", "pedestrian", "living_street", "residential", "service",
    "unclassified", "tertiary", "tertiary_link", "secondary", "secondary_link",
    "primary", "primary_link", "steps", "track", "cycleway", "corridor", "road",
}
NO_ACCESSO = {"no", "private"}


def percorribile(tags):
    hw = tags.get("highway")
    foot = tags.get("foot")
    if foot in NO_ACCESSO:
        return False
    if hw in ("motorway", "motorway_link", "trunk", "trunk_link"):
        return foot in ("yes", "designated")
    if hw not in PEDONALI:
        return False
    if tags.get("access") in NO_ACCESSO and foot not in ("yes", "designated", "permissive"):
        return False
    if hw == "cycleway" and foot not in ("yes", "designated", "permissive"):
        # Le ciclabili sono spesso affiancate al marciapiede; senza foot esplicito
        # le teniamo comunque (in Italia il pedone non e' vietato per default).
        return True
    return True


def dentro(lat, lon):
    return BBOX[0] <= lat <= BBOX[2] and BBOX[1] <= lon <= BBOX[3]


def metri(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    p = math.pi / 180
    x = (lon2 - lon1) * p * math.cos((lat1 + lat2) / 2 * p)
    y = (lat2 - lat1) * p
    return 6371000 * math.hypot(x, y)


def semplifica(punti, tolleranza_m=2.5):
    # Douglas-Peucker in metri approssimati (bastano per tracciati di poche centinaia di metri).
    if len(punti) < 3:
        return punti
    kx = 111320 * math.cos(math.radians(punti[0][0]))
    ky = 110540
    xy = [(p[1] * kx, p[0] * ky) for p in punti]
    tenere = [False] * len(punti)
    tenere[0] = tenere[-1] = True
    pila = [(0, len(punti) - 1)]
    while pila:
        i, j = pila.pop()
        ax, ay = xy[i]
        bx, by = xy[j]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        dmax, kmax = -1, -1
        for k in range(i + 1, j):
            px, py = xy[k]
            if l2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / l2))
                d = math.hypot(px - ax - t * dx, py - ay - t * dy)
            if d > dmax:
                dmax, kmax = d, k
        if dmax > tolleranza_m:
            tenere[kmax] = True
            pila.append((i, kmax))
            pila.append((kmax, j))
    return [p for p, t in zip(punti, tenere) if t]


class Vie(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.vie = []          # liste di (id nodo, lat, lon)

    def way(self, w):
        if "highway" not in w.tags or not percorribile(w.tags):
            return
        nodi = []
        for n in w.nodes:
            if not n.location.valid():
                continue
            nodi.append((n.ref, n.location.lat, n.location.lon))
        if len(nodi) >= 2 and any(dentro(lat, lon) for _, lat, lon in nodi):
            self.vie.append(nodi)


def componente_maggiore(archi, n_nodi):
    padre = list(range(n_nodi))

    def trova(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for a, b, _, _ in archi:
        ra, rb = trova(a), trova(b)
        if ra != rb:
            padre[ra] = rb
    conta = defaultdict(int)
    for a, _, _, _ in archi:
        conta[trova(a)] += 1
    radice = max(conta, key=conta.get)
    return [e for e in archi if trova(e[0]) == radice]


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python3 prepara_rete_pedonale.py <file.osm.pbf>")
    h = Vie()
    h.apply_file(sys.argv[1], locations=True, idx="flex_mem")
    print("Vie percorribili a piedi nel riquadro di Roma:", len(h.vie))

    uso = defaultdict(int)
    for v in h.vie:
        for i, (nid, _, _) in enumerate(v):
            uso[nid] += 2 if i in (0, len(v) - 1) else 1
    incroci = {nid for nid, u in uso.items() if u >= 2}

    ids = {}

    def id_di(nid):
        if nid not in ids:
            ids[nid] = len(ids)
        return ids[nid]

    archi = []
    for v in h.vie:
        tratto = [v[0]]
        for nodo in v[1:]:
            tratto.append(nodo)
            if nodo[0] in incroci:
                punti = [(lat, lon) for _, lat, lon in tratto]
                lun = sum(metri(punti[i], punti[i + 1]) for i in range(len(punti) - 1))
                if tratto[0][0] != nodo[0] and lun > 0:
                    archi.append((id_di(tratto[0][0]), id_di(nodo[0]), lun, semplifica(punti)))
                tratto = [nodo]
    print("Archi fra incroci:", len(archi))
    archi = componente_maggiore(archi, len(ids))
    print("Archi nella rete connessa principale:", len(archi))

    riquadri = defaultdict(list)
    for a, b, lun, punti in archi:
        m = punti[len(punti) // 2]
        chiave = (int(math.floor(m[0] / PASSO_LAT)), int(math.floor(m[1] / PASSO_LON)))
        q = [(round(lat * 1e5), round(lon * 1e5)) for lat, lon in punti]
        flat = [q[0][0], q[0][1]]
        for i in range(1, len(q)):
            flat += [q[i][0] - q[i - 1][0], q[i][1] - q[i - 1][1]]
        riquadri[chiave].append([a, b, round(lun, 1), flat])

    if OUT_DIR.exists():
        for f in OUT_DIR.glob("*.json"):
            f.unlink()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    totale = 0
    for (r, c), e in riquadri.items():
        testo = json.dumps({"e": e}, separators=(",", ":"))
        (OUT_DIR / ("r%d_%d.json" % (r, c))).write_text(testo)
        totale += len(testo)
    (OUT_DIR / "indice.json").write_text(json.dumps({
        "passo_lat": PASSO_LAT, "passo_lon": PASSO_LON,
        "riquadri": sorted("%d_%d" % k for k in riquadri),
        "fonte": "OpenStreetMap (ODbL), estratto Geofabrik centro Italia",
    }, separators=(",", ":")))
    print("Riquadri:", len(riquadri), "· peso totale %.1f MB" % (totale / 1e6))


if __name__ == "__main__":
    main()
