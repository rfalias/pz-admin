(function () {
  var badge = document.getElementById("status-badge");
  if (!badge) return;
  var dot = badge.querySelector(".status-dot");
  var text = badge.querySelector(".status-text");

  function relativeTime(iso) {
    if (!iso) return "";
    var started = new Date(iso).getTime();
    if (isNaN(started)) return "";
    var diffSec = Math.max(0, Math.floor((Date.now() - started) / 1000));
    var units = [
      ["d", 86400],
      ["h", 3600],
      ["m", 60],
    ];
    for (var i = 0; i < units.length; i++) {
      var value = Math.floor(diffSec / units[i][1]);
      if (value > 0) return "up " + value + units[i][0];
    }
    return "up " + diffSec + "s";
  }

  function refreshStatus() {
    fetch("/status/raw")
      .then(function (resp) { return resp.ok ? resp.json() : null; })
      .then(function (data) {
        if (!data) return;
        badge.classList.remove("status-running", "status-stopped", "status-unknown");
        if (data.status === "running") {
          badge.classList.add("status-running");
          var uptime = relativeTime(data.started_at);
          text.textContent = "running" + (uptime ? " (" + uptime + ")" : "");
        } else if (data.error) {
          badge.classList.add("status-unknown");
          text.textContent = data.status;
        } else {
          badge.classList.add("status-stopped");
          text.textContent = data.status;
        }
        badge.title = data.error || data.status;
      })
      .catch(function () {
        badge.classList.remove("status-running", "status-stopped");
        badge.classList.add("status-unknown");
        text.textContent = "unreachable";
      });
  }

  refreshStatus();
  setInterval(refreshStatus, 15000);
})();
