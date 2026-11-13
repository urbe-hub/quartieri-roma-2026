"""Test di prepara_antenne.py: parser delle coordinate (coi casi veri delle fonti), normalizzazioni
e controlli sui file scritti (data/antenne/antenne.json e civici.json)."""

import json
import re

import pytest

import prepara_antenne as a

ANTENNE = a.OUT_ANTENNE
CIVICI = a.OUT_CIVICI


def lettura(lat, lon, formato):
    """La lettura della coppia nel formato dato, arrotondata a 6 decimali."""
    trovate = {f: (la, lo) for f, la, lo in a.candidati_coppia(lat, lon)}
    assert formato in trovate, "formato %s non fra le letture %s" % (formato, trovate)
    return trovate[formato]


# ---------------------------------------------------------------- parser delle coordinate

def test_decimale_scritto_coi_simboli_dms():
    # 41°91'29.62" = 41.912962 (non 41 gradi e 91 minuti)
    assert lettura('41°91\'29.62" N', '12°50\'46.14"', "decimale_scritto_dms") == (41.912962, 12.504614)
    # la latitudine non e' un DMS valido (91 minuti): la coppia non puo' essere letta come DMS
    assert "dms" not in {f for f, _, _ in a.candidati_coppia('41°91\'29.62" N', '12°50\'46.14"')}


def test_dms_vero():
    la, lo = lettura('41° 54\' 33.90" N', '12° 30\' 46.40" E', "dms")
    assert (round(la, 5), round(lo, 5)) == (41.90942, 12.51289)


def test_via_bosio_13_le_due_scritture_sono_lo_stesso_posto():
    vero = lettura('41° 54\' 59.55" N', '12° 30\' 50.52" E', "dms")
    mascherato = lettura('41° 91\' 65.1" N', '12° 51\' 41.5" E', "decimale_scritto_dms")
    assert mascherato == (41.91651, 12.51415)
    assert round(vero[0], 5) == 41.91654 and round(vero[1], 5) == 12.51403
    assert a.metri(vero, mascherato) < 20


def test_decimale_con_la_virgola():
    assert lettura("41,890993 N", "12,528144 E", "decimale") == (41.890993, 12.528144)


def test_decimale_col_punto_e_il_simbolo_di_grado():
    assert lettura("41.878049° N", "12.540119° E", "decimale") == (41.878049, 12.540119)


def test_apici_tipografici():
    la, lo = lettura("41°53’ 4.39”N", "12°32’ 6.98”E", "dms")
    assert (round(la, 5), round(lo, 5)) == (41.88455, 12.53527)


def test_refuso_nei_simboli():
    # "12°61?25.21”": il '?' al posto dell'apice; 41°88’25.21” e' il decimale scritto dms 41.882521
    assert lettura("41°88’25.21” N", "12°61?25.21” E", "decimale_scritto_dms") == (41.882521, 12.612521)


def test_il_formato_si_decide_sulla_coppia():
    # la longitudine da sola ha due letture valide (50' e 46" sono formalmente corretti)...
    assert set(a.interpretazioni_valore('12°50\'46.14"')) == {"dms", "decimale_scritto_dms"}
    # ...ma in coppia con una latitudine "mascherata" resta una sola lettura
    assert [f for f, _, _ in a.candidati_coppia('41°91\'29.62" N', '12°50\'46.14"')] == ["decimale_scritto_dms"]


@pytest.mark.parametrize("lat, lon, atteso", [
    ("", "", "assente"),
    ("41° 92' 89.77.71''N", "12° 46' 20.70''E", "illeggibile"),   # due punti decimali: non si indovina
    ("41,890993 N", "12,528144 E", "decimale"),
])
def test_formato_sintattico(lat, lon, atteso):
    assert a.formato_sintattico(lat, lon) == atteso


def test_latitudine_e_longitudine_uguali_non_tornano():
    # Via dei Platani 38 (V, aprile 2026): la longitudine ripete la latitudine
    for _, la, lo in a.candidati_coppia("41° 52' 51.68'' N.", "41° 52' 51.68'' N"):
        assert la == lo


def test_separa_lat_long():
    assert a.separa_lat_long("Lat. 41°54'31.3\" – Long. 12°36'18.6\"E") == ("41°54'31.3\" –", "12°36'18.6\"E")
    # etichetta incollata al numero
    assert a.separa_lat_long("Lat 41°90'95.66\"N Long12°51'28.84\"E")[1].startswith("12")
    assert a.separa_lat_long("") == (None, None)


# ---------------------------------------------------------------- normalizzazioni

