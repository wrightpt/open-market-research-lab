import test from "node:test";
import assert from "node:assert/strict";
import { request as httpRequest } from "node:http";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import {
  DATASET_ID, MAX_PAGE_SIZE, listDatasets, describeDataset, getSample, readSyntheticCatalog,
} from "../catalog.mjs";
import { buildHttpServer, TOOL_NAMES } from "../server.mjs";

const ROOT = resolve(import.meta.dirname, "../../../");

async function localService(fn) {
  const server = buildHttpServer();
  await new Promise((yes, no) => server.once("error", no).listen(0, "127.0.0.1", yes));
  const url = `http://127.0.0.1:${server.address().port}`;
  try { return await fn(url); }
  finally { await new Promise((yes, no) => server.close(err => err ? no(err) : yes())); }
}

async function connectedClient(fn) {
  return localService(async (url) => {
    const client = new Client({ name: "public-synthetic-audit", version: "0.1.0" });
    const transport = new StreamableHTTPClientTransport(new URL(url + "/mcp"));
    await client.connect(transport);
    try { return await fn({ client, url }); }
    finally { await client.close(); }
  });
}

function parseResult(reply) {
  if (reply?.isError) throw new Error(JSON.stringify(reply));
  return reply.structuredContent ?? JSON.parse(reply.content?.[0]?.text || "{}");
}

function rawHttp({ url, path, method = "GET", host, origin, payload, chunked = false }) {
  return new Promise((yes, no) => {
    const request = httpRequest(new URL(path, url), {
      method,
      headers: {
        ...(host ? { Host: host } : {}),
        ...(origin ? { Origin: origin } : {}),
        ...(payload ? { "Content-Type": "application/json", ...(chunked ? { "Transfer-Encoding": "chunked" } : { "Content-Length": String(Buffer.byteLength(payload)) }) } : {}),
      },
      timeout: 2000,
    }, response => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", part => body += part);
      response.on("end", () => yes({ status: response.statusCode, body }));
    });
    request.on("error", no);
    request.end(payload);
  });
}

test("Only the exact approved synthetic manifest and SHA-256 are served", () => {
  const manifest = JSON.parse(readFileSync(join(ROOT, "data/synthetic-v1/manifest.json"), "utf8"));
  const list = listDatasets();
  assert.deepEqual(list.datasets.map(item => item.dataset_id), [DATASET_ID]);
  assert.equal(list.datasets[0].sha256, manifest.splits.development.sha256);
  assert.equal(list.datasets[0].synthetic, true);
  assert.equal(list.datasets[0].market_data, false);
  assert.equal(describeDataset().fields.length, 10);
  assert.equal(getSample({ dataset_id: DATASET_ID, offset: 0, limit: 5 }).observations.length, 5);
  assert.equal(getSample({ dataset_id: DATASET_ID, offset: 383, limit: 20 }).returned, 1);
  assert.throws(() => getSample({ dataset_id: DATASET_ID, offset: 0, limit: 21 }), /Invalid/);
  assert.throws(() => getSample({ dataset_id: "live-trading", offset: 0, limit: 1 }), /Invalid/);
  assert.throws(() => getSample({ dataset_id: DATASET_ID, offset: -1, limit: 1 }), /Invalid/);
});

