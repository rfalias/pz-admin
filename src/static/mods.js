(function () {
  var tbody = document.getElementById("mods-tbody");
  var addRowBtn = document.getElementById("add-row-btn");
  var importBtn = document.getElementById("import-btn");
  var importUrl = document.getElementById("import-url");
  var importStatus = document.getElementById("import-status");

  function addRow(modId, workshopId) {
    var tr = document.createElement("tr");
    tr.draggable = true;

    var handleCell = document.createElement("td");
    handleCell.className = "drag-handle";
    handleCell.title = "Drag to reorder";
    handleCell.textContent = "⠿";
    tr.appendChild(handleCell);

    var modCell = document.createElement("td");
    var modInput = document.createElement("input");
    modInput.type = "text";
    modInput.name = "mod_id";
    modInput.placeholder = "Base";
    modInput.value = modId || "";
    modCell.appendChild(modInput);
    tr.appendChild(modCell);

    var workshopCell = document.createElement("td");
    var workshopInput = document.createElement("input");
    workshopInput.type = "text";
    workshopInput.name = "workshop_id";
    workshopInput.placeholder = "123456789";
    workshopInput.value = workshopId || "";
    workshopCell.appendChild(workshopInput);
    tr.appendChild(workshopCell);

    var removeCell = document.createElement("td");
    var removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "row-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", function () { tr.remove(); });
    removeCell.appendChild(removeBtn);
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

  // --- Drag-and-drop row reordering ---
  var dragging = null;

  tbody.addEventListener("dragstart", function (e) {
    var tr = e.target.closest("tr");
    if (!tr) return;
    if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") {
      e.preventDefault();
      return;
    }
    dragging = tr;
    e.dataTransfer.effectAllowed = "move";
    setTimeout(function () { tr.classList.add("row-dragging"); }, 0);
  });

  tbody.addEventListener("dragend", function () {
    if (dragging) {
      dragging.classList.remove("row-dragging");
      dragging = null;
    }
    clearDropIndicator();
  });

  tbody.addEventListener("dragover", function (e) {
    if (!dragging) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    var target = e.target.closest("tr");
    if (!target || target === dragging) { clearDropIndicator(); return; }
    var rect = target.getBoundingClientRect();
    var insertBefore = e.clientY < rect.top + rect.height / 2;
    clearDropIndicator();
    target.classList.add(insertBefore ? "drop-above" : "drop-below");
  });

  tbody.addEventListener("dragleave", function (e) {
    if (!e.relatedTarget || !tbody.contains(e.relatedTarget)) clearDropIndicator();
  });

  tbody.addEventListener("drop", function (e) {
    e.preventDefault();
    var target = e.target.closest("tr");
    if (!target || !dragging || target === dragging) { clearDropIndicator(); return; }
    var rect = target.getBoundingClientRect();
    var insertBefore = e.clientY < rect.top + rect.height / 2;
    clearDropIndicator();
    tbody.insertBefore(dragging, insertBefore ? target : target.nextSibling);
  });

  function clearDropIndicator() {
    tbody.querySelectorAll(".drop-above, .drop-below").forEach(function (el) {
      el.classList.remove("drop-above", "drop-below");
    });
  }
})();
