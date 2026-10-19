/* Links that leave the site open in a new tab, so a reader keeps their place
   here. Internal links stay in the same tab. Rows that scripts render later
   (search results, the watchlist) are covered by watching the document.
   rel="noopener" goes with target so the new page gets no handle on this one. */
(function () {
  var here = location.hostname.replace(/^www\./, "");
  function external(a) {
    var host;
    try { host = new URL(a.getAttribute("href"), location.href); } catch (e) { return false; }
    if (host.protocol !== "https:" && host.protocol !== "http:") return false;
    return host.hostname.replace(/^www\./, "") !== here;
  }
  function mark(root) {
    var links = (root || document).querySelectorAll("a[href]");
    for (var i = 0; i < links.length; i++) {
      var a = links[i];
      if (a.target || !external(a)) continue;
      a.target = "_blank";
      a.rel = a.rel && a.rel.indexOf("noopener") >= 0 ? a.rel : (a.rel ? a.rel + " " : "") + "noopener";
    }
  }
  function start() {
    mark();
    if (typeof MutationObserver === "undefined") return;
    var pending = null;
    new MutationObserver(function () {
      if (pending) return;
      pending = setTimeout(function () { pending = null; mark(); }, 50);
    }).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