test("Fails closed for tampered bytes and non-synthetic source", () => {
  const temp = mkdtempSync(join(tmpdir(), "omr-synthetic-audit-"));
  try {
    const data = join(temp, "data/synthetic-v1");
    mkdirSync(data, { recursive: true });
    const manifest = readFileSync(join(ROOT, "data/synthetic-v1/manifest.json"));
    const fixture = readFileSync(join(ROOT, "data/synthetic-v1/development.csv"));
    writeFileSync(join(data, "manifest.json"), manifest);
    writeFileSync(join(data, "development.csv"), fixture);
    assert.equal(readSyntheticCatalog(temp).rows.length, 384);
    writeFileSync(join(data, "development.csv"), Buffer.concat([fixture, Buffer.from("unexpected")]));
    assert.throws(() => readSyntheticCatalog(temp), /SHA-256/);
    writeFileSync(join(data, "development.csv"), fixture);
    const modified = JSON.parse(manifest.toString());
    modified.synthetic = false;
    writeFileSync(join(data, "manifest.json"), JSON.stringify(modified));
    assert.throws(() => readSyntheticCatalog(temp), /synthetic/);
    modified.synthetic = true;
    modified.splits.development.file = "../../private/db";
    writeFileSync(join(data, "manifest.json"), JSON.stringify(modified));
    assert.throws(() => readSyntheticCatalog(temp), /Unapproved/);
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
});

test("Official MCP client discovers only three read-only, non-destructive tools", async () => {
  await connectedClient(async ({ client }) => {
    const { tools } = await client.listTools();
    assert.deepEqual(tools.map(t => t.name).sort(), [...TOOL_NAMES].sort());
    for (const tool of tools) {
      assert.equal(tool.annotations?.readOnlyHint, true, tool.name);
      assert.equal(tool.annotations?.destructiveHint, false, tool.name);
      assert.equal(tool.annotations?.openWorldHint, false, tool.name);
      assert.ok(tool.inputSchema, tool.name);
      assert.ok(tool.outputSchema, tool.name);
    }
  });
});

test("Official MCP client receives deterministic catalog and bounded sample", async () => {
  await connectedClient(async ({ client }) => {
    const list = parseResult(await client.callTool({ name: "list_datasets", arguments: {} }));
    assert.equal(list.datasets.length, 1);
    const detail = parseResult(await client.callTool({
      name: "describe_dataset", arguments: { dataset_id: DATASET_ID },
    }));
    assert.equal(detail.fields.length, 10);
    assert.equal(detail.accessible_split, "development");
    const sample = parseResult(await client.callTool({
      name: "get_sample", arguments: { dataset_id: DATASET_ID, offset: 5, limit: MAX_PAGE_SIZE },
    }));
    assert.equal(sample.returned, MAX_PAGE_SIZE);
    assert.equal(sample.next_offset, 25);
    assert.equal(sample.source_sha256, list.datasets[0].sha256);
    assert.deepEqual(sample.observations[0], getSample({
      dataset_id: DATASET_ID, offset: 5, limit: MAX_PAGE_SIZE,
    }).observations[0]);
    const txt = JSON.stringify(sample);
    assert.equal(/\/home\/|localhost|10\.10\./.test(txt), false);
    assert.equal(txt.includes("2024-01-18"), false, "Holdout not readable through this tool");
  });
});

test("Invalid tool arguments fail without returning arbitrary data", async () => {
  await connectedClient(async ({ client }) => {
    for (const args of [
      { dataset_id: DATASET_ID, offset: 0, limit: 21 },
      { dataset_id: "../", offset: 0, limit: 2 },
      { dataset_id: DATASET_ID, offset: 0, limit: 2, sql: "SELECT * FROM secrets" },
    ]) {
      let failed = false;
      try {
        const res = await client.callTool({ name: "get_sample", arguments: args });
        failed = !!res.isError;
      } catch { failed = true; }
      assert.equal(failed, true, JSON.stringify(args));
    }
  });
});

test("Host/origin rejection, loopback-only health and request bounds", async () => {
  await localService(async url => {
    const ready = await rawHttp({ url, path: "/healthz" });
    assert.equal(ready.status, 200);
    assert.equal(JSON.parse(ready.body).source, "synthetic_only");
    assert.equal((await rawHttp({ url, path: "/debug" })).status, 404);
    assert.equal((await rawHttp({ url, path: "/mcp" })).status, 405);
    assert.equal((await rawHttp({ url, path: "/healthz", host: "evil.invalid" })).status, 403);
    assert.equal((await rawHttp({ url, path: "/healthz", origin: "https://evil.invalid" })).status, 403);
    assert.equal((await rawHttp({ url, path: "/mcp", method: "POST", payload: "x".repeat(16_385) })).status, 413);
    assert.equal((await rawHttp({ url, path: "/mcp", method: "POST", payload: "{}" , chunked: true })).status, 411);
  });
});
