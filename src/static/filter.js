document.addEventListener("DOMContentLoaded", () => {
  const search = document.getElementById("settings-search");
  if (!search) return;

  const fields = Array.from(document.querySelectorAll(".field"));
  const groups = Array.from(document.querySelectorAll(".group"));

  function fieldText(field) {
    const label = field.querySelector("label");
    const help = field.querySelector(".help");
    const input = field.querySelector("input");
    const value = input ? (input.type === "checkbox" ? (input.checked ? "true" : "false") : input.value) : "";
    return [label ? label.textContent : "", help ? help.textContent : "", value]
      .join(" ")
      .toLowerCase();
  }

  function applyFilter() {
    const query = search.value.trim().toLowerCase();

    fields.forEach((field) => {
      const matches = !query || fieldText(field).includes(query);
      field.style.display = matches ? "" : "none";
    });

    groups.forEach((group) => {
      const hasVisibleField = Array.from(group.querySelectorAll(".field")).some(
        (field) => field.style.display !== "none"
      );
      group.style.display = hasVisibleField ? "" : "none";
      group.open = query ? hasVisibleField : false;
    });
  }

  search.addEventListener("input", applyFilter);
});
