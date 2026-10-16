# Phase 1 local validation — 2026-10-16

Local environment: Python 3.14.4, Node 22.23.2. No hosted CI run is claimed for
this branch; the workflow retains Python 3.11/3.14 on restricted GitHub-hosted
runners with a read-only token and adds the native Node tests.

| Check | Actual result |
| --- | --- |
| `python3 -m unittest discover -s tests -v` | 52 passed; 6.126 seconds |
| Portal-only Python rerun after input review | 9 passed; 4.033 seconds |
| `node --test developer_portal/tests/state.test.mjs` | 8 passed, 0 failed/skipped |
| `node developer_portal/tests/browser.cjs` | 9 rendered checks passed |
| `python3 -m market_lab verify-data` | Verified v1; development 384 rows, holdout metadata/structure 192 rows |
| `python3 -m market_lab validate submissions/baseline.json` | Valid; SHA-256 `1673b1bdc7992d87a0b41654f9571a6fcb30bc565680528228bcca1652e58854` |
| Source policy review | No obvious credentials/private host paths; no raw HTML insertion or browser credential storage |

Rendered checks used an existing Chrome through Playwright under a virtual display;
the optional browser dependency had no bundled Chromium. A long temporary path
exceeded Chrome's Unix socket limit; a short process-relative path to the same
ignored artifact directory resolved that environment issue. One initial browser
assertion retained its own search filter; clearing that filter fixed the test.
Final screenshots use the reduced-motion preference and wait for the selected
view: disabling animations only during capture had produced a blank capture.
Mobile brand spacing and the demo selector after logout were corrected in review.
No browser or dependency was downloaded. Final flows passed at 1440, 768 and
375 pixels, including ten metadata fields, split identities, loading, failed,
pending/denied, access request, once-only create/rotate/revoke, HTML-as-text, logout,
and empty persistent storage. Landing screenshots are local ignored artifacts.

No checked-in holdout outcome evaluation, backend login, real credential, external
API, database, deployment, push, or hosted endpoint was used. Tests exercise the
mock contract; they do not prove production authorization. The proposed nested
envelopes and research argument schemas in PORTAL_CONTRACT.md need backend review.
