(function () {
  var limits = window.EVENT_ZONE_LIMITS || { max_spawn_points_per_zone: 6, max_zombies_per_spawn_point: 50 };

  // --- Sub-tab switching -------------------------------------------------
  var subtabs = document.getElementById("spawnpoints-subtabs");
  var panels = {
    "event-spawns": document.getElementById("tab-event-spawns"),
    "trigger-zones": document.getElementById("tab-trigger-zones"),
  };
  var TAB_STORAGE_KEY = "pzAdminSpawnpointsTab";

  function showTab(name) {
    Object.keys(panels).forEach(function (key) {
      panels[key].style.display = key === name ? "" : "none";
    });
    subtabs.querySelectorAll(".subtab").forEach(function (tab) {
      tab.classList.toggle("active", tab.getAttribute("data-tab") === name);
    });
    localStorage.setItem(TAB_STORAGE_KEY, name);
  }

  if (subtabs) {
    subtabs.querySelectorAll(".subtab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        showTab(tab.getAttribute("data-tab"));
      });
    });
    var savedTab = localStorage.getItem(TAB_STORAGE_KEY);
    if (savedTab && panels[savedTab]) showTab(savedTab);
  }

  // --- Trigger zones -------------------------------------------------
  var zonesList = document.getElementById("zones-list");
  var addZoneBtn = document.getElementById("add-zone-btn");
  var zonesForm = document.getElementById("zones-form");

  function pointCount(card) {
    return card.querySelectorAll("[data-point-row]").length;
  }

  function updateAddPointBtn(card) {
    var btn = card.querySelector("[data-add-point]");
    btn.disabled = pointCount(card) >= limits.max_spawn_points_per_zone;
  }

  function buildPointRow() {
    var row = document.createElement("div");
    row.className = "zone-point-row";
    row.setAttribute("data-point-row", "");
    var inputs = {};

    function field(labelText, cls, value, extra) {
      var label = document.createElement("label");
      label.textContent = labelText + " ";
      var input = document.createElement("input");
      input.type = "number";
      input.className = cls;
      input.value = value;
      input.step = "1";
      if (extra) Object.keys(extra).forEach(function (k) { input[k] = extra[k]; });
      label.appendChild(input);
      row.appendChild(label);
      return input;
    }

    inputs.x = field("X", "zp-x", "0");
    inputs.y = field("Y", "zp-y", "0");
    inputs.z = field("Z", "zp-z", "0");

    var previewBtn = document.createElement("button");
    previewBtn.type = "button";
    previewBtn.className = "coord-preview-btn";
    previewBtn.setAttribute("aria-label", "Preview location");
    previewBtn.textContent = "🗺";
    row.appendChild(previewBtn);
    if (window.MapPreview) MapPreview.bindInputs(previewBtn, inputs.x, inputs.y, inputs.z);

    field("Zombies", "zp-count", "1", { min: "1", max: String(limits.max_zombies_per_spawn_point) });
    field("Jitter", "zp-jitter", "0", { min: "0" });

    var removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "item-remove-btn zone-point-remove-btn";
    removeBtn.setAttribute("aria-label", "Remove spawn point");
    removeBtn.textContent = "×";
    row.appendChild(removeBtn);

    return row;
  }

  function wireZoneCard(card) {
    var removeZoneBtn = card.querySelector(".zone-remove-btn");
    removeZoneBtn.addEventListener("click", function () { card.remove(); });

    var zoneFields = card.querySelector(".zone-fields");
    var zonePreviewBtn = zoneFields.querySelector("[data-coord-preview]");
    if (zonePreviewBtn && window.MapPreview) {
      MapPreview.bindInputs(
        zonePreviewBtn,
        zoneFields.querySelector('[name="zone_x"]'),
        zoneFields.querySelector('[name="zone_y"]'),
        zoneFields.querySelector('[name="zone_z"]')
      );
    }

    var pointsList = card.querySelector("[data-points-list]");
    var addPointBtn = card.querySelector("[data-add-point]");

    function wirePointRow(row) {
      row.querySelector(".zone-point-remove-btn").addEventListener("click", function () {
        row.remove();
        updateAddPointBtn(card);
      });
      var previewBtn = row.querySelector("[data-coord-preview]");
      if (previewBtn && window.MapPreview) {
        MapPreview.bindInputs(
          previewBtn,
          row.querySelector(".zp-x"),
          row.querySelector(".zp-y"),
          row.querySelector(".zp-z")
        );
      }
    }

    card.querySelectorAll("[data-point-row]").forEach(wirePointRow);

    addPointBtn.addEventListener("click", function () {
      if (pointCount(card) >= limits.max_spawn_points_per_zone) return;
      var row = buildPointRow();
      pointsList.appendChild(row);
      wirePointRow(row);
      updateAddPointBtn(card);
    });

    updateAddPointBtn(card);
  }

  function buildZoneCard() {
    var card = document.createElement("div");
    card.className = "zone-card";
    card.setAttribute("data-zone-card", "");
    card.innerHTML =
      '<input type="hidden" name="zone_id" value="">' +
      '<div class="zone-fields">' +
      '<label class="zone-field zone-field-name">Name<input type="text" name="zone_name" placeholder="Zone name"></label>' +
      '<label class="zone-field">X<input type="number" name="zone_x" value="0" step="1"></label>' +
      '<label class="zone-field">Y<input type="number" name="zone_y" value="0" step="1"></label>' +
      '<label class="zone-field">Z<input type="number" name="zone_z" value="0" step="1"></label>' +
      '<button type="button" class="coord-preview-btn" data-coord-preview aria-label="Preview location">🗺</button>' +
      '<label class="zone-field">Radius<input type="number" name="zone_radius" value="' + limits.min_radius + '" min="' + limits.min_radius + '" max="' + limits.max_radius + '" step="1"></label>' +
      '<label class="zone-field">Cooldown (s)<input type="number" name="zone_cooldown_sec" value="' + limits.min_cooldown_sec + '" min="' + limits.min_cooldown_sec + '" step="1"></label>' +
      '<label class="zone-field zone-field-outfit">Outfit (blank = random)<input type="text" name="zone_outfit_name" placeholder="e.g. ConstructionWorker"></label>' +
      '<label class="zone-field zone-field-pct">Female %<input type="number" name="zone_female_chance" value="0" min="0" max="100" step="1"></label>' +
      '<label class="zone-field zone-field-pct">Sprinter %<input type="number" name="zone_sprinter_chance" value="0" min="0" max="100" step="1"></label>' +
      '<button type="button" class="row-remove-btn zone-remove-btn">Remove zone</button>' +
      '</div>' +
      '<div class="zone-points-list" data-points-list></div>' +
      '<button type="button" class="zone-point-add-btn" data-add-point>Add spawn point</button>' +
      '<input type="hidden" name="zone_spawn_points_json" class="zone-points-json-field">';
    return card;
  }

  if (zonesList) {
    zonesList.querySelectorAll("[data-zone-card]").forEach(wireZoneCard);
  }

  if (addZoneBtn) {
    addZoneBtn.addEventListener("click", function () {
      var card = buildZoneCard();
      zonesList.appendChild(card);
      wireZoneCard(card);
      card.querySelector('[name="zone_name"]').focus();
    });
  }

  if (zonesForm) {
    zonesForm.addEventListener("submit", function () {
      zonesForm.querySelectorAll("[data-zone-card]").forEach(function (card) {
        var points = Array.from(card.querySelectorAll("[data-point-row]")).map(function (row) {
          return {
            id: row.getAttribute("data-point-id") || null,
            x: row.querySelector(".zp-x").value,
            y: row.querySelector(".zp-y").value,
            z: row.querySelector(".zp-z").value,
            zombie_count: row.querySelector(".zp-count").value,
            jitter_radius: row.querySelector(".zp-jitter").value,
          };
        });
        card.querySelector(".zone-points-json-field").value = JSON.stringify(points);
      });
    });
  }
})();
