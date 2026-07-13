(function () {
  var btn = document.getElementById("restart-btn");
  var flashBanner = document.getElementById("flash-banner");
  if (!btn || !flashBanner) return;

  function showFlash(message, isError) {
    flashBanner.innerHTML =
      '<div class="flash' + (isError ? " flash-error" : "") + '">' +
      message.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") +
      "</div>";
  }

  btn.addEventListener("click", function () {
    if (!confirm("Restart the " + btn.dataset.container + " container now? Players will be disconnected.")) {
      return;
    }
    btn.disabled = true;
    btn.textContent = "Restarting…";
    showFlash("Sending restart signal…", false);

    fetch("/restart", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        showFlash(data.error ? "Restart failed: " + data.error : data.message, !!data.error);
      })
      .catch(function () {
        showFlash("Restart failed: could not reach the server.", true);
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = "Restart Server";
        if (window.refreshStatus) window.refreshStatus();
      });
  });
})();
