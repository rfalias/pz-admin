(function () {
  var MOBILE_QUERY = "(max-width: 880px)";
  var STORAGE_KEY = "pzadmin-sidebar-collapsed";

  var toggle = document.getElementById("sidebar-toggle");
  var sidebar = document.getElementById("sidebar");
  var backdrop = document.getElementById("sidebar-backdrop");
  if (!toggle || !sidebar || !backdrop) return;

  function isMobile() {
    return window.matchMedia(MOBILE_QUERY).matches;
  }

  function setExpandedAttr() {
    var open = isMobile()
      ? document.body.classList.contains("sidebar-open")
      : !document.documentElement.classList.contains("sidebar-collapsed");
    toggle.setAttribute("aria-expanded", String(open));
  }

  function openMobile() {
    document.body.classList.add("sidebar-open");
    setExpandedAttr();
  }

  function closeMobile() {
    document.body.classList.remove("sidebar-open");
    setExpandedAttr();
  }

  function toggleDesktop() {
    var collapsed = document.documentElement.classList.toggle("sidebar-collapsed");
    localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
    setExpandedAttr();
  }

  toggle.addEventListener("click", function () {
    if (isMobile()) {
      if (document.body.classList.contains("sidebar-open")) {
        closeMobile();
      } else {
        openMobile();
      }
    } else {
      toggleDesktop();
    }
  });

  backdrop.addEventListener("click", closeMobile);

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeMobile();
  });

  sidebar.querySelectorAll("a").forEach(function (link) {
    link.addEventListener("click", function () {
      if (isMobile()) closeMobile();
    });
  });

  window.addEventListener("resize", function () {
    if (!isMobile()) closeMobile();
    setExpandedAttr();
  });

  setExpandedAttr();
})();
