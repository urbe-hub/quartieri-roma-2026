#!/usr/bin/env python3
"""
Icone dei servizi "da app" (stile app): una tessera
quadrata con gli angoli tondi, col colore del gruppo, e dentro l'illustrazione di
partenza (senza tessera) senza il disco bianco, centrata sul suo ingombro reale.

L'ingombro (getBBox) lo misura un Chromium headless: le illustrazioni non sono
centrate nel loro 64x64 (il parco sporge a sinistra, i tetti in alto), e centrarle a
occhio e' quello che non andava nella prima prova. Le SVG prodotte sono statiche e
versionate: questo script si rilancia solo se cambia un'illustrazione o un colore.

Le illustrazioni di partenza sono SVG 64x64 con disco bianco, uno per servizio (stessi nomi
dei file di icone/). Si leggono da una cartella data come argomento o con la variabile
d'ambiente MAPPA_ILLUSTRAZIONI; senza nessuna delle due, da icone/sorgenti/ se esiste.
Le tessere si scrivono in icone/, sopra quelle presenti.

Uso: python3 icone/prepara_icone_app.py [<cartella illustrazioni>]
     (serve playwright; CHROMIUM=<eseguibile> se la versione attesa non e' in cache)
"""

import glob
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

QUI = Path(__file__).resolve().parent
SORGENTE_PREDEFINITA = QUI / "sorgenti"


def cartella_sorgente():
    if len(sys.argv) > 2:
        raise SystemExit("Uso: python3 icone/prepara_icone_app.py [<cartella illustrazioni>]")
    scelta = sys.argv[1] if len(sys.argv) == 2 else os.environ.get("MAPPA_ILLUSTRAZIONI")
    cartella = Path(scelta).expanduser().resolve() if scelta else SORGENTE_PREDEFINITA
    if not cartella.is_dir() or not list(cartella.glob("*.svg")):
        raise SystemExit("Errore: nessuna illustrazione in " + str(cartella)
                         + ". Passa la cartella come argomento o con MAPPA_ILLUSTRAZIONI.")
    return cartella

# Gruppo del pannello Servizi -> gradiente della tessera (alto, basso)
GRADIENTI = {
    "scuole": ("#FFD36B", "#F2A93B"),
    "salute": ("#FF8A80", "#E0443E"),
    "verde": ("#8EDB8A", "#3E9F57"),
    "cultura": ("#B9A6FF", "#7058D6"),
    "quartiere": ("#FFB37A", "#E0752E"),
}
GRUPPO = {
    "nido": "scuole", "infanzia": "scuole", "primaria": "scuole", "media": "scuole", "superiore": "scuole",
    "casa-comunita": "salute", "pronto-soccorso": "salute", "ambulatorio": "salute",
    "farmacia": "salute", "consultorio": "salute",
    "parco": "verde", "sport": "verde",
    "museo": "cultura", "biblioteca": "cultura",
    "mercato": "quartiere", "centro-anziani": "quartiere",
}

LATO = 64
RAGGIO = 14.5          # angoli della tessera (circa il 22,6% del lato, come le app)
INGOMBRO_MAX = 48      # lato massimo dell'illustrazione dentro la tessera
INGOMBRO_AREA = 38     # lato del quadrato di area pari: disegni larghi e alti pesano uguale
CENTRO = (32, 32.5)    # mezza unita' piu' in basso: l'occhio vede piu' pesante la base


def illustrazione(svg):
    """Il disegno senza disco, bordo del disco, ombra a terra e filtro dell'ombra."""
    corpo = re.sub(r"^.*?<svg[^>]*>", "", svg, flags=re.S).rsplit("</svg>", 1)[0]
    corpo = re.sub(r"<title[^>]*>.*?</title>", "", corpo, flags=re.S)
    corpo = re.sub(r"<defs>.*?</defs>", "", corpo, flags=re.S)
    for _ in range(2):
        corpo = re.sub(r'<circle cx="32" cy="32" r="29"[^>]*/>', "", corpo, count=1)
    corpo = re.sub(r'<ellipse cx="32" cy="48\.5"[^>]*/>', "", corpo, count=1)
    return "\n".join("  " + r.strip() for r in corpo.strip().splitlines() if r.strip())


def chromium():
    if os.environ.get("CHROMIUM"):
        return os.environ["CHROMIUM"]
    trovati = sorted(glob.glob(os.path.expanduser(
        "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac-arm64/chrome-headless-shell")))
    return trovati[-1] if trovati else None


def main():
    sorgenti = sorted(cartella_sorgente().glob("*.svg"))
    disegni = {}
    for f in sorgenti:
        testo = f.read_text(encoding="utf-8")
        titolo = re.search(r"<title[^>]*>(.*?)</title>", testo, flags=re.S).group(1).strip()
        disegni[f.stem] = (titolo, illustrazione(testo))

    with sync_playwright() as p:
        exe = chromium()
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        pagina = browser.new_page()
        html = "".join('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
                       '<g id="g-' + nome + '">' + corpo + "</g></svg>" for nome, (_, corpo) in disegni.items())
        pagina.set_content("<!doctype html><body>" + html + "</body>")
        ingombri = pagina.evaluate("""nomi => Object.fromEntries(nomi.map(n => {
            const b = document.getElementById('g-' + n).getBBox();
            return [n, [b.x, b.y, b.width, b.height]];
        }))""", list(disegni))
        browser.close()

    for nome, (titolo, corpo) in disegni.items():
        if nome not in GRUPPO:
            raise SystemExit("Errore: " + nome + ".svg senza gruppo in GRUPPO.")
        x, y, w, h = ingombri[nome]
        # mezzo tratto in piu' per lato: getBBox misura la geometria, non lo stroke
        x, y, w, h = x - 0.75, y - 0.75, w + 1.5, h + 1.5
        s = min(INGOMBRO_MAX / max(w, h), INGOMBRO_AREA / (w * h) ** 0.5)
        tx, ty = CENTRO[0] - (x + w / 2) * s, CENTRO[1] - (y + h / 2) * s
        alto, basso = GRADIENTI[GRUPPO[nome]]
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-labelledby="{n}-t">\n'
            '  <title id="{n}-t">{titolo}</title>\n'
            '  <defs>\n'
            '    <linearGradient id="{n}-fondo" x1="0.3" y1="0" x2="0.7" y2="1">'
            '<stop offset="0" stop-color="{alto}"/><stop offset="1" stop-color="{basso}"/></linearGradient>\n'
            '    <linearGradient id="{n}-luce" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="#FFFFFF" stop-opacity="0.32"/>'
            '<stop offset="0.55" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient>\n'
            '  </defs>\n'
            '  <rect width="64" height="64" rx="{r}" fill="url(#{n}-fondo)"/>\n'
            '  <rect width="64" height="64" rx="{r}" fill="url(#{n}-luce)"/>\n'
            '  <rect x="0.5" y="0.5" width="63" height="63" rx="{r2}" fill="none" stroke="#3A2420" stroke-opacity="0.12"/>\n'
            '  <g transform="translate({tx} {ty}) scale({s})">\n{corpo}\n  </g>\n'
            '</svg>\n'
        ).format(n=nome, titolo=titolo, alto=alto, basso=basso, r=RAGGIO, r2=RAGGIO - 0.5,
                 tx=round(tx, 2), ty=round(ty, 2), s=round(s, 4), corpo=corpo)
        (QUI / (nome + ".svg")).write_text(svg, encoding="utf-8")
        print("{:16} ingombro {:5.1f}x{:4.1f} -> scala {:.3f}".format(nome, w, h, s))


if __name__ == "__main__":
    main()
