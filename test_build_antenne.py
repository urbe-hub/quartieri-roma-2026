"""Test della pagina Antenne (beta): build, interruttore, dati mancanti, header, ingresso nella mappa dei quartieri."""

import copy
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import build  # noqa: E402


@pytest.fixture
def uscita(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "ANTENNE_OUT", tmp_path / "dist" / "antenne")
    return tmp_path / "dist" / "antenne"


def costruisci(produzione=False):
    municipi = build.whitelist_feature_collection(
        json.loads(build.MUNICIPI_PATH.read_text(encoding="utf-8")), build.MUNICIPI_PROPERTIES_WHITELIST)
    return build.copia_antenne(produzione, municipi, build.costruisci_icone_servizi(), "data:image/png;base64,AAAA", "abc1234567")


def test_template_antenne_ha_i_marker_una_volta():
    t = (BASE / "antenne.template.html").read_text(encoding="utf-8")
    for m in (build.MARKER_FONTS_CSS, build.MARKER_LEAFLET_CSS, build.MARKER_LEAFLET_JS, build.MARKER_MUNICIPI_ANTENNE,
              build.MARKER_URBE_LOGO, build.MARKER_ICONE_SERVIZI, build.MARKER_VERSIONI, build.MARKER_ICONA, build.META_NOINDEX):
        assert t.count(m) == 1, m


def test_template_principale_non_collega_le_antenne():
    # la mappa dei quartieri resta quella di upstream: nessun segnaposto, nessun collegamento alle antenne
    t = (BASE / "mappa-quartieri.template.html").read_text(encoding="utf-8")
    assert "ANTENNE" not in t and "antenne/" not in t and "antenne-link" not in t
    assert not hasattr(build, "ANTENNE_LINK_HTML") and not hasattr(build, "MARKER_ANTENNE_LINK")


def test_dist_principale_senza_collegamenti_alle_antenne():
    index = BASE / "dist" / "index.html"
    if not index.exists():
        pytest.skip("dist/ non costruito")
    html = index.read_text(encoding="utf-8")
    assert 'href="antenne' not in html and "antenne-link" not in html


def test_pagina_scritta_con_dati_e_gate(uscita):
    versioni = costruisci()
    assert set(versioni) == {"antenne", "civici", "servizi"} and versioni["servizi"] == "abc1234567"
    assert sorted(p.name for p in uscita.iterdir()) == ["antenne.json", "civici.json", "index.html"]
    html = (uscita / "index.html").read_text(encoding="utf-8")
    for m in ("/*<<", "<<URBE_LOGO>>"):
        assert m not in html
    assert build.META_NOINDEX in html
    assert versioni["antenne"] in html and "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in html
    dati = json.loads((uscita / "antenne.json").read_text(encoding="utf-8"))
    assert len(dati["siti"]) == 123 and dati["raggio_m"] == 300
    # il file dei luoghi sensibili non e' inlinato nella pagina (si carica da ../servizi/)
    assert "../servizi/servizi.json" in html


def test_produzione_toglie_il_noindex_dalla_pagina(uscita):
    costruisci(produzione=True)
    assert build.META_NOINDEX not in (uscita / "index.html").read_text(encoding="utf-8")


