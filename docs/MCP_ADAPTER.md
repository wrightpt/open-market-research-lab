# Local stdio HTTPS adapter — Phase 2

Run `python3 -m omr_mcp` from this checkout. It is a Python 3.11+ standard-library
client of an operator-selected research API, not an API server, authentication
provider, data entitlement, execution engine, or database connector. No production
origin or credential is supplied. No HTTP listener or public endpoint is created.

## Configuration and request boundary

| Environment name | Meaning |
| --- | --- |
| `OMR_API_URL` | Required HTTPS origin only; optional port and trailing slash; no credentials, path, query, fragment, whitespace, or scoped IPv6 address |
| `OMR_API_KEY` | Required private key, 16–2048 non-space printable ASCII characters; never passed in arguments, URLs, prompts or saved source configs |
| `OMR_CA_FILE` | Optional explicit PEM trust anchor file, primarily for the HTTPS fixture; certificate and hostname verification remain mandatory |

HTTPS is mandatory, including literal loopback. There is no HTTP development
exception or insecure TLS switch. TLS 1.2 or newer uses Python certificate and
hostname verification. The adapter does not follow redirects, honor ambient proxy
variables, retry requests, perform service discovery, or load plugins. Only
`X-API-Key` carries the key; no query-string or Authorization copy is made.

Exactly seven names map to POST `/v1/research/tools/{name}` with an arguments
object: `list_datasets`, `describe_dataset`, `get_coverage`, `get_schema`,
`query_timeseries`, `get_research_examples`, `get_usage_limits`. Caller fields never
choose a URL, method, path, header, filesystem destination, or executable. Backend
owns argument schema, data authorization, query bounds, quota charging and audit.
`omr_mcp/contracts.py` declares per-tool inputSchema from the agreed public contract:
empty objects for list_datasets/get_research_examples/get_usage_limits; a `dataset`
string for describe_dataset/get_coverage/get_schema; and dataset, asset, start,
end, max_rows for query_timeseries. max_rows is 1–500 and end is exclusive.
Discovery schemas guide clients; the adapter forwards bounded objects without
duplicating backend validation or dataset entitlement checks. The constant
`X-QMA-Client-Transport: mcp-public-adapter` header is log attribution only, never
an identity or authorization signal. See [PORTAL_CONTRACT.md](PORTAL_CONTRACT.md)
for exact synthetic catalog identities and examples.

Backend success currently requires HTTP 200 with a JSON object. Non-200 responses
(including redirects), non-JSON, compression, malformed/duplicate/nonfinite JSON,
truncation, oversize bodies, and reflected credentials become a fixed MCP tool
error. Backend bodies, headers, exceptions and local paths never appear in errors.
Successful JSON is untrusted research content, not agent instructions. Secret
reflection checks are defense in depth, not a replacement for backend sanitization.

## Protocol versions and limits

