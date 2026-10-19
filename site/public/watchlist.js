/* Watchlist: the Watch button on an employer profile and the /watchlist page.

   The list is a set of employer IDs kept in this browser's localStorage and
   nowhere else; nothing about it is sent to the site. The page reads each
   watched employer from the same profile shard the profile page uses
   (/data/profiles/<id characters 5 to 7>.json, a static file), so it shows
   nothing the profile does not show.

   What changed since the last visit is found by comparing counts: each load
   stores a small snapshot per employer (postings, Approved LMIA flags, list
   rows on each list, findings, status). A visit ends after an hour without
   opening the page; until then a reload keeps the same baseline, so the marks
   do not vanish on refresh.

   Every storage call sits in try/catch, as in theme.js: a private window or
   blocked storage leaves the button hidden and the page says why. Every word
   the page draws comes from its JSON block (src/pages/watchlist.tsx); the
   profile button carries its two labels as attributes. Data is rendered with
   textContent only. */
(function () {
  var LIST_KEY = "watchlist";
  var VISIT_KEY = "watchlist-visit";
  var VISIT_GAP_MS = 60 * 60 * 1000;
  var CONCURRENCY = 4;
  var CODE_PREFIX = "lw1.";
  var ID_RE = /^emp-[0-9a-f]{10}$/;

  // -- storage ---------------------------------------------------------------

  function storageOk() {
    try {
      localStorage.setItem("watchlist-probe", "1");
      localStorage.removeItem("watchlist-probe");
      return true;
    } catch (e) {
      return false;
    }
  }
  function readJson(key) {
    var raw = null;
    try { raw = localStorage.getItem(key); } catch (e) { return null; }
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (e) { return null; }
  }
  function writeJson(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch (e) { return false; }
  }
  function clean(ids) {
    var seen = {};
    var out = [];
    (Array.isArray(ids) ? ids : []).forEach(function (id) {
      if (typeof id === "string" && ID_RE.test(id) && !seen[id]) { seen[id] = true; out.push(id); }
    });
    return out;
  }
  function readList() { return clean(readJson(LIST_KEY)); }
  function writeList(list) { return writeJson(LIST_KEY, clean(list)); }

  // -- the Watch button on a profile -----------------------------------------

  var toggle = document.getElementById("watch-toggle");
  if (toggle) {
    var employer = toggle.getAttribute("data-employer") || "";
    var maxOnProfile = Number(toggle.getAttribute("data-max")) || 100;
    if (ID_RE.test(employer) && storageOk()) {
      var paint = function () {
        var list = readList();
        var on = list.indexOf(employer) >= 0;
        var full = !on && list.length >= maxOnProfile;
        toggle.setAttribute("aria-pressed", on ? "true" : "false");
        toggle.textContent = toggle.getAttribute(on ? "data-label-on" : full ? "data-label-full" : "data-label-off") || "";
        toggle.disabled = full;
        toggle.classList.toggle("btn-active", on);
      };
      toggle.addEventListener("click", function () {
        var list = readList();
        var at = list.indexOf(employer);
        if (at >= 0) list.splice(at, 1);
        else if (list.length < maxOnProfile) list.unshift(employer);
        writeList(list);
        paint();
      });
      // Another tab may change the list while this profile is open.
      window.addEventListener("storage", function (e) { if (!e.key || e.key === LIST_KEY) paint(); });
      paint();
      toggle.style.display = "";
    }
  }

  // -- the watchlist page ----------------------------------------------------

  var root = document.getElementById("watchlist");
  var rowsEl = document.getElementById("watch-rows");
  if (!root || !rowsEl) return;

  var I18N = {};
  try { I18N = JSON.parse(document.getElementById("i18n").textContent) || {}; } catch (e) { I18N = {}; }
  var STRINGS = I18N.strings || {};
  var LANG = I18N.lang === "fr" ? "fr" : "en";
  var LOCALE = I18N.locale || "en-CA";
  var MAX = Number(I18N.max) || 100;
  var NUMBER = null;
  try { NUMBER = new Intl.NumberFormat(LOCALE); } catch (e) { NUMBER = null; }

  var statusEl = document.getElementById("watch-status");
  var moveEl = document.getElementById("watch-move");
  var moveStatus = document.getElementById("watch-move-status");
  var codeBox = document.getElementById("watch-code-box");
  var codeEl = document.getElementById("watch-code");
  var importText = document.getElementById("watch-import-text");
  var emptyRow = rowsEl.querySelector("tr") ? rowsEl.querySelector("tr").cloneNode(true) : null;
  var loadRun = 0;

  function tx(key, vars) {
    var s = STRINGS[key];
    if (s == null) return key;
    return vars ? s.replace(/\{(\w+)\}/g, function (m, name) { return name in vars ? String(vars[name]) : m; }) : s;
  }
  function txn(one, many, n, vars) {
    var singular = LANG === "fr" ? Math.abs(n) < 2 : n === 1;
    return tx(singular ? one : many, vars);
  }
  function num(n) { return NUMBER ? NUMBER.format(n || 0) : String(n || 0); }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function stamp(ms) {
    var d = new Date(ms);
    if (isNaN(d.getTime())) return "";
    var pad = function (v) { return (v < 10 ? "0" : "") + v; };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }
  function statusLabel(status) {
    var key = "status." + status;
    return STRINGS[key] != null ? tx(key) : tx("status.none");
  }

  // -- export and import codes -----------------------------------------------
  // lw1. then base64url of five bytes per ID (its ten hex digits) and a
  // checksum byte, so a list of ten is about seventy characters. Import also
  // takes any text holding employer IDs, such as pasted profile links.

  function encode(list) {
    var bytes = [];
    list.forEach(function (id) {
      for (var i = 4; i < 14; i += 2) bytes.push(parseInt(id.substr(i, 2), 16));
    });
    var sum = 0;
    bytes.forEach(function (b) { sum = (sum + b) % 256; });
    bytes.push(sum);
    var bin = "";
    bytes.forEach(function (b) { bin += String.fromCharCode(b); });
    return CODE_PREFIX + btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function decode(text) {
    var found = (text || "").toLowerCase().match(/emp-[0-9a-f]{10}/g);
    if (found) return clean(found);
    var compact = (text || "").replace(/\s+/g, "");
    var m = /lw1\.([A-Za-z0-9_-]+)/.exec(compact);
    if (!m) return [];
    var b64 = m[1].replace(/-/g, "+").replace(/_/g, "/");
    while (b64.length % 4) b64 += "=";
    var bin;
    try { bin = atob(b64); } catch (e) { return []; }
    if (bin.length < 6 || (bin.length - 1) % 5 !== 0) return [];
    var sum = 0;
    for (var i = 0; i < bin.length - 1; i++) sum = (sum + bin.charCodeAt(i)) % 256;
    if (sum !== bin.charCodeAt(bin.length - 1)) return [];
    var ids = [];
    for (var j = 0; j < bin.length - 1; j += 5) {
      var hex = "";
      for (var k = j; k < j + 5; k++) hex += (bin.charCodeAt(k) < 16 ? "0" : "") + bin.charCodeAt(k).toString(16);
      ids.push("emp-" + hex);
    }
    return clean(ids);
  }

  // -- snapshots and marks ----------------------------------------------------

  function snapshot(p) {
    var approvedFlags = 0, positive = 0, negative = 0;
    p.postings.forEach(function (x) { if (x && x.approved_seen_at) approvedFlags += 1; });
    p.esdc.forEach(function (x) { if (x && x.list === "positive") positive += 1; else negative += 1; });
    return { p: p.postings.length, a: approvedFlags, y: positive, n: negative, f: p.findings.length, s: p.employer.current_status };
  }
  var MARKS = [
    ["p", "watch.new_postings_one", "watch.new_postings_many"],
    ["a", "watch.new_approved_one", "watch.new_approved_many"],
    ["y", "watch.new_positive_one", "watch.new_positive_many"],
    ["n", "watch.new_negative_one", "watch.new_negative_many"],
    ["f", "watch.new_findings_one", "watch.new_findings_many"],
  ];
  function marks(now, before) {
    var out = [];
    MARKS.forEach(function (m) {
      var diff = (now[m[0]] || 0) - (before[m[0]] || 0);
      if (diff > 0) out.push(txn(m[1], m[2], diff, { n: num(diff) }));
    });
    if (before.s && now.s !== before.s) out.push(tx("watch.status_was", { status: statusLabel(before.s) }));
    return out;
  }

  // -- loading ----------------------------------------------------------------

  function validProfile(p) {
    return p && typeof p === "object" && p.employer && typeof p.employer === "object" &&
      Array.isArray(p.postings) && Array.isArray(p.esdc) && Array.isArray(p.findings);
  }
  // Each shard is fetched once, a few at a time. The result per ID is a
  // profile, "missing" (the shard has no such ID) or "failed" (no answer).
  function fetchProfiles(ids, done) {
    var shards = {};
    ids.forEach(function (id) { (shards[id.slice(4, 7)] = shards[id.slice(4, 7)] || []).push(id); });
    var keys = Object.keys(shards);
    var results = {};
    var next = 0, active = 0;
    if (!keys.length) { done(results); return; }
    function pump() {
      while (active < CONCURRENCY && next < keys.length) {
        (function (key) {
          active += 1;
          fetch("/data/profiles/" + key + ".json")
            .then(function (r) {
              if (r.status === 404) return {};
              if (!r.ok) throw new Error(String(r.status));
              return r.json();
            })
            .then(function (shard) {
              shards[key].forEach(function (id) {
                var p = shard && typeof shard === "object" ? shard[id] : null;
                results[id] = validProfile(p) ? p : "missing";
              });
            }, function () {
              shards[key].forEach(function (id) { results[id] = "failed"; });
            })
            .then(function () {
              active -= 1;
              if (next < keys.length) pump();
              else if (active === 0) done(results);
            });
        })(keys[next++]);
      }
    }
    pump();
  }

  function setCount(list) {
    var line = list.length ? txn("watch.count_one", "watch.count_many", list.length, { n: num(list.length) }) : "";
    return line;
  }

  function showEmpty() {
    rowsEl.textContent = "";
    if (emptyRow) rowsEl.appendChild(emptyRow.cloneNode(true));
  }

  function cell(tr, label, cls) {
    var td = el("td", cls);
    td.setAttribute("data-label", tx(label));
    tr.appendChild(td);
    return td;
  }

  function removeButton(tr, id, name) {
    var td = cell(tr, "watch.col_manage");
    var b = el("button", "btn-link", tx("watch.remove"));
    b.type = "button";
    b.setAttribute("aria-label", tx("watch.remove_aria", { name: name }));
    b.addEventListener("click", function () {
      var list = readList().filter(function (x) { return x !== id; });
      writeList(list);
      if (tr.parentNode) tr.parentNode.removeChild(tr);
      if (!list.length) { showEmpty(); statusEl.textContent = ""; }
      else statusEl.textContent = setCount(list) + " " + (statusEl.getAttribute("data-visit") || "");
    });
    td.appendChild(b);
    return td;
  }

  function positionsText(n) {
    return " " + txn("employer.positions_paren_one", "employer.positions_paren_many", n, { n: num(n) });
  }

  // A cell whose content is one element: on a phone each row restacks as a
  // grid, where every child of a cell would take a grid slot of its own.
  function boxed(tr, label, cls) {
    var box = el("span");
    cell(tr, label, cls).appendChild(box);
    return box;
  }

  function profileRow(id, p, found) {
    var e = p.employer;
    var tr = el("tr");
    var name = e.display_name || id;
    var who = boxed(tr, "col.employer");
    var link = el("a", null, name);
    link.href = "/employers/" + id;
    who.appendChild(link);
    var place = [e.city, e.province].filter(Boolean).join(", ");
    if (place) { who.appendChild(document.createElement("br")); who.appendChild(el("span", "muted small", place)); }
    var st = cell(tr, "col.status");
    st.appendChild(el("span", "badge badge-" + (STRINGS["status." + e.current_status] != null ? e.current_status : "none"), statusLabel(e.current_status)));
    cell(tr, "employer.pending_postings", "mono num").textContent = num(e.pending_count);
    var ap = boxed(tr, "employer.approved_lmias", "mono num");
    ap.textContent = num(e.approved_lmias);
    ap.appendChild(el("span", "muted", positionsText(e.approved_positions || 0)));
    var rf = boxed(tr, "employer.refused_lmias", "mono num");
    rf.textContent = num(e.refused_lmias);
    rf.appendChild(el("span", "muted", positionsText(e.refused_positions || 0)));
    cell(tr, "employer.findings_count", "mono num").textContent = num(e.finding_count);
    cell(tr, "watch.col_latest", "mono").textContent = e.last_seen || "";
    if (found.first) {
      // No earlier visit to compare with: nothing to mark yet. The cell stays
      // empty, so a phone's restacked row leaves it out.
      cell(tr, "watch.col_new");
      removeButton(tr, id, name);
      return tr;
    }
    var news = boxed(tr, "watch.col_new");
    if (found.added) {
      news.appendChild(el("span", "chip", tx("watch.added_since")));
    } else if (found.marks.length) {
      found.marks.forEach(function (m) { news.appendChild(el("span", "chip", m)); });
    } else {
      news.appendChild(el("span", "muted", tx("watch.nothing_new")));
    }
    removeButton(tr, id, name);
    return tr;
  }

  function problemRow(id, message) {
    var tr = el("tr");
    cell(tr, "col.employer").appendChild(el("span", "mono id", id));
    var td = cell(tr, "watch.col_new", "muted");
    td.colSpan = 7;
    td.textContent = message;
    removeButton(tr, id, id);
    return tr;
  }

  function load() {
    var run = ++loadRun;
    var list = readList();
    var visit = readJson(VISIT_KEY);
    if (!visit || typeof visit !== "object" || typeof visit.t !== "number") visit = null;
    var now = Date.now();
    var base = null, prev = null;
    if (visit && now - visit.t > VISIT_GAP_MS) { base = visit.snap || {}; prev = visit.t; }
    else if (visit) { base = visit.base || null; prev = visit.prev || null; }
    var visitLine = base && prev ? tx("watch.last_visit", { date: stamp(prev) }) : tx("watch.first_visit");
    statusEl.setAttribute("data-visit", visitLine);

    if (!list.length) {
      showEmpty();
      statusEl.textContent = "";
      writeJson(VISIT_KEY, { t: now, prev: prev, base: base, snap: {} });
      return;
    }
    statusEl.textContent = tx("watch.loading", { n: num(list.length) });
    fetchProfiles(list, function (results) {
      if (run !== loadRun) return;
      var snap = {};
      var oldSnap = (visit && visit.snap) || {};
      var rows = [];
      list.forEach(function (id, order) {
        var r = results[id];
        if (r === "missing") { rows.push({ order: order, rank: 2, tr: problemRow(id, tx("watch.missing", { id: id })) }); return; }
        if (!r || r === "failed") {
          if (oldSnap[id]) snap[id] = oldSnap[id];
          rows.push({ order: order, rank: 2, tr: problemRow(id, tx("watch.load_failed")) });
          return;
        }
        var now2 = snapshot(r);
        snap[id] = now2;
        var found = { first: !base, added: !!base && !base[id], marks: base && base[id] ? marks(now2, base[id]) : [] };
        var changed = found.added || found.marks.length > 0;
        rows.push({ order: order, rank: changed ? 0 : 1, name: (r.employer.display_name || id).toLowerCase(), tr: profileRow(id, r, found) });
      });
      // Changed employers first, then the rest by name; problems last, in list order.
      rows.sort(function (a, b) {
        if (a.rank !== b.rank) return a.rank - b.rank;
        if (a.rank === 2) return a.order - b.order;
        return a.name.localeCompare(b.name, LOCALE);
      });
      rowsEl.textContent = "";
      rows.forEach(function (r) { rowsEl.appendChild(r.tr); });
      statusEl.textContent = setCount(list) + " " + visitLine;
      writeJson(VISIT_KEY, { t: now, prev: prev, base: base, snap: snap });
    });
  }

  if (!storageOk()) {
    statusEl.textContent = tx("watch.no_storage");
    return;
  }
  moveEl.hidden = false;

  document.getElementById("watch-export").addEventListener("click", function () {
    var list = readList();
    if (!list.length) {
      codeBox.hidden = true;
      moveStatus.textContent = tx("watch.export_empty");
      return;
    }
    codeEl.value = encode(list);
    codeBox.hidden = false;
    moveStatus.textContent = "";
    codeEl.focus();
    codeEl.select();
  });

  document.getElementById("watch-import").addEventListener("click", function () {
    var ids = decode(importText.value);
    if (!ids.length) { moveStatus.textContent = tx("watch.import_none"); return; }
    var list = readList();
    var fresh = ids.filter(function (id) { return list.indexOf(id) < 0; });
    if (!fresh.length) { moveStatus.textContent = tx("watch.import_known"); return; }
    var room = Math.max(0, MAX - list.length);
    var added = fresh.slice(0, room);
    writeList(list.concat(added));
    var msg = added.length ? txn("watch.import_one", "watch.import_many", added.length, { n: num(added.length) }) : "";
    if (fresh.length > room) msg = (msg ? msg + " " : "") + tx("watch.import_full", { max: num(MAX) });
    moveStatus.textContent = msg;
    importText.value = "";
    codeBox.hidden = true;
    load();
  });

  window.addEventListener("storage", function (e) { if (!e.key || e.key === LIST_KEY) load(); });
  load();
})();
