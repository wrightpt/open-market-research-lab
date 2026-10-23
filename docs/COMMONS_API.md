# Commons local HTTP contract v1

Base: `http://127.0.0.1:8787/commons/api`. This is a local, synthetic-only
interface. There is no public identity, OAuth, payment or hosted-execution service.
The existing seven-tool HTTPS MCP adapter is unchanged and does not target this API.

## Session and request boundary

GET `/session` creates a one-hour, in-memory session and returns
`{actor, csrf_token, mode: "local_synthetic"}`. Retain the HttpOnly, SameSite=Strict
cookie. Other API reads require this cookie. All requests must use the exact
literal-loopback Host with port. POST requires the exact Origin, session cookie,
`X-CSRF-Token`, `Content-Type: application/json` and one Content-Length. Cross-site
browser requests, transfer encoding, duplicate JSON keys, nonfinite numbers,
excessive nesting and bodies over 2,000,000 bytes are rejected. API responses are
no-store. There is no CORS access or redirect-following contract.

Persisted mutations also require `Idempotency-Key` (8–100 ASCII letters, digits,
hyphens or underscores). A key is scoped to the local persona and binds the
operation, study ID and canonical body. Same-key retries return the retained study;
changed input with that key fails. A completed request never reruns the engine.
After an interrupted operation, the same key returns its retained failure; an
intentional retry must use a new key. After uncertain network delivery, inspect
the study or retry with the original key before starting a new operation.

## Resources

| Method / path | Body / result |
| --- | --- |
| GET `/meta` | Mode, personas, baseline submission, development dataset identity, local limits |
| POST `/persona` | `{actor: "researcher"}` or `{actor: "reviewer"}`; session-only demo selection |
| GET `/studies` | `{studies: [...]}`; summaries, submission, review decisions, newest created first |
| POST `/studies` | `{submission: <complete validated benchmark submission>, parent_id: null \| <study id>}` |
| GET `/studies/{id}` | Full study including retained evidence, reproduction, reviews and attempts |
| POST `/studies/{id}/run` | `{}`; author runs the bounded development engine and retains its report |
| POST `/studies/{id}/import` | `{report: <complete development report>}`; author attaches unverified evidence |
| POST `/studies/{id}/reproduce` | `{}`; other persona runs exact submission and compares the complete canonical report |
| POST `/studies/{id}/review` | `{verdict: "accepted" \| "needs_changes" \| "rejected", rationale, conflicts}` |
| GET `/studies/{id}/submission` | Download complete bounded submission JSON for the existing benchmark CLI |
| GET `/studies/{id}/export` | Download evidence package with both reports, reviews, attempt records and hashes |

Mutations return HTTP 200 with the full retained study. Engine failure also returns
the retained study with `status: "failed"`; clients must inspect this status.
Malformed or disallowed operations return 400 with `{error: {message}}`;
missing session returns 401, Host/Origin/CSRF rejection 403, unknown routes 404,
oversized body 413, wrong content type 415, and local storage failure 503.
No user-supplied filesystem path or executable is accepted over HTTP.

## Evidence and transitions

A study records its author persona, submission, source hash, manifest hash and
optional parent. There are no edit/delete endpoints. Create a new submission ID
and parent reference for a revision. The author may submit one report, either by
running the engine or importing data. All body fields and strategy limits follow
`schemas/submission.schema.json`; this API grants no new strategy vocabulary.

Transitions: `draft → running → submitted → verifying → reproduced | disputed`.
Imports move directly from draft to submitted. An engine or interrupted-process
failure retains `failed` plus an attempt receipt. A fresh request key may retry
the failed stage; prior attempts remain. An accepted review requires a matched
replay and a different persona; rejected and needs-changes reviews are also kept.
Reviews never replace the reproduction verdict or erase earlier decisions.

Imported evidence must bind the exact study submission, current/frozen engine and
development fixture. Numeric claims remain unverified until complete canonical
report equality; equal summary metrics alone do not pass. The comparison uses
the existing `market_lab.io.object_hash` canonical JSON encoding (sorted keys,
two-space indentation, trailing LF, no nonfinite values), not upload byte order.

Export `study_sha256` hashes the included study object. Each retained report has
its own canonical hash. `history` is event metadata for inspection, not a complete
standalone journal-chain proof; full journal verification requires all original
event files, including payloads. Export packages contain no session cookies or CSRF.

The current algorithm proves local same-engine repeatability only. Neither a
persona switch nor an accepted review establishes external reviewer independence.
