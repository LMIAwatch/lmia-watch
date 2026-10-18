/* Map page: clusters from /data/clusters/<scope>.json, area listings from
   /data/areas/<FSA>.json. Everything rendered from the files goes through
   textContent, never innerHTML. Every word the script draws comes from the
   page's <script type="application/json" id="i18n"> block (rendered by
   src/pages/map.tsx from src/i18n.ts). */
(function () {
  if (typeof L === "undefined") return;
  var controls = document.getElementById("map-controls");
  var map = L.map("map", { center: [56, -96], zoom: 4, minZoom: 3, maxZoom: 14 });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  }).addTo(map);
  var layer = L.layerGroup().addTo(map);
  var I18N = {};
  try { I18N = JSON.parse(document.getElementById("i18n").textContent) || {}; } catch (e) { I18N = {}; }
  var STRINGS = I18N.strings || {};
  var LOCALE = I18N.locale || "en-CA";
  // A string from the page's dictionary, with {name} filled from vars.
  function tx(key, vars) {
    var s = STRINGS[key];
    if (s == null) return key;
    return vars ? s.replace(/\{(\w+)\}/g, function (m, name) { return name in vars ? String(vars[name]) : m; }) : s;
  }
  function fmt(n) { return (n || 0).toLocaleString(LOCALE); }
  // Column headers as data-label, so the area list restacks on a phone (same
  // words as the table header in src/pages/map.tsx).
  var COLUMN = { status: tx("col.status"), employer: tx("col.employer"), job: tx("col.job"), date: tx("col.date") };

  function statuses() {
    var out = [];
    controls.querySelectorAll('input[name="status"]:checked').forEach(function (el) { out.push(el.value); });
    return out;
  }
  function scope() { return controls.querySelector('select[name="period"]').value; }

  function load() {
    var wanted = statuses();
    fetch("/data/clusters/" + encodeURIComponent(scope()) + ".json")
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (clusters) {
        layer.clearLayers();
        clusters.forEach(function (c) {
          var total = 0;
          wanted.forEach(function (s) { total += c[s] || 0; });
          if (!total) return;
          var size = Math.max(26, Math.min(70, 18 + Math.sqrt(total) * 6));
          var icon = L.divIcon({ className: "", html: "", iconSize: [size, size] });
          var marker = L.marker([c.lat, c.lon], { icon: icon, title: tx("map.cluster_title", { fsa: c.fsa, n: fmt(total) }) });
          marker.on("add", function () {
            var el = marker.getElement();
            if (!el) return;
            el.className += " cluster-icon";
            el.textContent = fmt(total);
            el.setAttribute("role", "button");
            el.setAttribute("aria-label", tx("map.cluster_label", { fsa: c.fsa, n: fmt(total) }));
          });
          marker.on("click", function () { showArea(c.fsa); });
          marker.addTo(layer);
        });
      });
  }

  function showArea(fsa) {
    fetch("/data/areas/" + encodeURIComponent(fsa) + ".json")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        document.getElementById("area-title").textContent = tx("map.area_title", { fsa: data.fsa, prov: data.prov });
        var wanted = statuses();
        var rows = (data.rows || []).filter(function (r) { return wanted.indexOf(r.status) >= 0; });
        document.getElementById("area-summary").textContent = tx("map.area_summary", { shown: fmt(rows.length), total: fmt(data.total) });
        var panel = document.getElementById("area-panel");
        if (panel.getBoundingClientRect().top > window.innerHeight - 80) {
          panel.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        var body = document.getElementById("area-rows");
        body.textContent = "";
        rows.forEach(function (r) {
          var tr = document.createElement("tr");
          var tdStatus = document.createElement("td");
          tdStatus.setAttribute("data-label", COLUMN.status);
          var badge = document.createElement("span");
          badge.className = "badge badge-" + r.status;
          badge.textContent = STRINGS["status." + r.status] != null ? tx("status." + r.status) : r.status;
          tdStatus.appendChild(badge);
          var tdEmp = document.createElement("td");
          tdEmp.setAttribute("data-label", COLUMN.employer);
          var a = document.createElement("a");
          a.href = "/employers/" + encodeURIComponent(r.employer_id);
          a.textContent = r.employer || "";
          tdEmp.appendChild(a);
          var tdJob = document.createElement("td");
          tdJob.setAttribute("data-label", COLUMN.job);
          tdJob.textContent = r.job || "";
          var tdDate = document.createElement("td");
          tdDate.setAttribute("data-label", COLUMN.date);
          tdDate.className = "mono";
          tdDate.textContent = r.date || r.period || "";
          tr.appendChild(tdStatus); tr.appendChild(tdEmp); tr.appendChild(tdJob); tr.appendChild(tdDate);
          body.appendChild(tr);
        });
        document.getElementById("area-list-link").href = "/search?q=" + encodeURIComponent(data.fsa);
        map.setView([data.lat, data.lon], Math.max(map.getZoom(), 9));
      });
  }

  controls.addEventListener("change", load);
  var locate = document.getElementById("locate");
  if (locate && navigator.geolocation) {
    locate.addEventListener("click", function () {
      navigator.geolocation.getCurrentPosition(function (pos) {
        map.setView([pos.coords.latitude, pos.coords.longitude], 10);
      });
    });
  } else if (locate) {
    locate.disabled = true;
  }
  load();
  var preset = controls.getAttribute("data-fsa");
  if (preset) showArea(preset);
})();
