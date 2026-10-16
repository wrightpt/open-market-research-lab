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
- There are no network clients, database drivers, subprocess execution, dynamic
  plugin loading, environment-secret reads, or telemetry in the runtime.
- A local actor able to edit the code or files can bypass hashes and receipts.
  These checks catch mistakes; they do not provide hostile-user isolation or
  externally witnessed custody. Path checks also do not defend against a hostile
  concurrent filesystem actor. Use a disposable isolated environment to review
  untrusted code, without credentials or private data.
- Holdout consumption is exclusively created and flushed to disk before outcome
  evaluation. Failed attempts remain consumed. Backups must retain receipts.

## GitHub Actions configuration

The checked-in workflow is designed for an eventual public repository; its
presence alone does not prove that hosted CI or repository settings are safe.
Its design uses `pull_request` and manual
dispatch only, GitHub-hosted `ubuntu-24.04` runners, a five-minute job limit, and
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

Before publishing on GitHub, enable **private vulnerability reporting** in the
repository's Security settings and verify the private report form. Report security
issues there, never in a public issue or PR. If private reporting cannot be
confirmed, hold publication until a confidential channel is established. Do not
paste credentials, real data, or private infrastructure details into reports.
No security response-time promise is made.