@pytest.mark.parametrize("testo, atteso", [
    ("Fastweb + Vodafone", ["Fastweb", "Vodafone"]),
    ("Tim - Fastweb", ["TIM", "Fastweb"]),
    ("Tim/Vodafone", ["TIM", "Vodafone"]),
    ("Telecom S.p.A", ["TIM"]),
    ("Wind Tre S.p.a.", ["WindTre"]),
    ("Iliad Italia Spa", ["Iliad"]),
    ("Illiad Italia S.p.A.", ["Iliad"]),
    ("Fiber Cop/Tim", ["FiberCop", "TIM"]),
    ("Vofafone - Tim S.p.A.", ["Vodafone", "TIM"]),
    ("Cellnex Italia S.p.A + Vodafone Italia S.p.A. + Fastweb S.p.A.", ["Cellnex", "Vodafone", "Fastweb"]),
    ("", []),
])
def test_gestori(testo, atteso):
    assert a.gestori_da_testo(testo)[0] == atteso


def test_gestori_sconosciuti_restano_cosi_come_sono():
    assert a.gestori_da_testo("OPNET S.r.l.")[0] == ["OPNET"]
    assert a.gestori_da_testo("IASO Tower S.r.l. ILIAD Italia S.p.A.")[0] == ["Iliad", "IASO Tower"]


@pytest.mark.parametrize("testo, atteso", [
    ("INSTALLAZIONE S.R.B. ILIAD SU INFRASTRUTTURA ESISTENTE", "installazione_su_esistente"),
    ("Installazione di una nuova Stazione Radio Base Wind Tre S.p.A. su struttura esistente di Cellnex Italia S.p.A.",
     "installazione_su_esistente"),
    ("NUOVA INSTALLAZIONE", "installazione"),
    ("Installazione", "installazione"),
    ("MODIFICA IMPIANTO", "modifica"),
    ("Modifica/Adeguamento", "modifica"),
    ("Adeguaemnto", "adeguamento"),
    ("ADEGUAMENTO", "adeguamento"),
    ("DISMISSIONE IMPIANTO", "dismissione"),
    ("RICONFIGURAZIONE IMPIANTO ESISTENTE/ REALIZZAZIONE DI UNA NUOVA INFRASTRUTTURA", "modifica"),
    ("boh", "altro"),
])
def test_tipologia(testo, atteso):
    assert a.tipologia_da_testo(testo) == atteso


@pytest.mark.parametrize("testo, iso, nota", [
    ("del 26/01/2024", "2024-01-26", False),
    ("del 2 settembre 2024", "2024-09-02", False),
    ("14/012026", "2026-01-14", True),     # barra mancante: interpretabile con certezza, con nota
    ("", None, False),
    ("31/02/2024", None, True),
])
def test_date(testo, iso, nota):
    risultato, n = a.parse_data_it(testo)
    assert risultato == iso and bool(n) == nota


@pytest.mark.parametrize("grezzo, via, civico, lettera", [
    ("Via Antonio Bosio, 13", "Via Antonio Bosio", 13, ""),
    ("Via Tor De’ Schiavi n. 219", "Via Tor De' Schiavi", 219, ""),
    ("Via Prenestina, 174 G", "Via Prenestina", 174, "G"),
    ("Via dei Castani, 236A", "Via dei Castani", 236, "A"),
    ("Via Del Campo 44 D, Sc A", "Via Del Campo", 44, "D"),
    ("Via Amos Zanibelli, 18 c/o IH Hotel", "Via Amos Zanibelli", 18, ""),
    ("Via di Tor Tre Teste, snc", "Via di Tor Tre Teste", None, ""),
    ("viale Gorizia / via Bosio 13", "via Bosio", 13, ""),
    ("via dei B. Buozzi n.58", "via dei B. Buozzi", 58, ""),
    ("Via Alessandria", "Via Alessandria", None, ""),
])
def test_ripulisci_indirizzo(grezzo, via, civico, lettera):
    v, n, l, _ = a.ripulisci_indirizzo(grezzo)
    assert (v, n, l) == (via, civico, lettera)


