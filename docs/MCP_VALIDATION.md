# Phase 2 local validation — 2026-10-16

The initial adapter-only run passed 30 tests in 1.972 seconds. Subsequent review
added a maximum-nesting stdio regression check and rejected escaped lone surrogates.
Phase 2 checkpoint gate: **85 Python tests passed in 7.837 seconds**, **8 Node tests
passed (0 failed/skipped)**, fixture verification succeeded (384 development rows,
192 holdout rows checked only for metadata/structure), and the baseline submission
validated with unchanged SHA-256
`1673b1bdc7992d87a0b41654f9571a6fcb30bc565680528228bcca1652e58854`.
The total comprises 43 original benchmark/policy tests, 9 portal tests and 33
adapter tests. `git diff --check` passed. The first combined run had one missing
link while this receipt file was being added; the corrected final run is fully green.
Both raw receipts remain in ignored artifacts. The 9 rendered UI checks also passed.
The final transport review also proved cancellation before connect sends nothing,
and a late DNS/connection completion cannot send credentials after the deadline.

This receipt describes the Phase 2 checkpoint before the separately committed
parent integration corrections. Full backend and vendor-client tests remain separate.

The test boundary is a newly generated loopback HTTPS fixture and actual Python
stdio subprocesses, not a production service. All test credentials are synthetic;
ephemeral TLS files are generated under ignored artifacts and removed by teardown.
No existing credential, private source/history/schema, database, cluster, Vault,
account, holdout outcome, public endpoint, deployment or push is used.

Compatibility evidence is specific to modern MCP 2026-07-28 per-request metadata,
discovery, result/cache fields, and legacy 2025-11-25 initialize/initialized/tool
calls. Tests cover malformed requests, unknown methods/tools, metadata omission,
unsupported versions, JSON byte/depth/encoding bounds, certificate trust/hostname,
redirect refusal, proxy avoidance, error/body/header redaction, reflected credentials,
wall deadlines, one-call concurrency, cancellation, EOF, and stdout framing.

Setup snippets were checked against local Codex CLI help and official client
documentation; no real Claude Code/Codex/OpenCode/ChatGPT account integration was
activated. Backend schemas and proposed envelopes still require contract review;
production authorization, key expiry/revocation and quota/audit enforcement are
backend acceptance gates. Hosted CI has not run on these unpushed commits.
