// Read-only public synthetic fixture adapter. Never import private repositories
// or accept a filesystem path, query language, executable code, or source URL.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
export const DATASET_ID = "synthetic-liquidity-v1";
export const MAX_PAGE_SIZE = 20;

const FIXTURE_FIELDS = Object.freeze([
  "timestamp", "open", "high", "low", "close", "volume", "spread_bps",
  "depth_usd", "open_interest_usd", "liquidation_usd",
]);
const FIELD_INFO = Object.freeze([
  { name: "timestamp", unit: "UTC", meaning: "Synthetic bar close; values are available at this close" },
  { name: "open", unit: "toy quote", meaning: "Opening price for the prior synthetic hour" },
  { name: "high", unit: "toy quote", meaning: "Highest synthetic quote during the hour" },
  { name: "low", unit: "toy quote", meaning: "Lowest synthetic quote during the hour" },
  { name: "close", unit: "toy quote", meaning: "Closing synthetic quote for the hour" },
  { name: "volume", unit: "invented units", meaning: "Fictional trade volume" },
  { name: "spread_bps", unit: "basis points", meaning: "Synthetic quoted spread" },
  { name: "depth_usd", unit: "invented USD", meaning: "Synthetic near-mid aggregate liquidity" },
  { name: "open_interest_usd", unit: "invented USD", meaning: "Synthetic derivative open interest" },
  { name: "liquidation_usd", unit: "invented USD", meaning: "Synthetic liquidations, never observed" },
]);

function validatedCsv(csv) {
  if (csv.length > 256_000) throw new Error("Synthetic fixture exceeds read limit");
  const lines = csv.trimEnd().split("\n");
  if (lines[0] !== FIXTURE_FIELDS.join(",")) {
    throw new Error("Fixture columns differ from the published data contract");
  }
  return lines.slice(1).map((line, i) => {
    const values = line.split(",");
    if (values.length !== FIXTURE_FIELDS.length ||
      !/^20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(values[0])) {
      throw new Error("Malformed synthetic fixture row " + (i + 1));
    }
    const row = { timestamp: values[0] };
    for (let column = 1; column < values.length; column++) {
      const numeric = Number(values[column]);
      if (values[column] === "" || !Number.isFinite(numeric)) {
        // The source fixture marks certain market features as unknown.
        if (values[column] === "" && column >= 6) {
          row[FIXTURE_FIELDS[column]] = null;
          continue;
        }
        throw new Error("Unexpected invalid fixture field");
      }
      row[FIXTURE_FIELDS[column]] = numeric;
    }
    return row;
  });
}

export function readSyntheticCatalog(root = ROOT) {
  const manifest = JSON.parse(readFileSync(resolve(root, "data/synthetic-v1/manifest.json"), "utf8"));
  if (manifest.dataset_id !== DATASET_ID || manifest.synthetic !== true ||
      manifest.venue !== "NONE" || manifest.instrument !== "SYNTHETIC:TOY-USD") {
    throw new Error("Only the reviewed synthetic dataset may be served");
  }
  if (manifest.splits?.development?.file !== "data/synthetic-v1/development.csv" ||
      manifest.splits?.holdout?.file !== "data/synthetic-v1/holdout.csv") {
    throw new Error("Unapproved synthetic fixture file paths");
  }
  const raw = readFileSync(resolve(root, "data/synthetic-v1/development.csv"), "utf8");
  const digest = createHash("sha256").update(raw).digest("hex");
  if (digest !== manifest.splits.development.sha256) {
    throw new Error("Synthetic dataset SHA-256 mismatch");
  }
  const rows = validatedCsv(raw);
  if (rows.length !== manifest.splits.development.rows) {
    throw new Error("Synthetic fixture row count mismatch");
  }
  // Read only the public *development* rows. The visible holdout remains excluded
  // from agent sample tools, even though its metadata is publicly documented.
  const identity = {
    dataset_id: DATASET_ID,
    title: "Synthetic Liquidity and Deleveraging Benchmark",
    provenance: "original_generated_synthetic",
    synthetic: true,
    market_data: false,
    instrument: manifest.instrument,
    venue: manifest.venue,
    timeframe_seconds: manifest.interval_seconds,
    accessible_split: "development",
    rows: rows.length,
    sha256: digest,
    first_close: manifest.splits.development.first_close,
    last_close: manifest.splits.development.last_close,
    access: "public_sample_only",
    license: "Apache-2.0 original synthetic fixtures",
    limitations: [
      "No real exchange observations, API keys, or account information",
      "Cannot demonstrate market predictability, profitability, or independent holdout accuracy",
      "No Kubernetes, Vault, ClickHouse or trading connectivity",
    ],
  };
  return Object.freeze({ identity: Object.freeze(identity), rows: Object.freeze(rows), fields: FIELD_INFO });
}

export const catalog = readSyntheticCatalog();

export function listDatasets() {
  return { datasets: [catalog.identity] };
}

export function describeDataset() {
  return { ...catalog.identity, fields: catalog.fields };
}

export function getSample({ dataset_id, offset = 0, limit = 5 }) {
  if (dataset_id !== DATASET_ID ||
      !Number.isSafeInteger(offset) || offset < 0 || offset >= catalog.rows.length ||
      !Number.isSafeInteger(limit) || limit < 1 || limit > MAX_PAGE_SIZE) {
    throw new Error("Invalid synthetic dataset or bounded sample window");
  }
  const observations = catalog.rows.slice(offset, offset + limit);
  return {
    dataset_id: DATASET_ID,
    split: "development",
    source_sha256: catalog.identity.sha256,
    source_kind: "synthetic_only",
    offset,
    requested_limit: limit,
    returned: observations.length,
    next_offset: offset + observations.length < catalog.rows.length
      ? offset + observations.length : null,
    time_semantics: "All fields observed at the closed hour; backtests cannot act before the next bar opens",
    observations,
  };
}
