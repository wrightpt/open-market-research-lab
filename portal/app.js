"use strict";

// Static website enhancement only. The sole data fetch is a same-origin synthetic
// catalog generated from the public repository's versioned fixture manifest.
// No account creation, analytics, third-party scripts, or credential handling.

const catalogState = { fields: [] };
const elements = {
  name: document.getElementById("catalog-name"),
  summary: document.getElementById("catalog-summary"),
  instrument: document.getElementById("catalog-instrument"),
  interval: document.getElementById("catalog-interval"),
  source: document.getElementById("catalog-source"),
  splits: document.getElementById("catalog-splits"),
  fields: document.getElementById("catalog-fields"),
  filter: document.getElementById("field-filter"),
  message: document.getElementById("catalog-message"),
};

function textElement(tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = String(value);
  return element;
}

function fillFields(query = "") {
  if (!elements.fields) return;
  const normalized = query.trim().toLowerCase();
  const filtered = catalogState.fields.filter((f) =>
    [f.name, f.unit, f.description].some((value) =>
      String(value).toLowerCase().includes(normalized),
    ),
  );
  elements.fields.replaceChildren();
  if (filtered.length === 0) {
    const row = document.createElement("tr");
    const cell = textElement("td", "", "No matching fields.");
    cell.colSpan = 3;
    row.append(cell);
    elements.fields.append(row);
  } else {
    const fragment = document.createDocumentFragment();
    for (const field of filtered) {
      const row = document.createElement("tr");
      row.append(
        textElement("td", "", field.name),
        textElement("td", "", field.unit),
        textElement("td", "", field.description),
      );
      fragment.append(row);
    }
    elements.fields.append(fragment);
  }
  elements.message.textContent = `${filtered.length} of ${catalogState.fields.length} synthetic fields shown`;
}

function renderCatalog(catalog) {
  if (
    catalog?.source_kind !== "synthetic_generated" ||
    catalog?.venue !== "NONE" ||
    catalog?.api_availability !== "not_available" ||
    catalog?.mcp_availability !== "not_available" ||
    catalog?.requires_key !== false ||
    !Array.isArray(catalog.fields)
  ) {
    throw new Error("The public catalog is not a verified synthetic-only fixture");
  }

  elements.name.textContent = catalog.title;
  elements.summary.textContent = catalog.summary;
  elements.instrument.textContent = catalog.instrument;
  elements.interval.textContent = `${Math.round(catalog.interval_seconds / 60)} minutes`;
  elements.source.textContent = "Generated / no venue";
  const splitFragment = document.createDocumentFragment();
  for (const [name, label] of [
    ["development", "Development"],
    ["holdout", "Holdout exercise"],
  ]) {
    const split = catalog.splits?.[name];
    if (
      !split ||
      !Number.isSafeInteger(split.rows) ||
      split.rows < 1 ||
      !/^[a-f0-9]{64}$/.test(split.sha256)
    ) {
      throw new Error("Missing or invalid synthetic split provenance");
    }
    const card = textElement("div", "split-card", "");
    const description =
      name === "development"
        ? "Open for development"
        : "Public fixture; not blinded";
    const hash = textElement("code", "split-hash", `SHA-256 ${split.sha256.slice(0, 12)}…`);
    hash.title = split.sha256;
    card.append(
      textElement("span", "", label),
      textElement("strong", "", `${split.rows.toLocaleString()} bars`),
      textElement("small", "", description),
      textElement("small", "split-coverage",
        `${split.first_close.slice(0, 10)} → ${split.last_close.slice(0, 10)} UTC`),
      hash,
    );
    splitFragment.append(card);
  }
  elements.splits.replaceChildren(splitFragment);
  catalogState.fields = catalog.fields;
  fillFields(elements.filter?.value ?? "");
}

async function loadCatalog() {
  if (!elements.fields || !elements.message) return;
  try {
    const response = await fetch("./catalog.json", {
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
    });
    if (!response.ok) throw new Error("Unable to load synthetic catalog");
    renderCatalog(await response.json());
  } catch (_err) {
    elements.fields.replaceChildren();
    const row = document.createElement("tr");
    const cell = textElement(
      "td",
      "",
      "The local catalog could not load. Inspect the public fixture manifest on GitHub.",
    );
    cell.colSpan = 3;
    row.append(cell);
    elements.fields.append(row);
    elements.message.textContent = "Catalog unavailable; no API request was made.";
  }
}

function activateAgent(tab) {
  const tabs = [...document.querySelectorAll('[role="tab"][data-agent]')];
  for (const item of tabs) {
    const active = item === tab;
    item.setAttribute("aria-selected", String(active));
    item.tabIndex = active ? 0 : -1;
    const panel = document.getElementById(item.getAttribute("aria-controls"));
    if (panel) panel.hidden = !active;
  }
}

function initAgentTabs() {
  const tabs = [...document.querySelectorAll('[role="tab"][data-agent]')];
  for (const [index, tab] of tabs.entries()) {
    tab.addEventListener("click", () => activateAgent(tab));
    tab.addEventListener("keydown", (event) => {
      const shift = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (shift !== 0) {
        event.preventDefault();
        const next = tabs[(index + shift + tabs.length) % tabs.length];
        activateAgent(next);
        next.focus();
      } else if (event.key === "Home" || event.key === "End") {
        event.preventDefault();
        const next = event.key === "Home" ? tabs[0] : tabs[tabs.length - 1];
        activateAgent(next);
        next.focus();
      }
    });
  }
}

let toastTimer;
function announce(message) {
  const toast = document.getElementById("copy-status");
  if (!toast) return;
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  toastTimer = window.setTimeout(() => {
    toast.hidden = true;
  }, 2200);
}

function initCopyButtons() {
  for (const button of document.querySelectorAll("[data-copy-target]")) {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) {
        announce("Nothing to copy");
        return;
      }
      const text = target.textContent.trim();
      try {
        if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(text);
        announce("Copied to clipboard");
      } catch (_error) {
        announce("Clipboard unavailable. Select and copy the text manually.");
      }
    });
  }
}

elements.filter?.addEventListener("input", (event) => {
  fillFields(event.target.value);
});
initAgentTabs();
initCopyButtons();
loadCatalog();
