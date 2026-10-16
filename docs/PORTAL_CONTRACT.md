# Portal contract v1 — frontend/backend integration boundary

Status: sanitized frontend/backend contract, confirmed through parent integration
review on 2026-10-16. Routes, account states, key envelopes, usage fields and tool
argument shapes below are agreed. No private backend source, schema, or history
was consulted. This is the collaboration boundary; do not build a second production
authorization layer. Full backend mount/authorization tests are a separate receipt.

The backend mounts the static assets at `/portal/` and owns sessions, GitHub OAuth,
CSRF generation/validation, access decisions, API-key security, quotas, and audit.
The browser sends same-origin cookies with `credentials: same-origin`, never API
keys to portal endpoints, and `X-CSRF-Token` on every mutation. Tokens and once-only
key secrets stay in memory and visible DOM only; no browser storage or URL params.

## Agreed routes

| Method and route | Request | Response consumed by UI |
| --- | --- | --- |
| GET `/portal/api/session` | none | `{authenticated, user: {id, login, access_status} \| null, csrf_token, mode}` |
| GET `/portal/api/datasets` | none | `{datasets: [metadata]}`; metadata projection below |
| GET `/portal/api/keys` | none | `{keys: [{id, name, scopes, expires_at, created_at, revoked}]}`; never secrets |
| POST `/portal/api/access-requests` | `{purpose: string}` | `{access_status: "pending"}`; UI then refreshes session |
| POST `/portal/api/keys` | `{name, scopes: ["research:read"], expires_in_days: 30}` | `{key: key_metadata, secret: string}` |
| POST `/portal/api/keys/{id}/rotate` | `{}` | `{key: new_key_metadata, secret: string}`; old key revoked atomically by backend |
| DELETE `/portal/api/keys/{id}` | no body | 200 `{revoked: true}`; UI refreshes key list |
| GET `/portal/api/usage` | none | `{limits, usage}`; nested fields below |
| POST `/portal/api/logout` | `{}` | 204, or 200 JSON; UI discards secrets and refreshes session |
| GET `/portal/auth/github` | navigation | backend OAuth redirect; demo only shows a mock-login notice |

`access_status`: `none`, `pending`, `approved`, `denied`. Unknown values fail closed
to unavailable. `mode: demo` belongs only to the standalone loopback fixture and
its scenario selector. `mode: synthetic-test` labels the backend account/key
prototype, hides that selector, and does not claim live GitHub OAuth is configured.
Only a separately configured `production` mode presents the real GitHub sign-in
link. Authentication alone is not approval. Controls never implement authorization.
Key names are nonempty printable ASCII, at most 64 characters; UI and demo enforce
that input contract. Key scope and expiry remain research:read and 30 days.

Errors: `{error: {code, message}}` with HTTP 400/401/403/409/429/5xx. UI
shows fixed status-based guidance, never raw exception text, headers, or payloads.
All responses containing session/key/account information require `Cache-Control:
no-store`; redirects are not accepted by browser API fetches. Mutation 401/403 responses trigger a fresh session check before another key action.

## Sanitized catalog metadata

```json
{
  "id": "synthetic-liquidity-v1",
  "title": "Liquidity deterioration lab",
  "synthetic": true,
  "asset": "TOY-USD",
  "venue": "NONE",
  "description": "Deterministic engineering fixtures, not market observations.",
  "schema_version": 1,
  "time_basis": "UTC bar close; features available at that close; next-row open execution",
  "granularity": "1h",
  "freshness": "Frozen fixture; no live updates",
  "retention": "Versioned source fixture; immutable v1",
  "provenance": "market_lab.fixtures:v1:integer-lcg",
  "license": "Apache-2.0 (original synthetic fixture only)",
  "coverage": [{"split": "development", "start": "2024-01-01T01:00:00Z", "end": "2024-01-17T00:00:00Z", "rows": 384, "sha256": "2f09fc34b9c7124b4d3bcdb93b8227c6c3a451b1c10d544016860d174fa6d544"}],
  "gaps": "24 omitted hours between splits; missing depth stays unknown",
  "fields": [{"name": "timestamp", "type": "string", "unit": "UTC bar close", "nullable": false}]
}
```

This example describes only the offline toy dataset. The demo returns both split identities and all ten fields from public fixture
metadata, never holdout outcomes. Phase 1 presents synthetic records only. Unknown
or non-synthetic catalog records are withheld with an explicit status notice.
Metadata contains no storage names, internal hostnames, backend tables, account
identifiers, or acquisition endpoints. Dataset details come from this catalog;
there is no invented dataset-detail route.

The UI renders `schema_version` and the dataset's own `time_basis` dynamically.
Never apply the toy bar-close convention to API fixtures. Backend synthetic
timeseries use UTC bucket boundaries and end-exclusive queries. The catalogs
are distinct; never attach toy CSV hashes or coverage to an API dataset ID.

Usage values are nonnegative integers:
`limits: {requests_per_day, requests_per_minute, rows_per_request}` and
`usage: {requests_today, rows_today, resets_at}` (UTC timestamp). UI never invents
quota values for absent fields; it shows unavailable. Backend is authoritative.

## Demo-only behavior

The fixture server binds literal `127.0.0.1` only, validates Host and mutation
Origin/CSRF, serves a fixed asset allowlist, and has no database or OAuth client.
`/portal/demo/scenario` is a loopback-only mock control, not a production route.
Scenarios: anonymous, unrequested, approved, pending, denied, loading, failure. Account and key
state are throwaway in-memory mock values. Mock key strings cannot access any API.
`/portal/auth/github` must never impersonate real GitHub login in this preview.

## Shared research transport

Only POST `/v1/research/tools/{name}` with a JSON arguments object and `X-API-Key`
is agreed. Names: `list_datasets`, `describe_dataset`, `get_coverage`, `get_schema`,
`query_timeseries`, `get_research_examples`, `get_usage_limits`. Backend owns argument
schema, authorization, query/row/concurrency bounds, and audit. The adapter does
not translate to SQL, inspect storage, or accept arbitrary paths/URLs/methods.

The agreed argument shapes are:

| Tools | JSON arguments |
| --- | --- |
| list_datasets, get_research_examples, get_usage_limits | `{}` |
| describe_dataset, get_coverage, get_schema | `{"dataset":"synthetic-perp-daily-v1"}` |
| query_timeseries | `{"dataset":"synthetic-perp-daily-v1","asset":"BTC","start":"2026-01-01T00:00:00Z","end":"2026-01-03T00:00:00Z","max_rows":100}` |

`max_rows` is at most 500; start is inclusive and end exclusive at UTC bucket
boundaries. Known API IDs are `synthetic-perp-daily-v1`,
`synthetic-perp-hourly-v1`, and `synthetic-liquidity-research-v1`. BTC, ETH, HYPE
and XMR are names for invented fixture series, not real market observations.
These examples are not entitlements: backend owns validation, asset availability,
schema enforcement, authorization, limits and audit. No real data is admitted.

`omr_mcp/contracts.py` exposes useful inputSchema for each tool. The adapter
forwards bounded arguments; it does not enforce dataset entitlements or duplicate
query authorization. It sends `X-QMA-Client-Transport: mcp-public-adapter` for log
attribution only. The backend must never trust that header as identity or permission.

The adapter accepts HTTP 200 JSON-object results and 16–2048 printable non-space
ASCII key strings. Its tests prove this transport boundary against a generated
local TLS fixture, not a real backend or vendor client. Parent will run integrated
backend tests separately. See [MCP_ADAPTER.md](MCP_ADAPTER.md) for exact limits.
