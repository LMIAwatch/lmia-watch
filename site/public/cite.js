/* Copy buttons for the citation blocks on /cite. Without this script each
   block is still plain text a reader can select. The button words come from
   the page (data-copy, data-copied), so the script holds no copy of its own. */
(function () {
  var root = document.querySelector(".cite-page");
  if (!root || !navigator.clipboard || !navigator.clipboard.writeText) return;
  var label = root.getAttribute("data-copy") || "";
  var done = root.getAttribute("data-copied") || "";
  Array.prototype.forEach.call(root.querySelectorAll("pre.cite-block"), function (pre) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn cite-copy";
    button.textContent = label;
    var heading = pre.previousElementSibling;
    if (heading && heading.id) button.setAttribute("aria-describedby", heading.id);
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(pre.textContent).then(function () {
        button.textContent = done;
        setTimeout(function () { button.textContent = label; }, 2000);
      }, function () {});
    });
    pre.parentNode.insertBefore(button, pre.nextSibling);
  });
})();
