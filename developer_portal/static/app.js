import {accountState, datasetRecords, usageView, apiClient, validKeyName, modeView} from "./state.mjs";

const $ = id => document.getElementById(id);
let session = null, catalog = [], generation = 0, busy = false;
const api = apiClient(window.fetch.bind(window), () => session?.csrf_token);
const write = (id, text) => { $(id).textContent = text; };
const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
};
function message(error) {
  return ({401: "Your session expired. Sign in again.", 403: "Access is not approved, or session verification failed. Refresh status.",
    409: "That action conflicts with current server state. Refresh and review.", 429: "The server's quota was reached. Wait for the reported reset."})[error.status] ||
    "The request could not be completed. Check the connection and retry; no success is assumed.";
}
function clearSecret() { write("secret-value", ""); write("copy-status", ""); $("secret-dialog").close(); }
function route() {
  clearSecret();
  const page = ["overview", "datasets", "api", "account", "challenge"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview";
  for (const view of document.querySelectorAll(".view")) view.hidden = view.id !== page;
  for (const link of document.querySelectorAll("nav a")) {
    if (link.hash === `#${page}`) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  document.title = `${page[0].toUpperCase() + page.slice(1)} · Open Market Research Lab`;
  $("main").focus({preventScroll: true});
}
function renderAccount() {
  const status = accountState(session);
  const mode = modeView(session?.mode);
  const messages = {
    anonymous: mode.test ? "Synthetic-test account/key prototype. Live GitHub sign-in is not configured here." : "Sign in to request access. The offline synthetic benchmark needs no account.",
    none: "Signed in. Research access has not been requested.",
    pending: "Access request pending. Keys and research access remain unavailable until the backend approves it.",
    denied: "Access request denied. No research access or key creation is available. Contact the maintainer through the approved review channel.",
    approved: "Research access approved by the backend. Keys remain limited to the scopes and quotas it permits.",
    unavailable: "Account state unavailable. No privileged action is enabled. Refresh status to retry.",
  };
  write("account-status", `${session?.user?.login ? `${session.user.login} · ` : ""}${messages[status]}`);
  $("github-login").hidden = status !== "anonymous" || !mode.login;
  $("logout").hidden = !session?.authenticated;
  $("request-form").hidden = status !== "none";
  $("approved-panel").hidden = status !== "approved";
  $("demo-banner").hidden = !mode.demo;
  $("test-banner").hidden = !mode.test;
  write("availability-detail", mode.availability);
  write("api-mode-status", mode.demo ? "The standalone loopback demo mocks portal operations; it does not serve the research API. The API examples refer to a separate synthetic backend." : "The research tools use the agreed synthetic API contract. Configure an approved HTTPS origin privately for the adapter. No production origin or credential is embedded in this UI.");
  if (session?.mode === "demo") {
    if (["none", "pending", "denied", "approved"].includes(status)) $("demo-scenario").value = status === "none" ? "unrequested" : status;
    else if (status === "anonymous" && !["loading", "failure"].includes($("demo-scenario").value)) $("demo-scenario").value = "anonymous";
  }
  write("github-login", session?.mode === "demo" ? "GitHub sign-in · demo notice ↗" : "Sign in with GitHub ↗");
}
function table(headers, rows) {
  const result = element("table"), head = element("thead"), heading = element("tr"), body = element("tbody");
  for (const title of headers) { const th = element("th", title); th.scope = "col"; heading.append(th); }
  head.append(heading);
  for (const values of rows) {
    const row = element("tr");
    for (const value of values) row.append(element("td", value ?? "Unknown"));
    body.append(row);
  }
  result.append(head, body); return result;
}
function detail(item) {
  $("dataset-detail").hidden = false;
  write("dataset-title", item.title); write("dataset-description", item.description);
  write("dataset-time-basis", item.time_basis ?? "Time basis unavailable. Do not assume bar-close or bucket timing; consult the dataset schema.");
  $("dataset-facts").replaceChildren();
  for (const [name, value] of Object.entries({Asset: item.asset, Venue: item.venue, Granularity: item.granularity,
    "Schema version": item.schema_version, Freshness: item.freshness, Retention: item.retention, Provenance: item.provenance, License: item.license, Gaps: item.gaps})) {
    const pair = element("div"); pair.append(element("dt", name), element("dd", value ?? "Unknown")); $("dataset-facts").append(pair);
  }
  $("dataset-coverage").replaceChildren(table(["Split", "UTC coverage", "Rows", "SHA-256"], item.coverage.map(c => [c.split, `${c.start} → ${c.end}`, c.rows, c.sha256])));
  $("dataset-fields").replaceChildren(table(["Field", "Type", "Unit", "Missing allowed"], item.fields.map(f => [f.name, f.type, f.unit, f.nullable ? "Yes · unknown" : "No"])));
}
function renderCatalog() {
  const search = $("dataset-search").value.toLowerCase();
  $("dataset-list").replaceChildren();
  const matches = catalog.filter(item => `${item.title} ${item.id} ${item.asset} ${item.venue}`.toLowerCase().includes(search));
  for (const item of matches) {
    const button = element("button", undefined, "dataset-row"), text = element("span");
    text.append(element("strong", item.title), element("small", `${item.asset} / ${item.venue} · ${item.granularity} · ${item.id}`));
    button.append(text, element("span", "Inspect →")); button.addEventListener("click", () => detail(item));
    $("dataset-list").append(button);
  }
  if (catalog.length && !matches.length) write("catalog-status", "No synthetic fixtures match your search.");
}
async function refreshCatalog(ticket = generation) {
  write("catalog-status", "Loading catalog…"); $("dataset-list").replaceChildren(); $("dataset-detail").hidden = true;
  try {
    const response = await api("/datasets"); if (ticket !== generation) return;
    catalog = datasetRecords(response);
    write("catalog-status", `${catalog.length} synthetic dataset${catalog.length === 1 ? "" : "s"}. ${response.datasets.length !== catalog.length ? "Unsupported or non-synthetic records are withheld." : "Exact fixture identity; no live feed."}`);
    renderCatalog(); if (catalog.length === 1) detail(catalog[0]);
  } catch (error) { if (ticket === generation) { catalog = []; write("catalog-status", message(error)); } }
}
function ask(action, name) {
  write("confirm-title", action === "rotate" ? "Rotate this key?" : "Revoke this key?");
  write("confirm-description", `${name}: ${action === "rotate" ? "the old key will stop working and a replacement secret will be shown once." : "the key will stop working. This cannot be undone."}`);
  $("confirm-dialog").showModal();
  return new Promise(resolve => {
    const finish = answer => { $("confirm-dialog").close(); resolve(answer); };
    $("confirm-accept").onclick = () => finish(true); $("confirm-cancel").onclick = () => finish(false);
    $("confirm-dialog").oncancel = () => resolve(false);
  });
}
async function loadKeys(ticket = generation) {
  write("key-status", "Loading keys…"); $("key-list").replaceChildren();
  const data = await api("/keys"); if (ticket !== generation) return;
  if (!Array.isArray(data.keys)) throw new Error("Invalid keys");
  write("key-status", data.keys.length ? "Key metadata only. Existing secrets cannot be retrieved." : "No keys yet.");
  for (const key of data.keys) {
    if (!/^[a-zA-Z0-9_-]+$/.test(key.id)) continue;
    const row = element("div", undefined, "key-row"), info = element("div", undefined, "key-info");
    info.append(element("strong", key.name), element("small", `${(key.scopes || []).join(", ")} · expires ${key.expires_at}`)); row.append(info);
    if (key.revoked) row.append(element("span", "REVOKED", "revoked"));
    else for (const action of ["rotate", "revoke"]) {
      const button = element("button", action === "rotate" ? "Rotate" : "Revoke", "button small secondary");
      button.addEventListener("click", async () => {
        if (busy || !await ask(action, key.name)) return;
        await mutate(async () => {
          const result = await api(`/keys/${encodeURIComponent(key.id)}${action === "rotate" ? "/rotate" : ""}`, action === "rotate" ? "POST" : "DELETE", action === "rotate" ? {} : undefined);
          if (action === "rotate") reveal(result);
          else if (result.revoked !== true) throw new Error("Invalid revocation response");
          await loadKeys().catch(error => write("key-status", message(error)));
        });
      }); row.append(button);
    }
    $("key-list").append(row);
  }
}
function reveal(result) {
  if (document.hidden || $("account").hidden || accountState(session) !== "approved") return;
  if (typeof result.secret !== "string" || !result.secret.length || result.secret.length > 4096) throw new Error("Invalid secret envelope");
  write("secret-value", result.secret); write("copy-status", "");
  write("secret-kind", session?.mode === "demo" ? "MOCK KEY · intentionally unusable for any API." : session?.mode === "synthetic-test" ? "SYNTHETIC-TEST KEY · store securely and use only with the approved synthetic backend." : "Store in your local secret manager or protected environment.");
  $("secret-dialog").showModal();
}
async function refreshUsage(ticket) {
  write("usage-label", "Loading…"); $("usage-meter").hidden = true;
  const result = await api("/usage"); if (ticket !== generation) return;
  const view = usageView(result); if (!view) throw new Error("Invalid usage");
  write("usage-label", `${view.used} / ${view.limit} requests`); $("usage-meter").value = view.percent; $("usage-meter").hidden = false;
  write("usage-detail", `${session?.mode === "demo" ? "MOCK QUOTA · " : ""}${result.usage.rows_today ?? "Unknown"} rows today. ${result.limits.rows_per_request ?? "Unknown"} rows per request. ${result.limits.requests_per_minute ?? "Unknown"} requests per minute. Resets ${result.usage.resets_at ?? "unknown"}.`);
}
async function refresh() {
  const ticket = ++generation; clearSecret(); session = null; renderAccount();
  $("key-list").replaceChildren(); write("usage-detail", "Waiting for the backend's usage record.");
  write("connection", "Connecting to the same-origin portal…");
  try {
    const response = await api("/session"); if (ticket !== generation) return;
    session = response;
    renderAccount(); write("connection", modeView(session.mode).connection);
  } catch (error) { if (ticket === generation) { session = null; renderAccount(); write("connection", message(error)); } }
  if (ticket !== generation) return;
  const jobs = [refreshCatalog(ticket)];
  if (accountState(session) === "approved") {
    jobs.push(loadKeys(ticket).catch(error => write("key-status", message(error))));
    jobs.push(refreshUsage(ticket).catch(error => { write("usage-label", "Unavailable"); write("usage-detail", message(error)); }));
  }
  await Promise.all(jobs);
}
async function mutate(callback) {
  if (busy) return; busy = true; write("action-status", "Submitting…"); clearSecret();
  document.querySelectorAll("#account button").forEach(button => button.disabled = true);
  try { await callback(); write("action-status", "Server acknowledged the action."); }
  catch (error) { write("action-status", message(error)); if ([401, 403].includes(error.status)) await refresh(); }
  finally { busy = false; document.querySelectorAll("#account button").forEach(button => button.disabled = false); }
}
$("request-form").addEventListener("submit", event => { event.preventDefault(); mutate(async () => { await api("/access-requests", "POST", {purpose: $("purpose").value}); $("purpose").value = ""; await refresh(); }); });
$("key-form").addEventListener("submit", event => { event.preventDefault(); mutate(async () => {
  if (!validKeyName($("key-name").value)) throw new Error("Invalid key name");
  const result = await api("/keys", "POST", {name: $("key-name").value.trim(), scopes: ["research:read"], expires_in_days: 30});
  $("key-name").value = ""; reveal(result);
  await loadKeys().catch(error => write("key-status", message(error)));
}); });
$("key-name").addEventListener("input", () => $("key-name").setCustomValidity(validKeyName($("key-name").value) ? "" : "Use 1–64 printable ASCII characters, including a non-space character."));
$("logout").addEventListener("click", () => mutate(async () => { await api("/logout", "POST", {}); await refresh(); }));
$("refresh-account").addEventListener("click", refresh);
$("reload-datasets").addEventListener("click", () => refreshCatalog());
$("dataset-search").addEventListener("input", renderCatalog);
$("dismiss-secret").addEventListener("click", clearSecret);
$("secret-dialog").addEventListener("cancel", clearSecret);
$("copy-secret").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("secret-value").textContent); write("copy-status", "Copied. Clear your clipboard after secure storage."); }
  catch { write("copy-status", "Clipboard unavailable. Select and save the key securely before dismissing."); }
});
$("demo-scenario").addEventListener("change", async event => {
  if (session?.mode !== "demo" || busy) return;
  try {
    const response = await fetch("/portal/demo/scenario", {method: "POST", credentials: "same-origin", redirect: "error", headers: {"Content-Type": "application/json", "X-CSRF-Token": session.csrf_token}, body: JSON.stringify({scenario: event.target.value})});
    if (!response.ok) throw new Error("Demo switch failed"); await refresh();
  } catch { write("connection", "Demo state change failed. Refresh to retry."); }
});
window.addEventListener("hashchange", route); window.addEventListener("pagehide", clearSecret);
document.addEventListener("visibilitychange", () => { if (document.hidden) clearSecret(); });
route(); refresh();