def test_abbreviazioni_si_agganciano_alle_vie_ufficiali():
    vie = a.VieAntenne({
        "CIRCONVALLAZIONE NOMENTANA": [(488, 41.9, 12.5, "", "", "UFFICIALE")],
        "VIALE BRUNO BUOZZI": [(58, 41.92, 12.47, "", "", "UFFICIALE")],
        "VIA CESARE FRACASSINI": [(13, 41.93, 12.47, "", "", "UFFICIALE")],
        "VIA ANTONIO BOSIO": [(13, 41.91, 12.51, "", "", "UFFICIALE")],
        "PIAZZA GONDAR": [(7, 41.93, 12.52, "", "", "UFFICIALE")],
        "VIALE DELLA SERENISSIMA": [(91, 41.89, 12.55, "", "", "UFFICIALE")],
    })
    assert vie.trova_motivo("Circ.ne Nomentana")[0] == "CIRCONVALLAZIONE NOMENTANA"
    assert vie.trova_motivo("Circ. Nomentana")[0] == "CIRCONVALLAZIONE NOMENTANA"
    assert vie.trova_motivo("via dei B. Buozzi")[0] == "VIALE BRUNO BUOZZI"
    assert vie.trova_motivo("Via C. Fracassini")[0] == "VIA CESARE FRACASSINI"
    assert vie.trova_motivo("via Bosio")[0] == "VIA ANTONIO BOSIO"
    assert vie.trova_motivo("p.za Gondar")[0] == "PIAZZA GONDAR"
    assert vie.trova_motivo("V.le della Serenissima")[0] == "VIALE DELLA SERENISSIMA"
    # una via inesistente non si aggancia ad altro
    assert vie.trova_motivo("Via Piave")[0] is None
    # "piazza" non si scambia con "via"
    assert vie.trova_motivo("Via Gondar")[0] is None


def test_via_ambigua_non_si_aggancia():
    vie = a.VieAntenne({"VIALE REGINA MARGHERITA": [(1, 41.9, 12.5, "", "", "UFFICIALE")],
                        "VIA REGINA MARGHERITA": [(1, 41.91, 12.5, "", "", "UFFICIALE")]})
    via, motivo = vie.trova_motivo("Regina Margherita")
    assert via is None or "ambigua" in (motivo or "") or via == "VIA REGINA MARGHERITA"


def test_geometria():
    assert a.metri((41.9, 12.5), (41.9009, 12.5)) == pytest.approx(100, abs=2)
    assert a.distanza_polilinea((41.9, 12.5), [[12.49, 41.9009], [12.51, 41.9009]]) == pytest.approx(100, abs=2)


# ---------------------------------------------------------------- file scritti

@pytest.fixture(scope="module")
def dati():
    return json.loads(ANTENNE.read_text(encoding="utf-8"))


