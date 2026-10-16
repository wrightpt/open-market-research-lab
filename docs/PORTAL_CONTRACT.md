# Portal contract v1 — frontend/backend integration boundary

Status: public synthetic UI implementation contract, 2026-10-16. The routes and
mutation headers below are agreed. **Nested response shapes marked proposed are
mock assumptions awaiting backend review**, not a claim that the backend implements
them. No private backend source, schema, or history was consulted. This document
is the collaboration boundary; do not build a second production authorization layer.

The backend mounts the static assets at `/portal/` and owns sessions, GitHub OAuth,
CSRF generation/validation, access decisions, API-key security, quotas, and audit.
The browser sends same-origin cookies with `credentials: same-origin`, never API
keys to portal endpoints, and `X-CSRF-Token` on every mutation. Tokens and once-only
key secrets stay in memory and visible DOM only; no browser storage or URL params.

## Agreed routes

| Method and route | Request | Response consumed by UI |
| --- | --- | --- |
| GET `/portal/api/session` | none | `{authenticated, user: {id, login, access_status} \| null, csrf_token, mode}` |
| GET `/portal/api/datasets` | none | `{datasets: [metadata]}`; metadata proposal below |
| GET `/portal/api/keys` | none | `{keys: [{id, name, scopes, expires_at, created_at, revoked}]}`; never secrets |
| POST `/portal/api/access-requests` | **proposed** `{purpose: string}` | **proposed** `{access_status: "pending"}`; UI then refreshes session |
| POST `/portal/api/keys` | `{name, scopes: ["research:read"], expires_in_days: 30}` | **proposed** `{key: key_metadata, secret: string}` |
| POST `/portal/api/keys/{id}/rotate` | `{}` | **proposed** `{key: new_key_metadata, secret: string}`; old key revoked atomically by backend |
| DELETE `/portal/api/keys/{id}` | no body | **proposed** 204, or 200 JSON; UI refreshes key list |
| GET `/portal/api/usage` | none | `{limits, usage}`; nested proposal below |
| POST `/portal/api/logout` | `{}` | **proposed** 204, or 200 JSON; UI discards secrets and refreshes session |
| GET `/portal/auth/github` | navigation | backend OAuth redirect; demo only shows a mock-login notice |

`access_status`: proposed `none`, `pending`, `approved`, `denied`. Unknown values
fail closed to an unavailable state. `mode`: `demo` for the loopback preview;
proposed `production` for a separately configured backend. Authentication alone is
not approval. Hidden/disabled controls are convenience, never authorization.

Errors: proposed `{error: {code, message}}` with HTTP 400/401/403/409/429/5xx. UI
shows fixed status-based guidance, never raw exception text, headers, or payloads.
All responses containing session/key/account information require `Cache-Control:
no-store`; redirects are not accepted by browser API fetches. A 401 clears local
account state; a 403 refreshes approval before allowing another key action.

## Proposed sanitized metadata

```json
{
  "id": "synthetic-liquidity-v1",
  "title": "Liquidity deterioration lab",
  "synthetic": true,
  "asset": "TOY-USD",
  "venue": "NONE",
  "description": "Deterministic engineering fixtures, not market observations.",
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

The demo returns both split identities and all ten fields from public fixture
metadata, never holdout outcomes. Phase 1 presents synthetic records only. Unknown
or non-synthetic catalog records are withheld with an explicit status notice.
Metadata contains no storage names, internal hostnames, backend tables, account
identifiers, or acquisition endpoints. Dataset details come from this catalog;
there is no invented dataset-detail route.

Proposed usage values are nonnegative integers:
`limits: {requests_per_day, rows_per_request}` and
`usage: {requests_today, rows_today, resets_at}` (UTC timestamp). UI never invents
quota values for absent fields; it shows unavailable. Backend is authoritative.

## Demo-only behavior

The fixture server binds literal `127.0.0.1` only, validates Host and mutation
Origin/CSRF, serves a fixed asset allowlist, and has no database or OAuth client.
`/portal/demo/scenario` is a loopback-only mock control, not a production route.
Scenarios: anonymous, unrequested, approved, pending, denied, loading, failure. Account and key
state are throwaway in-memory mock values. Mock key strings cannot access any API.
`/portal/auth/github` must never impersonate real GitHub login in this preview.

## Shared research transport (Phase 2)

Only POST `/v1/research/tools/{name}` with a JSON arguments object and `X-API-Key`
is agreed. Names: `list_datasets`, `describe_dataset`, `get_coverage`, `get_schema`,
`query_timeseries`, `get_research_examples`, `get_usage_limits`. Backend owns argument
schema, authorization, query/row/concurrency bounds, and audit. The adapter does
not translate to SQL, inspect storage, or accept arbitrary paths/URLs/methods.

**Open integration items:** confirm metadata fields, key creation/rotation secret
envelope, access-request body/status vocabulary, usage units/reset field, and
research-tool argument schemas. The initial adapter forwards bounded object
arguments without claiming backend-specific validation. Contract tests can verify
these proposals; they cannot certify backend integration before that review.

Phase 2 additionally requires confirmation that research success is HTTP 200 with
a JSON object, and issued key strings are 16–2048 non-space printable ASCII
characters. The local adapter rejects other success envelopes and key encodings.
No assumption about backend tool argument field names is embedded. See
[MCP_ADAPTER.md](MCP_ADAPTER.md) for exact transport/protocol limits.
