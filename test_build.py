import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import build  # noqa: E402


def intestazioni_generali(config):
    return {h["key"]: h["value"] for h in config["headers"][0]["headers"]}


def test_anteprima_ha_x_robots_tag():
    gen = intestazioni_generali(build.config_vercel(produzione=False))
    assert gen["X-Robots-Tag"] == "noindex, nofollow"


def test_produzione_toglie_x_robots_tag():
    gen = intestazioni_generali(build.config_vercel(produzione=True))
    assert "X-Robots-Tag" not in gen


@pytest.mark.parametrize("produzione", [False, True])
def test_header_di_sicurezza(produzione):
    cfg = build.config_vercel(produzione)
    gen = intestazioni_generali(cfg)
    assert gen["X-Content-Type-Options"] == "nosniff"
    assert gen["Referrer-Policy"] == "strict-origin-when-cross-origin"
    csp = gen["Content-Security-Policy-Report-Only"]
    assert "font-src 'self' data:" in csp and "tile.openstreetmap.org" in csp
    assert "frame-ancestors" not in csp
    assert "X-Frame-Options" not in json.dumps(cfg)


def test_produzione_toglie_il_meta_noindex():
    html = "<head>\n" + build.META_NOINDEX + "\n<title>x</title></head>"
    out = build.senza_noindex(html)
    assert "noindex" not in out and "<title>x</title>" in out


def test_senza_noindex_fallisce_se_il_meta_manca():
    with pytest.raises(SystemExit):
        build.senza_noindex("<head></head>")


def test_template_ha_il_meta_noindex():
    assert build.META_NOINDEX in (BASE / "mappa-quartieri.template.html").read_text(encoding="utf-8")


def test_produzione_fallisce_senza_rete(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "RETE_SRC", tmp_path / "manca")
    monkeypatch.setattr(build, "RETE_OUT", tmp_path / "out" / "rete")
    monkeypatch.setattr(build, "QUINDICI_VECCHIO_OUT", tmp_path / "out" / "v.json")
    with pytest.raises(SystemExit):
        build.copia_rete(produzione=True)
    assert build.copia_rete(produzione=False) is None


def test_licenze_presenti():
    assert "BSD 2-Clause" in (BASE / "vendor" / "leaflet" / "LICENSE").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE" in (BASE / "vendor" / "fonts" / "OFL.txt").read_text(encoding="utf-8")