def test_struttura_principale(dati):
    assert set(dati) == {"generato", "raggio_m", "avvertenza", "gruppi_sensibili", "fonti", "siti", "pratiche", "controlli"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", dati["generato"])
    assert dati["raggio_m"] == 300
    assert "censimento" in dati["avvertenza"]
    assert dati["gruppi_sensibili"] == {
        "scuole": ["nido", "infanzia", "primaria", "media", "superiore"], "parchi": ["parchi_e_aree_gioco"],
        "sanita": ["pronto_soccorso", "pronto_soccorso_pediatrico", "pronto_soccorso_specialistico", "sanita",
                   "casa_comunita"], "anziani": ["centri_anziani"]}


def test_fonti_e_conteggi(dati):
    attese = {f["id"]: f["attese"] for f in a.FONTI}
    assert {f["id"] for f in dati["fonti"]} == set(attese)
    for f in dati["fonti"]:
        assert f["pratiche"] == attese[f["id"]]
        assert f["pratiche"] == sum(1 for p in dati["pratiche"] if p["fonte"]["id"] == f["id"])
        assert f["url"].startswith("https://www.comune.roma.it/") and f["scaricata"]
    assert len(dati["pratiche"]) == sum(attese.values()) == 219
    assert sum(1 for f in dati["fonti"] if f["municipio"] == "V") == 10
    assert sum(f["pratiche"] for f in dati["fonti"] if f["municipio"] == "V") == 54


def test_id_unici_e_riferimenti(dati):
    id_pratiche = [p["id"] for p in dati["pratiche"]]
    id_siti = [s["id"] for s in dati["siti"]]
    assert len(set(id_pratiche)) == len(id_pratiche)
    assert len(set(id_siti)) == len(id_siti)
    per_id = {p["id"]: p for p in dati["pratiche"]}
    viste = set()
    for s in dati["siti"]:
        for pid in s["pratiche"]:
            assert per_id[pid]["sito"] == s["id"] and per_id[pid]["municipio"] == s["municipio"]
            assert pid not in viste
            viste.add(pid)
    # ogni pratica localizzata sta in un sito; quelle non localizzate in nessuno
    for p in dati["pratiche"]:
        assert (p["sito"] is None) == (p["qualita"] == "non_localizzata") == (p["lat"] is None)


def test_pratiche_campi_e_valori(dati):
    for p in dati["pratiche"]:
        assert p["municipio"] in ("II", "V")
        assert p["formato_originale"] in a.FORMATI
        assert p["qualita"] in a.QUALITA_ORDINE
        assert p["tipologia"] in {"installazione", "installazione_su_esistente", "modifica", "adeguamento",
                                  "dismissione", "altro"}
        assert re.fullmatch(r"C[BF]/\d+/\d{4}|CF/\d{4}/\d+", p["protocollo"]), p["protocollo"]
        assert p["data_protocollo"] is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", p["data_protocollo"])
        assert isinstance(p["note"], list) and isinstance(p["gestori"], list)
        for g in p["gestori"]:
            assert isinstance(g, str) and g
        if p["lat"] is not None:
            assert a.Municipi().nel_comune(p["lat"], p["lon"])
        for k in ("distanza_civico_m", "distanza_via_m"):
            assert p[k] is None or (isinstance(p[k], int) and p[k] >= 0)
        if p["municipio"] == "V":
            assert p["catasto"] is None or set(p["catasto"]) == {"foglio", "particella"}
            assert p["codice_sito"]


def test_regole_di_qualita(dati):
    for p in dati["pratiche"]:
        dc, dv = p["distanza_civico_m"], p["distanza_via_m"]
        if p["qualita"] == "confermata":
            assert (dc is not None and dc <= a.SOGLIA_CONFERMATA_M) or (dc is None and dv is not None and dv <= a.SOGLIA_CONFERMATA_VIA_M)
        elif p["qualita"] == "plausibile":
            assert dc is None or a.SOGLIA_CONFERMATA_M < dc <= a.SOGLIA_PLAUSIBILE_M
        elif p["qualita"] == "da_indirizzo":
            assert p["civico"], p["id"]
            assert p["coord_dichiarate"]["lat"] is None or dc is None or dc > a.SOGLIA_CONFERMATA_M
        else:
            assert p["lat"] is None and p["lon"] is None


def test_siti(dati, ):
    municipi = a.Municipi()
    for s in dati["siti"]:
        assert re.fullmatch(r"(ii|v)-[a-z0-9-]+", s["id"]), s["id"]
        assert s["id"].startswith(s["municipio"].lower() + "-")
        # il sito sta nel suo municipio, oppure e' segnalato
        assert municipi.nel_municipio(s["municipio"], s["lat"], s["lon"]) == s["nel_municipio"]
        assert s["nel_municipio"], s["id"]
        assert s["stato"] in ("nuova_richiesta", "esistente", "dismissione_richiesta")
        assert s["n_vicini"] == len(s["vicini"])
        assert s["vicino_min_m"] == (s["vicini"][0]["m"] if s["vicini"] else None)
        assert [v["m"] for v in s["vicini"]] == sorted(v["m"] for v in s["vicini"])
        for v in s["vicini"]:
            assert v["m"] <= 300 and v["g"] in dati["gruppi_sensibili"] and v["c"] in dati["gruppi_sensibili"][v["g"]]
            assert set(v) == {"g", "c", "n", "i", "lat", "lon", "m"}
            assert abs(a.metri((s["lat"], s["lon"]), (v["lat"], v["lon"])) - v["m"]) <= 1
        date = [p["data_protocollo"] for p in dati["pratiche"] if p["sito"] == s["id"] and p["data_protocollo"]]
        assert s["prima_data"] == (min(date) if date else None) and s["ultima_data"] == (max(date) if date else None)


def test_stato_del_sito_dedotto_dalle_pratiche(dati):
    per_id = {p["id"]: p for p in dati["pratiche"]}
    for s in dati["siti"]:
        tipi = [per_id[i]["tipologia"] for i in s["pratiche"]]
        if tipi[0] == "dismissione":
            assert s["stato"] == "dismissione_richiesta"
        elif any(t in ("modifica", "adeguamento", "installazione_su_esistente") for t in tipi):
            assert s["stato"] == "esistente"
        else:
            assert s["stato"] == "nuova_richiesta" and set(tipi) <= {"installazione"}


def numero_protocollo(p):
    parti = p["protocollo"].split("/")
    return int(parti[1]) if parti[0] == "CB" else int(parti[2])


def test_siti_pratiche_in_ordine_decrescente(dati):
    per_id = {p["id"]: p for p in dati["pratiche"]}
    for s in dati["siti"]:
        chiavi = [(per_id[i]["anno"], numero_protocollo(per_id[i])) for i in s["pratiche"]]
        assert chiavi == sorted(chiavi, reverse=True), s["id"]


def test_controlli(dati):
    c = dati["controlli"]
    assert set(c) == {"II", "V"}
    for mun in ("II", "V"):
        pr = [p for p in dati["pratiche"] if p["municipio"] == mun]
        assert c[mun]["pratiche"] == len(pr)
        assert c[mun]["siti"] == sum(1 for s in dati["siti"] if s["municipio"] == mun)
        assert sum(c[mun]["per_qualita"].values()) == len(pr)
        assert sum(c[mun]["per_formato_originale"].values()) == len(pr)
        assert len(c[mun]["casi_incoerenti"]) == sum(1 for p in pr if p["qualita"] in ("da_indirizzo", "non_localizzata"))
    assert c["II"]["protocolli_ripetuti"] == ["CB/24360/2026"]
    assert c["V"]["protocolli_ripetuti"] == []


def test_casi_sentinella(dati):
    per_id = {p["id"]: p for p in dati["pratiche"]}
    # coordinate della pratica Iliad a Via Salaria 292 con probabile refuso: non si correggono
    p = per_id["ii-cb-50667-2026"]
    assert p["qualita"] == "da_indirizzo" and p["formato_originale"] == "decimale_scritto_dms"
    assert p["distanza_civico_m"] > 400 and p["civico"] == "292"
    # Via C. Fracassini 13: DMS valido ma a 3,7 km
    p = per_id["ii-cb-129506-2026"]
    assert p["qualita"] == "da_indirizzo" and p["formato_originale"] == "dms" and 3500 < p["distanza_civico_m"] < 3900
    assert p["toponimo_ufficiale"] == "Via Cesare Fracassini"
    # Via Antonio Bosio 13: le tre pratiche stanno nello stesso sito
    bosio = [x for x in dati["siti"] if x["id"] == "ii-via-antonio-bosio-13"]
    assert len(bosio) == 1 and len(bosio[0]["pratiche"]) >= 3
    # via dei B. Buozzi 58 e' viale Bruno Buozzi
    assert per_id["ii-cb-65619-2026"]["toponimo_ufficiale"] == "Viale Bruno Buozzi"
    # Via dell'Omo 171 (V): `41°88'25.21" / 12°61?25.21"` = 41.882521, 12.612521, fuori dal Municipio V
    p = per_id["v-cf-2026-204942"]
    assert (p["coord_dichiarate"]["lat"], p["coord_dichiarate"]["lon"]) == (41.88252, 12.61252)
    assert p["coord_dichiarate"]["nel_municipio"] is False and p["qualita"] == "da_indirizzo"


def test_pratiche_ordinate_e_file_deterministico():
    testo = ANTENNE.read_text(encoding="utf-8")
    # una pratica e un sito per riga (diff leggibili)
    assert testo.count('\n{"id": "ii-') + testo.count('\n{"id": "v-') == len(json.loads(testo)["siti"]) + len(json.loads(testo)["pratiche"])


# ---------------------------------------------------------------- indice dei civici

@pytest.fixture(scope="module")
def civici():
    return json.loads(CIVICI.read_text(encoding="utf-8"))


def test_civici_struttura(civici):
    assert civici["fonte"].startswith("Roma Capitale, GeoRoma, numeri civici (scaricati ")
    nomi = [(v[0], v[1]) for v in civici["vie"]]
    assert len(nomi) == len(set(nomi))   # una voce per via e municipio
    assert {v[1] for v in civici["vie"]} == {"II", "V"}
    for nome, mun, elenco in civici["vie"]:
        assert nome and elenco
        visti = set()
        for civ, lat, lon in elenco:
            assert re.fullmatch(r"\d+[A-Z]?( (bis|ter|quater|quinquies|sexies))?", civ), civ
            assert 41.7 < lat < 42.1 and 12.3 < lon < 12.7
            assert round(lat, 5) == lat and round(lon, 5) == lon
            assert (civ, lat, lon) not in visti
            visti.add((civ, lat, lon))
        numeri = [int(re.match(r"\d+", c[0]).group(0)) for c in elenco]
        assert numeri == sorted(numeri)


def test_civici_nomi_leggibili(civici):
    nomi = {v[0] for v in civici["vie"]}
    for atteso in ("Via Antonio Bosio", "Viale dell'Università", "Via dei Monti Parioli", "Via Tor de' Schiavi"):
        assert atteso in nomi, atteso
    assert not any(n.isupper() for n in nomi)
