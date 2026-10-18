/* Search page.

   Interaction model: the server renders a plain visit; this script then
   fetches the default scope once, in the background, and from then on every
   filter, sort and page change is answered from memory with no request. A
   deep link with filters renders first from the smallest slice that answers
   it, then switches to the full default scope when that arrives. The long
   scope (since 2023 Q4) is loaded only when asked, with a size notice above
   a threshold, and is answered from memory afterwards too.

   Everything rendered from data uses textContent. Every word the script
   draws comes from the page's <script type="application/json" id="i18n">
   block (rendered by src/pages/search.tsx from src/i18n.ts), so the script
   holds no copy of its own in either language. */
(function () {
  var results = document.getElementById("results");
  var form = document.getElementById("search-form");
  if (!results || !form) return;
  var PAGE = 25;
  var GATE_BYTES = 2 * 1024 * 1024;   // ask before loading more than this (raw JSON; roughly a quarter travels compressed)
  var CSV_MAX_ROWS = 50000;           // beyond this, point at the server-side CSVs
  var PROVINCES = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT", "XX", "UN"];
  var I18N = {};
  try { I18N = JSON.parse(document.getElementById("i18n").textContent) || {}; } catch (e) { I18N = {}; }
  var STRINGS = I18N.strings || {};
  var LANG = I18N.lang === "fr" ? "fr" : "en";
  var LOCALE = I18N.locale || "en-CA";
  var today = results.getAttribute("data-today") || new Date().toISOString().slice(0, 10);
  var WEEK_AGO = shiftDate(today, -7);
  var QUARTER_AGO = shiftDate(today, -92);
  var years = (results.getAttribute("data-years") || "").split(",").filter(Boolean);
  var latestLabel = periodLabel(results.getAttribute("data-latest"));
  var fromLabel = periodLabel(results.getAttribute("data-from"));

  var facets = null;
  var defaultRows = null;   // the whole default scope, once fetched
  var defaultPromise = null;
  var sliceRows = null;     // a deep link's slice, used until defaultRows arrives
  var longRows = null;      // the long scope, once the visitor asked for it
  var longLoading = false;
  var current = [];
  var viewSource = null;    // the rows and the filter key behind current
  var viewKey = null;
  var state = readState();

  // -- helpers --------------------------------------------------------------

  // A string from the page's dictionary, with {name} filled from vars. A
  // missing key shows the key itself, which the i18n test guards against.
  function tx(key, vars) {
    var s = STRINGS[key];
    if (s == null) return key;
    return vars ? s.replace(/\{(\w+)\}/g, function (m, name) { return name in vars ? String(vars[name]) : m; }) : s;
  }
  function txn(one, many, n, vars) {
    var singular = LANG === "fr" ? Math.abs(n) < 2 : n === 1;
    return tx(singular ? one : many, vars);
  }
  function has(key) { return STRINGS[key] != null; }
  function decimal(text) { return LANG === "fr" ? text.replace(".", ",") : text; }
  function fold(s) { return (s || "").toString().normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  // Plain ASCII text (most names) needs no Unicode normalisation, which is
  // the expensive part of fold.
  function quickFold(s) { var t = (s || "").toString(); return /[^\x00-\x7f]/.test(t) ? fold(t) : t.toLowerCase(); }
  // Folded text kept on the row the first time a filter or a sort needs it:
  // the long scope holds about 190,000 rows, and folding every name again on
  // each change and in each sort comparison took most of a second.
  function hay(r) {
    if (r._hay === undefined) r._hay = quickFold(r.employer) + " " + quickFold(r.city) + " " + quickFold(r.postal) + " " + quickFold(r.job);
    return r._hay;
  }
  function nameKey(r) {
    if (r._name === undefined) r._name = quickFold(r.employer);
    return r._name;
  }
  function shiftDate(iso, days) {
    var d = new Date(iso + "T00:00:00Z");
    if (isNaN(d.getTime())) return "";
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  }
  function fmt(n) { return (n || 0).toLocaleString(LOCALE); }
  function mb(bytes) { return tx("size.mb", { n: decimal((bytes / 1048576).toFixed(1)) }); }
  function periodLabel(p) {
    var m = /^(\d{4})Q(\d)(?:-Q(\d))?$/.exec(p || "");
    if (!m) return p || "";
    return m[3] ? tx("period.range", { y: m[1], q: m[2], q2: m[3] }) : tx("period.quarter", { y: m[1], q: m[2] });
  }
  function wage(r) {
    if (r.kind !== "posting" || (r.wage_min == null && r.wage_max == null)) return tx("common.na");
    var u = !r.unit ? "" : has("wage.unit." + r.unit) ? tx("wage.unit." + r.unit) : " " + r.unit.toLowerCase();
    var a = r.wage_min != null ? decimal(r.wage_min.toFixed(2)) : null, b = r.wage_max != null ? decimal(r.wage_max.toFixed(2)) : null;
    return a && b && a !== b ? tx("wage.range", { min: a, max: b, unit: u }) : tx("wage.single", { amount: a || b, unit: u });
  }
  function fetchJson(path) {
    return fetch("/data/" + path).then(function (r) { return r.ok ? r.json() : []; }).catch(function () { return []; });
  }

  // -- state from the form and the URL ---------------------------------------

  function readState() {
    var fd = new FormData(form);
    var params = new URLSearchParams(location.search);
    var q = (fd.get("q") || "").toString().trim();
    var noc = (fd.get("noc") || "").toString().trim().toLowerCase();
    return {
      q: q,
      qFold: quickFold(q),
      status: fd.getAll("status"),
      province: fd.getAll("province"),
      stream: fd.getAll("stream"),
      noc: noc,
      nocFold: quickFold(noc),
      wageMin: parseFloat(fd.get("wage_min")), wageMax: parseFloat(fd.get("wage_max")),
      date: (fd.get("date") || "any").toString(),
      indicator: (fd.get("indicator") || "").toString(),
      sort: (fd.get("sort") || "newest").toString(),
      page: Math.max(1, parseInt(params.get("page") || "1", 10) || 1),
    };
  }
  function writeUrl() {
    var url = new URL(location.href);
    url.search = "";
    if (state.q) url.searchParams.set("q", state.q);
    state.status.forEach(function (s) { url.searchParams.append("status", s); });
    state.province.forEach(function (p) { url.searchParams.append("province", p); });
    state.stream.forEach(function (s) { url.searchParams.append("stream", s); });
    if (state.noc) url.searchParams.set("noc", state.noc);
    if (!isNaN(state.wageMin)) url.searchParams.set("wage_min", String(state.wageMin));
    if (!isNaN(state.wageMax)) url.searchParams.set("wage_max", String(state.wageMax));
    if (state.date !== "any") url.searchParams.set("date", state.date);
    if (state.indicator) url.searchParams.set("indicator", state.indicator);
    if (state.sort !== "newest") url.searchParams.set("sort", state.sort);
    if (state.page > 1) url.searchParams.set("page", String(state.page));
    history.replaceState(null, "", url.toString());
  }
  function hasTextFilters() {
    return !!(state.q || state.noc || !isNaN(state.wageMin) || !isNaN(state.wageMax) || state.indicator || state.stream.length);
  }

  // -- which rows answer the view -------------------------------------------

  function sliceFiles() {
    var files = [];
    if (hasTextFilters() || (!state.status.length && !state.province.length)) return ["search/latest/all.json"];
    if (state.status.length && state.province.length) {
      state.province.forEach(function (p) { state.status.forEach(function (s) { files.push("search/latest/prov/" + p + "/" + s + ".json"); }); });
    } else if (state.province.length) {
      state.province.forEach(function (p) { files.push("search/latest/prov/" + p + ".json"); });
    } else {
      state.status.forEach(function (s) { files.push("search/latest/status/" + s + ".json"); });
    }
    return files;
  }
  function longFiles() {
    var files = [];
    PROVINCES.forEach(function (p) {
      files.push("search/long/" + p + "/postings.json");
      years.forEach(function (y) { files.push("search/long/" + p + "/" + y + ".json"); });
    });
    return files.filter(function (f) { return !facets || facets.files[f]; });
  }
  function planBytes(files) {
    var total = 0, rows = 0;
    files.forEach(function (f) { var i = facets && facets.files[f]; if (i) { total += i.bytes; rows += i.rows; } });
    return { bytes: total, rows: rows };
  }

  function passes(r, skip) {
    if (skip !== "status") {
      if (state.status.length ? state.status.indexOf(r.status) < 0 : r.status === "lapsed") return false;
    }
    if (skip !== "province" && state.province.length && state.province.indexOf(r.prov || "UN") < 0) return false;
    if (state.stream.length && state.stream.indexOf(r.stream) < 0) return false;
    if (state.q && hay(r).indexOf(state.qFold) < 0) return false;
    if (state.noc) {
      var code = (r.noc || "").toLowerCase();
      if (code.indexOf(state.noc) !== 0 && quickFold(r.job).indexOf(state.nocFold) < 0) return false;
    }
    if (!isNaN(state.wageMin) && !(r.wage_min != null && r.wage_min >= state.wageMin)) return false;
    if (!isNaN(state.wageMax) && !(r.wage_max != null && r.wage_max <= state.wageMax)) return false;
    if (state.date === "7d") {
      if (r.kind !== "posting" || !r.date || r.date < WEEK_AGO) return false;
    } else if (state.date === "last_quarter") {
      if (r.kind === "posting" && (!r.date || r.date < QUARTER_AGO)) return false;
    }
    if (state.indicator && (r.ind || []).indexOf(state.indicator) < 0) return false;
    return true;
  }
  function sortRows(rows) {
    if (state.sort === "positions") rows.sort(function (a, b) { return (b.positions || 0) - (a.positions || 0) || (b.sort_date > a.sort_date ? 1 : -1); });
    else if (state.sort === "name") rows.sort(function (a, b) { return nameKey(a) < nameKey(b) ? -1 : 1; });
    else rows.sort(function (a, b) { return b.sort_date > a.sort_date ? 1 : b.sort_date < a.sort_date ? -1 : nameKey(a) < nameKey(b) ? -1 : 1; });
    return rows;
  }

  // -- rendering -------------------------------------------------------------

  // Column headers as data-label on every cell, so a phone restacks each row
  // as a labelled block. Same labels as SearchRowView in src/pages/search.tsx.
  var COLUMN = {
    status: tx("col.status"), employer: tx("col.employer"), job: tx("col.job_or_occupation"), location: tx("col.location"),
    wage: tx("col.wage"), date: tx("col.date"), positions: tx("col.positions"), indicators: tx("col.indicators"),
    source: tx("col.source"),
  };
  function td(label, cls) {
    var el = document.createElement("td");
    if (label) el.setAttribute("data-label", label);
    if (cls) el.className = cls;
    return el;
  }
  function cell(tr, text, cls, label) {
    var el = td(label, cls);
    el.textContent = text == null ? "" : String(text);
    tr.appendChild(el);
    return el;
  }
  function renderRows(slice) {
    var body = document.getElementById("results-body");
    body.textContent = "";
    if (!slice.length) {
      var tr0 = document.createElement("tr");
      cell(tr0, tx("search.no_match"), "muted").setAttribute("colspan", "9");
      body.appendChild(tr0);
    }
    slice.forEach(function (r) {
      var tr = document.createElement("tr");
      var tdS = td(COLUMN.status);
      var badge = document.createElement("span");
      badge.className = "badge badge-" + r.status;
      badge.textContent = has("status." + r.status) ? tx("status." + r.status) : r.status;
      tdS.appendChild(badge); tr.appendChild(tdS);
      var tdE = td(COLUMN.employer);
      var a = document.createElement("a");
      a.href = "/employers/" + encodeURIComponent(r.employer_id);
      a.textContent = r.employer || "";
      tdE.appendChild(a); tr.appendChild(tdE);
      cell(tr, (r.kind === "esdc" && r.noc ? r.noc + " " : "") + (r.job || ""), null, COLUMN.job);
      cell(tr, [r.street, r.city].filter(Boolean).join(", ") + (r.prov ? ", " + r.prov : "") + (r.postal ? " " + r.postal : ""), null, COLUMN.location);
      cell(tr, wage(r), "mono", COLUMN.wage);
      cell(tr, r.kind === "posting" ? (r.date || "") : periodLabel(r.period), "mono", COLUMN.date);
      cell(tr, r.positions == null ? tx("common.see_posting") : fmt(r.positions), "mono num", COLUMN.positions);
      var tdI = td(COLUMN.indicators);
      if ((r.ind || []).length) {
        var chips = document.createElement("span");
        chips.className = "chips";
        r.ind.forEach(function (i) {
          var chip = document.createElement("span");
          chip.className = "chip";
          chip.textContent = has("ind." + i) ? tx("ind." + i) : i;
          chips.appendChild(chip);
        });
        tdI.appendChild(chips);
      }
      tr.appendChild(tdI);
      var tdSrc = td(COLUMN.source);
      var src = document.createElement("a");
      src.href = r.source; src.rel = "nofollow noopener"; src.className = "mono";
      src.textContent = r.kind === "posting"
        ? tx("search.source_jobbank", { ref: r.ref })
        : tx(r.status === "refused" ? "search.source_negative" : "search.source_positive", { period: r.period || "" });
      tdSrc.appendChild(src); tr.appendChild(tdSrc);
      body.appendChild(tr);
    });
  }
  function setCounts(byStatus, byProv) {
    document.querySelectorAll("[data-count]").forEach(function (el) {
      var parts = el.getAttribute("data-count").split(":");
      var n = parts[0] === "status" ? byStatus[parts[1]] : byProv[parts[1]];
      el.textContent = n == null ? " 0" : " " + fmt(n);
    });
  }
  function facetCounts(rows, complete) {
    var byStatus = {}, byProv = {};
    rows.forEach(function (r) {
      if (passes(r, "status")) byStatus[r.status] = (byStatus[r.status] || 0) + 1;
      if (passes(r, "province")) { var p = r.prov || "UN"; byProv[p] = (byProv[p] || 0) + 1; }
    });
    // A slice cannot count the dimension it was cut on; facets.json can.
    if (!complete && facets && state.date !== "since_2023q4") {
      var sp = facets.default.status_prov;
      if (state.status.length) {
        byStatus = {};
        Object.keys(sp).forEach(function (k) {
          var parts = k.split("|");
          if (!state.province.length || state.province.indexOf(parts[1]) >= 0) byStatus[parts[0]] = (byStatus[parts[0]] || 0) + sp[k];
        });
      }
      if (state.province.length) {
        byProv = {};
        Object.keys(sp).forEach(function (k) {
          var parts = k.split("|");
          if (state.status.length ? state.status.indexOf(parts[0]) >= 0 : parts[0] !== "lapsed") byProv[parts[1]] = (byProv[parts[1]] || 0) + sp[k];
        });
      }
    }
    setCounts(byStatus, byProv);
  }
  // The server renders each control as a link (a page it can serve) or as a
  // plain button (a page only this script can draw). Both get the handler,
  // once; a link becomes a button first.
  function swapToButtons() {
    ["page-prev", "page-next"].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el || el.getAttribute("data-wired")) return;
      var b = el;
      if (el.tagName === "A") {
        b = document.createElement("button");
        b.type = "button"; b.className = "btn"; b.id = id; b.textContent = el.textContent;
        el.replaceWith(b);
      }
      b.setAttribute("data-wired", "1");
      b.addEventListener("click", id === "page-prev" ? function () { state.page -= 1; render(); } : function () { state.page += 1; render(); });
    });
  }

  // Pick the rows in memory that answer the view, then draw.
  function render(partialNote) {
    var source, complete;
    if (state.date === "since_2023q4") {
      if (!longRows) { gateLong(); return; }
      source = longRows; complete = true;
    } else if (defaultRows) {
      source = defaultRows; complete = true;
    } else if (sliceRows) {
      source = sliceRows; complete = false;
    } else {
      return; // nothing in memory yet; the server-rendered rows stay on screen
    }
    hideGate();
    // A page change reuses the filtered, sorted rows; only a new filter, sort
    // or data set filters again.
    var key = JSON.stringify([state.q, state.status, state.province, state.stream, state.noc, state.wageMin,
      state.wageMax, state.date, state.indicator, state.sort]);
    var fresh = source !== viewSource || key !== viewKey;
    var rows = fresh ? sortRows(source.filter(function (r) { return passes(r, null); })) : current;
    viewSource = source; viewKey = key;
    current = rows;
    var total = rows.length;
    var pages = Math.max(1, Math.ceil(total / PAGE));
    if (state.page > pages) state.page = pages;
    var start = (state.page - 1) * PAGE;
    renderRows(rows.slice(start, start + PAGE));
    var count = document.getElementById("results-count");
    count.textContent = "";
    var strong = document.createElement("strong");
    var records = txn("search.records_one", "search.records_many", total, { n: fmt(total) });
    strong.textContent = partialNote ? tx("search.so_far", { count: records }) : records;
    count.appendChild(strong);
    var note = document.createElement("span");
    note.className = "muted";
    note.textContent = " " + (state.date === "since_2023q4"
      ? tx("search.note_since", { period: fromLabel })
      : tx("search.note_latest", { period: latestLabel }));
    count.appendChild(note);
    document.getElementById("page-range").textContent = total
      ? tx("search.showing", { from: fmt(start + 1), to: fmt(Math.min(total, start + PAGE)), total: fmt(total) })
      : "";
    document.getElementById("page-label").textContent = tx("search.page_of", { page: state.page, pages: pages });
    swapToButtons();
    document.getElementById("page-prev").disabled = state.page <= 1;
    document.getElementById("page-next").disabled = state.page >= pages;
    if (fresh) facetCounts(source, complete);
    writeUrl();
  }

  // -- loading ---------------------------------------------------------------

  // The default scope is fetched once; while it is on its way a deep link's
  // slice gives the visitor rows within a fraction of the time.
  function ensureDefault() {
    if (defaultPromise) return defaultPromise;
    defaultPromise = fetchJson("search/latest/all.json").then(function (rows) {
      defaultRows = rows;
      sliceRows = null;
      if (state.date !== "since_2023q4") render();
    });
    return defaultPromise;
  }
  function loadSliceThenDefault() {
    var files = sliceFiles();
    if (files.length === 1 && files[0] === "search/latest/all.json") { ensureDefault(); return; }
    Promise.all(files.map(fetchJson)).then(function (parts) {
      if (!defaultRows) { sliceRows = [].concat.apply([], parts); render(); }
    });
    ensureDefault();
  }
  function hideGate() { var g = document.getElementById("load-gate"); if (g) { g.hidden = true; } }
  function gateLong() {
    if (longLoading) return;
    var files = longFiles();
    var est = planBytes(files);
    var gate = document.getElementById("load-gate");
    gate.textContent = "";
    gate.hidden = false;
    var msg = document.createElement("p");
    msg.textContent = est.bytes > GATE_BYTES
      ? tx("search.gate_long", { rows: fmt(est.rows), files: fmt(files.length), size: mb(est.bytes) })
      : tx("search.gate_loading", { rows: fmt(est.rows) });
    gate.appendChild(msg);
    if (est.bytes > GATE_BYTES) {
      var load = document.createElement("button");
      load.type = "button"; load.className = "btn btn-primary"; load.textContent = tx("search.gate_load", { rows: fmt(est.rows) });
      load.addEventListener("click", function () { loadLong(files); });
      var csv = document.createElement("a");
      csv.href = "/data#downloads"; csv.className = "btn"; csv.textContent = tx("search.gate_csv");
      gate.appendChild(load); gate.appendChild(document.createTextNode(" ")); gate.appendChild(csv);
      document.getElementById("results-count").textContent = tx("search.gate_waiting");
    } else {
      loadLong(files);
    }
  }
  function loadLong(files) {
    if (longLoading) return; // a second click while the files arrive
    longLoading = true;
    var acc = [], i = 0;
    var msg = document.getElementById("load-gate");
    function step() {
      if (i >= files.length) {
        longRows = acc; longLoading = false; hideGate(); render(); return;
      }
      fetchJson(files[i]).then(function (rows) {
        i += 1;
        acc = acc.concat(rows);
        msg.textContent = tx("search.gate_progress", { done: fmt(i), files: fmt(files.length), rows: fmt(acc.length) });
        step();
      });
    }
    step();
  }

  // -- CSV -------------------------------------------------------------------

  function csv() {
    if (current.length > CSV_MAX_ROWS) { location.href = "/data#downloads"; return; }
    var cols = ["status", "employer", "employer_id", "job", "noc", "street", "city", "prov", "postal", "wage_min", "wage_max", "unit", "date", "period", "positions", "stream", "source"];
    var esc = function (v) { var s = v == null ? "" : String(v); return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    var lines = [cols.join(",")].concat(current.map(function (r) { return cols.map(function (c) { return esc(r[c]); }).join(","); }));
    var blob = new Blob([lines.join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "lmia-watch-search.csv";
    document.body.appendChild(a); a.click(); a.remove();
  }

  // -- wiring ----------------------------------------------------------------

  var debounce = null;
  function onChange(resetPage) {
    state = readState();
    if (resetPage !== false) state.page = 1;
    if (state.date === "since_2023q4" && !longRows) { gateLong(); return; }
    render();
  }
  form.addEventListener("submit", function (e) { e.preventDefault(); onChange(); });
  form.addEventListener("change", function (e) {
    if (e.target && e.target.id === "sort") { state = readState(); state.page = 1; render(); return; }
    onChange();
  });
  form.addEventListener("input", function (e) {
    if (!e.target || !/^(q|noc|wage_min|wage_max)$/.test(e.target.name || "")) return;
    clearTimeout(debounce);
    debounce = setTimeout(onChange, 150);
  });
  document.getElementById("csv-download").addEventListener("click", csv);

  fetchJson("search/facets.json").then(function (f) {
    facets = f && f.files ? f : null;
    if (state.date === "since_2023q4") { gateLong(); ensureDefault(); return; }
    var plain = !hasTextFilters() && !state.status.length && !state.province.length && state.sort === "newest";
    if (plain) ensureDefault(); else loadSliceThenDefault();
  });
})();
