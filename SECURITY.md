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

## Commons MVP boundary

The separate Commons MVP also binds literal loopback, enforces exact Host/Origin,
uses expiring in-memory sessions and CSRF, and caps requests at 2 MB. Its two local
personas are deliberately selectable demonstrations, not identities suitable for
multi-user access. Never publish, tunnel or production-mount this local server.
Its single-writer journal uses POSIX file locking, atomic file installation and
hash-linked events under `artifacts/`; it provides local durability and corruption
detection, not tamper-proof custody. Preserve the complete journal on backup.
Only the existing bounded development engine is callable. Uploaded reports are
JSON data, retained as unverified until a complete report replay matches. No code
uploads, external URLs, holdout evaluation, payment calls or worker launch exist.

## Offline metering fixture boundary

The separate local ledger under artifacts/ uses SQLite transactions, an exclusive
POSIX process lock, per-tenant fixture budgets, one-time execution claims and
append-only hash-chained receipts. An interrupted claimed operation becomes
uncertain on restart rather than silently repeating a potentially completed job.
These protections are local correctness checks, not externally witnessed payment
custody or tamper-proof storage against the OS owner. The CLI selects simulated
fixture principals and never authenticates paying users. No new HTTP/MCP route,
payment processor, wallet, public identity, live dataset, execution broker or
production access was added. See docs/METERING_PILOT.md for bounds and gates.

## Zero-funds x402-shaped HTTP fixture

The optional research_commons.sandbox_http server binds literal 127.0.0.1
and accepts only ephemeral HMAC-signed test bearer identities and fake payment
proofs. It is not connected to existing portals or services, has no public
minting, onchain settlement, wallet, webhook, database privilege or Kubernetes
identity, and must not be reverse-proxied, tunneled or deployed. An exclusive
ledger claim and separate hash-chained proof registry reject proof replays and
cross-tenant reads. Restart makes in-flight execution uncertain; no automatic
retry occurs. This is a correctness/security experiment, NOT real OAuth/OIDC,
x402 facilitator verification or payment custody. Review docs/X402_SANDBOX.md
for limitations and separate financial/production approval gates.

## Optional standalone OIDC and official x402 verification lab

Separate Keycloak container: ephemeral localhost development realm, two
random service-account secrets, RS256 JWKS and OAuth2 client-credentials.
Keys/secrets are never committed; realm imports are removed after owned
container shutdown. The sandbox accepts only a strict, explicitly injected
loopback OIDC verifier, with issuer/JWKS URL allowlisting, RS256 signature,
resource audience, scopes, time limits, and server-owned client→tenant
mapping. The original fake-token sandbox remains default for its unit tests.

Optional official @x402/core SDK integration contacts only fixed testnet
facilitator /supported and read-only /verify using an invalid signature.
It explicitly has **no settlement pathway**; /settle can commit real value
and is forbidden until a separate approved financial/security gate.
Development tokens or mock receipts grant no permissions to Kubernetes,
Vault, private datasets, agents, trading, production billing or ingress.
No reverse proxy, persistent public port or service deployment is created.
See docs/OIDC_OFFICIAL_X402_LAB.md for exact limits and review gates.

## Stdio HTTPS adapter boundary

The optional stdio adapter is a separate outbound HTTPS boundary documented in
[MCP_ADAPTER.md](docs/MCP_ADAPTER.md). It accepts only environment-selected HTTPS
origins and seven fixed POST tools; redirects and proxy environment variables are
ignored/rejected, and certificates/hostnames are verified. Credentials never enter
stdio request arguments or saved configs. Limits and generic errors protect the
transport; the backend still owns authorization and sanitization. A trusted operator
must approve the origin: this client is not a network or hostile-code sandbox.
Tests generate disposable loopback TLS material; they never retrieve existing keys.

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
