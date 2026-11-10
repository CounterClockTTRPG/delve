// The browser's look (web/src/looks/looks.ts), set before the first paint. A file, because the CSP allows no inline script.
// Print views never follow the look, so they get no attribute.
(function () {
  try {
    if (/\/print\/?$/.test(window.location.pathname)) return;
    var look = window.localStorage.getItem("delve.look");
    if (look === "gold-wood" || look === "dark-dungeon") document.documentElement.setAttribute("data-look", look);
  } catch (e) {}
})();
