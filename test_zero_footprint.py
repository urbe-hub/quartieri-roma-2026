import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent
GATE = BASE / "check_zero_footprint.py"

# Termini finti: il gate e' neutro, i termini veri stanno in un file locale a parte.
TERMINI_FINTI = {
    "vietate": [r"alfa", r"\bbeta\b", r"\bgamma[_\s]\d+", r"delta\s+epsilon", r"\bzeta\w*"],
    "strade_omonime": ["Via Alfa Rossi", "Piazza Beta Verdi"],
    "servizi_omonimi": ["Parco Alfa Bianchi (zona beta)"],
}


@pytest.fixture
def termini(tmp_path):
    f = tmp_path / "termini.json"
    f.write_text(json.dumps(TERMINI_FINTI), encoding="utf-8")
    return f


def run_gate(path, termini, *flag):
    return subprocess.run([sys.executable, str(GATE), *flag, "--termini", str(termini), str(path)],
                          capture_output=True, text=True)


def scrivi(tmp_path, contenuto, nome="index.html"):
    f = tmp_path / nome
    f.write_text(contenuto, encoding="utf-8")
    return f


def test_gate_boccia_termine_vietato(tmp_path, termini):
    assert run_gate(scrivi(tmp_path, "<html>mappa di Alfa</html>"), termini).returncode == 1


def test_gate_passa_pulito(tmp_path, termini):
    assert run_gate(scrivi(tmp_path, "<html>Quartieri di Roma, fonte Geoportale</html>"), termini).returncode == 0


# Evasioni: entita' HTML, spaziatura, campi numerici.
@pytest.mark.parametrize("frammento", [
    "Alf&#97;",
    "Delta&nbsp;Epsilon",
    "Delta  Epsilon",
    "Alf&amp;#97;",
    "beta",
    "zeta",
    "zetapiu",
    '"gamma_41":1',
    "gamma 12",
])
def test_gate_intercetta_controesempi(tmp_path, termini, frammento):
    f = scrivi(tmp_path, "<html><body>" + frammento + "</body></html>")
    assert run_gate(f, termini).returncode == 1, "Non intercettato: " + repr(frammento)


def test_gate_file_assente(tmp_path, termini):
    assert run_gate(tmp_path / "non-esiste.html", termini).returncode != 0


def test_gate_file_non_utf8(tmp_path, termini):
    f = tmp_path / "binario.html"
    f.write_bytes(b"\xff\xfe\x00\x01 binario non decodificabile")
    assert run_gate(f, termini).returncode != 0


def test_gate_senza_file_termini_avvisa_e_passa(tmp_path):
    f = scrivi(tmp_path, "<html>alfa beta</html>")
    r = run_gate(f, tmp_path / "manca.json")
    assert r.returncode == 0
    assert "Avviso" in r.stderr


def test_gate_senza_file_termini_resta_fail_closed_sul_file(tmp_path):
    r = run_gate(tmp_path / "non-esiste.html", tmp_path / "manca.json")
    assert r.returncode != 0


def test_gate_legge_i_termini_dalla_variabile_d_ambiente(tmp_path, termini):
    f = scrivi(tmp_path, "<html>Alfa</html>")
    import os
    env = dict(os.environ, ZERO_FOOTPRINT_TERMINI=str(termini))
    r = subprocess.run([sys.executable, str(GATE), str(f)], env=env, capture_output=True, text=True)
    assert r.returncode == 1


def test_gate_strade_ammette_vie_omonime(tmp_path, termini):
    f = scrivi(tmp_path, '{"vie":[["Via Alfa Rossi",["QU.II.03"]],["Piazza Beta Verdi",["QU.X.01"]]]}', "indice.json")
    assert run_gate(f, termini, "--strade").returncode == 0


def test_gate_strade_boccia_il_resto(tmp_path, termini):
    f = scrivi(tmp_path, '{"vie":[["Via Alfa Neri",["QU.II.03"]]]}', "indice.json")
    assert run_gate(f, termini, "--strade").returncode == 1


def test_gate_strade_ammette_indirizzo_con_civico(tmp_path, termini):
    f = scrivi(tmp_path, '{"servizi":[{"n":"X","i":"Via Alfa Rossi 118"},{"i":"Piazza Beta Verdi 66B"}]}', "s.json")
    assert run_gate(f, termini, "--strade").returncode == 0


def test_gate_strade_civico_non_apre_altro(tmp_path, termini):
    # Il civico vale solo attaccato a una via omonima esatta: il resto della stringa resta controllato.
    f = scrivi(tmp_path, '{"servizi":[{"i":"Via Alfa Rossi 118 zeta"}]}', "s.json")
    assert run_gate(f, termini, "--strade").returncode == 1


def test_gate_bundle_non_ammette_vie_omonime(tmp_path, termini):
    f = scrivi(tmp_path, '<script>var v="Via Alfa Rossi";</script>')
    assert run_gate(f, termini).returncode == 1


def test_gate_servizi_ammette_nomi_omonimi(tmp_path, termini):
    f = scrivi(tmp_path, '{"c":["parchi"],"p":[[0,"Parco Alfa Bianchi (zona beta)","Q","I",41.9,12.5]]}', "servizi.json")
    assert run_gate(f, termini, "--servizi").returncode == 0


def test_gate_servizi_boccia_il_resto(tmp_path, termini):
    f = scrivi(tmp_path, '{"c":["farmacie"],"p":[[0,"Farmacia Alfa","Q","I",41.9,12.5]]}', "servizi.json")
    assert run_gate(f, termini, "--servizi").returncode == 1


def test_gate_bundle_non_ammette_nomi_servizi_omonimi(tmp_path, termini):
    """L'eccezione vale solo sui file dei servizi (--servizi), mai sul bundle normale."""
    f = scrivi(tmp_path, '<script>var n="Parco Alfa Bianchi (zona beta)";</script>')
    assert run_gate(f, termini).returncode == 1


def test_gate_passa_bundle_reale():
    """Il bundle costruito (dist/index.html) deve restare pulito coi termini locali, se ci sono."""
    bundle = Path(os.environ.get("MAPPA_DIST", BASE / "dist")) / "index.html"
    termini = BASE / "zero_footprint_termini.json"
    if not bundle.exists() or not termini.exists():
        pytest.skip("bundle o file dei termini assente")
    assert run_gate(bundle, termini).returncode == 0
