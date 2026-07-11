(function () {
  var tbody = document.getElementById("spawnpoints-tbody");
  var addBtn = document.getElementById("add-spawnpoint-btn");

  function addRow() {
    var tr = document.createElement("tr");

    var nameCell = document.createElement("td");
    var idInput = document.createElement("input");
    idInput.type = "hidden";
    idInput.name = "id";
    idInput.value = "";
    nameCell.appendChild(idInput);
    var nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.name = "name";
    nameInput.placeholder = "Spawn name";
    nameCell.appendChild(nameInput);
    tr.appendChild(nameCell);

    ["x", "y", "z"].forEach(function (field) {
      var cell = document.createElement("td");
      var input = document.createElement("input");
      input.type = "number";
      input.name = field;
      input.step = "1";
      input.value = "0";
      cell.appendChild(input);
      tr.appendChild(cell);
    });

    var createdByCell = document.createElement("td");
    var createdByInput = document.createElement("input");
    createdByInput.type = "hidden";
    createdByInput.name = "created_by";
    createdByInput.value = "";
    createdByCell.appendChild(createdByInput);
    var createdBySpan = document.createElement("span");
    createdBySpan.className = "help";
    createdBySpan.textContent = "(you, on save)";
    createdByCell.appendChild(createdBySpan);
    tr.appendChild(createdByCell);

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

  addBtn.addEventListener("click", function () {
    var tr = addRow();
    tr.querySelector('[name="name"]').focus();
  });
})();
