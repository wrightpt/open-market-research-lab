# Open Market Research Lab — reproducible synthetic research benchmark

A contributor-friendly lab for reproducible research mechanics. The initial challenge
asks whether liquidity deterioration and deleveraging alerts can precede drawdowns.
Every supplied observation is **deterministic synthetic data**. Results test code,
accounting, and research procedure; they provide **no evidence of market
predictability, profitability, alpha, or trading readiness**.

This checkout contains a Python standard-library backtest, a bounded JSON strategy
contract, synthetic fixtures with SHA-256 identities, tests, and contribution and
release policies. There are no services, accounts, databases, API keys, external
data integrations, or deployment components. The runnable lab has no public service or cluster access.

## Human quickstart

From the repository root, with **Python 3.11 or newer**:

```bash
python3 -m market_lab --help
python3 -m market_lab verify-data
python3 -m market_lab validate submissions/baseline.json
python3 -m unittest discover -s tests -v
python3 -m market_lab backtest submissions/baseline.json
```

No install, package manager, network, or virtual environment is required. The
environment profile is `stdlib-system`. The backtest writes
`artifacts/development.json` and prints a small summary. It includes every decision,
fill, close equity mark, costs, control summaries, and alert evaluation sample.
The initial example uses 5 basis points of fees and 3 basis points of adverse
slippage **per fill**, including terminal liquidation.

Outputs never overwrite existing files. For another development run:

```bash
python3 -m market_lab backtest submissions/baseline.json --output artifacts/development-002.json
```

Paths must be relative to this repository; outputs must be under `artifacts/`.
Do not delete prior evidence just to reuse a filename. `artifacts/` is ignored by
Git: retain original reports locally and explicitly review any evidence selected
for a future release. CLI validation errors exit with code 2.

## Claude Code, Codex, and OpenCode quickstart

Start your usual **interactive** agent in this checkout. All agents share
[AGENTS.md](AGENTS.md); there are no provider-specific hooks or permissions.
Give the agent a bounded task such as:

> Read AGENTS.md and the linked policies. Verify the synthetic fixture hashes,
> validate submissions/baseline.json, and run the unit tests. Explain the causal
> timing and accounting. Work only here; do not evaluate holdout, connect to
> external systems, access credentials, push, publish, or deploy.

For implementation work, specify one change and ask for its targeted test and
reviewed diff. The contributor owns the result regardless of which agent helped.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete local workflow.

## Development and the holdout exercise

Development is the only split accepted by `backtest`. Record all tried settings
and failed results. After the submission, selection rationale, costs, and
development report are final, freeze them:

```bash
python3 -m market_lab freeze submissions/baseline.json --development artifacts/development.json
```

The freeze binds the config, code and contract hash, dataset hashes, and development
report hash. It does **not** evaluate holdout. Only when deliberately exercising the
one-pass gate, run:

```bash
python3 -m market_lab holdout artifacts/freeze.json
```

That command writes a dataset-wide consumption receipt **before** opening the
holdout. A failed attempt stays consumed. A second attempt, including a different
submission, is rejected in this checkout. Do not reset, delete, move, or bypass
that receipt to retune. A new clone does not make a spent holdout fresh.

Both fixture files and their generator are visible. This is a **holdout workflow
exercise**, not a genuinely blind test or an independent sample from a market.
Routine tests verify holdout structure and gate behavior without evaluating its
strategy outcomes. Read [DATA_POLICY.md](DATA_POLICY.md) before any holdout work.

## Repository map

| Path | Purpose |
| --- | --- |
| `market_lab/` | Local CLI, bounded validation, causal features, accounting, evaluation |
| `data/synthetic-v1/` | Development/holdout CSVs and immutable versioned manifest |
| `schemas/submission.schema.json` | Machine-readable strategy submission contract |
| `submissions/baseline.json` | One transparent, fixed example; no parameter search |
| `tests/` | Causality, cost, data, contract, evidence, and workflow boundary checks |
| `docs/CHALLENGE.md` | Question, rules, outcomes, controls, and limits |
| `docs/ARCHITECTURE.md` | Formulas, data flow, trust boundaries, and design choices |
| `docs/RELEASE_GATES.md` | Local engineering acceptance and separately authorized future gates |
| `docs/LOCAL_VALIDATION.md` | Actual local test results and retained artifact identities |
| `.github/` | PR/issue templates and GitHub-hosted Python 3.11/3.14 CI |
| `outreach/` | Unpublished benchmark/code-review draft and forum launch gates |

[SECURITY.md](SECURITY.md) defines the threat model. Source code and original
synthetic fixtures are offered under the [Apache License 2.0](LICENSE), which
permits commercial reuse of these files. It does **not** license external market
data, internal trading strategies, private Kubernetes systems, or API access.
See [public release status](docs/PUBLIC_RELEASE.md) and the
[reproducibility review challenge](https://github.com/wrightpt/open-market-research-lab/issues/1).
PRs are welcome for focused fixes with synthetic evidence; the v1 JSON schema
currently admits only its built-in research rule, not arbitrary executable strategies.
