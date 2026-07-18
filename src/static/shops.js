(function () {
  var form = document.getElementById("shops-form");
  var datalist = document.getElementById("items-datalist");
  var itemsByLabel = {};

  function loadItemsIndex() {
    ItemsDatalist.populate(datalist, function (data) {
      itemsByLabel = data.byLabel;
    });
  }

  function buildStockItem(item, displayName, iconFile, price) {
    var row = document.createElement("div");
    row.className = "stock-item";
    row.setAttribute("data-item", item);

    if (iconFile) {
      var img = document.createElement("img");
      img.className = "item-icon";
      img.src = "/static/images/" + iconFile;
      img.alt = "";
      row.appendChild(img);
    } else {
      var blank = document.createElement("span");
      blank.className = "item-icon item-icon-blank";
      row.appendChild(blank);
    }

    var nameSpan = document.createElement("span");
    nameSpan.className = "item-name";
    nameSpan.textContent = displayName;
    row.appendChild(nameSpan);

    var priceInput = document.createElement("input");
    priceInput.type = "number";
    priceInput.min = "0";
    priceInput.step = "1";
    priceInput.className = "item-price-input";
    priceInput.value = price;
    row.appendChild(priceInput);

    var removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "item-remove-btn";
    removeBtn.setAttribute("aria-label", "Remove item");
    removeBtn.textContent = "×";
    row.appendChild(removeBtn);

    return row;
  }

  function handleAddInput(input) {
    input.addEventListener("input", function () {
      var entry = itemsByLabel[input.value];
      if (!entry) return;
      var stockList = input.closest("td").querySelector(".stock-list");
      var row = buildStockItem(entry.fullType, entry.displayName, entry.icon, "0");
      stockList.appendChild(row);
      input.value = "";
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") e.preventDefault();
    });
  }

  document.querySelectorAll(".item-add-input").forEach(handleAddInput);

  form.addEventListener("click", function (e) {
    if (e.target.classList.contains("item-remove-btn")) {
      e.target.closest(".stock-item").remove();
    }
  });

  form.addEventListener("submit", function () {
    form.querySelectorAll("tbody > tr").forEach(function (row) {
      var stockJsonField = row.querySelector(".stock-json-field");
      if (!stockJsonField) return;
      var stock = Array.from(row.querySelectorAll(".stock-item")).map(function (item) {
        var priceInput = item.querySelector(".item-price-input");
        return {
          item: item.getAttribute("data-item"),
          price: priceInput ? priceInput.value : "0",
        };
      });
      stockJsonField.value = JSON.stringify(stock);
    });
  });

  loadItemsIndex();

  if (window.MapPreview) {
    MapPreview.bindStaticLinks("a.map-link");
  }
})();