The implementation follows the official [2026-07-28 stdio binding](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio),
[base metadata rules](https://modelcontextprotocol.io/specification/2026-07-28/basic),
[versioning lifecycle](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning),
and [result schemas](https://modelcontextprotocol.io/specification/2026-07-28/schema).
Modern requests are stateless: each supplies these fields in **`params._meta`**,
including the first request. There is no required modern `initialize` handshake.

```json
{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}
```

Send each JSON object as one UTF-8 newline-terminated line, not pretty-printed
multiline JSON or Content-Length frames. `tools/list`, `tools/call`, and `ping`
use the same metadata. A tool call also puts `name` and `arguments` in `params`.
Missing required metadata returns `-32602`; unsupported modern versions return
`-32022` with `supported` and `requested`. Modern results include `resultType:
"complete"` and server identity; discovery/listing include `ttlMs: 0` and
`cacheScope: "private"`. This adapter advertises tools only; it has no resources,
prompts, subscriptions, sampling, elicitation, tasks or server-to-client requests.

Uncorrelated parse/invalid-request errors omit `id`; known valid IDs are echoed
unchanged. Both the [modern schema](https://modelcontextprotocol.io/specification/2026-07-28/schema#jsonrpcerrorresponse)
and [legacy 2025-11-25 schema](https://modelcontextprotocol.io/specification/2025-11-25/schema#jsonrpcerrorresponse)
define an optional string/number RequestId, not null. A stdio regression covers
parse failures, invalid null request IDs, and correlated errors in both eras.

An independent compatibility path implements [legacy 2025-11-25 initialization](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle):
`initialize` with that exact version, clientInfo and capabilities, followed by
`notifications/initialized`. Subsequent legacy calls omit modern metadata/results.
Other legacy revisions are explicitly rejected. Modern metadata still selects
modern behavior in an initialized process. Tests exercise both eras through real
stdin/stdout subprocesses; this is not a claim of testing every agent release.

| Boundary | Limit / behavior |
| --- | --- |
| Stdin line | 65,536 bytes including newline; overlong/unterminated input returns error then exits 2 |
| JSON inputs | 16 levels, no duplicates/nonfinite numbers/lone surrogates; no batch arrays |
| Tool arguments | 32,768 UTF-8 bytes before any HTTPS operation |
| HTTP body | 262,144 bytes; streamed limit even without Content-Length; no decompression |
| HTTP headers | Python http.client's bounded parser (64 KiB per line, 100 headers); no header forwarding to stdout |
| Stdio output | 2,097,152 bytes including newline and text/structured duplication; depth 20 allows protocol wrapping; JSON only |
| Pending work | One HTTPS call and eight queued input/completion events; control requests remain responsive |
| Deadline | 10 seconds to return a tool result, including platform DNS/TLS/read stalls; no automatic retry |
| Cancellation | Suppress further replies, signal worker, check before sending credentials and between reads; work may already have reached the backend |
| EOF | Finish/discard pending result within its deadline, then exit; stuck resolver thread is daemonized |

A timed-out platform resolver may remain alive until the OS returns. A semaphore
admits no second network worker while it remains active; restart the adapter if
needed. A connection returning after its deadline is closed before sending the
API key or body. Cancellation cannot undo backend audit/quota work, and must not be used as
an automatic retry signal. Duplicate in-flight IDs close the transport. Idle stdin
and client stdout consumption are flow-controlled by the client, not network timers.

## Reproduce without credentials or a remote service

```bash
python3 -m unittest discover -s tests -p test_mcp.py -v
```

Tests require the local `openssl` binary to generate an ephemeral test certificate
and private key under ignored `artifacts/`. No certificate, private key, token,
network download or external service is checked in. Python runtime has no third-party
packages. The fixture binds literal loopback HTTPS, verifies its trusted certificate,
rejects wrong hostnames and unknown trust, checks redirects/proxies/leaks/limits,
and launches the actual adapter subprocess. Test-only credentials are visibly fake.

## Operation, rotation and rollback

After a separate backend is approved, pass its origin/key privately to the client
process using [AGENT_SETUP.md](AGENT_SETUP.md). Only authorize a reviewed origin;
the adapter is not an outbound network sandbox. It never contacts Kubernetes,
Vault, ClickHouse or another private control/data plane. Inspect all seven discovered
tools before use. Keep datasets and key scopes constrained at the backend.

On rotation, privately update the process environment and restart the adapter;
never print the environment for troubleshooting. Revoke a compromised key in the
backend and stop all adapter instances using it. EOF or process termination stops
the adapter. Select an earlier reviewed commit for code rollback; never restore
keys, authorization ledgers, consumption receipts or quotas as part of code rollback.
Keep raw restricted data and secrets out of logs/agent transcripts. The adapter
contains no audit store; the shared API must retain redacted audit records.

Production integration still needs real backend negative authorization/expiry/revocation
tests, success-envelope compatibility, operator credentials, and explicit
activation approval. These are separate from the local transport acceptance tests.
