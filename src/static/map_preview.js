/* Shared hover-triggered map preview, backed by /shops/map-preview (a
   server-stitched crop of the official PZ map - see map_preview.py). Used
   by any page with map coordinates: call MapPreview.bindStaticLinks(sel)
   for fixed data-x/data-y links, or MapPreview.bind(el, {getX, getY, ...})
   for coordinates that can change (e.g. live-editable inputs). */
window.MapPreview = (function () {
  var backdrop, img, link, coords, closeBtn;
  var showTimer = null;
  var currentKey = null;
  var ready = false;

  function init() {
    if (ready) return;
    backdrop = document.getElementById("map-hover-backdrop");
    if (!backdrop) return;
    img = document.getElementById("map-hover-preview-img");
    link = document.getElementById("map-hover-preview-link");
    coords = document.getElementById("map-hover-preview-coords");
    closeBtn = document.getElementById("map-hover-preview-close");

    backdrop.addEventListener("mousedown", function (e) {
      if (e.target === backdrop) hide();
    });
    closeBtn.addEventListener("click", hide);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && backdrop.classList.contains("is-open")) hide();
    });
    ready = true;
  }

  function defaultUrl(x, y) {
    return "https://map.projectzomboid.com/?" + x + "x" + y + "x14";
  }

  function hide() {
    if (showTimer) { clearTimeout(showTimer); showTimer = null; }
    if (backdrop) backdrop.classList.remove("is-open");
  }

  function show(x, y, label, url) {
    init();
    if (!ready) return;
    var key = x + "," + y;
    if (currentKey !== key) {
      img.src = "/shops/map-preview?x=" + encodeURIComponent(x) + "&y=" + encodeURIComponent(y);
      link.href = url || defaultUrl(x, y);
      coords.textContent = label || (x + ", " + y);
      currentKey = key;
    }
    backdrop.classList.add("is-open");
  }

  function bind(el, opts) {
    el.addEventListener("mouseenter", function () {
      if (showTimer) clearTimeout(showTimer);
      showTimer = setTimeout(function () {
        var x = opts.getX();
        var y = opts.getY();
        if (x === null || x === undefined || x === "" || y === null || y === undefined || y === "") return;
        show(x, y, opts.getLabel ? opts.getLabel() : null, opts.getUrl ? opts.getUrl() : null);
      }, 500);
    });
    el.addEventListener("mouseleave", function () {
      if (showTimer) { clearTimeout(showTimer); showTimer = null; }
    });
  }

  function bindStaticLinks(selector) {
    document.querySelectorAll(selector).forEach(function (el) {
      bind(el, {
        getX: function () { return el.getAttribute("data-x"); },
        getY: function () { return el.getAttribute("data-y"); },
        getLabel: function () { return el.textContent.trim(); },
        getUrl: function () { return el.getAttribute("href") || el.getAttribute("data-href"); },
      });
    });
  }

  /* For editable coordinate fields: reads the live .value of the given
     inputs at hover-time, so it always previews the current (possibly
     unsaved) x/y. */
  function bindInputs(el, xInput, yInput, zInput) {
    bind(el, {
      getX: function () { return xInput.value; },
      getY: function () { return yInput.value; },
      getLabel: function () {
        return xInput.value + ", " + yInput.value + ", " + (zInput ? zInput.value : "0");
      },
    });
  }

  document.addEventListener("DOMContentLoaded", init);

  return { bind: bind, bindStaticLinks: bindStaticLinks, bindInputs: bindInputs };
})();
