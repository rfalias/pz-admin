(function () {
  var dataEl = document.getElementById("commands-data");
  if (!dataEl) return;
  var COMMANDS = JSON.parse(dataEl.textContent);
  var byName = {};
  COMMANDS.forEach(function (c) { byName[c.name] = c; });

  var select = document.getElementById("command-select");
  var search = document.getElementById("command-search");
  var description = document.getElementById("command-description");
  var fieldsContainer = document.getElementById("param-fields");
  var preview = document.getElementById("command-preview");
  var runBtn = document.getElementById("run-btn");
  var resultPanel = document.getElementById("result-panel");
  var resultMeta = document.getElementById("result-meta");
  var resultOutput = document.getElementById("result-output");
  var historyList = document.getElementById("history-list");
  var historyEmpty = document.getElementById("history-empty");
  var itemsDatalist = document.getElementById("items-datalist");
  var itemsByLabel = {};

  if (window.ItemsDatalist && itemsDatalist) {
    ItemsDatalist.populate(itemsDatalist, function (data) {
      itemsByLabel = data.byLabel;
    });
  }

  COMMANDS.forEach(function (c) {
    var opt = document.createElement("option");
    opt.value = c.name;
    opt.textContent = c.name;
    opt.dataset.searchText = (c.name + " " + (c.description || "")).toLowerCase();
    select.appendChild(opt);
  });

  if (search) {
    search.addEventListener("input", function () {
      var query = search.value.trim().toLowerCase();
      var options = Array.from(select.options);
      var selectedHidden = false;
      options.forEach(function (opt) {
        var matches = !query || opt.dataset.searchText.indexOf(query) !== -1;
        opt.hidden = !matches;
        if (opt.selected && !matches) selectedHidden = true;
      });
      if (selectedHidden) {
        var firstVisible = options.find(function (opt) { return !opt.hidden; });
        if (firstVisible) {
          select.value = firstVisible.value;
          renderFields(byName[select.value]);
        }
      }
    });
  }

  function fieldId(param) {
    return "param-" + param.name;
  }

  function renderFields(cmd) {
    fieldsContainer.innerHTML = "";
    description.textContent = cmd.description || "";

    cmd.params.forEach(function (param) {
      var wrapper = document.createElement("div");
      wrapper.className = "field";

      var label = document.createElement("label");
      label.textContent = param.label + (param.flag ? " (" + param.flag + ")" : "") + (param.required ? " *" : "");
      label.setAttribute("for", fieldId(param));
      wrapper.appendChild(label);

      if (param.type === "select") {
        var sel = document.createElement("select");
        sel.id = fieldId(param);
        if (!param.required) {
          var blank = document.createElement("option");
          blank.value = "";
          blank.textContent = "(none)";
          sel.appendChild(blank);
        }
        (param.options || []).forEach(function (opt) {
          var o = document.createElement("option");
          o.value = opt;
          o.textContent = opt;
          sel.appendChild(o);
        });
        sel.addEventListener("change", updatePreview);
        wrapper.appendChild(sel);
      } else if (param.type === "bool_flag") {
        var bsel = document.createElement("select");
        bsel.id = fieldId(param);
        if (!param.required) {
          var bblank = document.createElement("option");
          bblank.value = "";
          bblank.textContent = "(unset)";
          bsel.appendChild(bblank);
        }
        ["true", "false"].forEach(function (v) {
          var o = document.createElement("option");
          o.value = v;
          o.textContent = v;
          bsel.appendChild(o);
        });
        bsel.addEventListener("change", updatePreview);
        wrapper.appendChild(bsel);
      } else if (param.type === "flag_bool") {
        var row = document.createElement("div");
        row.className = "flag-row";
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.id = fieldId(param);
        cb.addEventListener("change", updatePreview);
        row.appendChild(cb);
        wrapper.removeChild(label);
        var inlineLabel = document.createElement("label");
        inlineLabel.textContent = param.label + " (" + param.flag + ")";
        inlineLabel.setAttribute("for", fieldId(param));
        row.appendChild(inlineLabel);
        wrapper.appendChild(row);
      } else if (param.type === "coords") {
        var row2 = document.createElement("div");
        row2.className = "coords-row";
        ["x", "y", "z"].forEach(function (axis) {
          var inp = document.createElement("input");
          inp.type = "number";
          inp.placeholder = axis;
          inp.id = fieldId(param) + "-" + axis;
          inp.addEventListener("input", updatePreview);
          row2.appendChild(inp);
        });
        wrapper.appendChild(row2);
      } else if (param.type === "number") {
        var ninp = document.createElement("input");
        ninp.type = "number";
        ninp.id = fieldId(param);
        if (param.placeholder) ninp.placeholder = param.placeholder;
        ninp.addEventListener("input", updatePreview);
        wrapper.appendChild(ninp);
      } else if (param.type === "item") {
        var iinp = document.createElement("input");
        iinp.type = "text";
        iinp.id = fieldId(param);
        iinp.setAttribute("list", "items-datalist");
        iinp.placeholder = param.placeholder || "Search items by name, or type module.item";
        iinp.addEventListener("input", updatePreview);
        wrapper.appendChild(iinp);
      } else {
        var tinp = document.createElement("input");
        tinp.type = "text";
        tinp.id = fieldId(param);
        if (param.placeholder) tinp.placeholder = param.placeholder;
        tinp.addEventListener("input", updatePreview);
        wrapper.appendChild(tinp);
      }

      fieldsContainer.appendChild(wrapper);
    });

    updatePreview();
  }

  function quote(value) {
    return '"' + String(value).replace(/"/g, '\\"') + '"';
  }

  function buildCommand(cmd) {
    var parts = [cmd.name];
    cmd.params.forEach(function (param) {
      if (param.type === "coords") {
        var x = document.getElementById(fieldId(param) + "-x").value;
        var y = document.getElementById(fieldId(param) + "-y").value;
        var z = document.getElementById(fieldId(param) + "-z").value;
        if (x !== "" && y !== "" && z !== "") {
          parts.push(x + "," + y + "," + z);
        }
        return;
      }

      var el = document.getElementById(fieldId(param));
      if (!el) return;

      if (param.type === "flag_bool") {
        if (el.checked) parts.push(param.flag);
        return;
      }

      var value = el.value;
      if (value === "" || value === undefined) return;

      if (param.type === "item") {
        var matched = itemsByLabel[value];
        if (matched) value = matched.fullType;
      }

      if (param.type === "bool_flag") {
        parts.push("-" + value);
      } else if (param.type === "flag_text") {
        parts.push(param.flag + " " + quote(value));
      } else if (param.quoted) {
        parts.push(quote(value));
      } else {
        parts.push(value);
      }
    });
    return parts.join(" ");
  }

  function updatePreview() {
    var cmd = byName[select.value];
    if (!cmd) return;
    preview.value = buildCommand(cmd);
  }

  function addHistory(command, response, error) {
    historyEmpty.style.display = "none";
    historyList.style.display = "";
    var li = document.createElement("li");
    var time = document.createElement("span");
    time.className = "history-time";
    time.textContent = new Date().toLocaleTimeString() + " - ";
    li.appendChild(time);
    var text = document.createElement("span");
    text.textContent = command + (error ? " (error: " + error + ")" : response ? " -> " + response : "");
    li.appendChild(text);
    historyList.insertBefore(li, historyList.firstChild);
    while (historyList.children.length > 20) {
      historyList.removeChild(historyList.lastChild);
    }
  }

  function runCommand() {
    var cmd = byName[select.value];
    var commandText = preview.value.trim();
    if (!commandText) return;

    if (cmd && cmd.destructive) {
      if (!confirm('Run "' + commandText + '"? This command has lasting effects on the server.')) {
        return;
      }
    }

    runBtn.disabled = true;
    fetch("/remote/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: commandText }),
    })
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        resultPanel.style.display = "";
        if (data.error) {
          resultMeta.textContent = "Error running: " + commandText;
          resultOutput.textContent = data.error;
        } else {
          resultMeta.textContent = "Ran: " + commandText;
          resultOutput.textContent = data.response || "(no response)";
        }
        addHistory(commandText, data.response, data.error);
      })
      .catch(function (err) {
        resultPanel.style.display = "";
        resultMeta.textContent = "Error running: " + commandText;
        resultOutput.textContent = String(err);
        addHistory(commandText, null, String(err));
      })
      .finally(function () {
        runBtn.disabled = false;
      });
  }

  select.addEventListener("change", function () {
    renderFields(byName[select.value]);
  });
  runBtn.addEventListener("click", runCommand);

  renderFields(COMMANDS[0]);
  select.value = COMMANDS[0].name;
})();
