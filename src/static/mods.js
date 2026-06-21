(function () {
  var tbody = document.getElementById("mods-tbody");
  var addRowBtn = document.getElementById("add-row-btn");
  var importBtn = document.getElementById("import-btn");
  var importUrl = document.getElementById("import-url");
  var importStatus = document.getElementById("import-status");

  function addRow(modId, workshopId) {
    var tr = document.createElement("tr");

    var modCell = document.createElement("td");
    var modInput = document.createElement("input");
    modInput.type = "text";
    modInput.name = "mod_id";
    modInput.placeholder = "Base";
    modInput.value = modId || "";
    modCell.appendChild(modInput);

    var workshopCell = document.createElement("td");
    var workshopInput = document.createElement("input");
    workshopInput.type = "text";
    workshopInput.name = "workshop_id";
    workshopInput.placeholder = "123456789";
    workshopInput.value = workshopId || "";
    workshopCell.appendChild(workshopInput);

    var removeCell = document.createElement("td");
    var removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "row-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", function () { tr.remove(); });
    removeCell.appendChild(removeBtn);

    tr.appendChild(modCell);
    tr.appendChild(workshopCell);
    tr.appendChild(removeCell);
    tbody.appendChild(tr);
    return tr;
  }

  addRowBtn.addEventListener("click", function () {
    var tr = addRow("", "");
    tr.querySelector("input").focus();
  });

  function existingPairs() {
    var pairs = new Set();
    tbody.querySelectorAll("tr").forEach(function (tr) {
      var m = tr.querySelector('[name="mod_id"]').value.trim();
      var w = tr.querySelector('[name="workshop_id"]').value.trim();
      pairs.add(m + "::" + w);
    });
    return pairs;
  }

  importBtn.addEventListener("click", function () {
    var url = importUrl.value.trim();
    if (!url) return;

    importBtn.disabled = true;
    importStatus.textContent = "Fetching...";

    fetch("/mods/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: url }),
    })
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        if (data.error) {
          importStatus.textContent = "Error: " + data.error;
          return;
        }

        var pairs = existingPairs();
        var addedTitles = [];

        data.mods.forEach(function (mod) {
          var modIds = mod.mod_ids.length ? mod.mod_ids : [""];
          var addedAny = false;
          modIds.forEach(function (modId) {
            var key = modId + "::" + mod.workshop_id;
            if (pairs.has(key)) return;
            pairs.add(key);
            addRow(modId, mod.workshop_id);
            addedAny = true;
          });
          if (addedAny) {
            addedTitles.push((mod.title || mod.workshop_id) + (mod.is_dependency ? " (dependency)" : ""));
          }
        });

        var parts = [];
        parts.push(addedTitles.length ? "Added: " + addedTitles.join(", ") + "." : "No new rows added.");
        if (data.errors && data.errors.length) parts.push(data.errors.join(" "));
        importStatus.textContent = parts.join(" ");
      })
      .catch(function (err) {
        importStatus.textContent = "Error: " + err;
      })
      .finally(function () {
        importBtn.disabled = false;
      });
  });
})();
