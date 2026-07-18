/* Shared client-side item lookup, backed by /shops/items-index.json (see
   items_index.py). Used anywhere an admin needs to pick a PZ item by name
   instead of typing its exact module.item id - the Shops stock editor and
   the Remote Control command builder (additem/removeitem). */
window.ItemsDatalist = (function () {
  var cache = null; // {entries, byLabel}

  function labelFor(entry) {
    return entry.displayName + " (" + entry.fullType + ")";
  }

  function load(callback) {
    if (cache) {
      callback(cache);
      return;
    }
    fetch("/shops/items-index.json")
      .then(function (resp) { return resp.ok ? resp.json() : []; })
      .then(function (entries) {
        var byLabel = {};
        entries.forEach(function (entry) { byLabel[labelFor(entry)] = entry; });
        cache = { entries: entries, byLabel: byLabel };
        callback(cache);
      })
      .catch(function () {
        cache = { entries: [], byLabel: {} };
        callback(cache);
      });
  }

  function populate(datalistEl, callback) {
    load(function (data) {
      var html = "";
      data.entries.forEach(function (entry) {
        html += '<option value="' + labelFor(entry).replace(/"/g, "&quot;") + '">';
      });
      datalistEl.innerHTML = html;
      if (callback) callback(data);
    });
  }

  return { load: load, populate: populate, labelFor: labelFor };
})();
