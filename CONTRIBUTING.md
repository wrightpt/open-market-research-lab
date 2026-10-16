# Contributing locally

Read [AGENTS.md](AGENTS.md), [DATA_POLICY.md](DATA_POLICY.md), and
[SECURITY.md](SECURITY.md). Contributions are original work within this repository.
Do not import private implementations, market data, research outcomes, account
identifiers, machine paths, or credentials. Use the system Python standard library;
no dependency installation or workstation configuration is necessary.

## Code changes

1. Inspect `git status --short --branch` and preserve existing work.
2. Explain the bounded change and its failure case. Keep I/O out of feature and
   accounting functions. Do not add arbitrary-code strategy plugins.
3. Add the smallest test that proves behavior. For a full initial prototype or
   changes spanning timing, accounting, or custody, run the complete local gate:

   ```bash
   python3 -m unittest discover -s tests -v
   python3 -m market_lab verify-data
   python3 -m market_lab validate submissions/baseline.json
   git diff --check
   ```

4. Run a development smoke test if execution changed, with a new artifact name.
   Review the complete diff and resulting evidence, including failed checks.
5. Local work may be committed after review. Once the public repository is
   released, fork it, make an isolated branch, and submit a PR using the included
   template. Never deploy or connect this code to private trading infrastructure.

Use readable PEP 8 Python with focused modules. No formatter or linter package is
required. Run the stdlib syntax/whitespace checks in `tests/test_repository.py`.
Changes to the schema must keep the validator's supported keyword subset explicit
and update adversarial input tests. Runtime imports remain standard library only.

## Portal and adapter changes

For portal work, also run `node --test developer_portal/tests/state.test.mjs`.
Use the loopback mock, never production OAuth or keys, to review access states.
For adapter work, `python3 -m unittest discover -s tests -p test_mcp.py -v`
exercises actual stdio and generated loopback HTTPS fixtures; it needs a local
OpenSSL binary but no third-party Python packages or remote service. Review
[PORTAL_CONTRACT.md](docs/PORTAL_CONTRACT.md) before changing envelopes. Supply
separate UI and adapter commits with exact local receipts. Backend authorization
and production activation require independent review. Do not run untrusted PR
executables on a credentialed workstation; use restricted GitHub-hosted CI.

## Strategy submissions

Copy `submissions/baseline.json` to a new repository-local JSON file. Choose a new
ID; explain the hypothesis, prior work, engineering acceptance criteria, and limits.
Keep the exact dataset hashes. The schema bounds lookbacks, thresholds, costs,
horizons, input size, row count, and one parameter set per invocation. Only the
built-in `liquidity_guard_v1` strategy is admitted in v1. There are no code entry
points, URLs, commands, external symbols, or executable attachments.

Record every development trial in retained reports and an accompanying rationale.
`research.development_trials` is a required disclosure, not an automatically audited
search counter. Numerical success does not select or validate this example.
Do not tune on holdout, choose the best holdout result, regenerate v1 fixtures,
or reopen a consumed holdout after a code fix. Change the dataset version and
disclose prior exposure if a later, separately scoped study needs fresh data.

Use the [PR template](.github/pull_request_template.md) as a local review checklist.
Public hosting requires the separate [release gates](docs/PUBLIC_RELEASE.md).
Original code contributed through a PR is offered under Apache-2.0 unless
otherwise agreed in writing; never submit code or data you cannot license.
AI-assisted changes need the same attribution, tests, review, and data rights
as human changes.
