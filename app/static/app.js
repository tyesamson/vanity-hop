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

function markCopied(button) {
  if (!button) return;
  const previous = button.getAttribute("data-copy-label") || button.textContent || "Copy";
  button.setAttribute("data-copy-label", previous);
  button.textContent = "Copied";
  button.classList.add("copied");
  window.setTimeout(() => {
    button.textContent = previous;
    button.classList.remove("copied");
  }, 1600);
}

async function copyValue(button, value) {
  if (!value) return false;
  try {
    await navigator.clipboard.writeText(value);
    markCopied(button);
    return true;
  } catch {
    return false;
  }
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const value = button.getAttribute("data-copy");
  if (!(await copyValue(button, value))) {
    window.prompt("Copy this URL", value);
  }
});

const autoCopy = document.querySelector("[data-copy-on-load]");
if (autoCopy) {
  const url = autoCopy.getAttribute("data-copy") || "";
  if (sessionStorage.getItem("vh-copied") === url) {
    markCopied(autoCopy);
  }
  sessionStorage.removeItem("vh-copied");
}

document.getElementById("create-form")?.addEventListener("submit", async (event) => {
  const form = event.target;
  event.preventDefault();
  try {
    const response = await fetch(form.action, { method: "post", body: new FormData(form) });
    if (!response.ok) {
      form.submit();
      return;
    }
    const next = new URL(response.url);
    const slug = next.searchParams.get("created");
    if (slug && origin) {
      const url = `${origin}/${slug}`;
      sessionStorage.setItem("vh-copied", url);
      await copyValue(null, url);
    }
    window.location.assign(`${next.pathname}${next.search}`);
  } catch {
    form.submit();
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
