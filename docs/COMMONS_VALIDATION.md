# Commons MVP local validation — 2026-10-22

Scope: the local synthetic evidence workflow added on top of specification commit
`0e29e0a46a76228d1127a3d99600e0ee6b4ea505`. No real data, live credentials,
holdout strategy evaluation, payments or public service were used.

## Commands and results

| Check | Result |
| --- | --- |
| `python3 -m unittest discover -s tests -v` | 110 tests passed on Python 3.14, including 22 Commons service/HTTP tests |
| `node --test developer_portal/tests/state.test.mjs` | 10 existing JavaScript checks passed |
| `node --check research_commons/static/app.js` | Passed |
| `node --check tests/browser_commons.cjs` | Passed |
| `python3 -m market_lab verify-data` | Exact synthetic fixture identities and row counts verified; no outcomes scored |
| `python3 -m market_lab validate submissions/baseline.json` | Valid |
| `git diff --check` | Passed |
| Browser workflow | 13 checks passed in Chromium, desktop 1440px and mobile 390px |

The environment registry resolved this unregistered repository to its workspace
fallback; its detector did not identify a package-managed Python project. The
repository's documented standard-library `python3` workflow was used. No packages
were installed and no unrelated environment registry was changed.

## Behavioral evidence

The tests cover actual HTTP create/run/replay/export, immutable submissions,
linked forks, differing report sections, rejection of mismatched approvals,
author/reviewer separation, conflicting and concurrent idempotency requests,
restart persistence, interrupted and failed attempts, source drift, input limits,
duplicate JSON fields, nonfinite values, Host/Origin/CSRF, session requirements,
single-writer locking, symlink rejection and corrupted journals. Engine source is
pinned at startup; an in-process source change cannot be attached to a new study
as if it described the already-loaded code. An explicit
regression proves that importing evidence after a failed run preserves the failed
attempt rather than relabeling it completed.

Browser checks create a study, render injection-like text literally, run the
engine, switch demo personas, replay, record a review, export and reload. They
then fork, download a submission, execute the real benchmark CLI, alter one fee
measurement, import the report, reproduce the mismatch and reject it. The checks
also cover search, filtering, empty states, mobile layouts, visible API errors
and recovery. No browser exceptions or external network requests were observed.

Portable optional browser test: `tests/browser_commons.cjs`. Run a separate local
instance on port 8788 with a dedicated `artifacts/` state directory and seed data.
Use an existing trusted Playwright installation, set `ORC_TEST_URL` if needed and
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` when its default browser binary is unavailable.
The test writes new receipts and screenshots under `artifacts/browser-*` and
retains its studies. It does not reset evidence or install browsers/packages.

## Retained local receipts

- Final Python log: `artifacts/commons-unit-tests-final.log`.
- Browser pass using the retained portable test: `artifacts/browser-1792724033106/receipt.json`, with desktop/mobile
  screenshots, downloaded submission, original CLI report, altered report and
  exported evidence package in that directory.
- Earlier browser attempts remain in `artifacts/browser-1792723581725/` and
  `artifacts/browser-1792723673688/`. The first exposed a case-sensitive test
  assertion against CSS-uppercase text; the second exposed a real mobile guide
  overflow, fixed with a grid-child minimum-width rule. Both failed receipts remain.
- Browser workspace: `artifacts/commons-browser-validation/`.
- Interactive preview workspace: `artifacts/commons/`; contains only the two
  labeled demonstration studies unless the operator has added more.

These ignored local files are not published with source. The journal and evidence
packages provide local durability and repeatability, not externally witnessed
custody, independent human review or scientific admission. Actual public hosting,
identity, licensed data, billing and isolated worker operations remain separate
release gates.
