/* Search page.

   Interaction model: the server renders the first view, from the search
   database when it answers (rows, total, filter counts, a link to the next
   page), else from search/first.json with a sentence saying search is
   unavailable. This script then answers every change through /api/search:
   a filter, the sort or a page button fetches one page of 50 rows, typed
   text after a pause. Pages are keyset pages with no page numbers in the
   API, so Next sends the cursor of the last answer and Previous the cursor
   kept for the page before. When the API cannot answer (503, a network
   failure), the rows on screen stay and a sentence says why.

   Everything rendered from data uses textContent. Every word the script
   draws comes from the page's <script type="application/json" id="i18n">
   block (rendered by src/pages/search.tsx from src/i18n.ts), so the script
   holds no copy of its own in either language. */
(function () {
  var results = document.getElementById("results");
  var form = document.getElementById("search-form");
  if (!results || !form) return;
  var PAGE = 50;          // the API's page size (PAGE_SIZE in src/search_db.ts)
  // A word found in many names costs the database a large read, so typed
  // text is sent once the typing pauses, not on every key.
  var TYPING_MS = 300;
  var TEXT_FIELDS = /^(q|noc|wage_min|wage_max)$/;
  // The parameters the API can name as ignored, and the value a radio or
  // select returns to when its own is dropped.
  var PARAMS = ["q", "status", "province", "stream", "noc", "wage_min", "wage_max", "date", "year_from", "year_to", "indicator", "sort"];
  var RESET = { date: "any", indicator: "", sort: "newest" };
  var CSV_COLUMNS = ["status", "employer", "employer_id", "job", "noc", "street", "city", "prov", "postal", "wage_min", "wage_max", "unit", "date", "period", "positions", "stream", "source"];
  var I18N = {};
  try { I18N = JSON.parse(document.getElementById("i18n").textContent) || {}; } catch (e) { I18N = {}; }
  var STRINGS = I18N.strings || {};
  var LANG = I18N.lang === "fr" ? "fr" : "en";
  var LOCALE = I18N.locale || "en-CA";
  var SINCE = results.getAttribute("data-since") || "";

  // live: the rows on screen answer the form (the server's database view, or
  // an API answer). Otherwise they are the fallback's newest rows, and its
  // page links stay plain links until the API answers.
  var live = results.getAttribute("data-mode") === "db";
  var state = readForm();
  // The page on screen: its number when known, its cursor (null for the
  // first page), the cursors of the pages before it, the next page's cursor,
  // and the first page's total, which a later page does not always repeat.
  var page = live ? (parseInt(results.getAttribute("data-page") || "", 10) || null) : 1;
  var cursor = live ? (results.getAttribute("data-cursor") || null) : null;
  var next = live ? (results.getAttribute("data-next") || null) : null;
  var stack = live && cursor && page === 2 ? [null] : [];
  var totalAttr = results.getAttribute("data-total") || "";
  var total = live && /^\d+$/.test(totalAttr) ? parseInt(totalAttr, 10) : null;
  var capped = results.getAttribute("data-capped") === "1";
  var current = null;     // the rows of the last API answer, for the CSV
  var shownKey = live ? keyOf(state, cursor) : null;
  var pendingKey = null;
  var seq = 0;
  var inflight = null;

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
  function fmt(n) { return (n || 0).toLocaleString(LOCALE); }
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

  // -- state from the form and the URL ---------------------------------------

  function readForm() {
    var fd = new FormData(form);
    var text = function (name) { return (fd.get(name) || "").toString().trim(); };
    var all = function (name) { return fd.getAll(name).map(String); };
    return {
      q: text("q"), status: all("status"), province: all("province"), stream: all("stream"), noc: text("noc"),
      wage_min: text("wage_min"), wage_max: text("wage_max"), date: text("date") || "any",
      year_from: text("year_from"), year_to: text("year_to"), indicator: text("indicator"), sort: text("sort") || "newest",
    };
  }
  // The filters as URL parameters, in the order the server writes its links
  // (searchParamsOf in src/pages/search.tsx), so the API and the address bar
  // see the same thing.
  function filterParams(s) {
    var p = new URLSearchParams();
    if (s.q) p.set("q", s.q);
    s.status.forEach(function (v) { p.append("status", v); });
    s.province.forEach(function (v) { p.append("province", v); });
    s.stream.forEach(function (v) { p.append("stream", v); });
    if (s.noc) p.set("noc", s.noc);
    if (s.wage_min) p.set("wage_min", s.wage_min);
    if (s.wage_max) p.set("wage_max", s.wage_max);
    if (s.date !== "any") p.set("date", s.date);
    if (s.year_from) p.set("year_from", s.year_from);
    if (s.year_to) p.set("year_to", s.year_to);
    if (s.indicator) p.set("indicator", s.indicator);
    if (s.sort !== "newest") p.set("sort", s.sort);
    return p;
  }
  function keyOf(s, c) {
    var p = filterParams(s);
    if (c) p.set("cursor", c);
    return p.toString();
  }
  // The page number travels with the cursor only for display: the cursor
  // alone says where the page starts.
  function writeUrl() {
    var p = filterParams(state);
    if (cursor) {
      p.set("cursor", cursor);
      if (page) p.set("page", String(page));
    }
    var url = new URL(location.href);
    url.search = p.toString();
    history.replaceState(null, "", url.toString());
  }

  // -- rendering -------------------------------------------------------------

  // Column headers as data-label on every cell, so a phone restacks each row
  // as a labelled block. Same labels, short forms and titles as SearchRowView
  // in src/pages/search.tsx, so a row drawn here matches the server's.
  var COLUMN = {
    status: tx("col.status"), employer: tx("col.employer"), job: tx("places.col_occupation"), location: tx("col.location"),
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
  // A line-break opportunity after each slash of a title ("foreman/woman"),
  // as slashBreaks in src/layout.tsx gives the server's rows.
  function slashText(el, s) {
    s.split("/").forEach(function (part, i) {
      if (i) {
        el.appendChild(document.createTextNode("/"));
        el.appendChild(document.createElement("wbr"));
      }
      if (part) el.appendChild(document.createTextNode(part));
    });
  }
  // City, province and postal code in the cell; the full address, street
  // included, in its title (placeLabel and addressLabel in search.tsx).
  function place(r, withStreet) {
    return [withStreet ? r.street : null, r.city, r.prov].filter(Boolean).join(", ") + (r.postal ? " " + r.postal : "");
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
      var tdJ = cell(tr, r.kind === "esdc" && r.noc ? r.noc + " " : "", null, COLUMN.job);
      slashText(tdJ, r.job || "");
      var tdL = cell(tr, place(r, false), null, COLUMN.location);
      if (r.street) tdL.title = place(r, true);
      cell(tr, wage(r), "mono", COLUMN.wage);
      cell(tr, r.kind === "posting" ? (r.date || "") : periodLabel(r.period), r.kind === "posting" ? "mono" : "mono period", COLUMN.date);
      cell(tr, r.positions == null ? tx("common.see_posting") : fmt(r.positions), "mono", COLUMN.positions);
      var tdI = td(COLUMN.indicators);
      if ((r.ind || []).length) {
        var chips = document.createElement("span");
        chips.className = "chips";
        r.ind.forEach(function (i) {
          var chip = document.createElement("span");
          var full = has("ind." + i) ? tx("ind." + i) : i;
          var short = has("ind_short." + i) ? tx("ind_short." + i) : full;
          chip.className = "chip";
          chip.textContent = short;
          if (short !== full) chip.title = full;
          chips.appendChild(chip);
        });
        tdI.appendChild(chips);
      }
      tr.appendChild(tdI);
      var tdSrc = td(COLUMN.source);
      var src = document.createElement("a");
      src.href = r.source; src.rel = "nofollow noopener"; src.className = "mono";
      src.title = r.kind === "posting"
        ? tx("search.source_jobbank", { ref: r.ref })
        : tx(r.status === "refused" ? "search.source_negative" : "search.source_positive", { period: r.period || "" });
      src.textContent = r.kind === "posting" ? tx("search.source_jobbank_short") : tx("search.source_esdc_short");
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
  // The API stops counting at 10,000 and says so with capped.
  function totalText() {
    if (total == null) return "";
    return capped ? tx("search.total_capped", { n: fmt(total) }) : fmt(total);
  }
  function renderCount() {
    var count = document.getElementById("results-count");
    count.textContent = "";
    var strong = document.createElement("strong");
    strong.textContent = total == null ? ""
      : capped ? tx("search.records_capped", { n: fmt(total) })
      : txn("search.records_one", "search.records_many", total, { n: fmt(total) });
    count.appendChild(strong);
    count.appendChild(document.createTextNode(" "));
    var note = document.createElement("span");
    note.className = "muted"; note.id = "results-note";
    note.textContent = tx("search.note_all", { year: SINCE });
    count.appendChild(note);
  }
  function renderPaging() {
    var shown = current ? current.length : 0;
    var from = page ? (page - 1) * PAGE + 1 : 0;
    document.getElementById("page-range").textContent = page && total != null && shown
      ? tx("search.showing", { from: fmt(from), to: fmt(from + shown - 1), total: totalText() })
      : "";
    var pages = total != null && !capped ? Math.max(1, Math.ceil(total / PAGE)) : 0;
    document.getElementById("page-label").textContent = !page ? ""
      : pages ? tx("search.page_of", { page: page, pages: pages }) : tx("search.page", { page: page });
    wireButtons();
  }
  // The server renders each page control as a link (a page it can serve) or
  // as a plain button. Once the rows answer the form, both become buttons
  // that page through the API, each wired once.
  function wireButtons() {
    ["page-prev", "page-next"].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      var b = el;
      if (el.tagName === "A") {
        b = document.createElement("button");
        b.type = "button"; b.className = "btn"; b.id = id; b.textContent = el.textContent;
        el.replaceWith(b);
      }
      if (!b.getAttribute("data-wired")) {
        b.setAttribute("data-wired", "1");
        b.addEventListener("click", id === "page-prev" ? back : forward);
      }
    });
    document.getElementById("page-prev").disabled = !stack.length;
    document.getElementById("page-next").disabled = !next;
  }
  // One sentence above the table while the API cannot answer: the fallback's
  // own (the newest rows are on screen) until an answer has replaced them,
  // then one saying the rows predate the change.
  function unavailable(on) {
    var note = document.getElementById("search-unavailable");
    if (!on) { if (note) note.remove(); return; }
    if (!note) {
      note = document.createElement("p");
      note.id = "search-unavailable"; note.className = "panel bordered"; note.setAttribute("role", "status");
      results.insertBefore(note, results.querySelector(".table-wrap"));
    }
    note.textContent = live ? tx("search.unavailable_kept") : tx("search.unavailable");
  }
  // A parameter the API dropped is cleared from its control, so the form
  // shows the filters the rows answer. A text field the visitor has typed
  // on since the request left keeps what it holds now.
  function clearIgnored(names, sent) {
    names.forEach(function (name) {
      if (PARAMS.indexOf(name) < 0) return;
      form.querySelectorAll('[name="' + name + '"]').forEach(function (el) {
        if (el.type === "checkbox") el.checked = false;
        else if (el.type === "radio") el.checked = el.value === RESET[name];
        else if (el.value.trim() === String(sent[name] || "")) el.value = RESET[name] || "";
      });
    });
    state = readForm();
  }

  // -- requests --------------------------------------------------------------

  // target: the page to show, as { cursor, page, stack }. Only the newest
  // request counts; an older one still on its way is cancelled or ignored.
  function load(target) {
    var sent = state;
    var key = keyOf(sent, target.cursor);
    if (key === shownKey || key === pendingKey) return;
    seq += 1;
    var mine = seq;
    if (inflight) inflight.abort();
    inflight = typeof AbortController === "function" ? new AbortController() : null;
    pendingKey = key;
    // A plain same-origin fetch: the browser marks it Sec-Fetch-Site
    // same-origin, which is what the API's page-only check accepts.
    fetch("/api/search?" + key, inflight ? { signal: inflight.signal } : {})
      .then(function (res) {
        // A cursor the API refuses (the data changed under an old address):
        // the first page of the same filters.
        if (res.status === 400 && target.cursor) return { retry: true };
        if (!res.ok) throw new Error("search " + res.status);
        return res.json();
      })
      .then(function (body) {
        if (mine !== seq) return;
        pendingKey = null;
        if (body && body.retry) { load({ cursor: null, page: 1, stack: [] }); return; }
        if (!body || !Array.isArray(body.rows)) throw new Error("search answer");
        show(body, target, sent);
      })
      .catch(function (e) {
        if (mine !== seq || (e && e.name === "AbortError")) return;
        pendingKey = null;
        unavailable(true);
      });
  }
  function show(body, target, sent) {
    cursor = target.cursor; page = target.page; stack = target.stack;
    next = typeof body.next === "string" && body.next ? body.next : null;
    if (!cursor || typeof body.total === "number") {
      total = typeof body.total === "number" ? body.total : null;
      capped = !!body.capped;
    }
    live = true;
    current = body.rows;
    if (Array.isArray(body.ignored) && body.ignored.length) clearIgnored(body.ignored, sent);
    shownKey = keyOf(state, cursor);
    if (body.facets) setCounts(body.facets.status || {}, body.facets.prov || {});
    renderRows(body.rows);
    renderCount();
    renderPaging();
    unavailable(false);
    writeUrl();
  }
  function forward() {
    if (next) load({ cursor: next, page: page ? page + 1 : null, stack: stack.concat([cursor]) });
  }
  function back() {
    if (stack.length) load({ cursor: stack[stack.length - 1], page: page ? page - 1 : null, stack: stack.slice(0, -1) });
  }

  // -- CSV -------------------------------------------------------------------

  // The rows on screen. Rows the server drew are fetched again as data; the
  // fallback's rows cannot be, so the downloads page has them instead.
  function csv() {
    if (current) { save(current); return; }
    if (!live) { location.href = "/data#downloads"; return; }
    fetch("/api/search?" + keyOf(state, cursor))
      .then(function (r) { if (!r.ok) throw new Error("search " + r.status); return r.json(); })
      .then(function (body) { if (!body || !Array.isArray(body.rows)) throw new Error("search answer"); save(body.rows); })
      .catch(function () { location.href = "/data#downloads"; });
  }
  function save(rows) {
    var esc = function (v) { var s = v == null ? "" : String(v); return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    var lines = [CSV_COLUMNS.join(",")].concat(rows.map(function (r) { return CSV_COLUMNS.map(function (c) { return esc(r[c]); }).join(","); }));
    var blob = new Blob([lines.join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "lmia-watch-search.csv";
    document.body.appendChild(a); a.click(); a.remove();
  }

  // -- wiring ----------------------------------------------------------------

  var typing = null;
  // Any new filter or sort starts again from the first page.
  function onFilters() {
    clearTimeout(typing);
    state = readForm();
    load({ cursor: null, page: 1, stack: [] });
  }
  // On a phone the filters sit between the box and the rows, so a submit
  // also closes the keyboard and brings the answer into view: the rows when
  // the fold is open, else the box, with the fold's line and the first rows
  // under it.
  var PHONE = typeof matchMedia === "function" ? matchMedia("(max-width: 700px)") : null;
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    onFilters();
    if (!PHONE || !PHONE.matches) return;
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    var fold = document.getElementById("filters-open");
    var target = fold && fold.checked ? results : form.querySelector(".search-form");
    if (target) target.scrollIntoView({ block: "start" });
  });
  // A text field's own change (on leaving it) usually repeats what its pause
  // already sent; load() skips a request that is on screen or on its way.
  // The fold's checkbox has no name: opening the filters is not a filter.
  form.addEventListener("change", function (e) {
    if (e.target && e.target.name) onFilters();
  });
  form.addEventListener("input", function (e) {
    if (!e.target || !TEXT_FIELDS.test(e.target.name || "")) return;
    clearTimeout(typing);
    typing = setTimeout(onFilters, TYPING_MS);
  });
  document.getElementById("csv-download").addEventListener("click", csv);

  if (live) wireButtons();
  // Nothing on screen (neither the database nor the fallback file answered
  // the server): the API may answer now.
  else if (results.getAttribute("data-ssr") === "0") load({ cursor: null, page: 1, stack: [] });
})();
