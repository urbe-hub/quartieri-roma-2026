/*
 * Vista 3D della mappa "Quartieri di Roma 2026" (MapLibre GL, vendorizzato in vendor/maplibre-gl/).
 *
 * Modulo a parte: il build lo copia in dist/3d/ e la mappa 2D lo scarica solo al primo
 * "3D". Non carica dati: riceve dalla 2D aree, municipi, registro delle categorie e
 * servizi gia' pronti (contratto in window.Vista3D.apri, sotto) e restituisce cosa si
 * sceglie. Niente layer di testo (servirebbero i glyph di un servizio esterno): nomi,
 * etichette delle aree e cartiglio (piccolo, solo a Roma e nel municipio: nell'area c'e' la
 * scheda della 2D) sono HTML sovrapposto; i numeri dei grappoli sono
 * immagini disegnate al volo.
 *
 *   Vista3D.supportato()          -> true se il browser ha WebGL
 *   Vista3D.apri(opt)             -> crea l'unica istanza di Map dentro opt.contenitore
 *     opt.contenitore             elemento vuoto, gia' visibile
 *     opt.aree, opt.municipi      FeatureCollection della 2D (aree gia' decodificate)
 *     opt.palette, opt.amaranto   colori dei municipi (stessa rampa della 2D) e del brand
 *     opt.romani                  { "8": "VIII", ... }
 *     opt.tipi                    { "QUARTIERE": "Quartiere", ... }
 *     opt.categorie               registro delle categorie dei servizi (SERVIZI_CATEGORIE: chiave,
 *                                 gruppo, etichetta, singolare...)
 *     opt.gruppi                  gruppi del registro, in ordine (SERVIZI_GRUPPI: chiave, etichetta)
 *     opt.attive                  { chiave: bool }, lo stesso oggetto della 2D (caselle)
 *     opt.icone                   { chiave: svg }, le icone illustrate della 2D (ICONE_SVG)
 *     opt.grappolo                (punti) -> html dentro il grappolo, quello della 2D (htmlGrappolo)
 *     opt.servizi()               Promise dei punti [{ props: {categoria, nome, codice_area,
 *                                 municipio}, latlng: {lat, lng} }] o null se non disponibili
 *     opt.tipiAttivi              { RIONE: bool, QUARTIERE: bool, "ZONA FUNZIONALE": bool }, i filtri
 *                                 per tipo della 2D (activeTipi); assente: tutti accesi
 *     opt.selezione               { tipo: "roma" } | { tipo: "municipio", arabo } | { tipo: "area", codice }
 *     opt.riduciMovimento         true: niente voli ne' crescite, si salta allo stato finale
 *     opt.mobile                  true su telefono (window.MAPPA_MQ_TELEFONO)
 *     opt.onSeleziona(sel)        ogni scelta fatta in 3D (tocco, vista d'insieme, municipio)
 *     opt.onArea(props|null)      a ogni ingresso in un'area (proprieta' della feature, per la
 *                                 scheda della 2D) e all'uscita dal livello area (null)
 *     opt.scheda()                l'elemento della scheda sopra la 3D (o null): a livello area
 *                                 la camera inquadra l'area nello spazio libero accanto (desktop)
 *                                 o sopra (telefono), e le etichette non le finiscono sotto
 *     opt.cartiglio()             telefono, a Roma e nel municipio: px occupati in basso dal cartiglio
 *                                 della 2D sopra la 3D (0 se non c'e'), la camera ci inquadra sopra
 *     opt.pannello()              px da lasciare liberi a destra per il pannello Servizi sopra la 3D
 *                                 (0 se non c'e'): a livello area su desktop la camera li evita
 *     opt.compattaPannello(si)    facoltativa: riduce (true) o ripristina (false) il pannello Servizi alla sola testata;
 *                                 true restituisce se ha cambiato qualcosa
 *     opt.onErrore(messaggio)     la 3D non puo' continuare (WebGL perso, Map non creata)
 *   Vista3D.seleziona(sel)        vola a una selezione decisa fuori (elenco, municipio)
 *   Vista3D.filtraTipi(attivi)    i filtri per tipo cambiati nella 2D (stessa forma di opt.tipiAttivi)
 *   Vista3D.attiveCambiate()      le caselle del pannello Servizi della 2D sono cambiate: rilegge
 *                                 opt.attive e ridisegna i servizi (icone nell'area, numeri nel municipio)
 *   Vista3D.selezione()           selezione corrente
 *   Vista3D.chiudi()              distrugge la Map (una sola istanza alla volta)
 *   Vista3D.stato()               { aperta, pronta, livello, munK } (per i test)
 */
