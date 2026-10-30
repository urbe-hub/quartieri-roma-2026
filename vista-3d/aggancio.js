  // ======================================================================
  // Vista 3D (inlinato dal build dentro lo script della 2D, da vista-3d/aggancio.js).
  // Qui solo il tasto 2D/3D, il caricatore e il contratto con window.Vista3D: MapLibre
  // e il modulo (dist/3d/) si scaricano al primo "3D", mai al primo caricamento.
  // La 3D riceve i dati gia' decodificati e la selezione corrente; cio' che si sceglie
  // in 3D resta "pendente" e si applica alla 2D quando si torna in 2D.
  // Hash: #3d, #3d/<codice area>, #3d/municipio-<n> (convive con #<codice>, #via=, #15=).
  // Cronologia: entrare in 3D col tasto aggiunge UNA voce (pushState); le scelte dentro
  // la 3D la riscrivono (replaceState). "Indietro" e il tasto 2D tornano alla voce di
  // prima, quindi la 3D non crea voci doppie e "Indietro" non esce dal sito.
  (function () {
    var gruppoEl = document.getElementById("vista-dd");
    if (!gruppoEl) return;
    var btn2d = gruppoEl.querySelector('[data-vista="2d"]'), btn3d = gruppoEl.querySelector('[data-vista="3d"]');
    var contenitore = null, aperta = false, pendente = null, caricamento = null;
    var stiliAggiunti = false, giroApertura = 0;
    var compattoDa3D = false, ritornoApplica = false, q15Salvato = null, muni2D = "", areaServizi = null;
    // il livello da cui si e' entrati nell'area della 3D (municipio o Roma): la x della
    // scheda e un tipo spento ci tornano, come deseleziona della 2D col suo menu
    var origine = { tipo: "roma" };
    var HASH_3D = /^3d(?:\/(.+))?$/;

    function webglDisponibile() {
      try {
        var c = document.createElement("canvas");
        var gl = window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl"));
        if (!gl) return false;
        var lose = gl.getExtension("WEBGL_lose_context");
        if (lose) lose.loseContext();
        return true;
      } catch (e) { return false; }
    }
    // L'hash decodificato; un'escape malformata (link troncato) vale come hash vuoto.
    function leggiHash() {
      try { return decodeURIComponent((location.hash || "").replace(/^#/, "")); } catch (e) { return ""; }
    }
    function selDaHash() {
      var m = HASH_3D.exec(leggiHash());
      if (!m) return null;
      if (!m[1]) return { tipo: "roma" };
      var mm = /^municipio-(\d+)$/.exec(m[1]);
      if (mm) return { tipo: "municipio", arabo: parseInt(mm[1], 10) };
      return { tipo: "area", codice: m[1] };
    }
    function scriviHash(s, nuovaVoce) {
      var h = "#3d" + (s.tipo === "area" ? "/" + encodeURIComponent(s.codice) : (s.tipo === "municipio" ? "/municipio-" + s.arabo : ""));
      if (nuovaVoce && history.pushState) history.pushState({ v3d: true }, "", h);
      else if (history.replaceState) history.replaceState(history.state, "", h);
    }
    function pulisciHash() { if (history.replaceState) history.replaceState(null, "", location.pathname + location.search); }
    function hash2D() {
      if (!history.replaceState) return;
      if (selectedEntry) history.replaceState(null, "", "#" + encodeURIComponent(selectedEntry.feature.properties.codice || ""));
      else pulisciHash();
    }
    function voceNostra() { return !!(history.state && history.state.v3d); }
    function selezione2D() {
      if (selectedEntry) return { tipo: "area", codice: selectedEntry.feature.properties.codice };
      if (activeMunicipio) return { tipo: "municipio", arabo: parseInt(activeMunicipio, 10) };
      return { tipo: "roma" };
    }
    function segna(in3d) {
      btn2d.setAttribute("aria-pressed", String(!in3d));
      btn3d.setAttribute("aria-pressed", String(in3d));
    }

    // Prova pigra: al caricamento basta che il browser conosca WebGL (nessun contesto
    // creato); il contesto vero si prova al primo "3D".
    if (!window.WebGLRenderingContext) {
      gruppoEl.hidden = true;
      if (selDaHash()) { pulisciHash(); setTimeout(function () { avviso("La vista 3D non è disponibile su questo dispositivo: ecco la mappa."); }, 800); }
      return;
    }
    gruppoEl.hidden = false;
    var webglProvato = false;

    // Su telefono il tasto sta nella barra in alto sulla mappa, a destra della ricerca
    // (cornice del telefono); su desktop nella barra delle statistiche,
    // prima di "Cos'e'" (che collocaCornice, registrata prima, ha gia' riportato li').
    var aboutBtn = document.getElementById("about-btn"), mqTelefono = window.matchMedia(window.MAPPA_MQ_TELEFONO || "(max-width: 720px)");
    function collocaTasto() {
      if (mqTelefono.matches) { if (gruppoEl.parentNode.id !== "barra-mappa") document.getElementById("barra-mappa").appendChild(gruppoEl); }
      else if (gruppoEl.nextElementSibling !== aboutBtn) aboutBtn.parentNode.insertBefore(gruppoEl, aboutBtn);
    }
    collocaTasto();
    if (mqTelefono.addEventListener) mqTelefono.addEventListener("change", collocaTasto);
    else if (mqTelefono.addListener) mqTelefono.addListener(collocaTasto);

    // MapLibre e il modulo in parallelo, eseguiti in ordine (async=false).
    function carica() {
      if (caricamento) return caricamento;
      // i fogli di stile si aggiungono una volta sola, anche dopo un tentativo fallito
      if (!stiliAggiunti) {
        stiliAggiunti = true;
        ["3d/maplibre-gl.css", "3d/vista-3d.css"].forEach(function (href) {
          var l = document.createElement("link"); l.rel = "stylesheet"; l.href = conVersione(href, "3d"); document.head.appendChild(l);
        });
      }
      var ultimoMaplibre = null;
      caricamento = new Promise(function (ok, ko) {
        ["3d/maplibre-gl.js", "3d/vista-3d.js"].forEach(function (src, i) {
          if (i === 0 && window.maplibregl) return;
          if (i === 1 && window.Vista3D) {
            // modulo gia' presente: si aspetta solo MapLibre (se e' stato riaggiunto ora)
            if (window.maplibregl) ok();
            else if (ultimoMaplibre) ultimoMaplibre.onload = function () { if (window.maplibregl) ok(); else ko(); };
            return;
          }
          var s = document.createElement("script");
          s.src = conVersione(src, "3d"); s.async = false;
          s.onerror = function () { s.remove(); ko(); };
          if (i === 0) ultimoMaplibre = s;
          if (i === 1) s.onload = function () { if (window.Vista3D && window.maplibregl) ok(); else ko(); };
          document.head.appendChild(s);
        });
      });
      caricamento.catch(function () { caricamento = null; });
      return caricamento;
    }

    function fallisci(msg, definitivo) {
      chiudi3d(false, true);
      hash2D();
      if (definitivo) gruppoEl.hidden = true;
      avviso(msg);
    }

    // daTasto: aperta dal tasto 3D (nuova voce di cronologia); altrimenti da un link o
    // da avanti/indietro, e la voce c'e' gia'.
    function apri3d(sel, daTasto) {
      if (aperta) { if (sel && window.Vista3D) vola3d(sel); return; }
      if (presentazioneOn) return;
      if (!webglProvato) {
        webglProvato = true;
        if (!webglDisponibile()) {
          gruppoEl.hidden = true;
          if (selDaHash()) hash2D();
          avviso("La vista 3D non è disponibile su questo dispositivo.");
          return;
        }
      }
      if (tourAttivo()) chiudiTour();
      chiudiSchedaServizio();
      // 15 minuti accesi: si chiudono e tornano, sullo stesso punto, al ritorno in 2D.
      q15Salvato = null;
      if (q15 && q15.attivo) {
        var m15 = /^15=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/.exec(leggiHash());
        if (m15 && !(isFinite(parseFloat(m15[1])) && isFinite(parseFloat(m15[2])))) m15 = null;
        q15Salvato = m15 ? L.latLng(parseFloat(m15[1]), parseFloat(m15[2])) : (q15.marker ? q15.marker.getLatLng() : true);
        q15Disattiva();
        if (m15 && history.replaceState) history.replaceState(history.state, "", "#15=" + m15[1] + "," + m15[2]);
      }
      aperta = true; segna(true);
      // il municipio che la 2D mostra davvero: il menu segue la 3D, la 2D no (applicaA2D)
      muni2D = activeMunicipio || "";
      var in2d = selezione2D();
      sel = sel || in2d;
      // un hash #3d/<...> che non porta a nulla si legge come Roma, e l'URL si corregge
      if ((sel.tipo === "area" && !entryDi(sel.codice)) || (sel.tipo === "municipio" && !(sel.arabo >= 1 && sel.arabo <= 15))) sel = { tipo: "roma" };
      // l'area d'arrivo si lascia verso il municipio del menu della 2D se e' il suo, se no Roma
      var eSel = sel.tipo === "area" ? entryDi(sel.codice) : null;
      origine = sel.tipo !== "area" ? sel : (eSel && muni2D && muni2D === String(eSel.feature.properties.municipio_num_arabo) ?
        { tipo: "municipio", arabo: parseInt(muni2D, 10) } : { tipo: "roma" });
      // Aperta da un link #3d/<...> la 2D e' altrove: al ritorno deve raggiungere la 3D.
      pendente = JSON.stringify(sel) === JSON.stringify(in2d) ? null : sel;
      scriviHash(sel, !!daTasto);
      if (!contenitore) {
        contenitore = document.createElement("div");
        contenitore.id = "vista-3d";
        document.getElementById("map-wrap").appendChild(contenitore);
      }
      contenitore.hidden = false;
      contenitore.innerHTML = '<div class="v3d-attesa">Preparo la vista 3D…</div>';
      document.body.classList.add("vista-3d-on");
      // la scheda della 2D sta sopra la 3D solo nell'area: subito quella dell'area di arrivo
      var eArrivo = sel.tipo === "area" ? entryDi(sel.codice) : null;
      schedaArea(eArrivo ? eArrivo.feature.properties : null);
      // cartiglio e indietro della barra: il livello di arrivo (o Roma, se si arriva in un'area)
      cartiglioSel = { tipo: "roma" }; cornice3d(sel.tipo === "area" ? { tipo: "roma" } : sel);
      if (mqTelefono.matches) resetBtn.classList.toggle("visible", sel.tipo !== "roma");
      var giro = ++giroApertura;
      carica().then(function () {
        if (!aperta || giro !== giroApertura) return;
        contenitore.innerHTML = "";
        var ok = window.Vista3D.apri({
          contenitore: contenitore,
          aree: QUARTIERI, municipi: MUNICIPI,
          palette: PALETTE, amaranto: AMARANTO,
          romani: municipioRomano, tipi: TIPO_SINGOLARE,
          categorie: SERVIZI_CATEGORIE, gruppi: SERVIZI_GRUPPI, attive: serviziAttive, icone: ICONE_SVG, grappolo: htmlGrappolo,
          servizi: function () { return caricaServizi().then(function (r) { return r ? serviziDati : null; }); },
          // scheda del servizio (componente della 2D, sopra la 3D); i 15 minuti sono della 2D:
          // si torna in 2D e partono dal servizio, come "15 min" della scheda d'area
          schedaServizio: function (props, ll, el) {
            apriSchedaServizio(props, ll, el, { quindici: function (p) {
              dopoChiusura = function () { setTimeout(function () { avvia15DaPunto(p); }, 0); };
              torna2D();
            } });
          },
          chiudiScheda: chiudiSchedaServizio,
          tipiAttivi: activeTipi,
          selezione: sel,
          riduciMovimento: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
          mobile: suMobile(),
          onSeleziona: function (s) { pendente = s; scriviHash(s); segnaOrigine(s); elencoSegue(s); cornice3d(s); },
          // nell'area la scheda della 2D (mostraInfo) sopra la 3D; fuori dall'area via
          onArea: schedaArea,
          scheda: function () { return infoPanel.classList.contains("visible") ? infoPanel : null; },
          // telefono: il cartiglio della 2D in basso, sopra la 3D (spazio che occupa dal fondo)
          cartiglio: function () {
            var c = document.getElementById("cartiglio");
            return c && c.offsetHeight ? Math.round(document.getElementById("map-wrap").getBoundingClientRect().bottom - c.getBoundingClientRect().top + 12) : 0;
          },
          // nell'area su desktop il pannello Servizi in alto a destra: la camera lo evita,
          // anche se i dati arrivano dopo il volo (il pannello esce comunque, pieno o col
          // messaggio "non disponibili")
          pannello: function () { return areaServizi && !mqTelefono.matches ? destraServizi() : 0; },
          pannelloFondo: function () {
            if (!areaServizi || mqTelefono.matches || !serviziPanelEl || serviziPanelEl.hidden) return 0;
            var w = document.getElementById("map-wrap").getBoundingClientRect(), r = serviziPanelEl.getBoundingClientRect();
            return r.height ? Math.max(0, Math.round(r.bottom - w.top)) : 0;
          },
          // la camera dell'area chiede spazio: il pannello Servizi si riduce alla testata (e si
          // riapre da solo alla camera successiva o al ritorno in 2D, se lo aveva chiuso lei)
          compattaPannello: function (si) {
            if (!serviziPanelEl) return false;
            if (si) {
              if (serviziPanelEl.hidden || serviziPanelEl.classList.contains("collapsed")) return false;
              serviziPanelEl.classList.add("collapsed"); compattoDa3D = true;
              serviziPanelHead.setAttribute("aria-expanded", "false");
              posizionaServiziPanel();
              return true;
            }
            if (!compattoDa3D) return false;
            compattoDa3D = false;
            serviziPanelEl.classList.remove("collapsed");
            serviziPanelHead.setAttribute("aria-expanded", "true");
            posizionaServiziPanel();
            return false;
          },
          onErrore: function (msg, definitivo) { aperta = true; fallisci(msg, definitivo !== false); }
        });
        if (ok === false && aperta) fallisci("La vista 3D non è disponibile su questo dispositivo.", true);
      }).catch(function () { if (aperta && giro === giroApertura) fallisci("La vista 3D non si è caricata: riprova più tardi.", false); });
    }

    function entryDi(codice) {
      return entries.filter(function (x) { return String(x.feature.properties.codice) === String(codice); })[0] || null;
    }
    function applicaA2D(s) {
      if (s.tipo === "area") {
        var e = entryDi(s.codice);
        if (!e) { pulisciHash(); return; }
        if (activeMunicipio && activeMunicipio !== String(e.feature.properties.municipio_num_arabo)) {
          activeMunicipio = ""; municipioSelect.value = ""; applicaFiltri(); aggiornaRollup();
        }
        selezionaEntry(e, false);
        return;
      }
      if (selectedLayer) deseleziona();
      // senza area nella 2D resta accesa la voce che la 3D ha evidenziato: via anche quella
      var att = document.querySelector("#area-list li.active");
      if (att) att.classList.remove("active");
      var valore = s.tipo === "municipio" ? String(s.arabo) : "";
      // il menu ha gia' seguito la 3D: conta il municipio che la 2D mostrava all'apertura
      if (municipioSelect.value !== valore || muni2D !== valore) {
        municipioSelect.value = valore; municipioSelect.dispatchEvent(new Event("change"));
      } else if (!valore) { rimuoviIngresso(); vistaInsieme(); }
      pulisciHash();
    }

    // applica=false: la 2D ha gia' qualcosa da fare (via cercata, presentazione, hash).
    // ripristina15: riaccende i 15 minuti chiusi all'apertura (ritorno "vero" in 2D).
    function chiudi3d(applica, ripristina15) {
      if (!aperta) return;
      aperta = false; segna(false);
      chiudiSchedaServizio();
      try { if (window.Vista3D) window.Vista3D.chiudi(); } catch (e) {}
      if (contenitore) { contenitore.hidden = true; contenitore.innerHTML = ""; }
      document.body.classList.remove("vista-3d-on");
      map.invalidateSize();
      servizi2D();
      aggiornaServizi2D();
      var s = pendente, punto = q15Salvato; pendente = null; q15Salvato = null;
      // senza una scelta da applicare (Indietro, ricerca, guida) l'elenco torna quello
      // della 2D; con una scelta resta quello della 3D e applicaA2D ci porta la 2D
      if (!(applica && s)) elenco2D();
      if (applica) {
        if (s) applicaA2D(s);
        else hash2D();
      }
      // la scheda torna quella della 2D: posizione e stile della 2D, aperta solo se la 2D
      // ha un'area scelta
      infoPanel.style.transform = ""; infoPanel.style.transition = "";
      cartiglioSel = null; aggiornaCartiglio(); aggiornaReset();
      if (selectedEntry) mostraInfo(selectedEntry.feature.properties);
      else if (infoPanel.classList.contains("visible")) {
        infoPanel.classList.remove("visible");
        if (serviziPanelEl) posizionaServiziPanel();
      }
      if (ripristina15 && punto) {
        q15Attiva(true);
        if (punto !== true) q15Piazza(punto, !s);
      }
      if (dopoChiusura) { var f = dopoChiusura; dopoChiusura = null; f(); }
    }
    var dopoChiusura = null;

    // Ritorno in 2D dal tasto, da Esc o dalla guida: se la voce di cronologia e' quella
    // aggiunta entrando, si torna indietro di una (la chiusura arriva con hashchange).
    function torna2D() {
      if (!aperta) return;
      if (voceNostra()) {
        ritornoApplica = true;
        history.back();
        setTimeout(function () { if (aperta && ritornoApplica) { ritornoApplica = false; chiudi3d(true, true); } }, 600);
      } else chiudi3d(true, true);
    }

    // Con la 3D aperta basta il pannello (coperto, ma pronto e coerente); i marker della
    // Leaflet nascosta si ridisegnano alla chiusura, quando aperta e' gia' false.
    function aggiornaServizi2D() {
      if (serviziStato !== "ok" || !ambitoServiziCorrente) return;
      disegnaServiziPanel();
      if (!aperta) disegnaServizi(false);
    }

    // ---------- Pannello Servizi della 2D sopra la 3D ----------
    // Nell'area il pannello vero della 2D (#servizi-panel), alzato sopra la 3D da
    // body.vista-3d-on, mostra le categorie dell'area della 3D; a Roma e nel municipio e'
    // nascosto. Le caselle cambiano serviziAttive come in 2D e la 3D si ridisegna; i marker
    // della Leaflet coperta no: li rifa' il ritorno in 2D (servizi2D + aggiornaServizi2D).
    // I punti del focus della 2D (serviziFocusCorrenti) restano quelli della 2D: il pannello
    // si disegna coi punti dell'area della 3D scambiandoli per un attimo, cosi' un
    // ridisegno della Leaflet (moveend, zoomend) non ci mette mai i servizi della 3D.
    function serviziArea(props) {
      areaServizi = props ? props.codice : null;
      if (!serviziPanelEl) return;
      if (!props) { serviziPanelEl.hidden = true; return; }
      var codice = areaServizi;
      var riempi = function (ok) {
        if (!aperta || areaServizi !== codice) return;
        if (!ok || serviziStato !== "ok") { mostraServiziNonDisponibili(); return; }
        var punti2D = serviziFocusCorrenti;
        serviziFocusCorrenti = serviziDati.filter(function (p) { return p.props.codice_area === codice; });
        try { disegnaServiziPanel(); } finally { serviziFocusCorrenti = punti2D; }
        serviziPanelEl.hidden = false;
        posizionaServiziPanel();
      };
      // dati gia' pronti: subito, cosi' la camera dell'area (opt.pannello) ne conosce
      // l'ingombro; se no quando arrivano, dopo il ridisegno della 2D a fine caricamento
      if (serviziStato === "ok") riempi(true);
      else Promise.resolve(caricaServizi()).then(riempi);
    }
    // Desktop, area della 3D: il pannello sale in cima alla mappa (sotto la legenda della
    // 2D, coperta, galleggiava a mezza altezza sopra la tessera), a sinistra dei pulsanti
    // dello zoom della 3D, e l'elenco scende fino all'attribuzione. posizionaServiziPanel
    // della 2D lo mette sotto la legenda: si chiama lei (stile, 15 minuti) e poi si corregge.
    // Riassegnata qui: mostraInfo, la scheda e la 3D passano tutte da questo nome (resize e
    // ResizeObserver della legenda tengono l'originale: c'e' il resize qui sotto).
    // margine destro del pannello (a sinistra dello zoom della 3D) e, con larghezza=true,
    // tutto lo spazio che occupa da destra (anche da nascosto: max-width del CSS)
    function destraServizi(larghezza) {
      if (!serviziPanelEl) return 0;
      var wrap = document.getElementById("map-wrap").getBoundingClientRect(), destra = 12;
      var zoom = contenitore && contenitore.querySelector(".maplibregl-ctrl-top-right .maplibregl-ctrl");
      if (zoom && zoom.offsetWidth) destra = Math.round(wrap.right - zoom.getBoundingClientRect().left + 10);
      if (larghezza === false) return destra;
      return destra + (serviziPanelEl.offsetWidth || parseFloat(getComputedStyle(serviziPanelEl).maxWidth) || 210);
    }
    var posizionaServiziPanel2D = posizionaServiziPanel;
    posizionaServiziPanel = function () {
      var spazio = posizionaServiziPanel2D();
      if (!aperta || !areaServizi || !serviziPanelEl || mqTelefono.matches || !contenitore) return spazio;
      var wrap = document.getElementById("map-wrap").getBoundingClientRect();
      serviziPanelEl.style.top = "12px";
      serviziPanelEl.style.right = destraServizi(false) + "px";
      var fondo = wrap.bottom - 12, attr = contenitore.querySelector(".maplibregl-ctrl-bottom-right .maplibregl-ctrl");
      if (attr && attr.offsetHeight) fondo = Math.min(fondo, attr.getBoundingClientRect().top - 8);
      // finestra stretta: la scheda dell'area puo' stare sotto il pannello (le colonne si toccano)
      var sch = infoPanel.classList.contains("visible") ? infoPanel.getBoundingClientRect() : null;
      if (sch && sch.width) {
        var pr = serviziPanelEl.getBoundingClientRect();
        if (sch.right > pr.left && sch.left < pr.right && sch.top > pr.top) fondo = Math.min(fondo, sch.top - 10);
      }
      var testa = serviziPanelHead.getBoundingClientRect().height || 36;
      spazio = Math.round(fondo - (wrap.top + 12) - testa - 13);
      serviziPanelBody.style.maxHeight = Math.max(SERVIZI_CORPO_MIN, spazio) + "px";
      return spazio;
    };
    window.addEventListener("resize", function () { if (aperta && areaServizi) posizionaServiziPanel(); });
    // la scheda cambia altezza quando arrivano i servizi: il pannello ricalcola il suo fondo
    if (window.ResizeObserver) new ResizeObserver(function () { if (aperta && areaServizi) posizionaServiziPanel(); }).observe(document.getElementById("info-panel"));
    // Al ritorno: il pannello torna all'ambito della 2D (marker ridisegnati dal chiamante).
    function servizi2D() {
      areaServizi = null;
      if (compattoDa3D && serviziPanelEl) {
        compattoDa3D = false; serviziPanelEl.classList.remove("collapsed");
        if (serviziPanelHead) serviziPanelHead.setAttribute("aria-expanded", "true");
      }
      if (!serviziPanelEl || (q15 && q15.attivo)) return;
      serviziPanelEl.hidden = !ambitoServiziCorrente || serviziStato !== "ok";
      posizionaServiziPanel();
    }
    // Caselle cambiate a 3D aperta: lo stesso stato del gestore della 2D (serviziAttive,
    // casella del gruppo), poi la 3D. In cattura e fermato qui: il gestore della 2D
    // ridisegnerebbe anche i marker della Leaflet coperta.
    // ATTENZIONE: copia i gestori change di disegnaServiziPanel nel template (casella del
    // gruppo e casella della categoria): se cambiano li', questa va riallineata.
    if (serviziPanelHead) serviziPanelHead.addEventListener("click", function () { compattoDa3D = false; });
    var serviziPanelBodyEl = document.getElementById("servizi-panel-body");
    if (serviziPanelBodyEl) serviziPanelBodyEl.addEventListener("change", function (ev) {
      if (!aperta) return;
      var t = ev.target, det = t && t.closest ? t.closest(".sp-gruppo") : null;
      if (!det || t.type !== "checkbox") return;
      ev.stopPropagation();
      var gruppo = det.querySelector(".sp-chk-gruppo");
      var caselle = [].slice.call(det.querySelectorAll('input[id^="sp-chk-"]'));
      var categorie = caselle.map(function (c) { return { chiave: c.id.slice(7) }; });
      if (t === gruppo) caselle.forEach(function (c) { c.checked = t.checked; });
      caselle.forEach(function (c) { serviziAttive[c.id.slice(7)] = c.checked; });
      statoCasellaGruppo(gruppo, categorie);
      if (window.Vista3D && window.Vista3D.attiveCambiate) window.Vista3D.attiveCambiate();
    }, true);

    // ---------- Elenco che segue la 3D ----------
    // Le scelte fatte dentro la 3D arrivano all'elenco come dalla 2D: menu municipio,
    // filtro, riepilogo, voce evidenziata. La mappa Leaflet non si muove, e la sua area
    // scelta non viene deselezionata dal filtro (toglierebbe la scheda e il pannello
    // sopra la 3D): al ritorno ci pensa applicaA2D.
    // Il filtro senza la deselezione della 2D (applicaFiltri chiude l'area scelta se il
    // filtro la nasconde): l'elenco e le sagome della Leaflet possono restare
    // incoerenti con l'area della 2D solo finche' la 3D e' aperta: alla chiusura le
    // riallinea elenco2D() (senza applicare) o applicaA2D (con una scelta da applicare).
    function filtraSenzaDeselezionare() {
      var sel = selectedEntry;
      selectedEntry = null;
      try { applicaFiltri(); } finally { selectedEntry = sel; }
    }
    function filtraElenco(valore) {
      municipioSelect.value = valore;
      if (activeMunicipio === valore) return;
      activeMunicipio = valore;
      filtraSenzaDeselezionare();
      aggiornaRollup();
    }
    // Chiusura senza applicare: l'elenco torna allo stato della 2D (menu, filtro vero,
    // riepilogo, voce dell'area scelta), coerente con la scheda e le sagome della Leaflet.
    function elenco2D() {
      municipioSelect.value = muni2D;
      activeMunicipio = muni2D;
      applicaFiltri();
      aggiornaRollup();
      var att = document.querySelector("#area-list li.active");
      if (att) att.classList.remove("active");
      if (selectedEntry) evidenziaLista(selectedEntry);
    }
    // La ricerca scritta a 3D aperta filtra l'elenco come in 2D, ma senza deselezionare
    // l'area della 2D (toglierebbe la scheda sopra la 3D): copia il gestore input di searchEl
    // nel template (testoRicerca, applicaFiltri, aggiornaVie), da riallineare se cambia.
    searchEl.addEventListener("input", function (ev) {
      if (!aperta) return;
      ev.stopImmediatePropagation();
      testoRicerca = foldAccenti(searchEl.value.trim());
      filtraSenzaDeselezionare();
      aggiornaVie();
    }, true);
    function elencoSegue(s) {
      if (s.tipo === "area") {
        var e = entryDi(s.codice);
        if (!e) return;
        filtraElenco(String(e.feature.properties.municipio_num_arabo));
        evidenziaLista(e);
        return;
      }
      filtraElenco(s.tipo === "municipio" ? String(s.arabo) : "");
      var att = document.querySelector("#area-list li.active");
      if (att) att.classList.remove("active");
    }

    function segnaOrigine(s) { if (s.tipo !== "area") origine = s; }
    function vola3d(s, opz) {
      pendente = s; scriviHash(s); segnaOrigine(s); cornice3d(s);
      if (window.Vista3D) window.Vista3D.seleziona(s, opz);
    }

    // ---------- Deseleziona della 2D con la 3D aperta ----------
    // Esc della 2D (anche dalla ricerca vuota o dopo "Cos'e'"), i filtri per tipo e ogni
    // altro percorso della 2D che deseleziona toglierebbero la scheda (e il pannello Servizi)
    // mentre la 3D resta nell'area. Con la 3D aperta la 2D non deseleziona: la sua area resta
    // scelta e al ritorno la riallineano applicaA2D o elenco2D (che rifa' applicaFiltri a 3D
    // chiusa). La presentazione chiude la 3D e deve poter ripulire la 2D: li' passa.
    // Riassegnata: chi chiama deseleziona per nome (applicaFiltri, Esc, ...) passa di qui.
    var deseleziona2D = deseleziona;
    deseleziona = function () {
      if (aperta && !presentazioneOn) return;
      deseleziona2D.apply(this, arguments);
    };

    // ---------- Scheda della 2D sopra la 3D ----------
    // Nell'area la scheda e' quella vera della 2D (#info-panel, riempita da mostraInfo), alzata
    // sopra la 3D da body.vista-3d-on. Su telefono e' la scheda bassa della 2D (maniglia,
    // tocco e trascinamento sono della 2D); la x e il trascinamento che lascia l'area non
    // arrivano a deseleziona della 2D: qui diventano una selezione della 3D.
    var infoPanel = document.getElementById("info-panel");
    function schedaArea(props) {
      serviziArea(props);
      if (!props) {
        infoPanel.classList.remove("visible");
        infoPanel.style.transform = ""; infoPanel.style.transition = "";
        if (serviziPanelEl) posizionaServiziPanel();
        return;
      }
      // ogni ingresso in un'area parte con la scheda bassa (la camera inquadra sopra di lei)
      infoPanel.scrollTop = 0;
      mostraInfo(props);
      schedaAlta(false);
    }
    // deseleziona della 2D tradotto in 3D: si torna al livello da cui si e' entrati
    // nell'area (al municipio dell'area se si veniva da un municipio, altrimenti a Roma; il
    // menu, che nell'area segue la 3D, non conta), e l'elenco si riallinea a quel livello.
    // Tornando a Roma la camera resta dov'e' come nella 2D: prima chiudere
    // la scheda riportava alla vista di Roma intera.
    // fermo=false (tasto indietro della barra): a Roma la camera torna su Roma intera.
    function deseleziona3d(fermo) {
      var s = window.Vista3D && window.Vista3D.selezione(), dest = { tipo: "roma" };
      if (origine.tipo === "municipio") {
        var e = s && s.tipo === "area" ? entryDi(s.codice) : null;
        dest = { tipo: "municipio", arabo: e ? parseInt(e.feature.properties.municipio_num_arabo, 10) : origine.arabo };
      }
      schedaArea(null);
      vola3d(dest, dest.tipo === "roma" && fermo !== false ? { fermo: true } : null);
      elencoSegue(dest);
    }
    var lasciaArea2D = lasciaArea;
    lasciaArea = function () { if (aperta && !presentazioneOn) deseleziona3d(); else lasciaArea2D(); };
    function dentroScheda(ev) { return aperta && ev.target && ev.target.closest && ev.target.closest("#info-panel"); }
    document.addEventListener("click", function (ev) {
      if (!dentroScheda(ev)) return;
      if (ev.target.closest("#info-close")) { ev.stopPropagation(); ev.preventDefault(); deseleziona3d(); }
    }, true);

    // ---------- Cornice del telefono sopra la 3D ----------
    // Il cartiglio della 2D dice il livello della 3D (Roma o il municipio); il tasto indietro
    // della barra sale di un livello nella 3D: dall'area al livello da cui si era entrati,
    // dal municipio a Roma intera.
    function cornice3d(s) {
      cartiglioSel = s && s.tipo !== "area" ? s : cartiglioSel;
      aggiornaCartiglio();
      if (mqTelefono.matches) resetBtn.classList.toggle("visible", !!s && s.tipo !== "roma");
    }
    resetBtn.addEventListener("click", function (ev) {
      if (!aperta) return;
      ev.stopImmediatePropagation(); ev.preventDefault();
      var s = window.Vista3D && window.Vista3D.selezione();
      if (s && s.tipo === "area") deseleziona3d(false);
      else { var dest = { tipo: "roma" }; vola3d(dest); elencoSegue(dest); }
    }, true);
    // "15 min" della scheda: i 15 minuti sono della 2D. Si torna in 2D (come col tasto 2D,
    // la cronologia resta pulita) e, a 2D pronta sull'area, partono da li'.
    document.getElementById("info-q15-btn").addEventListener("click", function (ev) {
      if (!aperta) return;
      ev.stopImmediatePropagation(); ev.preventDefault();
      dopoChiusura = function () { setTimeout(avvia15DaScheda, 0); };
      torna2D();
    }, true);
    // Il tasto posizione sopra la 3D: l'area trovata si apre in 3D.
    var posizioneTrovata2D = posizioneTrovata;
    posizioneTrovata = function (e, ll) {
      if (!aperta) { posizioneTrovata2D(e, ll); return; }
      var s = { tipo: "area", codice: e.feature.properties.codice };
      vola3d(s); elencoSegue(s);
    };

    btn3d.addEventListener("click", function () { apri3d(null, true); });
    btn2d.addEventListener("click", torna2D);

    // In 3D l'elenco e il filtro municipio fanno volare la 3D; la ricerca per via,
    // la guida e la presentazione riportano in 2D (lassu' non ci sono).
    var sidebar = document.getElementById("sidebar");
    function areaDaLi(target) {
      var li = target && target.closest ? target.closest("#area-list li") : null;
      return li ? entries.filter(function (x) { return x.li === li; })[0] : null;
    }
    function scegliDaElenco(ev) {
      var e = areaDaLi(ev.target);
      if (!e) return false;
      ev.stopPropagation(); ev.preventDefault();
      vola3d({ tipo: "area", codice: e.feature.properties.codice });
      evidenziaLista(e);
      if (suMobile()) chiudiDrawer();
      return true;
    }
    sidebar.addEventListener("click", function (ev) {
      if (!aperta) return;
      if (scegliDaElenco(ev)) return;
      if (ev.target.closest && ev.target.closest("#street-results")) chiudi3d(false);
    }, true);
    sidebar.addEventListener("keydown", function (ev) {
      if (!aperta || (ev.key !== "Enter" && ev.key !== " ")) return;
      if (ev.target === searchEl) {
        if (ev.key !== "Enter") return;
        chiudi3d(false);
        // nessun risultato da aprire (la 2D non riscrive l'hash): via #3d dalla barra
        if (!(streetEl.querySelector("button") || primaAreaVisibile())) hash2D();
        return;
      }
      if (ev.target.closest && ev.target.closest("#street-results")) { chiudi3d(false); return; }
      scegliDaElenco(ev);
    }, true);
    sidebar.addEventListener("change", function (ev) {
      if (!aperta || ev.target !== municipioSelect) return;
      ev.stopPropagation();
      var v = municipioSelect.value, dest = v ? { tipo: "municipio", arabo: parseInt(v, 10) } : { tipo: "roma" };
      activeMunicipio = null;   // filtraElenco riapplica sempre il filtro
      elencoSegue(dest);        // menu, filtro e nessuna voce evidenziata, come la 2D
      vola3d(dest);
    }, true);
    // Filtri per tipo (Rioni, Quartieri, Zone funzionali): il pulsante della 2D cambia
    // activeTipi e applica i suoi filtri (sul proprio click, prima di questo che arriva in
    // risalita; la sua deselezione e' fermata sopra); la 3D aperta li segue. Se il tipo
    // spento e' quello dell'area della 3D, come la 2D: l'area si lascia (stessa strada della x).
    var tipoButtons = document.getElementById("tipo-buttons");
    if (tipoButtons) tipoButtons.addEventListener("click", function (ev) {
      if (!aperta || !window.Vista3D || !window.Vista3D.filtraTipi) return;
      if (!(ev.target.closest && ev.target.closest(".tipo-btn"))) return;
      window.Vista3D.filtraTipi(activeTipi);
      var s = window.Vista3D.selezione(), e = s && s.tipo === "area" ? entryDi(s.codice) : null;
      if (e && !activeTipi[e.feature.properties.tipo]) deseleziona3d();
    });
    // La guida parte subito dopo questo click: la 3D si chiude adesso, e la voce di
    // cronologia aggiunta entrando perde il segno (resta una voce in piu', solo qui).
    tourBtn.addEventListener("click", function () {
      if (!aperta) return;
      chiudi3d(true, true);
      if (voceNostra() && history.replaceState) history.replaceState(null, "", location.hash);
    }, true);

    // Esc torna in 2D, se non c'e' un drawer, un pannello o un popup aperto da chiudere prima.
    document.addEventListener("keydown", function (ev) {
      if (!aperta || ev.key !== "Escape") return;
      var t = ev.target;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
      if (sidebar.classList.contains("open") || document.getElementById("about-scrim").classList.contains("open")) return;
      ev.stopPropagation(); ev.preventDefault();
      var pop = contenitore && contenitore.querySelector(".v3d-popup:not([hidden])");
      if (pop) { if (window.Vista3D && window.Vista3D.chiudiPopup) window.Vista3D.chiudiPopup(); else pop.hidden = true; return; }
      torna2D();
    }, true);

    // Avanti/indietro (e i link incollati): una voce #3d apre la 3D, una voce senza la chiude.
    window.addEventListener("hashchange", function () {
      var s = selDaHash();
      if (s && !aperta) apri3d(s, false);
      else if (s && aperta && ((s.tipo === "area" && !entryDi(s.codice)) || (s.tipo === "municipio" && !(s.arabo >= 1 && s.arabo <= 15)))) {
        // hash non valido a 3D aperta: l'URL torna a quello della selezione corrente
        var cor = window.Vista3D && window.Vista3D.selezione && window.Vista3D.selezione();
        scriviHash(cor && cor.tipo ? cor : (pendente && pendente.tipo ? pendente : { tipo: "roma" }));
      }
      else if (!s && aperta) { var ap = ritornoApplica; ritornoApplica = false; chiudi3d(ap, !presentazioneAttivaDaHash()); }
    });
    var iniziale = selDaHash();
    if (iniziale) apri3d(iniziale, false);
  })();
