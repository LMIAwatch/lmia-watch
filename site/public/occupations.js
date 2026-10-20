/* Type-to-filter on the occupations index. Each row carries its code and
   both language titles in data-occ; a category with no matching row is
   hidden. Accents are folded, so "cuisiniere" finds "Cuisiniers/cuisinieres"
   whichever way it is typed. The box stays hidden without this script, and
   the category links beside the list still work. */
(function () {
  var box = document.getElementById("occ-filter-box");
  var input = document.getElementById("occ-filter");
  var status = document.getElementById("occ-filter-status");
  if (!box || !input) return;
  function fold(s) {
    s = (s || "").toLowerCase();
    return s.normalize ? s.normalize("NFD").replace(/[̀-ͯ]/g, "") : s;
  }
  var sections = Array.prototype.slice.call(document.querySelectorAll("section[data-cat]"));
  var groups = sections.map(function (section) {
    var rows = Array.prototype.slice.call(section.querySelectorAll("tr[data-occ]"));
    return { section: section, rows: rows.map(function (tr) { return { tr: tr, key: fold(tr.getAttribute("data-occ")) }; }) };
  });
  var total = groups.reduce(function (n, g) { return n + g.rows.length; }, 0);
  function apply() {
    var q = fold(input.value.replace(/^\s+|\s+$/g, ""));
    var shown = 0;
    groups.forEach(function (g) {
      var inGroup = 0;
      g.rows.forEach(function (r) {
        var match = !q || r.key.indexOf(q) >= 0;
        r.tr.style.display = match ? "" : "none";
        if (match) inGroup += 1;
      });
      g.section.style.display = inGroup ? "" : "none";
      shown += inGroup;
    });
    if (!status) return;
    if (!q) status.textContent = "";
    else if (!shown) status.textContent = input.getAttribute("data-none") || "";
    else status.textContent = (input.getAttribute("data-count") || "__N__/__TOTAL__").replace("__N__", String(shown)).replace("__TOTAL__", String(total));
  }
  input.addEventListener("input", apply);
  box.hidden = false;
  if (input.value) apply();
})();
