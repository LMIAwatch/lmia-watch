// Theme switch. Runs in the head, before the first paint, so a saved choice
// never flashes the other scheme. With no saved choice the stylesheet follows
// the system setting. The choice is a per-viewer convenience kept in this
// browser only; nothing about it is sent anywhere.
(function () {
  var root = document.documentElement;
  root.classList.add("js");
  var saved = null;
  try { saved = localStorage.getItem("theme"); } catch (e) {}
  if (saved === "dark" || saved === "light") root.setAttribute("data-theme", saved);

  function current() {
    var set = root.getAttribute("data-theme");
    if (set === "dark" || set === "light") return set;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  // Delegated, because the button is rendered after this script runs.
  document.addEventListener("click", function (e) {
    var target = e.target;
    var button = target && target.closest ? target.closest(".theme-toggle") : null;
    if (!button) return;
    var next = current() === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch (e) {}
  });
})();
