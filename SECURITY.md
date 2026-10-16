# Security and scope

This prototype runs locally with the caller's normal OS permissions. Its JSON
validation is **not a sandbox for hostile Python or PR code**. Review source before
running it. No live-market, account, database, credential, infrastructure, or
deployment access is part of the implementation or its tests.

## Trust boundaries

- Submissions are bounded declarative JSON, at most 32 KiB and 16 levels deep.
  Unknown fields, duplicate keys, nonfinite numbers, unbounded parameters, different
  dataset hashes, and executable strategy names fail validation.
- CSVs are limited to 256,000 bytes and 1,000 hourly rows, with finite ranges,
  exact columns, OHLC bounds, explicit missing values, and SHA-256 custody.
- CLI paths are repository-relative and reject traversal and symlinks. Outputs
  use exclusive creation under `artifacts/`. Existing reports are never replaced.
- The offline `market_lab` runtime has no network clients, database drivers,
  subprocess execution, dynamic plugin loading, environment-secret reads, or telemetry.
- A local actor able to edit the code or files can bypass hashes and receipts.
  These checks catch mistakes; they do not provide hostile-user isolation or
  externally witnessed custody. Path checks also do not defend against a hostile
  concurrent filesystem actor. Use a disposable isolated environment to review
  untrusted code, without credentials or private data.
- Holdout consumption is exclusively created and flushed to disk before outcome
  evaluation. Failed attempts remain consumed. Backups must retain receipts.

## Portal preview boundary

The portal preview binds only literal IPv4 loopback and validates Host, Origin,
and CSRF on mutations. It has no real identity or persistent authorization state.
Never expose it through a tunnel, proxy, public bind, or production mount.
The UI renders untrusted strings with text nodes, fetches only same-origin API
paths, and keeps once-only secrets in memory/DOM until dismissal, navigation,
or tab hiding. Explicit clipboard copies remain the user's responsibility.
The production backend must supply secure sessions, OAuth, authorization and
no-store responses; hiding a UI control is never an access-control boundary.

## GitHub Actions configuration

The workflow runs on this public repository and is configured for `pull_request`
and manual dispatch only. Its first hosted manual run passed for Python 3.11 and
3.14; that does not prove hostile-fork PR isolation by itself. The design uses
GitHub-hosted `ubuntu-24.04` runners, a five-minute job limit, and
`permissions: {contents: read}` at both workflow and job levels. All other token
permissions are unspecified/disabled. There is no `pull_request_target`,
`workflow_run`, self-hosted runner, environment, repository secret reference,
OIDC permission, publishing step, cache, artifact upload, or deployment job.

Checkout credentials are not persisted. Action versions are pinned to full commit
SHAs. PR text is never interpolated into shell commands. The workflow is written
in the JSON subset of YAML so stdlib tests can parse and check its structure.
Future reviewers must inspect workflow and test changes together: a PR can modify
its own checks. Repository/organization settings and runner execution are a
separate hosting gate, not something a local file proves.

Security rationale follows [GitHub's secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use).
Pinned upstream sources: [checkout v7.0.1](https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1)
and [setup-python v7.0.0](https://github.com/actions/setup-python/commit/5fda3b95a4ea91299a34e894583c3862153e4b97).

## Reporting a problem

**Private vulnerability reporting is enabled** on the public GitHub repository
under Security and quality. Use the private reporting flow, never a public issue
or PR, for security-sensitive disclosures. Do not paste credentials, real data,
or private infrastructure details into public discussion. No security
response-time promise is made.
