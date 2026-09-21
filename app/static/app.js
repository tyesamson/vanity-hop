const preview = document.getElementById("slug-preview");
const origin = preview?.dataset.origin || "";
const prefix = preview?.dataset.prefix || document.getElementById("prefix-display")?.textContent || "";
const slugInput = document.getElementById("slug-input");

function updatePreview() {
  if (!preview || !origin) return;
  const custom = (slugInput?.value || "").trim().toLowerCase();
  const tail = custom || "xxxx";
  const slug = prefix && custom.startsWith(prefix) ? custom : `${prefix}${tail}`;
  preview.textContent = `${origin}/${slug}`;
}

slugInput?.addEventListener("input", updatePreview);

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const value = button.getAttribute("data-copy");
  try {
    await navigator.clipboard.writeText(value);
    const previous = button.textContent;
    button.textContent = "Copied";
    window.setTimeout(() => {
      button.textContent = previous;
    }, 1400);
  } catch {
    window.prompt("Copy this URL", value);
  }
});

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (form instanceof HTMLFormElement && (form.getAttribute("method") || "get").toLowerCase() === "post") {
    if (!form.querySelector("input[name=csrf_token]")) {
      const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content");
      if (token) {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "csrf_token";
        input.value = token;
        form.appendChild(input);
      }
    }
  }
  const message = form.getAttribute("data-confirm");
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});

const selectAll = document.getElementById("select-all");
const rowChecks = () => [...document.querySelectorAll(".row-check")];
const bulkDelete = document.getElementById("bulk-delete");

function syncBulk() {
  const selected = rowChecks().filter((box) => box.checked);
  if (bulkDelete) bulkDelete.disabled = selected.length === 0;
  if (selectAll) {
    const boxes = rowChecks().filter((box) => box.offsetParent !== null);
    selectAll.checked = boxes.length > 0 && boxes.every((box) => box.checked);
  }
}

selectAll?.addEventListener("change", () => {
  for (const box of rowChecks()) {
    if (box.closest(".hop")?.style.display === "none") continue;
    box.checked = selectAll.checked;
  }
  syncBulk();
});

document.addEventListener("change", (event) => {
  if (event.target.classList?.contains("row-check")) syncBulk();
});

document.getElementById("bulk-form")?.addEventListener("submit", (event) => {
  const count = rowChecks().filter((box) => box.checked).length;
  if (!count) {
    event.preventDefault();
    return;
  }
  if (!window.confirm(`Delete ${count} selected ${count === 1 ? "link" : "links"}?`)) {
    event.preventDefault();
  }
});

document.getElementById("link-filter")?.addEventListener("input", (event) => {
  const query = event.target.value.trim().toLowerCase();
  for (const row of document.querySelectorAll(".hop")) {
    const hay = row.getAttribute("data-filter") || "";
    row.style.display = hay.toLowerCase().includes(query) ? "" : "none";
  }
  syncBulk();
});

syncBulk();
