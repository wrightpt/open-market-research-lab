// Synthetic-only, read-only MCP server for local testing.
// Deliberately has no production adapter, credentials, public listener, or
// configurable DB/cluster endpoint. Never deploy without a separate review.
import { createServer } from "node:http";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";
import {
  toNodeHandler, localhostHostValidation, localhostOriginValidation,
} from "@modelcontextprotocol/node";
import * as z from "zod/v4";
import {
  DATASET_ID, MAX_PAGE_SIZE, catalog, listDatasets, describeDataset, getSample,
} from "./catalog.mjs";

export const TOOL_NAMES = Object.freeze([
  "list_datasets", "describe_dataset", "get_sample",
]);
const safety = Object.freeze({
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: false,
});
const description =
  "Use only the publicly published synthetic fixture. No real market data, " +
  "production infrastructure access, trading, or performance predictions.";

function result(data) {
  return {
    structuredContent: data,
    content: [{ type: "text", text: JSON.stringify(data) }],
  };
}

export function buildMcpServer() {
  const server = new McpServer(
    { name: "open-market-research-synthetic", version: "0.1.0" },
    { instructions:
      "Only deterministic synthetic development data is accessible. " +
      "Do not claim market predictability or profitability. " +
      "Never request secrets, kubeconfigs, trades, or production database access." },
  );

  server.registerTool("list_datasets", {
    title: "List public synthetic datasets",
    description: `Discover only synthetic datasets offered by Open Market Research Lab. ${description}`,
    inputSchema: z.object({}).strict(),
    outputSchema: z.object({
      datasets: z.array(z.object({
        dataset_id: z.literal(DATASET_ID),
        synthetic: z.literal(true),
        sha256: z.string().regex(/^[a-f0-9]{64}$/),
      })),
    }),
    annotations: safety,
  }, async () => result(listDatasets()));

  server.registerTool("describe_dataset", {
    title: "Describe synthetic dataset provenance and fields",
    description: `Get the complete public synthetic dataset catalog and field meanings. ${description}`,
    inputSchema: z.object({
      dataset_id: z.literal(DATASET_ID),
    }).strict(),
    outputSchema: z.object({
      dataset_id: z.literal(DATASET_ID),
      synthetic: z.literal(true),
      fields: z.array(z.object({
        name: z.string(), unit: z.string(), meaning: z.string(),
      })),
    }),
    annotations: safety,
  }, async () => result(describeDataset()));

  server.registerTool("get_sample", {
    title: "Read bounded synthetic development observations",
    description: `Read at most ${MAX_PAGE_SIZE} rows of published, invented market data. ` +
      "This is NOT real price history. Offset is a row index within the development fixture. " +
      "Do not treat the public fixture as a blinded holdout or market evidence.",
    inputSchema: z.object({
      dataset_id: z.literal(DATASET_ID),
      offset: z.number().int().min(0).max(catalog.rows.length - 1).default(0),
      limit: z.number().int().min(1).max(MAX_PAGE_SIZE).default(5),
    }).strict(),
    outputSchema: z.object({
      dataset_id: z.literal(DATASET_ID),
      source_kind: z.literal("synthetic_only"),
      source_sha256: z.string().regex(/^[a-f0-9]{64}$/),
      returned: z.number().int().min(0).max(MAX_PAGE_SIZE),
      observations: z.array(z.object({ timestamp: z.string() })).max(MAX_PAGE_SIZE),
    }),
    annotations: safety,
  }, async (args) => result(getSample(args)));

  return server;
}

export function buildHttpServer() {
  const handler = createMcpHandler(() => buildMcpServer(), { responseMode: "json" });
  const nodeHandler = toNodeHandler(handler);
  const checkHost = localhostHostValidation();
  const checkOrigin = localhostOriginValidation();

  const httpServer = createServer((request, response) => {
    if (!checkHost(request, response) || !checkOrigin(request, response)) return;
    if (request.url === "/healthz" && request.method === "GET") {
      response.writeHead(200, {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
        "x-content-type-options": "nosniff",
      }).end('{"status":"ok","source":"synthetic_only"}');
      return;
    }
    if (request.url !== "/mcp") {
      response.writeHead(404, { "content-type": "text/plain", "cache-control": "no-store" }).end("Not found");
      return;
    }
    if (request.method !== "POST") {
      response.writeHead(405, { allow: "POST" }).end("Method not allowed");
      return;
    }
    // A public gateway will need its own ingress body limit. Locally, reject
    // chunked or missing-length POST bodies rather than permitting unbounded
    // streamed input around the Content-Length cap.
    if (request.headers["transfer-encoding"] || request.headers["content-length"] == null) {
      response.writeHead(411).end("Content-Length required");
      return;
    }
    const contentLength = Number(request.headers["content-length"]);
    if (!Number.isSafeInteger(contentLength) || contentLength < 1 || contentLength > 16_384) {
      response.writeHead(413).end("Payload too large");
      return;
    }
    void nodeHandler(request, response);
  });
  httpServer.requestTimeout = 8_000;
  httpServer.headersTimeout = 8_000;
  httpServer.keepAliveTimeout = 3_000;
  httpServer.on("close", () => { void handler.close(); });
  return httpServer;
}

function main() {
  const port = Number(process.env.PORT ?? 8787);
  if (!Number.isSafeInteger(port) || port < 1024 || port > 65535) {
    throw new Error("PORT must be an integer between 1024 and 65535");
  }
  // Intentionally no HOST override: avoid unintentionally exposing local MCP.
  const httpServer = buildHttpServer();
  httpServer.listen(port, "127.0.0.1", () => {
    console.log(`Synthetic-only MCP ready on http://127.0.0.1:${port}/mcp`);
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