(function () {
  "use strict";

  // Servizi dentro un'area: gli stessi marcatori HTML della 2D (.servizio-marker con la
  // SVG illustrata, .servizio-cluster col numero, balzo), raggruppati con la stessa griglia
  // della 2D sulle coordinate del mondo, ciascuno alzato alla quota della tessera nel suo
  // punto (proiezione esatta, non una traslazione unica). Nella vista municipio i servizi
  // non sono punti: il numero sta nell'etichetta di ogni area.
  var SERVIZI_ICON_MIN = 28, SERVIZI_ICON_MAX = 36;
  var TILE_URL = (typeof window.MAPPA_TILE_URL === "string" && window.MAPPA_TILE_URL) || "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  // Stile della 2D (template: stileBase, opacitaBase, preparaPattern, stileMaschera, TESSERA)
  var ZOOM_VICINO = 14;                                   // da vicino il colore si alleggerisce
  var OPAC = { area: 0.42, zf: 0.5, areaVicino: 0.26, zfVicino: 0.32 };
  // La base OSM sale con la tessera d'area: sul tetto (opaco) sta la carta dell'area,
  // le stesse tile ritagliate sul contorno, velata del colore del municipio come la
  // selezione della 2D (CARTA_VELO). Le pareti sono l'anello del bordo.
  var CARTA_VELO = 0.3;
  // la tessera d'area sale con la sua forma nelle tessere della sorgente; oltre questa attesa
  // (ms) si sale comunque, senza carta finche' le pareti non ci sono
  var ATTESA_FORMA = 6000;
  var VELO = { colore: "#1C2024", opacita: 0.38 };
  var MASCHERA = { colore: "#ffffff", opacita: 0.58 };
  // Roma intera: ingresso dall'alto verso una vista inclinata.
  // Le aree si alzano per tipo (H_TIPO, in metri) staccate da una fuga di ~38 m, e la
  // camera vola dall'alto, piatta e col nord in alto, a una vista inclinata e ruotata
  // di 17 gradi. Municipio e area restano col nord in alto.
  var ROMA_BEARING = -17, ROMA_FUGA = 38, ROMA_DURATA = 1800;
  function pitchRoma() { return S.opt.mobile ? 48 : 52; }
  // Vista municipio: le aree si alzano con un'altezza per tipo (l'unico dato detto con
  // l'altezza). Valori relativi, moltiplicati per k (metri per unita'): k e' tarato su
  // MUN_PARETE px di altezza per il rione alla camera d'arrivo; con l'inclinazione la
  // parete a vista e' circa l'80%: ~52 px il rione, ~35 il quartiere, ~18 la zona
  // funzionale, piu' di 12 px fra un tipo e l'altro (misurato in test_vista_3d.py).
  var H_TIPO = { RIONE: 900, QUARTIERE: 600, "ZONA FUNZIONALE": 320 }, H_TIPO_MIN = 320, MUN_PARETE = 65;
  var MINUSCOLE = { di: 1, del: 1, della: 1, delle: 1, dei: 1, degli: 1, dello: 1, e: 1, a: 1, al: 1, alla: 1, alle: 1, ai: 1, da: 1, in: 1, la: 1, le: 1, lo: 1, il: 1, "de'": 1 };

  var S = null;        // stato dell'istanza aperta
  var cache = null;    // geometrie preparate (restano fra un'apertura e l'altra)

  // ---------- utilita' ----------
  function fold(s) { return String(s == null ? "" : s).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z]/g, ""); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
  }
  function titolo(s) {
    return String(s || "").toLowerCase().split(" ").map(function (w, i) {
      if (i > 0 && MINUSCOLE[w]) return w;
      return w.replace(/(^|['’\-.(])([a-zà-ÿ])/g, function (m, a, b) { return a + b.toUpperCase(); });
    }).join(" ");
  }
  function km2(s) {
    if (typeof s !== "number" || !(s > 0)) return "";
    var dec = s < 1 ? 2 : 1;
    return s.toLocaleString("it-IT", { minimumFractionDigits: dec, maximumFractionDigits: dec }) + " km²";
  }
  function numero(n) { return n.toLocaleString("it-IT"); }
  // come scurisci della 2D: il contorno di un'area e' il suo colore scurito
  function scurisci(hex, f) {
    var n = parseInt(hex.slice(1), 16);
    return "rgb(" + Math.round(((n >> 16) & 255) * f) + "," + Math.round(((n >> 8) & 255) * f) + "," + Math.round((n & 255) * f) + ")";
  }
  // verso il crema del fondo di una frazione k (le tessere di Roma in rilievo)
  function schiarisci(hex, k) {
    var n = parseInt(hex.slice(1), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
    function m(c, t) { return Math.round(c + (t - c) * k); }
    return "rgb(" + m(r, 244) + "," + m(g, 240) + "," + m(b, 234) + ")";
  }
  function colore(m) { return S.opt.palette[(m - 1) % S.opt.palette.length] || "#9aa0a6"; }
  // Filtri per tipo della 2D (activeTipi): una copia, e una chiave per sapere se cambiano.
  function copiaTipi(a) { var o = {}; Object.keys(H_TIPO).forEach(function (t) { o[t] = !a || a[t] !== false; }); return o; }
  function chiaveTipi(t) { return Object.keys(H_TIPO).map(function (k) { return t[k] ? 1 : 0; }).join(""); }
  function tipoAttivo(k) { var e = cache.byCode[k]; return !!e && S.tipi[e.p.tipo] !== false; }

  function poligoni(g) { return g.type === "Polygon" ? [g.coordinates] : (g.type === "MultiPolygon" ? g.coordinates : []); }
  function bbox(g, b) {
    b = b || [180, 90, -180, -90];
    poligoni(g).forEach(function (pol) { pol[0].forEach(function (p) {
      if (p[0] < b[0]) b[0] = p[0]; if (p[1] < b[1]) b[1] = p[1];
      if (p[0] > b[2]) b[2] = p[0]; if (p[1] > b[3]) b[3] = p[1];
    }); });
    return b;
  }
  // Il mondo con dei buchi: gli anelli esterni di `g` (come creaVelo e la maschera della
  // 2D; un buco interno all'area resta coperto, limite noto della 2D).
  var MONDO = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
  function mondoBucato(geometrie) {
    var anelli = [MONDO];
    geometrie.forEach(function (g) { poligoni(g).forEach(function (pol) { anelli.push(pol[0]); }); });
    return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: anelli } }] };
  }
  // Ogni poligono si stringe verso il proprio baricentro di circa `metri`: la fuga fra
  // le tessere di Roma in rilievo (qui la forma esatta non conta, il bordo si').
  function stringi(g, metri) {
    return { type: "MultiPolygon", coordinates: poligoni(g).map(function (pol) {
      var o = pol[0], cx = 0, cy = 0;
      o.forEach(function (p) { cx += p[0]; cy += p[1]; }); cx /= o.length; cy /= o.length;
      var b = bbox({ type: "Polygon", coordinates: [o] });
      var raggio = Math.max((b[2] - b[0]) * 111320 * Math.cos(cy * Math.PI / 180), (b[3] - b[1]) * 110540) / 2 || 1;
      var k = Math.max(0.86, 1 - metri / raggio);
      return pol.map(function (r) { return r.map(function (p) { return [cx + (p[0] - cx) * k, cy + (p[1] - cy) * k]; }); });
    }) };
  }
  function esagono(lon, lat, r) {
    var dLat = r / 110540, dLon = r / (111320 * Math.cos(lat * Math.PI / 180)), anello = [];
    for (var i = 0; i <= 6; i++) { var a = Math.PI / 3 * (i % 6) + Math.PI / 6; anello.push([lon + Math.cos(a) * dLon, lat + Math.sin(a) * dLat]); }
    return [anello];
  }
  // Bordo di larghezza costante attorno al contorno (anche sulle forme concave): un
  // rettangolo per lato, centrato sul lato, piu' un esagono su ogni vertice per chiudere
  // i giunti. E' l'inviluppo del contorno a distanza w/2, senza offset di poligoni:
  // i pezzi si sovrappongono, ma hanno stesso colore e stessa quota.
  function bordo(g, w) {
    var pezzi = [], lat0 = (bbox(g)[1] + bbox(g)[3]) / 2;
    var mx = 111320 * Math.cos(lat0 * Math.PI / 180), my = 110540, h = w / 2;
    poligoni(g).forEach(function (pol) { pol.forEach(function (r) {
      for (var i = 0; i < r.length - 1; i++) {
        var a = r[i], b = r[i + 1];
        var dx = (b[0] - a[0]) * mx, dy = (b[1] - a[1]) * my, L = Math.sqrt(dx * dx + dy * dy);
        if (L < 0.5) continue;
        var nx = -dy / L * h / mx, ny = dx / L * h / my;
        pezzi.push([[[a[0] + nx, a[1] + ny], [b[0] + nx, b[1] + ny], [b[0] - nx, b[1] - ny], [a[0] - nx, a[1] - ny], [a[0] + nx, a[1] + ny]]]);
        pezzi.push(esagono(a[0], a[1], h * 1.04));
      }
    }); });
    return { type: "MultiPolygon", coordinates: pezzi };
  }

  function prepara(opt) {
    if (cache && cache.aree === opt.aree) return cache;
    var c = { aree: opt.aree, byCode: {}, perMun: {}, romaBox: null, kmqRoma: 0, munBox: {}, munGeo: {}, tessere: null, municipi: null, maschera: null };
    var feats = [];
    opt.aree.features.forEach(function (f) {
      var p = f.properties || {};
      if (!p.codice || !f.geometry) return;
      var m = parseInt(p.municipio_num_arabo, 10) || 0;
      c.byCode[p.codice] = { p: p, g: f.geometry, m: m, box: bbox(f.geometry) };
      (c.perMun[m] = c.perMun[m] || []).push(p.codice);
      c.romaBox = bbox(f.geometry, c.romaBox);
      c.kmqRoma += p.superficie_kmq || 0;
      // la forma vera, senza fughe: la citta' e' piatta e disegnata come la 2D
      feats.push({ type: "Feature", properties: { codice: p.codice, m: m, zf: p.tipo === "ZONA FUNZIONALE" }, geometry: f.geometry });
    });
    c.tessere = { type: "FeatureCollection", features: feats };
    c.municipi = { type: "FeatureCollection", features: opt.municipi.features.map(function (f) {
      var m = parseInt(f.properties.municipio, 10);
      c.munBox[m] = bbox(f.geometry); c.munGeo[m] = f.geometry;
      return { type: "Feature", properties: { m: m }, geometry: f.geometry };
    }) };
    // Roma in rilievo (solo a livello Roma): ogni area stretta verso il proprio baricentro
    // (la fuga fra le tessere), alta per tipo, del colore del municipio appena schiarito di
    // un tono stabile per area (dal codice: niente casualita' fra un'apertura e l'altra).
    c.roma = { type: "FeatureCollection", features: feats.map(function (f) {
      var e = c.byCode[f.properties.codice], cod = f.properties.codice, hsh = 0;
      for (var i = 0; i < cod.length; i++) hsh = (hsh * 31 + cod.charCodeAt(i)) % 997;
      var base = opt.palette[(e.m - 1) % opt.palette.length] || "#9aa0a6";
      return { type: "Feature", properties: { codice: cod, col: schiarisci(base, 0.7 * (hsh % 7) / 20 * 0.6) }, geometry: stringi(e.g, ROMA_FUGA) };
    }) };
    // Roma intera (i contorni dei municipi), per inquadrarla tutta sopra il cartiglio
    c.romaGeo = { type: "MultiPolygon", coordinates: [].concat.apply([], opt.municipi.features.map(function (f) { return f.geometry ? poligoni(f.geometry) : []; })) };
    // maschera fuori Roma: il mondo bucato dai municipi (costruisciMaschera della 2D)
    c.maschera = mondoBucato(opt.municipi.features.map(function (f) { return f.geometry; }).filter(Boolean));
    cache = c;
    return c;
  }

  // Registro della 2D: categoria -> voce, gruppi in ordine (letti a ogni apertura).
  function registro(opt) {
    var r = { cat: {}, gruppi: (opt.gruppi || []).slice() };
    (opt.categorie || []).forEach(function (c) { r.cat[c.chiave] = c; });
    return r;
  }
  function gruppoDi(chiave) { var c = S.reg.cat[chiave]; return c ? c.gruppo : ""; }
  function singolare(chiave) { var c = S.reg.cat[chiave]; return c ? (c.singolare || c.etichetta) : chiave; }
  function categorieDelGruppo(g) {
    return Object.keys(S.reg.cat).filter(function (k) { return S.reg.cat[k].gruppo === g; });
  }

  // Un punto dentro l'area (per l'etichetta nella vista municipio): il baricentro dei
  // vertici del poligono piu' grande, o il punto interno piu' vicino.
  function dentroAnello(x, y, r) {
    var d = false;
    for (var i = 0, j = r.length - 1; i < r.length; j = i++) {
      var xi = r[i][0], yi = r[i][1], xj = r[j][0], yj = r[j][1];
      if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) d = !d;
    }
    return d;
  }
  function dentro(pol, x, y) {
    if (!dentroAnello(x, y, pol[0])) return false;
    for (var k = 1; k < pol.length; k++) if (dentroAnello(x, y, pol[k])) return false;
    return true;
  }
  function puntoInterno(g) {
    var pol = poligoni(g).map(function (p) { var b = bbox({ type: "Polygon", coordinates: p }); return { p: p, a: (b[2] - b[0]) * (b[3] - b[1]), b: b }; })
      .sort(function (a, b) { return b.a - a.a; })[0];
    if (!pol) return null;
    var o = pol.p[0], cx = 0, cy = 0;
    o.forEach(function (q) { cx += q[0]; cy += q[1]; }); cx /= o.length; cy /= o.length;
    if (dentro(pol.p, cx, cy)) return [cx, cy];
    var best = null, bd = Infinity, b = pol.b;
    for (var i = 1; i < 12; i++) for (var j = 1; j < 12; j++) {
      var x = b[0] + (b[2] - b[0]) * i / 12, y = b[1] + (b[3] - b[1]) * j / 12;
      var d = (x - cx) * (x - cx) + (y - cy) * (y - cy);
      if (d < bd && dentro(pol.p, x, y)) { bd = d; best = [x, y]; }
    }
    return best || [cx, cy];
  }

  // ---------- animazione ----------
  function ease(t) { var v = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; return Math.min(1, Math.max(0, v)); }
  function easeBack(t) { var c1 = 1.15, c3 = c1 + 1; return Math.max(0, 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2)); }
  function tween(chiave, durata, passo, fine, curva) {
    if (S.tween[chiave]) cancelAnimationFrame(S.tween[chiave]);
    S.tween[chiave] = null;
    if (S.opt.riduciMovimento || durata <= 0) { passo(1); if (fine) fine(); return; }
    var t0 = performance.now(), mio = S;
    (function frame(ora) {
      if (S !== mio) return;
      var t = Math.max(0, Math.min(1, (ora - t0) / durata));   // il timestamp di rAF puo' precedere t0
      passo((curva || ease)(t));
      if (t < 1) S.tween[chiave] = requestAnimationFrame(frame);
      else { S.tween[chiave] = null; if (fine) fine(); }
    })(t0);
  }
  // Ritardo sullo stesso orologio dei fotogrammi (requestAnimationFrame + performance.now),
  // non su setTimeout: tessere, camera e ritardi restano allineati anche se il dispositivo
  // perde fotogrammi.
  function dopo(ms, fn) {
    var gen = S.gen, mio = S, fino = performance.now() + (S.opt.riduciMovimento ? 0 : ms);
    if (ms <= 0 || S.opt.riduciMovimento) { fn(); return; }
    (function giro() {
      if (S !== mio || S.gen !== gen) return;
      if (performance.now() >= fino) fn(); else requestAnimationFrame(giro);
    })();
  }

  // Visibilita' delle aree (feature-state `vis`, 0..1): moltiplica l'opacita' di
  // riempimento, retino e contorno. Ogni passaggio e' una sola interpolazione continua:
  // per ogni area si scrivono una volta il valore di partenza (`vis0`, quello visibile in
  // quel momento, anche a meta' di un passaggio) e quello d'arrivo (`vis`); a ogni
  // fotogramma cambia solo il fattore t nell'espressione. Mai filtri, mai sorgenti
  // ricaricate: era questo lo sfarfallio fra una zona e l'altra.
  function espressioni(t) {
    var fs = function (k) { return ["coalesce", ["feature-state", k], 0]; };
    var vis = ["+", fs("vis0"), ["*", ["-", fs("vis"), fs("vis0")], t]];
    // come opacitaBase della 2D: sopra lo zoom 14 il colore si alleggerisce
    var opac = function (lontano, vicino) { return ["step", ["zoom"], ["*", vis, lontano], ZOOM_VICINO, ["*", vis, vicino]]; };
    S.map.setPaintProperty("aree-fill", "fill-opacity", opac(OPAC.area, OPAC.areaVicino));
    S.map.setPaintProperty("aree-retino", "fill-opacity", opac(OPAC.zf, OPAC.zfVicino));
    S.map.setPaintProperty("aree-linea", "line-opacity", ["*", vis, 0.7]);
  }
  // mappa = { codice: 0|1 } (le aree assenti vanno a 0)
  function visibilita(mappa, durata, fine) {
    var t = S.t, cambi = 0;
    Object.keys(cache.byCode).forEach(function (k) {
      var st = S.st[k] || { vis0: 0, vis: 0 };
      var n = { vis0: st.vis0 + (st.vis - st.vis0) * t, vis: mappa[k] ? 1 : 0 };
      if (n.vis0 === st.vis0 && n.vis === st.vis) return;
      S.st[k] = n; cambi++;
      S.map.setFeatureState({ source: "aree", id: k }, n);
    });
    // Niente da cambiare: ogni area e' gia' ferma dove deve stare (anche a meta' di un
    // passaggio, se nessuna aveva vis diverso da vis0). Si chiude l'eventuale passaggio in
    // corso (la sua fine apparteneva alla selezione di prima) e si risponde subito.
    if (!cambi) {
      if (S.tween.aree) { cancelAnimationFrame(S.tween.aree); S.tween.aree = null; }
      if (S.t !== 1) { S.t = 1; espressioni(1); }
      if (fine) fine();
      return;
    }
    S.t = 0;
    tween("aree", durata == null ? 900 : durata, function (k) { S.t = k; espressioni(k); }, fine);
  }

  // Velo della 2D (TESSERA.velo*): il fuori si scurisce, il buco e' la sagoma di cio'
  // che si guarda. A terra sopra le aree, sotto le estrusioni (strVelo, senza tessere).
  // La sagoma di uno strato cambia solo a strato spento (sotto un velo visibile il buco
  // salterebbe da una forma all'altra). Fra due sagome si passa con una dissolvenza
  // incrociata: "velo-vecchio" tiene la sagoma corrente a opacita' 0, prende il posto del
  // velo e scende mentre il velo risale col buco nuovo.
  function opacita(id) { return S.veloOp[id] || 0; }
  function veloOp(id, v) { S.veloOp[id] = v; S.map.triggerRepaint(); }
  function veloA(b, durata) {
    var a = opacita("velo");
    tween("velo", durata == null ? 900 : durata, function (k) { veloOp("velo", a + (b - a) * k); });
  }
  function bucoIn(id, g) {
    if (opacita(id) > 0.01) S.veloSalti++;            // per i test: mai sotto un velo visibile
    S.veloG[id] = g || null;
    if (id === "velo") S.veloBuco = g; else S.vecchioBuco = g;
    S.map.triggerRepaint();
  }
  // a velo vecchio spento, la sagoma corrente pronta per la prossima dissolvenza
  function preparaVecchio() {
    if (S.vecchioBuco !== S.veloBuco && opacita("velo-vecchio") <= 0.01 && !S.tween.vecchio) bucoIn("velo-vecchio", S.veloBuco);
  }
  function veloSu(g, durata) {
    var d = durata == null ? 900 : durata, a = opacita("velo");
    if (g === S.veloBuco) { veloA(VELO.opacita, d); return; }
    if (a <= 0.01) {
      if (S.tween.velo) { cancelAnimationFrame(S.tween.velo); S.tween.velo = null; }
      veloOp("velo", 0);
      bucoIn("velo", g); preparaVecchio();
      veloA(VELO.opacita, d);
      return;
    }
    if (S.vecchioBuco === S.veloBuco && opacita("velo-vecchio") <= 0.01 && !S.tween.vecchio) {
      // nello stesso fotogramma il vecchio (stessa sagoma) sostituisce il
      // velo, che a opacita' 0 cambia sagoma e poi risale
      if (S.tween.velo) { cancelAnimationFrame(S.tween.velo); S.tween.velo = null; }
      veloOp("velo-vecchio", a);
      veloOp("velo", 0);
      bucoIn("velo", g);
      // Fuori da entrambi i buchi i due strati si sommano: 1 - (1 - v)(1 - w). Il vecchio
      // segue la curva del velo (stessa durata, stessa ease, stesso fotogramma di partenza)
      // in modo che la somma vada da a a VELO.opacita senza avvallamento (con w = a(1 - k)
      // scendeva al 34% a meta').
      tween("vecchio", d, function (k) {
        var v = VELO.opacita * k, T = a + (VELO.opacita - a) * k;
        veloOp("velo-vecchio", Math.max(0, 1 - (1 - T) / (1 - v)));
      }, preparaVecchio);
      veloA(VELO.opacita, d);
      return;
    }
    // ripiego (una scelta nuova a meta' dissolvenza): il velo scende, cambia sagoma a
    // velo spento e risale
    tween("velo", Math.max(120, 350 * a / VELO.opacita), function (k) { veloOp("velo", a * (1 - k)); }, function () {
      bucoIn("velo", g); preparaVecchio();
      veloA(VELO.opacita, d);
    });
  }
  function veloGiu(durata) { veloA(0, durata); }

  // ---------- camera ----------
  // A Roma e nel municipio in basso c'e' il cartiglio piccolo (CARTIGLIO_SPAZIO px col suo
  // margine). Nell'area c'e' la scheda della 2D: su telefono chiusa in basso (la sua altezza
  // piu' 16 px), su desktop in basso a sinistra (l'area si inquadra alla sua destra).
  var CARTIGLIO_SPAZIO = { tel: 104, desk: 130 }, SPAZIO_MIN = 120;
  function schedaSopra() {
    var el = S.livello === "area" && S.opt.scheda ? S.opt.scheda() : null;
    return el && el.offsetHeight ? el : null;
  }
  function padding() {
    var sch = schedaSopra();
    if (S.opt.mobile) return { top: 96, bottom: sch ? sch.offsetHeight + 16 : Math.max(CARTIGLIO_SPAZIO.tel, (S.opt.cartiglio && S.opt.cartiglio()) || 0), left: 22, right: 22 };
    if (sch) {
      // La tessera nello spazio libero fra la scheda (a sinistra) e il pannello Servizi (in
      // alto a destra). Nelle finestre strette (tablet, telefono in orizzontale) li' non resta
      // spazio (era negativo: lo zoom diventava NaN e la 3D non arrivava mai): si prova sopra
      // la scheda, poi sotto il pannello, sempre evitandolo. Il primo spazio di almeno SPAZIO_MIN px per
      // lato, altrimenti il piu' grande.
      var W = S.el.clientWidth, H = S.el.clientHeight, b = S.el.getBoundingClientRect(), r = sch.getBoundingClientRect();
      var accanto = Math.max(70, r.right - b.left + 24), sopra = Math.max(70, b.bottom - r.top + 16);
      var larg = function (p) { return W - p.left - p.right; }, alt = function (p) { return H - p.top - p.bottom; };
      var area = function (p) { return Math.max(0, larg(p)) * Math.max(0, alt(p)); };
      var scegli = function () {
        var pan = S.opt.pannello ? S.opt.pannello() || 0 : 0;
        var rp = Math.max(24, pan + 24);
        // fondo del pannello (px dal bordo alto della mappa): sotto di esso c'e' una fascia libera
        var fp = pan && S.opt.pannelloFondo ? S.opt.pannelloFondo() || 0 : 0;
        var prove = [
          { top: 70, bottom: 70, left: accanto, right: Math.max(70, pan + 24) },
          { top: 70, bottom: sopra, left: 24, right: Math.max(24, pan + 24) },
          { top: 24, bottom: 24, left: accanto, right: rp },
          { top: 24, bottom: sopra, left: 24, right: rp }
        ];
        if (fp) {
          prove.push({ top: fp + 16, bottom: 24, left: accanto, right: 24 });
          prove.push({ top: fp + 16, bottom: sopra, left: 24, right: 24 });
        }
        var buona = prove.filter(function (p) { return larg(p) >= SPAZIO_MIN && alt(p) >= SPAZIO_MIN; })[0];
        if (buona) return { p: buona, ok: true, pan: pan };
        // ripiego: accanto alla scheda e al pannello, margini minimi
        var ultima = { top: 24, bottom: 24, left: r.right - b.left + 10, right: pan + 10 };
        prove.push(ultima);
        return { p: prove.slice().sort(function (p, q) { return area(q) - area(p); })[0], ok: false, pan: pan };
      };
      // Prima col pannello Servizi come l'ha lasciato la persona; se la tessera non ha
      // SPAZIO_MIN px liberi, il pannello si riduce alla sola testata (libera la colonna) e si
      // riprova. A ogni nuova camera si parte di nuovo dal pannello com'era.
      if (S.opt.compattaPannello) S.opt.compattaPannello(false);
      var ris = scegli();
      if (!ris.ok && ris.pan && S.opt.compattaPannello && S.opt.compattaPannello(true)) {
        var ris2 = scegli();
        if (ris2.ok) ris = ris2; else S.opt.compattaPannello(false);
      }
      var scelta = ris.p;
      // mai un padding piu' grande dell'area: MapLibre non saprebbe inquadrare
      scelta = Object.assign({}, scelta);
      var resto = function (tot, x, y) {
        var max = Math.max(0, tot - 40);
        if (x + y > max) { var k = max / (x + y || 1); return [Math.floor(x * k), Math.floor(y * k)]; }
        return [x, y];
      };
      var v = resto(W, scelta.left, scelta.right), h = resto(H, scelta.top, scelta.bottom);
      scelta.left = v[0]; scelta.right = v[1]; scelta.top = h[0]; scelta.bottom = h[1];
      return scelta;
    }
    return { top: 70, bottom: CARTIGLIO_SPAZIO.desk, left: 70, right: 70 };
  }
  // Nord in alto, come la 2D, nel municipio e nell'area (bearing 0); Roma intera ruotata (ROMA_BEARING).
  function vola(opt) {
    S.camArrivo = opt;
    if (S.opt.riduciMovimento) S.map.jumpTo(opt);
    else S.map.flyTo(Object.assign({ duration: 2500, curve: 1.42, essential: true }, opt));
    return opt.zoom;
  }
  // Inclinazioni (nord sempre in alto): l'area un po' piu' inclinata del municipio, cosi'
  // la tessera che si alza si vede; su telefono 2 gradi in meno.
  function pitchFocus() { return S.opt.mobile ? 44 : 46; }
  function pitchMunicipio() { return pitchFocus() - 4; }
  // Metri per pixel allo zoom z di MapLibre: il mondo e' largo 512 * 2^z px (tessere da
  // 512), quindi 40075016,686 / 512 = 78271,517 m/px allo zoom 0 sull'equatore.
  function mppA(lat, z) { return 78271.517 * Math.cos(lat * Math.PI / 180) / Math.pow(2, z); }
  // Altezza della tessera d'area allo zoom z: AREA_PARETE px di parete a vista al centro
  // dell'area, all'inclinazione dell'area (la parete a schermo e' circa altezza / mpp *
  // sin(inclinazione)). Misurata in test_vista_3d.py (batteria_area: fra 40 e 80 px).
  var AREA_PARETE = 60;
  function altezzaArea(e, z) {
    var mpp = mppA((e.box[1] + e.box[3]) / 2, z);
    return Math.max(6, Math.min(900, mpp * AREA_PARETE / Math.sin(pitchFocus() * Math.PI / 180)));
  }
  // cameraForBounds non conosce l'inclinazione (la parte vicina si allarga,
  // quella lontana si stringe) ne' i tetti alzati. Si cerca la camera d'arrivo proiettando
  // il contorno vero (a terra e, se `quota(z)` da' metri, anche sul tetto) su una copia
  // della camera: tutto dentro lo schermo, sopra il cartiglio o la scheda, con `alto` px liberi sopra.
  // `bearing` (facoltativo, 0 di norma) solo per Roma intera.
  function inquadra(geo, box, pitch, maxZoom, alto, quota, durata, bearing) {
    var pad = padding(), tr = S.map.transform.clone();
    var pts = [];
    poligoni(geo).forEach(function (pol) {
      var r = pol[0], passo = Math.max(1, Math.floor(r.length / 160));
      for (var i = 0; i < r.length; i += passo) pts.push(new maplibregl.LngLat(r[i][0], r[i][1]));
    });
    var mcs = quota ? pts.map(function (ll) { return maplibregl.MercatorCoordinate.fromLngLat(ll); }) : null;
    // su telefono si stringono i margini
    var L = S.opt.mobile ? 14 : pad.left, R = tr.width - (S.opt.mobile ? 14 : pad.right), T = pad.top + alto, B = tr.height - pad.bottom - 10;
    S.dimInquadra = tr.width + "x" + tr.height;
    var rot = bearing || 0;
    var cam = S.map.cameraForBounds([[box[0], box[1]], [box[2], box[3]]], { padding: pad, bearing: rot }) || {};
    var centro = maplibregl.LngLat.convert(cam.center || [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]), z = cam.zoom || 11;
    tr.bearing = rot; tr.pitch = pitch;
    var misura = function () {
      tr.center = centro; tr.zoom = z;
      var b = [Infinity, Infinity, -Infinity, -Infinity], h = quota ? quota(z) : 0;
      var su = function (q) { b[0] = Math.min(b[0], q.x); b[1] = Math.min(b[1], q.y); b[2] = Math.max(b[2], q.x); b[3] = Math.max(b[3], q.y); };
      pts.forEach(function (ll) { su(tr.locationPoint(ll)); });
      if (h) mcs.forEach(function (mc) { su(tr.coordinatePoint(mc, h)); });
      return b;
    };
    // il centro del contorno a schermo va al centro dello spazio libero
    var centra = function () {
      var b = misura(), dx = (b[0] + b[2]) / 2 - (L + R) / 2, dy = (b[1] + b[3]) / 2 - (T + B) / 2;
      centro = tr.pointLocation(new maplibregl.Point(tr.width / 2 + dx, tr.height / 2 + dy));
    };
    for (var i = 0; i < 10; i++) {
      var b = misura(), sc = Math.min((R - L) / (b[2] - b[0]), (B - T) / (b[3] - b[1]));
      if (!(sc > 0 && isFinite(sc))) break;               // niente spazio: resta lo zoom di cameraForBounds
      z = Math.min(maxZoom, z + Math.log(sc) / Math.LN2 * 0.9);
      centra();
    }
    // Ultimi ritocchi, ricentrando a ogni passo: lo spazio libero non contiene sempre il
    // centro dello schermo, e allontanandosi attorno a quello il contorno ne usciva (su un
    // tablet lo zoom scendeva di 1,5 livelli, la tessera restava minuscola).
    for (var j = 0; j < 30; j++) {
      var f = misura();
      if (f[0] >= L - 1 && f[2] <= R + 1 && f[1] >= T - 1 && f[3] <= B + 1) break;
      z -= 0.05;
      centra();
    }
    var arrivo = { center: [centro.lng, centro.lat], zoom: z, bearing: rot, pitch: pitch };
    if (durata) arrivo.duration = durata;
    return vola(arrivo);
  }
  // Finestra cambiata (telefono ruotato, finestra ridimensionata): la camera reinquadra la
  // selezione corrente, senza rifare il passaggio; a passaggio in corso aspetta che finisca
  // (una selezione nuova cancella l'attesa e inquadra da se').
  function riquadra() {
    if (!S || !S.sel) return;
    if (!S.pronta || S.map.isMoving()) { S.timer.push(setTimeout(riquadra, 300)); return; }
    var sel = S.sel, c = cache;
    // la soglia del telefono della 2D (suMobile): ruotato, il telefono puo' passarla
    S.opt.mobile = window.matchMedia(window.MAPPA_MQ_TELEFONO || "(max-width: 720px)").matches;
    if (sel.tipo === "roma") cameraRoma(600);
    else if (sel.tipo === "municipio") inquadra(c.munGeo[sel.arabo], c.munBox[sel.arabo], pitchMunicipio(), 14, MUN_PARETE, null, 600);
    else { var e = c.byCode[sel.codice]; inquadra(e.g, e.box, pitchFocus(), 16.2, 12, function (zz) { return altezzaArea(e, zz); }, 600); }
  }
  // Roma intera come l'ingresso di prima: inclinata e ruotata, tutta nello schermo sopra
  // il cartiglio, tetti compresi (le tessere piu' alte, i rioni).
  function cameraRoma(durata) {
    return inquadra(cache.romaGeo, cache.romaBox, pitchRoma(), 12, 0, function () { return H_TIPO.RIONE; }, durata, ROMA_BEARING);
  }
  // Municipio: tutto il contorno, con lo spazio per le pareti in alto.
  function cameraMunicipio(m, pitch, maxZoom) { return inquadra(cache.munGeo[m], cache.munBox[m], pitch, maxZoom, MUN_PARETE); }

  // ---------- mappa ----------
  function creaMappa(el, c) {
    var map = new maplibregl.Map({
      container: el,
      style: {
        version: 8,
        // Niente transizioni di stile (MapLibre ne mette 300 ms a ogni setPaintProperty): ogni
        // passaggio e' gia' animato qui, fotogramma per fotogramma. Con la transizione lo
        // scambio fra velo e velo vecchio arrivava in ritardo mentre il buco nuovo era gia'
        // disegnato: la destinazione restava scoperta per un fotogramma o due.
        transition: { duration: 0, delay: 0 },
        sources: {
          osm: { type: "raster", tiles: [TILE_URL], tileSize: 256, maxzoom: 19,
                 // su telefono il testo corto della 2D; le fonti complete sono in "Cos'e'"
                 attribution: (S.opt.mobile ? "Mappa non ufficiale · Dati: Roma Capitale · © " : "Mappa non ufficiale · Dati: Roma Capitale, GeoRoma e altre fonti · © ") +
                   "<a href=\"https://www.openstreetmap.org/copyright\" target=\"_blank\" rel=\"noopener\">" + (S.opt.mobile ? "OpenStreetMap</a>" : "OpenStreetMap contributors</a>") }
        },
        layers: [
          { id: "fondo", type: "background", paint: { "background-color": "#EDE8E1" } },
          { id: "osm", type: "raster", source: "osm",
            // a colori come la 2D
            paint: { "raster-saturation": 0, "raster-contrast": 0, "raster-opacity": 1, "raster-fade-duration": 150 } }
        ]
      },
      bounds: [[c.romaBox[0], c.romaBox[1]], [c.romaBox[2], c.romaBox[3]]],
      fitBoundsOptions: { padding: 20 },
      minZoom: 8, maxZoom: 18, maxPitch: 70,
      maxBounds: [[c.romaBox[0] - 0.6, c.romaBox[1] - 0.45], [c.romaBox[2] + 0.6, c.romaBox[3] + 0.45]],
      bearing: 0, dragRotate: false, pitchWithRotate: false, touchPitch: false,
      attributionControl: false,
      antialias: !S.opt.mobile,
      pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
      fadeDuration: 0
    });
    map.touchZoomRotate.disableRotation();
    map.keyboard.disableRotation();
    // Attribuzione sempre leggibile (mai compressa nell'icona): su telefono in alto a destra,
    // il basso e' del cartiglio e della scheda.
    map.addControl(new maplibregl.AttributionControl({ compact: false }), S.opt.mobile ? "top-right" : "bottom-right");
    if (!S.opt.mobile) map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    return map;
  }

  // Retino delle zone funzionali, come preparaPattern della 2D: una tessera per colore
  // di PALETTE, fondo al 16%, riga di 2,4 px all'85%, passo di 7 px a 45 gradi. Il passo
  // in diagonale di 7 px vuole una tessera di 7*radice(2) = ~10 px per ripetersi senza giunte.
  function registraRetini() {
    var pr = Math.min(window.devicePixelRatio || 1, 2), lato = 10, px = Math.round(lato * pr);
    S.opt.palette.forEach(function (col, i) {
      var id = "retino-" + i;
      if (S.map.hasImage(id)) return;
      var cv = document.createElement("canvas"); cv.width = px; cv.height = px;
      var x = cv.getContext("2d");
      x.scale(px / lato, px / lato);
      x.globalAlpha = 0.16; x.fillStyle = col; x.fillRect(0, 0, lato, lato);
      x.globalAlpha = 0.85; x.strokeStyle = col; x.lineWidth = 2.4; x.lineCap = "square";
      // righe "/" (la verticale ruotata di 45 gradi della 2D), ripetute oltre i bordi
      [-lato, 0, lato].forEach(function (o) { x.beginPath(); x.moveTo(o - 1, lato + 1); x.lineTo(o + lato + 1, -1); x.stroke(); });
      S.map.addImage(id, x.getImageData(0, 0, px, px), { pixelRatio: px / lato });
    });
  }

  function aggiungiLayer(c) {
    var map = S.map, palette = S.opt.palette;
    map.setLight({ anchor: "map", color: "#FFF6EC", intensity: 0.42, position: [1.4, 205, 38] });
    map.addSource("aree", { type: "geojson", data: c.tessere, promoteId: "codice" });
    map.addSource("municipi", { type: "geojson", data: c.municipi });
    map.addSource("maschera", { type: "geojson", data: c.maschera });
    map.addSource("roma", { type: "geojson", data: c.roma, promoteId: "codice" });
    ["focus", "focus-bordo"].forEach(function (id) {
      map.addSource(id, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    });
    // il municipio che si alza: le sue aree e i loro bordi, per codice (stato `k` per area)
    ["mun", "mun-bordo"].forEach(function (id) {
      map.addSource(id, { type: "geojson", data: { type: "FeatureCollection", features: [] }, promoteId: "codice" });
    });
    S.colMun = ["match", ["get", "m"]]; S.colLinea = ["match", ["get", "m"]];
    var retino = ["match", ["get", "m"]];
    palette.forEach(function (col, i) { S.colMun.push(i + 1, col); S.colLinea.push(i + 1, scurisci(col, 0.62)); retino.push(i + 1, "retino-" + i); });
    S.colMun.push("#9aa0a6"); S.colLinea.push(scurisci("#9aa0a6", 0.62)); retino.push("retino-0");
    registraRetini();

    // Tutto piatto e a terra, come la 2D: maschera fuori Roma, riempimento (o retino per
    // le zone funzionali), contorno, confini dei municipi, velo; sopra solo le estrusioni
    // del focus. Filtri fissati qui una volta sola, mai cambiati nei passaggi.
    map.addLayer({ id: "maschera", type: "fill", source: "maschera",
      paint: { "fill-color": MASCHERA.colore, "fill-opacity": MASCHERA.opacita, "fill-antialias": false } });
    map.addLayer({ id: "aree-fill", type: "fill", source: "aree", filter: ["!=", ["get", "zf"], true],
      paint: { "fill-color": S.colMun, "fill-opacity": 0, "fill-antialias": false } });
    map.addLayer({ id: "aree-retino", type: "fill", source: "aree", filter: ["==", ["get", "zf"], true],
      paint: { "fill-pattern": retino, "fill-opacity": 0, "fill-antialias": false } });
    map.addLayer({ id: "aree-linea", type: "line", source: "aree",
      paint: { "line-color": S.colLinea, "line-width": 1, "line-opacity": 0 } });
    // confini dei municipi come la 2D (.municipio-line: amaranto, 1,4 px, 55%); quello del
    // municipio scelto si accende con l'opacita', non con un filtro
    map.addLayer({ id: "mun-line", type: "line", source: "municipi",
      paint: { "line-color": S.opt.amaranto, "line-opacity": 0.55, "line-width": 1.4 } });
    map.addLayer(strVelo("velo"));
    map.addLayer(strVelo("velo-vecchio"));
    map.addLayer({ id: "mun-focus", type: "line", source: "municipi",
      // il confine del municipio scelto si accende con una dissolvenza breve dello stile
      paint: { "line-color": S.opt.amaranto, "line-width": ["interpolate", ["linear"], ["zoom"], 10, 2.5, 14, 5], "line-opacity": 0,
               "line-opacity-transition": { duration: 300, delay: 0 } } });
    espressioni(0);
    // Municipio alzato: ogni area del colore pieno del municipio (come la selezione della
    // 2D), alta hTipo * k; sopra, il contorno scurito come bordo estruso alla stessa quota
    // (le linee stanno a terra). k arriva come feature-state: un'espressione con ["get"]
    // cambiata con setPaintProperty rifarebbe le tessere della sorgente a ogni fotogramma.
    // Nascosti finche' la piu' bassa non supera i 2 m (vedi altezzaMun).
    var k = ["coalesce", ["feature-state", "k"], 0], hk = ["*", ["get", "hTipo"], k];
    map.addLayer({ id: "mun-ext", type: "fill-extrusion", source: "mun", layout: { visibility: "none" }, paint: {
      "fill-extrusion-color": ["get", "col"], "fill-extrusion-height": hk, "fill-extrusion-base": 0, "fill-extrusion-opacity": 1 } });
    map.addLayer({ id: "mun-bordo", type: "fill-extrusion", source: "mun-bordo", layout: { visibility: "none" }, paint: {
      "fill-extrusion-color": ["get", "col"], "fill-extrusion-base": ["max", 0, ["-", hk, 1]], "fill-extrusion-height": ["+", hk, 2],
      "fill-extrusion-opacity": 1, "fill-extrusion-vertical-gradient": false } });
    S.munVis = "none";
    // Roma in rilievo: altezza per area come feature-state `h` (metri), scritta a ogni
    // fotogramma della crescita (mai un'espressione con ["get"] cambiata, mai un filtro).
    // Sempre accesa (uno strato a visibility none ferma la sua sorgente: la crescita
    // partirebbe senza tessere); a terra ha opacita' 0 e non si disegna.
    map.addLayer({ id: "roma-ext", type: "fill-extrusion", source: "roma", paint: {
      "fill-extrusion-color": ["get", "col"], "fill-extrusion-height": ["coalesce", ["feature-state", "h"], 0],
      "fill-extrusion-base": 0, "fill-extrusion-opacity": 0, "fill-extrusion-vertical-gradient": true } });
    S.romaSu = false;
    // Tessera del focus: pareti amaranto (sull'anello del bordo, cave), lastra sottile del
    // colore del municipio sopra (piena finche' la carta dell'area non e' pronta, vedi lastra()), bordo amaranto a larghezza costante sul piano.
    map.addLayer({ id: "focus-wall", type: "fill-extrusion", source: "focus-bordo", paint: {
      "fill-extrusion-color": S.opt.amaranto, "fill-extrusion-height": 0, "fill-extrusion-base": 0, "fill-extrusion-opacity": 1 } });
    map.addLayer({ id: "focus-top", type: "fill-extrusion", source: "focus", paint: {
      "fill-extrusion-color": ["get", "col"], "fill-extrusion-height": 0, "fill-extrusion-base": 0, "fill-extrusion-opacity": 1 } });
    map.addLayer(strCarta());
    map.addLayer({ id: "focus-bordo", type: "fill-extrusion", source: "focus-bordo", paint: {
      "fill-extrusion-color": S.opt.amaranto, "fill-extrusion-height": 0, "fill-extrusion-base": 0, "fill-extrusion-opacity": 1, "fill-extrusion-vertical-gradient": false } });
  }

  // ---------- carta sul tetto della tessera d'area ----------
  // Le tile OSM dell'area, a uno zoom vicino a quello d'arrivo, composte in un canvas e
  // ritagliate sul contorno: e' la texture di un rettangolo alla quota del tetto, allineato
  // al mondo (gli angoli sono i bordi delle tile in coordinate mercatore). Lo strato WebGL
  // (custom, "3d") condivide la profondita' delle estrusioni: pareti e bordo restano davanti
  // e dietro come prima. Si disegna solo con la tessera su (S.focusVis "visible") e con la
  // carta pronta; finche' le tile arrivano il tetto e' la lastra a colore pieno, poi la carta
  // la sostituisce nello stesso fotogramma (lastra()). Niente addLayer ne' setData durante
  // le transizioni: lo strato c'e' da subito.
  function caricaCarta(e, col, z) {
    var zt = Math.max(10, Math.min(18, Math.round(z) + 1)), n, x0, y0, x1, y1;
    var tx = function (lon, k) { return (lon + 180) / 360 * k; };
    var ty = function (lat, k) { var r = lat * Math.PI / 180; return (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * k; };
    for (;; zt--) {
      n = Math.pow(2, zt);
      x0 = Math.floor(tx(e.box[0], n)); x1 = Math.floor(tx(e.box[2], n));
      y0 = Math.floor(ty(e.box[3], n)); y1 = Math.floor(ty(e.box[1], n));
      if ((x1 - x0 + 1) * 256 <= 4096 && (y1 - y0 + 1) * 256 <= 4096) break;
    }
    var c = { pronta: false, box: [x0 / n, y0 / n, (x1 + 1) / n, (y1 + 1) / n] };
    var cv = document.createElement("canvas"), g = cv.getContext("2d");
    cv.width = (x1 - x0 + 1) * 256; cv.height = (y1 - y0 + 1) * 256;
    g.fillStyle = "#EDE8E1"; g.fillRect(0, 0, cv.width, cv.height);   // una tile persa e' fondo, non un buco
    var manca = (x1 - x0 + 1) * (y1 - y0 + 1), rotte = 0;
    var fine = function () {
      if (--manca > 0) return;
      if (rotte * 4 > cv.width / 256 * cv.height / 256) return;     // OSM irraggiungibile: resta il tetto pieno
      // ritaglio sul contorno (con i buchi), poi il velo del colore del municipio
      g.beginPath();
      poligoni(e.g).forEach(function (pol) { pol.forEach(function (r) {
        r.forEach(function (q, i) {
          var px = (tx(q[0], n) - x0) * 256, py = (ty(q[1], n) - y0) * 256;
          if (i) g.lineTo(px, py); else g.moveTo(px, py);
        });
        g.closePath();
      }); });
      g.globalCompositeOperation = "destination-in"; g.fill("evenodd");
      g.globalCompositeOperation = "source-atop"; g.globalAlpha = CARTA_VELO; g.fillStyle = col;
      g.fillRect(0, 0, cv.width, cv.height);
      c.canvas = cv; c.pronta = true;
      if (S && S.carta === c) lastra();
    };
    for (var x = x0; x <= x1; x++) for (var y = y0; y <= y1; y++) (function (x, y) {
      var im = new Image();
      im.crossOrigin = "anonymous";
      im.onload = function () { g.drawImage(im, (x - x0) * 256, (y - y0) * 256); fine(); };
      im.onerror = function () { rotte++; fine(); };
      im.src = TILE_URL.replace("{z}", zt).replace("{x}", x).replace("{y}", y);
    })(x, y);
    return c;
  }
  function strCarta() {
    var gl, prog, va, vao, buf, tex, caricata, loc = {};
    var VS = "uniform mat4 u_m; uniform float u_z; uniform vec4 u_box; attribute vec2 a_uv; varying vec2 v_uv;" +
      "void main() { v_uv = a_uv; gl_Position = u_m * vec4(mix(u_box.xy, u_box.zw, a_uv), u_z, 1.0); }";
    var FS = "precision mediump float; uniform sampler2D u_tex; varying vec2 v_uv;" +
      "void main() { vec4 c = texture2D(u_tex, v_uv); if (c.a < 0.01) discard; gl_FragColor = c; }";
    var sh = function (tipo, src) { var o = gl.createShader(tipo); gl.shaderSource(o, src); gl.compileShader(o); return o; };
    var collega = function () {
      gl.linkProgram(prog);
      if (gl.getProgramParameter(prog, gl.LINK_STATUS)) return;
      if (window.console) console.warn("Vista 3D: shader non collegato", gl.getProgramInfoLog(prog));
      gl.deleteProgram(prog); prog = null;
    };
    return {
      id: "focus-carta", type: "custom", renderingMode: "3d",
      onAdd: function (map, g) {
        gl = g; prog = gl.createProgram();
        gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
        collega();
        if (!prog) return;
        ["u_m", "u_z", "u_box", "u_tex"].forEach(function (k) { loc[k] = gl.getUniformLocation(prog, k); });
        loc.a_uv = gl.getAttribLocation(prog, "a_uv");
        // un vertex array tutto suo (WebGL2): disegnando con quello legato da MapLibre i suoi
        // attributi accesi facevano fallire il disegno (su desktop il piano non compariva)
        var ext = !gl.createVertexArray && gl.getExtension("OES_vertex_array_object");
        va = gl.createVertexArray ? { crea: function () { return gl.createVertexArray(); }, lega: function (v) { gl.bindVertexArray(v); }, ora: gl.VERTEX_ARRAY_BINDING }
          : ext ? { crea: function () { return ext.createVertexArrayOES(); }, lega: function (v) { ext.bindVertexArrayOES(v); }, ora: ext.VERTEX_ARRAY_BINDING_OES } : null;
        var prima = va && gl.getParameter(va.ora);
        if (va) { vao = va.crea(); va.lega(vao); }
        buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
        gl.enableVertexAttribArray(loc.a_uv);
        gl.vertexAttribPointer(loc.a_uv, 2, gl.FLOAT, false, 0, 0);
        if (va) va.lega(prima);
        tex = gl.createTexture();
      },
      render: function (g, m) {
        var c = S && S.carta;
        if (!prog || !c || !c.pronta || S.focusVis !== "visible" || !(S.focus && S.focus.forma)) return;
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, tex);
        if (caricata !== c) {
          caricata = c;
          gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, c.canvas);
          gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        }
        // un metro sopra la tessera (la lastra arriva a h + 0,5 ed e' gia' spenta, il bordo a
        // h + 3 resta sopra), in unita' mercatore alla latitudine del centro come le estrusioni
        var z = maplibregl.MercatorCoordinate.fromLngLat(S.map.getCenter(), S.focusH + 1).z;
        gl.useProgram(prog);
        gl.uniformMatrix4fv(loc.u_m, false, m);
        gl.uniform1f(loc.u_z, z);
        gl.uniform4f(loc.u_box, c.box[0], c.box[1], c.box[2], c.box[3]);
        gl.uniform1i(loc.u_tex, 0);
        if (!va) return;
        var prima = gl.getParameter(va.ora);
        va.lega(vao);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        va.lega(prima);
      }
    };
  }

  // ---------- velo ----------
  // Il velo senza sorgente GeoJSON: un rettangolo a tutto schermo del colore del velo, tranne
  // dentro il buco (stencil pari/dispari dei contorni esterni, a ventaglio). Come sorgente
  // a ogni buco nuovo MapLibre buttava le sue tessere: nei voli lunghi (zoom che scende e
  // risale) non c'erano ne' tessere ne' madri e restavano i pezzi della vista di prima, un
  // rettangolo scuro che scivolava. Ora il velo copre sempre tutto lo schermo e il buco
  // cambia nello stesso fotogramma.
  function strVelo(id) {
    var gl, prog, va, vao, quad, loc = {}, pronto = null;
    var VS = "uniform mat4 u_m; attribute vec2 a_pos; void main() { gl_Position = u_m * vec4(a_pos, 0.0, 1.0); }";
    var FS = "precision mediump float; uniform vec4 u_col; void main() { gl_FragColor = u_col; }";
    var sh = function (tipo, src) { var o = gl.createShader(tipo); gl.shaderSource(o, src); gl.compileShader(o); return o; };
    var collega = function () {
      gl.linkProgram(prog);
      if (gl.getProgramParameter(prog, gl.LINK_STATUS)) return;
      if (window.console) console.warn("Vista 3D: shader non collegato", gl.getProgramInfoLog(prog));
      gl.deleteProgram(prog); prog = null;
    };
    var I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
    var rgb = [1, 3, 5].map(function (i) { return parseInt(VELO.colore.substr(i, 2), 16) / 255; });
    // contorni esterni del buco in coordinate mercatore, relative al primo punto (float32
    // a zoom 16 sbaglierebbe di metri): l'origine entra nella matrice, calcolata in doppia
    var buco = function (g) {
      if (pronto && pronto.g === g) return pronto;
      if (pronto) gl.deleteBuffer(pronto.buf);
      var v = [], parti = [], o = null;
      poligoni(g).forEach(function (pol) {
        var r = pol[0], da = v.length / 2;
        r.forEach(function (q) {
          var mc = maplibregl.MercatorCoordinate.fromLngLat(q);
          if (!o) o = [mc.x, mc.y];
          v.push(mc.x - o[0], mc.y - o[1]);
        });
        parti.push([da, r.length]);
      });
      var buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(v), gl.STATIC_DRAW);
      pronto = { g: g, buf: buf, parti: parti, o: o || [0, 0] };
      return pronto;
    };
    var attributo = function (buf) {
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.enableVertexAttribArray(loc.a_pos);
      gl.vertexAttribPointer(loc.a_pos, 2, gl.FLOAT, false, 0, 0);
    };
    return {
      id: id, type: "custom", renderingMode: "2d",
      onAdd: function (map, g) {
        gl = g; prog = gl.createProgram();
        gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
        collega();
        if (!prog) return;
        loc.u_m = gl.getUniformLocation(prog, "u_m"); loc.u_col = gl.getUniformLocation(prog, "u_col");
        loc.a_pos = gl.getAttribLocation(prog, "a_pos");
        // un vertex array tutto suo, come la carta del tetto
        var ext = !gl.createVertexArray && gl.getExtension("OES_vertex_array_object");
        va = gl.createVertexArray ? { crea: function () { return gl.createVertexArray(); }, lega: function (v) { gl.bindVertexArray(v); }, ora: gl.VERTEX_ARRAY_BINDING }
          : ext ? { crea: function () { return ext.createVertexArrayOES(); }, lega: function (v) { ext.bindVertexArrayOES(v); }, ora: ext.VERTEX_ARRAY_BINDING_OES } : null;
        if (va) vao = va.crea();
        quad = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, quad);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      },
      render: function (g, m) {
        var a = S && S.veloOp[id];
        if (!prog || !a || a <= 0.001 || !va) return;
        var prima = gl.getParameter(va.ora);
        va.lega(vao);
        gl.useProgram(prog);
        gl.disable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE);
        var b = S.veloG[id];
        if (b) {
          // il buco nello stencil: ogni ventaglio inverte, dentro resta dispari
          var h = buco(b), o = h.o, mm = Array.prototype.slice.call(m);
          for (var i = 0; i < 4; i++) mm[12 + i] = m[i] * o[0] + m[4 + i] * o[1] + m[12 + i];
          gl.enable(gl.STENCIL_TEST); gl.stencilMask(0xFF);
          gl.clearStencil(0); gl.clear(gl.STENCIL_BUFFER_BIT);
          gl.colorMask(false, false, false, false);
          gl.stencilFunc(gl.ALWAYS, 0, 0xFF); gl.stencilOp(gl.KEEP, gl.KEEP, gl.INVERT);
          gl.uniformMatrix4fv(loc.u_m, false, mm);
          attributo(h.buf);
          h.parti.forEach(function (pt) { gl.drawArrays(gl.TRIANGLE_FAN, pt[0], pt[1]); });
          gl.colorMask(true, true, true, true);
          gl.stencilFunc(gl.EQUAL, 0, 0xFF); gl.stencilOp(gl.KEEP, gl.KEEP, gl.KEEP);
        } else gl.disable(gl.STENCIL_TEST);
        gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
        gl.uniformMatrix4fv(loc.u_m, false, I);
        gl.uniform4f(loc.u_col, rgb[0] * a, rgb[1] * a, rgb[2] * a, a);
        attributo(quad);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        if (b) {
          // stencil a zero e maschere di ritaglio di MapLibre da rifare: lo strato dopo
          // (mun-focus) e' della stessa sorgente di quello prima e le darebbe per buone
          gl.clear(gl.STENCIL_BUFFER_BIT);
          if (S.map.painter) S.map.painter.currentStencilSource = undefined;
        }
        va.lega(prima);
      }
    };
  }

  // ---------- quota: icone ed etichette sul piano della tessera ----------
  function urlSvg(svg) { return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg); }
  // Spostamento a schermo fra il punto a terra e lo stesso punto a `metri` di quota:
  // proiezione esatta della camera (pitch, prospettiva), punto per punto.
  function scostamento(ll, metri) {
    if (!metri) return [0, 0];
    var t = S.map.transform, mc = maplibregl.MercatorCoordinate.fromLngLat(ll);
    var a = t.coordinatePoint(mc, metri), b = t.coordinatePoint(mc, 0);
    return [Math.round(a.x - b.x), Math.round(a.y - b.y)];
  }
  function quotaServizi() { return S.livello === "area" ? (S.focusH || 0) + 3 : 0; }
  function quota() {
    if (!S) return;
    var qs = quotaServizi();
    (S.marcatori || []).forEach(function (m) { m.marker.setOffset(scostamento(m.ll, qs)); });
    // nella vista municipio ogni nome sta sul tetto della sua tessera (quota per tipo)
    (S.etichette || []).forEach(function (e) {
      var q = e.h ? e.h * (S.munK || 0) + 3 : S.quotaEtichette;
      e.el.setAttribute("data-quota", Math.round(q));
      e.marker.setOffset(scostamento(e.ll, q));
    });
  }

  // ---------- DOM sovrapposto ----------
  function creaDom(el) {
    var d = document.createElement("div");
    d.className = "v3d-ui";
    d.innerHTML =
      '<button type="button" class="v3d-reset" hidden>&#8592;&nbsp; Vista d\'insieme</button>' +
      '<div class="v3d-cartiglio v3d-out" aria-live="polite">' +
        '<div class="v3d-nome"></div><div class="v3d-meta"></div>' +
      '</div>' +
      // stesse classi del tooltip dei servizi della 2D (stile e freccia identici)
      '<div class="v3d-popup leaflet-tooltip servizio-tooltip leaflet-tooltip-top" role="status" hidden></div>';
    el.appendChild(d);
    S.ui = {
      reset: d.querySelector(".v3d-reset"), cart: d.querySelector(".v3d-cartiglio"),
      nome: d.querySelector(".v3d-nome"), meta: d.querySelector(".v3d-meta"), popup: d.querySelector(".v3d-popup")
    };
    // le voci dell'elenco di un grappolo (zoom massimo) aprono la scheda di quel servizio
    S.ui.popup.addEventListener("click", function (ev) {
      var b = ev.target.closest && ev.target.closest(".st-voce"), v = b && S.vociPopup && S.vociPopup[parseInt(b.getAttribute("data-i"), 10)];
      if (!v) return;
      ev.stopPropagation();
      chiudiPopup();
      S.opt.schedaServizio(v.p.props, v.p.latlng, v.el);
    });
    S.ui.reset.addEventListener("click", function () { scegli({ tipo: "roma" }); });
  }

  // Il cartiglio (piccolo: nome e una riga di dati) non si ricrea: cambia il testo dentro
  // gli stessi elementi, con una dissolvenza breve solo se il nome cambia davvero.
  function cartiglio(nome, meta, medio) {
    var u = S.ui, gen = S.gen;
    var cambia = u.nome.textContent !== nome || u.cart.hidden;
    if (cambia) u.cart.classList.add("v3d-out");
    dopo(cambia && !S.opt.riduciMovimento ? 300 : 0, function () {
      if (S.gen !== gen) return;
      u.cart.hidden = false;
      u.meta.innerHTML = meta;
      if (cambia) { u.nome.textContent = nome; u.nome.classList.toggle("v3d-nome-medio", !!medio); }
      adattaNome();
      // un fotogramma a v3d-out dopo hidden = false, cosi' la dissolvenza in entrata parte
      requestAnimationFrame(function () { if (S && S.gen === gen) u.cart.classList.remove("v3d-out"); });
    });
  }
  // Nell'area il cartiglio sparisce (c'e' la scheda della 2D): dissolvenza, poi via.
  function nascondiCartiglio() {
    var u = S.ui, gen = S.gen;
    u.cart.classList.add("v3d-out");
    dopo(S.opt.riduciMovimento ? 0 : 300, function () { if (S.gen === gen) u.cart.hidden = true; });
  }

  // Nome su due righe al massimo, sempre (a 32 px al massimo): si parte dalla misura del CSS e si
  // scende finche' il testo, bilanciato, sta in due righe.
  function adattaNome() {
    var el = S && S.ui && S.ui.nome;
    if (!el || !el.textContent) return;
    el.style.fontSize = "";
    var cs = getComputedStyle(el), size = parseFloat(cs.fontSize), minimo = 18;
    var righe = function () { var lh = parseFloat(getComputedStyle(el).lineHeight) || size * 0.95; return Math.round(el.scrollHeight / lh); };
    while (righe() > 2 && size > minimo) { size -= 2; el.style.fontSize = size + "px"; }
  }

  // Popup dei servizi: stesso contenuto del tooltip della 2D (nome, "prevista", categoria),
  // appoggiato sopra l'icona.
  function testoServizio(p) {
    var nome = (p.nome === singolare(p.cat) && p.ind) ? p.ind : p.nome;
    return esc(nome) + (p.prevista ? " (prevista)" : "") + '<span class="st-cat">' + esc(singolare(p.cat)) + "</span>";
  }
  function popup(el, html, elenco) {
    var p = S.ui.popup, r = el.getBoundingClientRect(), b = S.el.getBoundingClientRect();
    p.innerHTML = html; p.hidden = false;
    p.classList.toggle("servizio-elenco", !!elenco);
    var w = S.el.clientWidth, x = r.left + r.width / 2 - b.left;
    // come la 2D (scegliServizio): l'icona scelta resta accesa, le altre si spengono
    S.el.querySelectorAll(".attiva").forEach(function (x) { x.classList.remove("attiva"); });
    el.classList.add("attiva");
    S.el.classList.add("servizi-scelta");
    p.style.left = Math.max(110, Math.min(w - 110, x)) + "px";
    p.style.top = (r.top - b.top + (elenco ? 0 : r.height * 0.15)) + "px";
  }
  function chiudiPopup() {
    if (!S || !S.ui) return;
    if (S.opt.chiudiScheda) S.opt.chiudiScheda();
    S.ui.popup.hidden = true;
    S.el.classList.remove("servizi-scelta");
    S.el.querySelectorAll(".attiva").forEach(function (x) { x.classList.remove("attiva"); });
  }

  // ---------- focus ----------
  function altezzaFocus(h) {
    var map = S.map;
    S.focusH = h;
    map.setPaintProperty("focus-wall", "fill-extrusion-height", h);
    map.setPaintProperty("focus-top", "fill-extrusion-base", Math.max(0, h - 2));
    map.setPaintProperty("focus-top", "fill-extrusion-height", h > 0 ? h + 0.5 : 0);
    map.setPaintProperty("focus-bordo", "fill-extrusion-base", Math.max(0, h - 1));
    map.setPaintProperty("focus-bordo", "fill-extrusion-height", h > 0 ? h + 3 : 0);
    // A terra la tessera non si disegna: tetto e pareti starebbero alla quota delle tessere
    // di sfondo e i due colori si contenderebbero i pixel (il glitch fra una zona e l'altra).
    // Con un'area caricata e ancora a terra gli strati restano accesi a opacita' 0 (non si
    // disegnano): uno strato a visibility none ferma la sua sorgente, e la forma nuova
    // arrivava solo al primo fotogramma visibile, quando la crescita era gia' partita.
    var vis = h >= 2 ? "visible" : (S.focus ? "spento" : "none");
    if (S.focusVis !== vis) {
      S.focusVis = vis;
      ["focus-wall", "focus-top", "focus-bordo"].forEach(function (id) {
        map.setLayoutProperty(id, "visibility", vis === "none" ? "none" : "visible");
        map.setPaintProperty(id, "fill-extrusion-opacity", vis === "visible" ? 1 : 0);
      });
      S.lastraO = vis === "visible" ? 1 : 0;
      lastra();
    }
    if (S.marcatori && S.marcatori.length) quota();
  }
  // La lastra colorata del tetto: piena finche' la carta non e' pronta, poi a opacita' 0
  // (resta per i tocchi): due superfici a mezzo metro si contendevano la profondita' e da
  // lontano vinceva la lastra, a chiazze.
  function lastra() {
    if (S.focusVis !== "visible") return;
    var o = S.carta && S.carta.pronta ? 0 : 1;
    if (S.lastraO !== o) { S.lastraO = o; S.map.setPaintProperty("focus-top", "fill-extrusion-opacity", o); }
  }
  // La tessera del focus scende prima di cambiare forma: mai una geometria nuova con le
  // pareti di quella vecchia.
  function abbassaFocus(fine, durata) {
    var da = S.focusH || 0;
    if (!S.focus || da <= 0) { if (fine) fine(); return; }
    tween("focus", durata || 450, function (k) { altezzaFocus(da * (1 - k)); }, fine);
  }
  // A tessera cresciuta e camera arrivata la parete a vista resta quella dell'arrivo a ogni
  // zoom: con l'altezza fissa in metri, avvicinandosi (tocco su un grappolo, rotella, dita)
  // il tetto cresceva sullo schermo fino a superare la camera, che finiva dentro la tessera.
  // Durante il volo d'arrivo l'altezza resta quella calcolata per la camera d'arrivo.
  function seguiZoom() {
    if (S.livello !== "area" || !S.focus || !S.focus.su || S.tween.focus || S.zoomArrivo != null) return;
    altezzaFocus(altezzaArea(cache.byCode[S.focus.codice], S.map.getZoom()));
  }
  // se lo zoom non e' quello previsto (un gesto in volo) la tessera si adegua in un attimo
  function adeguaFocus(fine) {
    if (S.livello !== "area" || !S.focus || !S.focus.su || S.tween.focus) { if (fine) fine(); return; }
    var da = S.focusH, a = altezzaArea(cache.byCode[S.focus.codice], S.map.getZoom());
    if (Math.abs(a - da) < 1) { if (fine) fine(); return; }
    tween("focus", 250, function (k) { altezzaFocus(da + (a - da) * k); }, fine);
  }
  // fine della crescita: da qui la tessera segue lo zoom
  function focusSu(fine) {
    S.focus.su = true;
    if (S.zoomArrivo != null) { if (fine) fine(); return; }
    adeguaFocus(fine);
  }
  function svuotaFocus() {
    var vuoto = { type: "FeatureCollection", features: [] };
    S.focus = null; S.carta = null;
    S.map.getSource("focus").setData(vuoto);
    S.map.getSource("focus-bordo").setData(vuoto);
    altezzaFocus(0);
  }

  // ---------- municipio alzato ----------
  // k (metri per unita' di hTipo) su ogni area caricata. Come altezzaFocus: sotto i 2 m
  // (misurati sulla piu' bassa, la zona funzionale) gli strati sono nascosti, mai
  // disegnati a terra sopra le tessere piatte.
  function altezzaMun(k) {
    var map = S.map;
    S.munK = k;
    S.munCodici.forEach(function (c) {
      // l'area scelta dal municipio passa alla tessera del focus, che parte dalla sua quota
      var kc = c === S.munFuori ? 0 : k;
      map.setFeatureState({ source: "mun", id: c }, { k: kc });
      map.setFeatureState({ source: "mun-bordo", id: c }, { k: kc });
    });
    var vis = k * H_TIPO_MIN >= 2 ? "visible" : "none";
    if (S.munVis !== vis) {
      S.munVis = vis;
      ["mun-ext", "mun-bordo"].forEach(function (id) { map.setLayoutProperty(id, "visibility", vis); });
    }
    if (S.etichette && S.etichette.length) quota();
  }
  function fermaMun() { if (S.tween.mun) { cancelAnimationFrame(S.tween.mun); S.tween.mun = null; } }
  // Il municipio scende prima di cambiare forma (o tipi): mai una sorgente nuova sopra 0.
  function abbassaMun(fine) {
    var da = S.munK || 0;
    if (da <= 0) { fermaMun(); if (fine) fine(); return; }
    tween("mun", 450, function (t) { altezzaMun(da * (1 - t)); }, fine);
  }
  // Solo a k 0 (strati nascosti): le aree del municipio m coi tipi accesi, e i loro bordi
  // larghi W metri (rifatti solo se cambia la larghezza).
  function caricaMun(m, W) {
    var col = colore(m), lin = scurisci(col, 0.62), ext = [], brd = [];
    altezzaMun(0);
    S.munCodici = []; S.munFuori = null;
    (cache.perMun[m] || []).forEach(function (k) {
      if (!tipoAttivo(k)) return;
      var e = cache.byCode[k], h = H_TIPO[e.p.tipo] || H_TIPO.QUARTIERE;
      if (!e.bordoMun || e.bordoMun.W !== W) e.bordoMun = { W: W, g: bordo(e.g, W) };
      S.munCodici.push(k);
      ext.push({ type: "Feature", properties: { codice: k, m: m, tipo: e.p.tipo, hTipo: h, col: col }, geometry: e.g });
      brd.push({ type: "Feature", properties: { codice: k, hTipo: h, col: lin }, geometry: e.bordoMun.g });
    });
    S.munM = m; S.munChiave = chiaveTipi(S.tipi);
    S.map.getSource("mun").setData({ type: "FeatureCollection", features: ext });
    S.map.getSource("mun-bordo").setData({ type: "FeatureCollection", features: brd });
    altezzaMun(0);
  }
  // Sale (o si adegua) fino a kt, col rimbalzo della tessera d'area.
  function alzaMun(kt, fine) {
    var da = S.munK || 0;
    tween("mun", da > 0 ? 600 : 1300, function (t) { altezzaMun(da + (kt - da) * t); }, fine, da > 0 ? ease : easeBack);
  }
  // Il municipio m alzato coi tipi accesi: se e' gia' quello caricato resta su e si
  // adegua, altrimenti scende, cambia e risale dopo `attesa` ms (la camera quasi arrivata).
  // Le etichette escono a crescita finita, ciascuna sulla sua tessera.
  // Ogni chiamata annulla quelle prima (munGen): un filtro cambiato in volo rifa' solo questo.
  // Si sale solo a sorgenti caricate (setData e' asincrono): a riposo l'attesa e' 0, e con
  // le tessere di prima ancora in memoria un tipo appena spento si sarebbe alzato per un
  // fotogramma.
  function municipioSu(m, attesa) {
    var mg = ++S.munGen, gen = S.gen, t0 = performance.now(), ist = S;
    var mio = function () { return S === ist && S.gen === gen && S.munGen === mg; };
    var sale = function () {
      if (!mio()) return;
      if (!(S.map.isSourceLoaded("mun") && S.map.isSourceLoaded("mun-bordo"))) { requestAnimationFrame(sale); return; }
      S.munFuori = null;
      alzaMun(S.munKt, function () {
        if (!mio()) return;
        mostraEtichette((cache.perMun[m] || []).filter(tipoAttivo), 0);
        segnaPronta("mun");
      });
    };
    if (S.munM === m && S.munChiave === chiaveTipi(S.tipi) && S.munK > 0) { sale(); return; }
    abbassaMun(function () {
      if (!mio()) return;
      caricaMun(m, S.munW);
      dopo(Math.max(0, attesa - (performance.now() - t0)), sale);
    });
  }

  // ---------- Roma in rilievo (l'ingresso di prima) ----------
  // Quota d'arrivo di un'area a livello Roma: per tipo, 0 se il tipo e' spento.
  function hRoma(k) { return tipoAttivo(k) ? (H_TIPO[cache.byCode[k].p.tipo] || H_TIPO.QUARTIERE) : 0; }
  function scriviRoma(alt) {
    var max = 0;
    Object.keys(alt).forEach(function (k) {
      var h = alt[k];
      if (S.romaH[k] !== h) { S.romaH[k] = h; S.map.setFeatureState({ source: "roma", id: k }, { h: h }); }
    });
    Object.keys(S.romaH).forEach(function (k) { if (S.romaH[k] > max) max = S.romaH[k]; });
    // sotto i 2 m non si disegna (mai tetti a terra sopra le aree piatte della 2D)
    var su = max >= 2;
    if (S.romaSu !== su) { S.romaSu = su; S.map.setPaintProperty("roma-ext", "fill-extrusion-opacity", su ? 0.9 : 0); }
  }
  // Dalla quota visibile ora (anche a meta' di un passaggio) a `arrivo` ({codice: metri},
  // assenti a 0). L'area in S.romaFermo resta dov'e': la tessera del focus la prende in consegna.
  function romaVerso(arrivo, durata, fine, curva) {
    var da = {}, uguale = true;
    Object.keys(cache.byCode).forEach(function (k) { da[k] = S.romaH[k] || 0; if (da[k] !== (arrivo[k] || 0)) uguale = false; });
    if (uguale) { if (S.tween.roma) { cancelAnimationFrame(S.tween.roma); S.tween.roma = null; } if (fine) fine(); return; }
    tween("roma", durata, function (t) {
      var alt = {};
      Object.keys(da).forEach(function (k) { if (k !== S.romaFermo) alt[k] = da[k] + ((arrivo[k] || 0) - da[k]) * t; });
      scriviRoma(alt);
    }, fine, curva);
  }
  function romaSu(durata, fine) {
    var alt = {};
    Object.keys(cache.byCode).forEach(function (k) { alt[k] = hRoma(k); });
    romaVerso(alt, durata, fine);
  }
  function romaGiu(durata) { romaVerso({}, durata == null ? 600 : durata); }

  // ---------- servizi ----------
  function dimensioneIcona(z) {
    var t = Math.max(0, Math.min(1, (z - 13) / 5)); // come la 2D: 13 -> 28 px, 18 -> 36 px
    return Math.round(SERVIZI_ICON_MIN + (SERVIZI_ICON_MAX - SERVIZI_ICON_MIN) * t);
  }
  // Id interni delle SVG univoci per istanza (come svgConIdUnici della 2D).
  var seqIcona = 0;
  function svgUnica(svg) {
    var suf = "-v" + (seqIcona++);
    return svg.replace(/id="([^"]+)"/g, function (m, id) { return 'id="' + id + suf + '"'; })
      .replace(/url\(#([^)]+)\)/g, function (m, id) { return "url(#" + id + suf + ")"; })
      .replace(/aria-labelledby="([^"]+)"/g, function (m, id) { return 'aria-labelledby="' + id + suf + '"'; });
  }
  function togliMarcatori() {
    (S.marcatori || []).forEach(function (m) { m.marker.remove(); });
    S.marcatori = [];
  }
  // Pixel dello schermo su cui si fanno i gruppi: durante il volo quelli della camera
  // d'arrivo (zoom, inclinazione, rotazione), a fermo quelli della camera corrente. Sulla
  // vista inclinata le distanze in verticale si accorciano: una griglia sulla mappa piatta
  // lasciava grappoli uno sopra l'altro.
  // Desktop (approvato cosi'): la griglia resta sulle coordinate del mondo allo zoom.
  function proiettore() {
    if (!S.opt.mobile) {
      var z = S.zoomArrivo != null ? S.zoomArrivo : S.map.getZoom(), mondo = 512 * Math.pow(2, z);
      return { su: function (ll) { var mc = maplibregl.MercatorCoordinate.fromLngLat([ll.lng, ll.lat]); return { x: mc.x * mondo, y: mc.y * mondo }; } };
    }
    var tr = S.map.transform, a = S.camArrivo;
    if (S.zoomArrivo != null && a && a.center) {
      tr = tr.clone();
      tr.center = maplibregl.LngLat.convert(a.center); tr.zoom = a.zoom; tr.bearing = a.bearing; tr.pitch = a.pitch;
    }
    return {
      su: function (ll) { return tr.locationPoint(new maplibregl.LngLat(ll.lng, ll.lat)); },
      giu: function (x, y) { var l = tr.pointLocation(new maplibregl.Point(x, y)); return [l.lng, l.lat]; }
    };
  }
  // Come raggruppaServizi della 2D (435946e4); su telefono sui pixel dello schermo. Desktop: celle di
  // 1,6 icone, grappolo da 2 punti in su, al baricentro. Telefono: celle di 1,15 icone;
  // una cella con 1 o 2 punti resta a icone (2 affiancate di mezza icona per parte); i
  // punti delle celle da 3 in su vanno in grappoli su una griglia di un grappolo piu' 4 px,
  // al centro della sua cella: due grappoli non si toccano mai.
  function raggruppa(punti, dim) {
    var pr = proiettore(), mobile = S.opt.mobile, lato = dim * (mobile ? 1.15 : 1.6), celle = {}, chiavi = [];
    punti.forEach(function (p) {
      var pt = pr.su(p.latlng), k = Math.round(pt.x / lato) + "_" + Math.round(pt.y / lato);
      if (!celle[k]) { celle[k] = { punti: [], pt: [] }; chiavi.push(k); }
      celle[k].punti.push(p); celle[k].pt.push(pt);
    });
    var grappoli = [], icone = [], densi = [];
    chiavi.forEach(function (k) {
      var c = celle[k], n = c.punti.length;
      if (!mobile) {
        if (n === 1) icone.push({ punto: c.punti[0], pos: null });
        else grappoli.push({ punti: c.punti, pos: null });
      } else if (n >= 3) {
        c.punti.forEach(function (p, i) { densi.push({ p: p, pt: c.pt[i] }); });
      } else if (n === 2) {
        var cx = (c.pt[0].x + c.pt[1].x) / 2, cy = (c.pt[0].y + c.pt[1].y) / 2;
        c.punti.forEach(function (p, i) { icone.push({ punto: p, pos: pr.giu(cx + (i ? 1 : -1) * dim * 0.5, cy) }); });
      } else icone.push({ punto: c.punti[0], pos: null });
    });
    if (densi.length) {
      var largo = Math.max(dim, 30) + 4, celleG = {}, chiaviG = [];
      densi.forEach(function (d) {
        var gx = Math.floor(d.pt.x / largo), gy = Math.floor(d.pt.y / largo), k = gx + "_" + gy;
        if (!celleG[k]) { celleG[k] = { punti: [], gx: gx, gy: gy }; chiaviG.push(k); }
        celleG[k].punti.push(d.p);
      });
      chiaviG.forEach(function (k) {
        var c = celleG[k];
        if (c.punti.length >= 3) grappoli.push({ punti: c.punti, pos: pr.giu((c.gx + 0.5) * largo, (c.gy + 0.5) * largo) });
        else c.punti.forEach(function (p) { icone.push({ punto: p, pos: null }); });
      });
    }
    return { grappoli: grappoli, icone: icone };
  }
  // Allo zoom d'arrivo durante il volo; si rifanno solo quando cambia lo zoom.
  function disegnaServizi(conBalzo) {
    togliMarcatori();
    if (S.modoServizi === "municipio") { contaNelleEtichette(); return 0; }
    var icone = S.opt.icone || {};
    var punti = (S.puntiFocus || []).filter(function (s) { return S.opt.attive[s.props.categoria] && icone[s.props.categoria]; });
    if (!punti.length) return 0;
    var z = S.zoomArrivo != null ? S.zoomArrivo : S.map.getZoom(), dim = dimensioneIcona(z);
    var gruppi = raggruppa(punti, dim);
    var voci = gruppi.icone.map(function (i) { return { g: [i.punto], pos: i.pos }; })
      .concat(gruppi.grappoli.map(function (c) { return { g: c.punti, pos: c.pos }; }));
    var animo = conBalzo && !S.opt.riduciMovimento;
    voci.forEach(function (v, idx) {
      // involucro per il Marker (MapLibre lo posiziona con transform), dentro l'elemento
      // della 2D, il cui balzo anima a sua volta transform
      var g = v.g, box = document.createElement("div"), el = document.createElement("div"), ll, ancora, d;
      box.className = "v3d-servizio";
      box.appendChild(el);
      // stessa cascata della 2D (ritardoBalzo nel template): 30 ms l'uno, al massimo 450
      var ritardo = animo ? "animation-delay:" + Math.min(idx * 30, 450) + "ms;" : "";
      if (g.length === 1) {
        var s = g[0];
        ll = v.pos || [s.latlng.lng, s.latlng.lat]; ancora = "bottom";
        el.className = "servizio-marker" + (animo ? " servizio-balzo" : "") + (s.props.prevista ? " servizio-prevista" : "");
        el.setAttribute("style", "width:" + dim + "px;height:" + dim + "px;" + ritardo);
        el.setAttribute("data-categoria", s.props.categoria);
        el.innerHTML = svgUnica(icone[s.props.categoria]);
        el.addEventListener("click", function (ev) {
          ev.stopPropagation();
          if (S.opt.schedaServizio) { chiudiPopup(); S.opt.schedaServizio(s.props, s.latlng, el); return; }
          popup(el, testoServizio({ nome: s.props.nome, ind: s.props.indirizzo, prevista: s.props.prevista, cat: s.props.categoria }), false);
        });
      } else {
        var lat = 0, lng = 0;
        g.forEach(function (p) { lat += p.latlng.lat; lng += p.latlng.lng; });
        ll = v.pos || [lng / g.length, lat / g.length]; ancora = "center"; d = Math.max(dim, 30);
        el.className = "servizio-cluster" + (animo ? " servizio-balzo" : "");
        el.setAttribute("style", "width:" + d + "px;height:" + d + "px;" + ritardo);
        // la cartella della 2D (htmlGrappolo), col pallino del numero; senza, il numero solo
        if (S.opt.grappolo) el.innerHTML = S.opt.grappolo(g); else el.textContent = g.length;
        el.addEventListener("click", function (ev) {
          ev.stopPropagation();
          // come la 2D: si avvicina di 2 livelli; allo zoom massimo l'elenco
          if (S.map.getZoom() < S.map.getMaxZoom() - 0.5) {
            // al centro va il grappolo sul tetto, non il suo punto a terra (la tessera segue
            // lo zoom: la parete a vista resta la stessa, e con lei lo scostamento)
            var su = scostamento(ll, quotaServizi());
            S.map.easeTo({ center: ll, offset: [-su[0], -su[1]], zoom: Math.min(S.map.getMaxZoom(), S.map.getZoom() + 2), duration: S.opt.riduciMovimento ? 0 : 600 });
          } else {
            var conScheda = !!S.opt.schedaServizio;
            S.vociPopup = conScheda ? g.slice(0, 12).map(function (p) { return { p: p, el: el }; }) : null;
            popup(el, g.slice(0, 12).map(function (p, i) {
              var t = testoServizio({ nome: p.props.nome, ind: p.props.indirizzo, prevista: p.props.prevista, cat: p.props.categoria });
              return conScheda ? '<button type="button" class="st-voce" data-i="' + i + '">' + t + "</button>" : t;
            })
              .join('<span class="st-sep"></span>') + (g.length > 12 ? '<span class="st-cat">e altri ' + (g.length - 12) + "</span>" : ""), true);
          }
        });
      }
      var marker = new maplibregl.Marker({ element: box, anchor: ancora }).setLngLat(ll).addTo(S.map);
      S.marcatori.push({ marker: marker, el: el, ll: ll });
    });
    S.zoomDisegno = Math.round(z * 4) / 4;
    quota();
    return punti.length;
  }
  function togliServizi() {
    S.puntiFocus = null;
    togliMarcatori();
  }
  function conServizi(filtro, fn) {
    var gen = S.gen, mio = S;
    // la promessa unica dei dati della 2D (anche se l'ha avviata la precarica in idle)
    Promise.resolve(S.opt.servizi ? S.opt.servizi() : null).then(function (dati) {
      if (S !== mio || S.gen !== gen) return;
      if (!dati) { segnaPronta("servizi"); return; }
      fn(dati.filter(filtro));
    }).catch(function () { if (S === mio) segnaPronta("servizi"); });
  }
  function mostraServizi(punti, modo) {
    S.modoServizi = modo;
    S.puntiFocus = punti;
    disegnaServizi(true);
    // pronta a balzo finito (0,3 s piu' lo sfalsamento massimo di 180 ms, come la 2D)
    dopo(modo === "municipio" ? 0 : 500, function () { segnaPronta("servizi"); disponiEtichette(); });
  }
  // Ridisegno quando cambia lo zoom (come la 2D): misura e gruppi seguono la scala.
  function zoomCambiato() {
    if (!S.marcatori || !S.marcatori.length || S.zoomArrivo != null) return;
    if (Math.round(S.map.getZoom() * 4) / 4 !== S.zoomDisegno) disegnaServizi(false);
  }

  // ---------- etichette delle aree (vista municipio) ----------
  // Stessa pillola delle etichette della 2D (.area-label), sulla tessera; se due si
  // toccano resta la piu' grande.
  function togliEtichette() {
    (S.etichette || []).forEach(function (e) { e.marker.remove(); });
    S.etichette = [];
  }
  function mostraEtichette(codici, quotaM) {
    togliEtichette();
    S.quotaEtichette = quotaM || 0;
    S.etichette = codici.map(function (k) {
      var e = cache.byCode[k], el = document.createElement("div");
      el.className = "area-label v3d-etichetta" + (S.livello === "municipio" ? " v3d-cliccabile" : "");
      el.setAttribute("data-tipo", e.p.tipo || "");
      el.setAttribute("data-codice", k);
      // il numero dei servizi accesi nell'area: lo stesso disco amaranto dei grappoli
      el.innerHTML = "<span>" + esc(e.p.denominazione) + '<b class="v3d-conta" hidden></b></span>';
      if (S.livello === "municipio") el.firstChild.addEventListener("click", function (ev) { ev.stopPropagation(); scegli({ tipo: "area", codice: k }); });
      var centro = e.centro || (e.centro = puntoInterno(e.g));
      var marker = new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat(centro).addTo(S.map);
      return { k: k, el: el, marker: marker, ll: centro, sup: e.p.superficie_kmq || 0,
               h: S.livello === "municipio" ? (H_TIPO[e.p.tipo] || H_TIPO.QUARTIERE) : 0 };
    });
    quota();
    contaNelleEtichette();
  }
  function contaNelleEtichette() {
    if (!S.etichette || !S.etichette.length) return;
    var conte = {};
    if (S.modoServizi === "municipio") (S.puntiFocus || []).forEach(function (s) {
      if (S.opt.attive[s.props.categoria] && S.opt.icone && S.opt.icone[s.props.categoria]) conte[s.props.codice_area] = (conte[s.props.codice_area] || 0) + 1;
    });
    S.etichette.forEach(function (e) {
      var b = e.el.querySelector(".v3d-conta"), n = conte[e.k] || 0;
      b.hidden = !n; b.textContent = n ? numero(n) : "";
    });
    disponiEtichette();
  }
  // Un'etichetta non copre mai cartiglio, scheda, pulsanti, icone o grappoli dei servizi.
  function disponiEtichette() {
    if (!S || !S.etichette || !S.etichette.length) return;
    var prese = [], W = S.el.clientWidth, H = S.el.clientHeight, base0 = S.el.getBoundingClientRect();
    [S.ui.cart, S.ui.reset].forEach(function (el) {
      if (!el || el.hidden) return;
      var r = el.getBoundingClientRect();
      if (r.width) prese.push([r.left - base0.left, r.top - base0.top, r.right - base0.left, r.bottom - base0.top]);
    });
    // la scheda su telefono entra dal basso con una transizione: conta dove arriva
    var sch = schedaSopra();
    if (sch) prese.push([sch.offsetLeft, S.opt.mobile ? H - sch.offsetHeight : sch.offsetTop, sch.offsetLeft + sch.offsetWidth, H]);
    (S.marcatori || []).forEach(function (m) {
      var r = m.el.getBoundingClientRect();
      prese.push([r.left - base0.left, r.top - base0.top, r.right - base0.left, r.bottom - base0.top]);
    });
    S.etichette.slice().sort(function (a, b) { return b.sup - a.sup; }).forEach(function (e) {
      e.el.style.visibility = "";
      var r = e.el.firstChild.getBoundingClientRect(), base = S.el.getBoundingClientRect();
      var x0 = r.left - base.left, y0 = r.top - base.top, x1 = x0 + r.width, y1 = y0 + r.height;
      var fuori = x0 < 4 || y0 < 4 || x1 > W - 4 || y1 > H - 4;   // mai un'etichetta tagliata dal bordo
      var tocca = prese.some(function (q) { return x0 < q[2] + 4 && q[0] < x1 + 4 && y0 < q[3] + 2 && q[1] < y1 + 2; });
      if (fuori || tocca) e.el.style.visibility = "hidden"; else prese.push([x0, y0, x1, y1]);
    });
  }

  // Pronta quando sono finite tutte le parti del passaggio (tessere, focus, servizi).
  function segnaPronta(parte) {
    if (!S) return;
    if (parte) delete S.manca[parte];
    if (Object.keys(S.manca).length) return;
    S.pronta = true; S.el.setAttribute("data-stato", "pronta");
  }
  function segnaInVolo() { S.pronta = false; S.el.setAttribute("data-stato", "volo"); }

  // Aree vicine (coi tipi accesi): il loro riquadro tocca quello dell'area allargato del
  // 30% (15% per lato). Di qualunque municipio: ci si orienta come nella 2D.
  function vicineDi(codice) {
    var e = cache.byCode[codice];
    if (!e.vicine) {
      var b = e.box, dx = (b[2] - b[0]) * 0.15, dy = (b[3] - b[1]) * 0.15, x = [b[0] - dx, b[1] - dy, b[2] + dx, b[3] + dy];
      e.vicine = Object.keys(cache.byCode).filter(function (k) {
        var q = cache.byCode[k].box;
        return k !== codice && q[0] <= x[2] && q[2] >= x[0] && q[1] <= x[3] && q[3] >= x[1];
      });
    }
    return e.vicine.filter(tipoAttivo);
  }

  // ---------- applicazione di una selezione ----------
  function applica(sel, opz) {
    S.gen++;
    S.timer.forEach(clearTimeout); S.timer = [];
    S.sel = sel;
    S.romaFermo = null;
    if (S.focus) S.focus.su = false;
    segnaInVolo();
    chiudiPopup();
    togliServizi();
    togliEtichette();
    S.modoServizi = sel.tipo === "roma" ? null : sel.tipo;
    S.zoomArrivo = null;
    var c = cache, map = S.map, vis = {}, codes = Object.keys(c.byCode);
    S.ui.reset.hidden = sel.tipo === "roma";
    var m = sel.tipo === "roma" ? -1 : (sel.tipo === "municipio" ? sel.arabo : c.byCode[sel.codice].m);
    map.setPaintProperty("mun-focus", "line-opacity", ["case", ["==", ["get", "m"], m], 1, 0]);

    // fuori dall'area la tessera del focus scende: "pronta" la aspetta (con la visibilita'
    // gia' a posto, come dopo un tipo spento, le tessere sarebbero pronte subito)
    var giuFocus = sel.tipo !== "area" && S.focus;
    var focusGiu = function () {
      if (!giuFocus) return;
      S.manca.focus = 1;
      abbassaFocus(function () { svuotaFocus(); segnaPronta("focus"); });
    };
    // fuori dalla vista municipio il municipio alzato scende (la sorgente resta, a k 0)
    if (sel.tipo !== "municipio") abbassaMun();

    // come applicaFiltri della 2D: i tipi spenti spariscono a ogni livello, e nella vista
    // municipio anche le aree degli altri municipi
    codes.forEach(function (k) { vis[k] = tipoAttivo(k) && (sel.tipo !== "municipio" || c.byCode[k].m === m) ? 1 : 0; });

    if (sel.tipo === "roma") {
      S.livello = "roma";
      veloGiu();
      // L'ingresso di prima: dall'alto, piatta e col nord in alto, la camera si inclina e
      // ruota mentre le aree si alzano per tipo; tutta nello schermo sopra il cartiglio
      // (tetti compresi). Tornando da un municipio o da un'area si sale dopo la discesa
      // della loro tessera. Con `fermo` (la x della scheda) la camera resta
      // dov'e' e Roma resta a terra: il rilievo da vicino sarebbe un muro.
      var fermo = !!(opz && opz.fermo);
      var attesa = (giuFocus || S.munK > 0) ? 450 : 0;
      if (fermo) { S.map.stop(); S.manca = { tessere: 1 }; }
      else { cameraRoma(); S.manca = { tessere: 1, roma: 1 }; }
      focusGiu();
      visibilita(vis, 900, function () { segnaPronta("tessere"); });
      if (!fermo) dopo(attesa, function () { romaSu(ROMA_DURATA, function () { segnaPronta("roma"); }); });
      fuoriArea();
      cartiglio("Roma", "<b>15</b> municipi · <b>" + numero(codes.length) + "</b> aree · <b>" + esc(km2(c.kmqRoma)) + "</b>");
      return;
    }

    var rom = S.opt.romani[String(m)] || String(m);

    if (sel.tipo === "municipio") {
      S.livello = "municipio";
      fuoriArea();
      var kmq = 0, n = 0;
      codes.forEach(function (k) {
        var e = c.byCode[k];
        if (e.m === m) { kmq += e.p.superficie_kmq || 0; n++; }
      });
      // il fuori del municipio si scurisce col velo della 2D, le sue aree si alzano per tipo
      veloSu(c.munGeo[m], 1200);
      romaGiu();
      // tutto il municipio nello schermo, sopra il cartiglio (anche su desktop: con lo zoom
      // in piu' di prima i municipi lunghi uscivano dallo schermo)
      var zm = cameraMunicipio(m, pitchMunicipio(), 14);
      var mppM = 78271.5 * Math.cos((c.munBox[m][1] + c.munBox[m][3]) / 2 * Math.PI / 180) / Math.pow(2, zm);
      S.munKt = mppM * MUN_PARETE / H_TIPO.RIONE;          // MUN_PARETE px di altezza per il rione
      S.munW = Math.max(6, Math.round(mppM * 2.2));       // contorno di ~2 px sul tetto
      // come la 2D: i servizi escono nell'ultimo tratto (65%), non a passaggio finito
      S.manca = { tessere: 1, servizi: 1, mun: 1 };
      focusGiu();
      visibilita(vis, 2100, function () { segnaPronta("tessere"); });
      S.munFino = performance.now() + 1100;               // la camera e' quasi arrivata
      municipioSu(m, 1100);
      dopo(1365, function () {
        conServizi(function (p) { return p.props.municipio === rom; }, function (punti) { mostraServizi(punti, "municipio"); });
      });
      cartiglio("Municipio " + rom, "<b>" + n + "</b> aree · <b>" + esc(km2(kmq)) + "</b>", true);
      return;
    }

    // area
    S.livello = "area";
    var e = c.byCode[sel.codice], p = e.p, col = colore(m);
    // la scheda della 2D si riempie prima della camera: l'inquadratura ne conosce l'ingombro
    nascondiCartiglio();
    S.inArea = true;
    if (S.opt.onArea) S.opt.onArea(p);
    veloSu(e.g, 1200);
    // da Roma in rilievo: tutte scendono, tranne l'area scelta, che la tessera del focus
    // prende in consegna alla sua quota (come dal municipio alzato)
    if ((S.romaH[sel.codice] || 0) > 0) S.romaFermo = sel.codice;
    romaGiu();
    // la tessera intera (piede e tetto) nello spazio libero, sopra il cartiglio: anche le
    // aree lunghe e strette, che cameraForBounds sull'inclinata tagliava
    var z = inquadra(e.g, e.box, pitchFocus(), 16.2, 12, function (zz) { return altezzaArea(e, zz); });
    S.zoomArrivo = S.opt.riduciMovimento ? null : z;
    var mpp = mppA((e.box[1] + e.box[3]) / 2, z);
    var H = altezzaArea(e, z);
    var W = Math.max(2, mpp * 4.5);                     // bordo di ~4,5 px
    // la carta del tetto si carica subito, mentre la tessera di prima scende
    var carta = S.carta && S.focus && S.focus.codice === sel.codice ? S.carta : caricaCarta(e, col, z);
    S.manca = { focus: 1, servizi: 1 };
    visibilita(vis, 1500);
    var gen = S.gen;
    // i nomi delle aree vicine, di qualunque municipio come la 2D: escono a camera quasi
    // arrivata, anche quando la visibilita' non cambia (area -> area)
    dopo(1500, function () { if (S.sel === sel) mostraEtichette(vicineDi(sel.codice), 0); });
    var servizi = function () {
      conServizi(function (s) { return s.props.codice_area === sel.codice; }, function (punti) { mostraServizi(punti, "area"); });
    };
    // La tessera parte subito, mentre la camera vola (prima aspettava 900 ms fissi, piu' la
    // discesa di quella di prima: il tocco sembrava non arrivare). Da h0: 0, o la quota
    // della stessa area nel municipio alzato.
    var cresci = function (h0) {
      if (S.gen !== gen) return;
      tween("focus", 1400, function (k) { altezzaFocus(h0 + (H - h0) * k); }, function () { focusSu(function () { segnaPronta("focus"); }); }, easeBack);
      dopo(1200, servizi);
    };
    var t0 = performance.now();
    if (S.focus && S.focus.codice === sel.codice && S.focusH > 0) {
      // stessa area (es. tornando dall'elenco): la tessera resta su
      var da = S.focusH;
      S.focus.H = H;
      tween("focus", 600, function (k) { altezzaFocus(da + (H - da) * k); }, function () {
        focusSu(function () { segnaPronta("focus"); servizi(); });
      });
    } else {
      abbassaFocus(function () {
        if (S.gen !== gen) return;
        S.focus = { codice: sel.codice, H: H }; S.carta = carta; lastra();
        map.getSource("focus").setData({ type: "FeatureCollection", features: [{ type: "Feature", properties: { codice: sel.codice, col: col }, geometry: e.g }] });
        map.getSource("focus-bordo").setData({ type: "FeatureCollection", features: [{ type: "Feature", properties: { codice: sel.codice }, geometry: bordo(e.g, W) }] });
        altezzaFocus(0);
        // Si sale con la forma nuova nelle tessere della sorgente (setData e' asincrono): nei
        // voli lunghi (un'area lontana, su telefono) il worker la rifa' anche dopo 3 s, e
        // partendo a tempo fisso (900 ms) la carta restava sospesa senza pareti, poi la tessera
        // spuntava di colpo a meta' altezza. Un'area fuori schermo parte quando la camera la
        // raggiunge. Le tessere ancora da rifare tengono la forma di prima: si aspetta solo se
        // quell'area e' nell'inquadratura (salirebbe lei); fuori, MapLibre le rifa' per ultime.
        var inVista = function (k) {
          var e = cache.byCode[k], v = map.getBounds(), mx = (v.getEast() - v.getWest()) * 0.2, my = (v.getNorth() - v.getSouth()) * 0.2;
          return !e || !(e.box[2] < v.getWest() - mx || e.box[0] > v.getEast() + mx || e.box[3] < v.getSouth() - my || e.box[1] > v.getNorth() + my);
        };
        var nuova = function (id) {
          var fs = map.querySourceFeatures(id), c;
          return fs.some(function (f) { return f.properties.codice === sel.codice; }) &&
            fs.every(function (f) { c = f.properties.codice; return c === sel.codice || !inVista(c); });
        };
        var focus = S.focus;
        var forma = function () { return nuova("focus") && nuova("focus-bordo"); };
        var dalMun = S.munK > 0 && S.munCodici.indexOf(sel.codice) >= 0;
        var parti = function () {
          if (S.gen !== gen) return;
          if (!forma() && performance.now() - t0 < ATTESA_FORMA) { requestAnimationFrame(parti); return; }
          // ripiego oltre ATTESA_FORMA: si sale, la carta aspetta le pareti (strCarta)
          focus.forma = forma();
          if (!focus.forma) (function guarda() {
            if (S.focus !== focus) return;
            if (forma()) { focus.forma = true; map.triggerRepaint(); } else requestAnimationFrame(guarda);
          })();
          var h0 = 0;
          if (S.romaFermo === sel.codice) {
            // nello stesso fotogramma la sua tessera di Roma sparisce e il focus prende il posto
            h0 = S.romaH[sel.codice] || 0;
            var zero = {}; zero[sel.codice] = 0; scriviRoma(zero);
          } else if (dalMun && S.munK > 0) {
            // nello stesso fotogramma la sua tessera del municipio sparisce e il focus prende il posto
            h0 = (H_TIPO[p.tipo] || H_TIPO.QUARTIERE) * S.munK;
            S.munFuori = sel.codice; altezzaMun(S.munK);
          }
          cresci(h0);
        };
        parti();
      }, 250);
    }
  }
  // Uscita dal livello area: la scheda della 2D se ne va.
  function fuoriArea() {
    if (!S.inArea) return;
    S.inArea = false;
    if (S.opt.onArea) S.opt.onArea(null);
  }

  // Filtri per tipo cambiati nella 2D (pulsanti Rioni, Quartieri, Zone funzionali). Cambia
  // solo cio' che dipende dai tipi, ferma o in volo: la visibilita' delle aree, le etichette
  // e, nella vista municipio, le tessere alzate (scendono, cambiano, risalgono). Camera,
  // focus e servizi non si toccano: in volo continuano il loro passaggio.
  function filtraTipi(attivi) {
    if (!S) return;
    var nuovi = copiaTipi(attivi);
    if (chiaveTipi(nuovi) === chiaveTipi(S.tipi)) return;
    S.tipi = nuovi;
    if (!S.map || !S.map.getLayer("aree-fill") || !S.sel) return;   // la prima selezione li legge
    var sel = S.sel, c = cache, vis = {};
    var m = sel.tipo === "municipio" ? sel.arabo : (sel.tipo === "area" ? c.byCode[sel.codice].m : -1);
    Object.keys(c.byCode).forEach(function (k) { vis[k] = tipoAttivo(k) && (sel.tipo !== "municipio" || c.byCode[k].m === m) ? 1 : 0; });
    // a riposo si riapre un passaggio breve; in volo le parti ancora in corso restano in
    // S.manca e si aggiungono quelle rifatte qui (la fine della visibilita' di prima e
    // l'eventuale crescita del municipio sono sostituite da queste)
    if (S.pronta) { segnaInVolo(); S.manca = {}; }
    togliEtichette();
    S.manca.tessere = 1;
    if (sel.tipo === "municipio") { S.manca.mun = 1; municipioSu(m, Math.max(0, (S.munFino || 0) - performance.now())); }
    if (sel.tipo === "roma") { S.manca.roma = 1; romaSu(500, function () { segnaPronta("roma"); }); }
    visibilita(vis, 500, function () {
      if (sel.tipo === "area" && S.sel === sel) mostraEtichette(vicineDi(sel.codice), 0);
      segnaPronta("tessere");
    });
  }

  // Caselle del pannello Servizi della 2D cambiate (opt.attive e' lo stesso oggetto): si
  // ridisegnano i servizi gia' caricati, senza balzo; in volo li rifa' l'arrivo.
  function attiveCambiate() {
    if (!S || !S.map || !S.puntiFocus) return;
    chiudiPopup();
    disegnaServizi(false);
  }

  // Scelta fatta dentro la 3D: si applica e si comunica alla 2D.
  function scegli(sel) {
    applica(sel);
    if (S.opt.onSeleziona) S.opt.onSeleziona(sel);
  }

  // Toccabile solo cio' che si vede: tipo acceso e area non spenta dal livello (nel
  // municipio le aree degli altri municipi sono a vis 0, inerti come nella 2D).
  function toccabile(k) { return !!k && tipoAttivo(k) && !!S.st[k] && S.st[k].vis === 1; }
  // Strati toccabili: a Roma anche le tessere in rilievo (il tocco cade sul tetto visto).
  function strati() {
    return (S.romaSu ? ["roma-ext"] : []).concat(["focus-top", "focus-wall", "mun-ext", "aree-fill", "aree-retino"]);
  }
  function suClick(ev) {
    var map = S.map;
    chiudiPopup();
    var f = map.queryRenderedFeatures(ev.point, { layers: strati() })
      .filter(function (x) { return x.properties && toccabile(x.properties.codice); })[0];
    if (!f) return;
    var e = cache.byCode[f.properties.codice];
    if (!e) return;
    // a Roma, come la 2D, il tocco entra direttamente nell'area
    if (!(S.livello === "area" && S.sel.codice === f.properties.codice)) scegli({ tipo: "area", codice: f.properties.codice });
  }

  function valida(sel) {
    if (sel && sel.tipo === "area" && cache.byCode[sel.codice]) return { tipo: "area", codice: sel.codice };
    if (sel && sel.tipo === "municipio" && cache.munBox[sel.arabo]) return { tipo: "municipio", arabo: sel.arabo };
    return { tipo: "roma" };
  }

  // definitivo=false: l'errore e' di questo tentativo, il tasto 3D resta (si puo' riprovare)
  function errore(msg, definitivo) {
    var cb = S && S.opt.onErrore;
    chiudi();
    if (cb) cb(msg, definitivo !== false);
  }

  // ---------- API ----------
  function supportato() {
    try {
      var c = document.createElement("canvas");
      var gl = window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl"));
      if (!gl) return false;
      var lose = gl.getExtension("WEBGL_lose_context");
      if (lose) lose.loseContext();
      return true;
    } catch (e) { return false; }
  }

  function apri(opt) {
    if (S) chiudi();
    var c = prepara(opt);
    S = { opt: opt, el: opt.contenitore, reg: registro(opt), gen: 0, timer: [], tween: {}, st: {}, t: 1, sel: null, livello: "",
          pronta: false, map: null, ui: null, puntiFocus: null, focus: null, focusH: 0, etichette: [], marcatori: [], zoomArrivo: null,
          tipi: copiaTipi(opt.tipiAttivi), munK: 0, munM: null, munCodici: [], munChiave: "", munKt: 0, munW: 10, munGen: 0, munFino: 0,
          romaH: {}, romaSu: false, romaFermo: null, veloOp: {}, veloG: {}, veloSalti: 0 };
    S.el.classList.add("v3d");
    S.el.setAttribute("data-stato", "carico");
    // Un div nuovo per ogni apertura: MapLibre lega listener al suo contenitore e non tutti
    // si tolgono con map.remove(); cosi' contenitore e mappa vecchia si liberano insieme.
    var elMappa = document.createElement("div");
    elMappa.className = "v3d-mappa";
    S.el.appendChild(elMappa);
    try {
      S.map = creaMappa(elMappa, c);
    } catch (e) {
      errore("La vista 3D non è disponibile su questo dispositivo.");
      return false;
    }
    creaDom(S.el);
    var mio = S;
    // Tile della base che non arrivano (rete, blocco): la 3D vive lo stesso, la base e'
    // solo contesto; si contano e si segnano sul contenitore. Ogni altro errore resta in console.
    S.erroriBase = 0;
    S.map.on("error", function (ev) {
      if (S !== mio) return;
      if (ev && (ev.sourceId === "osm" || ev.tile)) { S.erroriBase++; S.el.setAttribute("data-base", "assente"); return; }
      if (window.console) console.error(ev && ev.error ? ev.error : ev);
    });
    S.map.on("webglcontextlost", function () { if (S === mio) errore("La vista 3D si è interrotta: torno alla mappa."); });
    S.map.on("click", function (ev) { if (S === mio) suClick(ev); });
    // Durante i movimenti le etichette si dissolvono (si ricalcolano a fermo)
    S.map.on("movestart", function () { if (S === mio) { chiudiPopup(); S.el.classList.add("v3d-in-moto"); } });
    S.map.on("move", function () { if (S === mio) quota(); });
    S.map.on("zoom", function () { if (S === mio) seguiZoom(); });
    S.map.on("zoomend", function () { if (S === mio) zoomCambiato(); });
    S.map.on("moveend", function () {
      if (S !== mio) return;
      // a volo finito i gruppi si rifanno allo zoom vero, se diverso da quello previsto
      if (S.zoomArrivo != null) { S.zoomArrivo = null; zoomCambiato(); adeguaFocus(); }
      disponiEtichette(); S.el.classList.remove("v3d-in-moto");
    });
    S.onResize = function () { if (S === mio) adattaNome(); };
    S.map.on("resize", function () {
      if (S !== mio || S.dimInquadra === S.map.transform.width + "x" + S.map.transform.height) return;
      S.timer.forEach(clearTimeout); S.timer = [setTimeout(riquadra, 250)];
    });
    window.addEventListener("resize", S.onResize);
    if (!opt.mobile) {
      S.map.on("mousemove", function (ev) {
        if (S !== mio || !S.map.getLayer("aree-fill")) return;
        var hit = S.map.queryRenderedFeatures(ev.point, { layers: strati() })
          .some(function (x) { return x.properties && toccabile(x.properties.codice); });
        S.map.getCanvas().style.cursor = hit ? "pointer" : "";
      });
    }
    // Layer e selezione appena lo stile e' pronto, senza aspettare le tile ("load"
    // aspetta anche la base raster: con OSM irraggiungibile la 3D restava vuota).
    function avvia() {
      if (S !== mio || S.avviata) return;
      S.avviata = true;
      aggiungiLayer(c);
      S.map.once("render", function () { if (S === mio) S.disegnata = true; });
      // Si parte dall'alto, piatti: la crescita e l'inclinazione sono l'ingresso.
      applica(valida(opt.selezione));
    }
    if (S.map.isStyleLoaded()) avvia(); else S.map.once("style.load", avvia);
    // Rete di sicurezza: se in 8 s non c'e' nemmeno un fotogramma con le tessere, si torna alla 2D.
    // Il conto parte solo a documento visibile: in una scheda di sfondo il browser sospende
    // i fotogrammi e la 3D non puo' disegnare.
    function armaGuardia() {
      clearTimeout(mio.guardia);
      if (document.hidden) return;
      mio.guardia = setTimeout(function () {
        if (S !== mio || (S.avviata && S.disegnata)) return;
        if (document.hidden) return;
        errore("La vista 3D non è partita: torno alla mappa.", false);
      }, 8000);
    }
    S.suVisibilita = function () { if (S === mio && !(S.avviata && S.disegnata)) armaGuardia(); };
    document.addEventListener("visibilitychange", S.suVisibilita);
    armaGuardia();
    return true;
  }

  function chiudi() {
    if (!S) return;
    var s = S;
    S = null;
    Object.keys(s.tween).forEach(function (k) { if (s.tween[k]) cancelAnimationFrame(s.tween[k]); });
    s.timer.forEach(clearTimeout);
    clearTimeout(s.guardia);
    if (s.suVisibilita) document.removeEventListener("visibilitychange", s.suVisibilita);
    if (s.onResize) window.removeEventListener("resize", s.onResize);
    (s.etichette || []).forEach(function (e) { try { e.marker.remove(); } catch (x) {} });
    try { if (s.map) s.map.remove(); } catch (e) {}
    s.el.innerHTML = "";
    s.el.classList.remove("v3d");
    s.el.removeAttribute("data-stato");
  }

  window.Vista3D = {
    supportato: supportato,
    apri: apri,
    chiudi: chiudi,
    // opz.fermo (solo Roma): si torna al livello Roma senza muovere la camera (la x della
    // scheda, come deseleziona della 2D che lascia la mappa dov'e')
    seleziona: function (sel, opz) { if (S && S.map && S.map.getLayer("aree-fill")) applica(valida(sel), opz); else if (S) S.opt.selezione = sel; },
    filtraTipi: filtraTipi,
    attiveCambiate: attiveCambiate,
    chiudiPopup: chiudiPopup,
    selezione: function () { return S ? S.sel : null; },
    mappa: function () { return S ? S.map : null; },   // per i test e le misure
    // per i test: opacita' dei due veli, buchi cambiati sotto un velo visibile e, dato un
    // punto [lon, lat], quale velo lo copre (fuori dal suo buco)
    velo: function (ll) {
      if (!S || !S.veloOp) return null;
      var copre = function (id) {
        var g = S.veloG[id];
        return !(ll && g && poligoni(g).some(function (pol) { return dentroAnello(ll[0], ll[1], pol[0]); }));
      };
      return { velo: opacita("velo"), vecchio: opacita("velo-vecchio"), salti: S.veloSalti,
               copre: ll ? { velo: copre("velo"), vecchio: copre("velo-vecchio") } : null };
    },
    // per i test: quante righe prende un nome nel cartiglio (lo rimette com'era)
    misuraNome: function (nome, medio) {
      if (!S || !S.ui) return null;
      var el = S.ui.nome, prima = el.textContent, primaMedio = el.classList.contains("v3d-nome-medio");
      el.textContent = medio ? nome : titolo(nome); el.classList.toggle("v3d-nome-medio", !!medio);
      adattaNome();
      var lh = parseFloat(getComputedStyle(el).lineHeight), r = { righe: Math.round(el.scrollHeight / lh), px: parseFloat(getComputedStyle(el).fontSize) };
      el.textContent = prima; el.classList.toggle("v3d-nome-medio", primaMedio); adattaNome();
      return r;
    },
    stato: function () { return { aperta: !!S, pronta: !!(S && S.pronta), livello: S ? S.livello : "", munK: S ? S.munK : 0 }; }
  };
})();