def test_interruttore_spento_non_scrive_e_toglie_la_cartella(uscita, monkeypatch):
    uscita.mkdir(parents=True)
    (uscita / "vecchio.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(build, "ANTENNE_NEL_RILASCIO", False)
    assert costruisci() is None
    assert not uscita.exists()


def test_senza_dati_la_build_non_si_ferma(uscita, monkeypatch, tmp_path):
    monkeypatch.setattr(build, "ANTENNE_SRC", tmp_path / "manca")
    assert costruisci() is None
    assert not uscita.exists()


def test_dati_incoerenti_fanno_fallire(uscita, monkeypatch, tmp_path):
    src = tmp_path / "src"
    shutil.copytree(BASE / "data" / "antenne", src)
    d = json.loads((src / "antenne.json").read_text(encoding="utf-8"))
    d["siti"][0]["pratiche"] = ["pratica-che-non-esiste"]
    (src / "antenne.json").write_text(json.dumps(d), encoding="utf-8")
    monkeypatch.setattr(build, "ANTENNE_SRC", src)
    with pytest.raises(SystemExit):
        costruisci()


def test_validazione_di_stato_e_coordinate():
    d = json.loads((BASE / "data" / "antenne" / "antenne.json").read_text(encoding="utf-8"))
    assert build.valida_antenne(copy.deepcopy(d))
    for modifica in (lambda x: x["siti"][0].update(stato="boh"), lambda x: x["siti"][0].update(lat=10.0),
                     lambda x: x.update(raggio_m=5000), lambda x: x.pop("fonti")):
        x = copy.deepcopy(d)
        modifica(x)
        with pytest.raises(SystemExit):
            build.valida_antenne(x)
    with pytest.raises(SystemExit):
        build.valida_civici({"vie": [["Via X", "II", [["1", "non-numero", 12.5]]]]})


def test_anelli_dei_municipi_ii_e_v():
    m = json.loads(build.MUNICIPI_PATH.read_text(encoding="utf-8"))
    an = build.anelli_municipi(m)
    assert set(an) == {"II", "V"}
    for k in an:
        assert len(an[k]["anello"]) > 10 and all(41.7 < la < 42.1 and 12.3 < lo < 12.8 for la, lo in an[k]["anello"])
    with pytest.raises(SystemExit):
        build.anelli_municipi({"features": []})


def test_icone_solo_delle_categorie_sensibili(uscita):
    costruisci()
    html = (uscita / "index.html").read_text(encoding="utf-8")
    dati = json.loads((uscita / "antenne.json").read_text(encoding="utf-8"))
    cat = {c for cs in dati["gruppi_sensibili"].values() for c in cs}
    m = re.search(r"var ICONE = (\{.*?\});\n", html, re.S)
    icone = json.loads(m.group(1).replace("<\\/", "</"))
    assert set(icone) == cat


def test_header_per_antenne():
    cfg = build.config_vercel(False)
    per_fonte = {h["source"]: h["headers"] for h in cfg["headers"]}
    assert "max-age=31536000" in per_fonte["/antenne/antenne.json"][0]["value"]
    assert "max-age=31536000" in per_fonte["/antenne/civici.json"][0]["value"]
    for pagina in ("/antenne", "/antenne/", "/antenne/index.html"):
        assert "must-revalidate" in per_fonte[pagina][0]["value"]
    # la CSP generale gia' copre la pagina: stessa origine per i dati, tile OSM per la mappa
    csp = {h["key"]: h["value"] for h in cfg["headers"][0]["headers"]}["Content-Security-Policy-Report-Only"]
    assert "connect-src 'self'" in csp and "tile.openstreetmap.org" in csp


def test_javascript_della_pagina_e_sintatticamente_valido(uscita, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node non disponibile")
    costruisci()
    html = (uscita / "index.html").read_text(encoding="utf-8")
    script = re.findall(r"<script>\n(.*?)</script>", html, re.S)[-1]
    f = tmp_path / "pagina.js"
    f.write_text(script, encoding="utf-8")
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_testi_dinamici_passano_da_esc():
    # Tutte le stringhe dei dati vengono da pagine esterne: ogni assegnazione a innerHTML nel template
    # costruisce il markup solo da funzioni del template o da esc().
    t = (BASE / "antenne.template.html").read_text(encoding="utf-8")
    assert "function esc(" in t
    for crudo in (r"\.n\s*\+", r"\.indirizzo\s*\+", r"\.titolo\s*\+", r"\.note\s*\+"):
        assert not re.search(r'"\s*\+\s*[A-Za-z_.\[\]]*' + crudo, t), crudo


def test_nessun_testo_300_m_fisso_nel_pannello():
    # il raggio e' scelto dall'utente: "300 m" resta solo nelle fasce fisse del colore (50-150, 150-300, oltre 300)
    t = (BASE / "antenne.template.html").read_text(encoding="utf-8")
    js = t.split("var VERSIONI")[1]
    assert not re.search(r"entro 300 m|raggio di 300|300 m\b(?!.*fasce)", js.replace("oltre 300 m", "").replace("150\\u2013300", "")
                         .replace("nessun luogo sensibile entro 300 m", "").replace("150&ndash;300 m", ""))


def test_uscite_dal_punto_e_luoghi_leggibili():
    t = (BASE / "antenne.template.html").read_text(encoding="utf-8")
    for pezzo in ("function rimuoviPunto(", 'data-az="rimuovi"', 'id="guida-annulla"', "Rimuovi il punto", "function tipLuogo(", "tt-luogo"):
        assert pezzo in t, pezzo


def test_icona_e_colore_uguali_alla_mappa_dei_quartieri(uscita):
    costruisci()
    principale = (BASE / "mappa-quartieri.template.html").read_text(encoding="utf-8")
    antenne = (uscita / "index.html").read_text(encoding="utf-8")
    link = re.search(r'<link rel="icon"[^>]*>', principale).group(0)
    colore = re.search(r'<meta name="theme-color"[^>]*>', principale).group(0)
    assert antenne.count(link) == 1 and antenne.count(colore) == 1     # stessa identica icona, presa dal template principale
    assert 'rel="icon"' in antenne and antenne.count('rel="icon"') == 1
    assert "<<ICONA>>" not in antenne


def test_viewport_e_aree_sicure():
    t = (BASE / "antenne.template.html").read_text(encoding="utf-8")
    assert "width=device-width, initial-scale=1, viewport-fit=cover" in t
    assert "env(safe-area-inset-bottom" in t and "100dvh" in t
    assert "#q { font-size: 16px" in t   # niente zoom al focus sui campi


def test_scheda_a_due_forme_su_telefono():
    t = (BASE / "antenne.template.html").read_text(encoding="utf-8")
    for pezzo in ('creaFoglio("scheda", [function', "0.3 * innerHeight", ", 0.78]", 'data-tabsel', "sc-sintesi", "function tabsHtml(", 'creaFoglio("elenco", [76,'):
        assert pezzo in t, pezzo
    assert "creaFoglio(\"scheda\", [0.3, 0.54" not in t     # niente livello intermedio a meta' schermo
