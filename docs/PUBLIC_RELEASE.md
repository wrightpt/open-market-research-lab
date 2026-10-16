# Public source release — verified status

**Status: PUBLIC SOURCE REPOSITORY.** This is an open-source engineering
benchmark, not a service connected to a production trading cluster.

- GitHub: https://github.com/wrightpt/open-market-research-lab
- Initial public source revision:
  `6c610f4f4c77c7900ad93798e6a1854d1fce30bf`
- License: Apache License 2.0, for the original code and deterministic synthetic fixtures
- Hosted Actions run: https://github.com/wrightpt/open-market-research-lab/actions/runs/38830936693
- Hosted result: **success**, `stdlib (3.11)` and `stdlib (3.14)`
- Local reproducibility: **43 passing Python standard-library tests**, synthetic
  dataset hash verified, submission schema validated. The checked-in synthetic
  holdout was not evaluated for strategy outcomes.

## Repository and security controls

- The public repository is intentionally isolated from internal Kubernetes
  GitOps, `trading-system`, production ClickHouse, credentials, wallet/exchange
  accounts, and live order execution.
- Actions use GitHub-hosted ephemeral runners, full-SHA action pins, and
  read-only `GITHUB_TOKEN`. No repository secrets, self-hosted runners,
  deployment triggers, or production network connections are authorized.
- The repository's Actions default token permissions are read-only, full
  commit-SHA pinning is required, and Actions cannot approve its own PRs.
- `main` has branch protection: contributions come through pull requests,
  and both Python 3.11 and 3.14 CI jobs plus resolved review conversations
  are required. Force pushes and deletion are not allowed. No required
  reviewer count is currently enforced so the sole maintainer can handle PRs.
- GitHub **private vulnerability reporting** is enabled. Security-sensitive
  reports must use that channel rather than public issues.
- A manual hosted workflow completed successfully; testing the actual
  external-fork PR path is a separate outstanding acceptance test.

## Current participation workflow

Anyone may clone this repository, run the deterministic synthetic benchmark,
use Claude Code, Codex, OpenCode, or equivalent local tools to inspect it, and
propose code/documentation changes through a fork and PR. See
[CONTRIBUTING](../CONTRIBUTING.md) and the public
[reproducibility issue](https://github.com/wrightpt/open-market-research-lab/issues/1).

The current JSON strategy-submission contract accepts only the built-in
`liquidity_guard_v1` mechanism. An extensible public strategy architecture and
larger licensed data access are **future work**, not present capabilities.

## Disclosure and business trade-off

Apache 2.0 permits third parties to study, modify, redistribute, and
commercially reuse this code subject to its terms. This does not grant
redistribution rights for exchange data or access to private services.
Possible commercial value lies in separately authorized market datasets,
hosted reproducible evaluations, resource-isolated compute, and support.

Research results from scripted synthetic scenarios carry **no evidence of
market predictability, alpha, or profitability**.

## Still not launched

- No public market-data endpoint or database identity is enabled.
- No external contributor code runs inside the production cluster.
- No Reddit, Hacker News, Facebook, or other forum post has been published
  from this launch workflow. Drafts remain under `outreach/`; select and
  approve the exact destination and post text before sending.
- GitHub-hosted PR checks and private vulnerability reporting do not
  substitute for independent red-team review of future execution services.

## Future real-data admission

Each venue/source must have documented rights for downloads, display, derived
series, API/MCP distribution, commercial use and retention. Preserve origin
metadata, coverage/time semantics and missingness. Use only reviewed,
versioned product views through a dedicated read-only ClickHouse identity,
with auth, query/concurrency quotas and isolated infrastructure. Anonymous
submitted code belongs in disposable, segregated execution, **never inside
the cluster carrying live trading workloads**.
