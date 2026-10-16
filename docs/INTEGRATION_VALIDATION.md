# Parent contract corrections — 2026-10-16

Applied sanitized interface instructions supplied by the parent coordinator after
the Phase 2 checkpoint, in a separate correction commit. No private backend source,
history or schema was inspected. Parent owns planning PR4 and the separate backend
integration run. No push, deployment, public endpoint or live credentials were used.

| Local gate | Actual result |
| --- | --- |
| `python3 -m unittest discover -s tests -v` | **88 passed**, 8.618 seconds; 43 original tests + 10 portal + 35 adapter |
| `node --test developer_portal/tests/state.test.mjs` | **10 passed**, 0 failed/skipped |
| `node developer_portal/tests/browser.cjs` | **10 passed**; desktop, tablet, mobile, standalone mock and mounted synthetic-test contract fixture |
| `python3 -m market_lab verify-data` | v1 hashes verified; 384 development + 192 holdout rows checked for custody/structure only |
| `python3 -m market_lab validate submissions/baseline.json` | Valid; unchanged SHA-256 `1673b1bdc7992d87a0b41654f9571a6fcb30bc565680528228bcca1652e58854` |
| Source/CI review | No obvious private hostpaths/credentials; read-only GitHub-hosted workflow, pinned actions, no secrets or privileged PR events |

Receipts are under ignored `artifacts/integration-*.txt`. Screenshots contain only
the synthetic landing page. No checked-in holdout outcome was evaluated.

Corrections cover agreed purpose/access/key/revocation/usage envelopes, 64-character
ASCII key names, explicit synthetic-test mode without demo controls or live OAuth
claims, dynamic metadata.time_basis and schema_version, distinct toy/API catalogs,
seven useful per-tool schemas, fixed transport attribution, and omitted unknown IDs
for uncorrelated MCP errors. Dataset/asset examples do not grant entitlement;
the adapter still forwards bounded objects to backend validation/authorization.

The mounted-mode browser test is a sanitized contract fixture served through local
route interception. HTTPS tests use newly generated local certificates and actual
stdio subprocesses. **No actual backend, official SDK or Claude Code/Codex/OpenCode/
ChatGPT integration is claimed.** Parent will capture those distinct receipts.

Modern and legacy MCP schemas both permit omission of unreadable error IDs and
exclude null. A dedicated subprocess regression covers malformed/invalid messages
after modern discovery and legacy initialization, preserving known IDs and omitting
unknown ones. [MCP_ADAPTER.md](MCP_ADAPTER.md) links both authoritative schemas.
Public activation and real-data licensing/admission still require explicit approval.
