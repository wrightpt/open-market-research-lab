# Research developer portal — staged product architecture

**Stage 0, independently safe deliverable:** `portal/` contains only static
documentation and deterministic synthetic metadata. It is not deployed. Work
is independently auditing Kubernetes, Vault, network policies, and API isolation;
this document does not supersede or prejudge that audit.

## User journey and interface contract

| User action | Stage 0 public prototype | Proposed future service |
| --- | --- | --- |
| Understand the project | Static landing page and research methodology | Same, plus release/version notes |
| Browse available datasets | Versioned synthetic catalog linked to fixture manifest | Signed catalog with approved real-data provenance |
| Experiment locally | Clone, verify SHA-256, run standard-library benchmark | Optional offline SDK for approved exports |
| Submit a bug or review | GitHub issues and PRs | Signed experiment manifests and accepted evaluator |
| Register | **Unavailable** | GitHub OAuth sign-in, per-user account |
| Generate an API key | **Unavailable** | Entitled, scoped, expiring and revocable key |
| Use a local MCP adapter | **Unavailable** | User-controlled stdio adapter calling HTTPS data API |
| Use hosted MCP | **Unavailable** | Streamable HTTP + OAuth 2.1, isolated service |

Do not display a registration button or sell availability we have not
implemented. Public GitHub links are working and require no special account.

## Proposed trust boundaries — NOT live

```text
 Public browser / developer's local agent
     |     \
     |      +--> public static docs + synthetic fixtures (no auth)
     |
     +--> identity provider (GitHub OAuth; future)
     |       -> account / approval / rate tier
     |
     +--> HTTPS research gateway (future)
             |  scoped key OR audience-bound OAuth token
             |  query quotas, fixed endpoint enums, audit metadata
             |
             +--> approved synthetic records, initially
             +--> separately licensed data export or isolated read-only views
                        |
                        X no Kubernetes API, Vault, Trading secrets
                          or unrestricted production ClickHouse
```

The existing LAN-only, unauthenticated Kubernetes-reader MCP is **NOT** this
service and is never chained or proxied to outside clients. A local MCP adapter
is an optional client application, not a side door into Kubernetes.

## Phase 1 — private identity and synthetic sandbox

1. Keep `portal/` static, license-cleared, and served without any login for
   documentation and the synthetic benchmark.
2. Put an account service in a separate private staging environment. Use
   authorization-code OAuth with state/PKCE and strict redirect URI matching.
   Request minimal GitHub scopes; map provider identities to independent internal
   user IDs, never trust email alone as an immutable identity.
3. Issue access only after a deliberate beta entitlement decision (manual
   approval at first). No paid signup before customer terms, abuse budget and
   support channel are defined.
4. Generate API keys using a CSPRNG (at least 256 bits of entropy). Show secret
   material only once. Save a public lookup identifier and a keyed, one-way
   verification value plus scope, tenant, expiration, creation time and status.
   Do not save plaintext keys, echo them in logs, or accept them in URL params.
5. Establish global and per-tenant request/row/compute quotas, request deadlines,
   response-byte limits, and revocation that takes effect immediately.
6. Exercise the complete flow with **synthetic** datasets and explicit 401,
   403, 429, 422 and 503 negative tests.

For the first product wedge, **read-only typed API queries** are much easier
to secure and support than arbitrary SQL. Database SELECT privileges alone do
not prevent denial of service, inferential leakage, or excessive compute.

## Phase 2 — developer integrations

**Direct REST:** stable versioned endpoints for catalog, schema, coverage,
time-series queries, provenance, and usage; no table-name or raw SQL selector.

**Local MCP:** optional lightweight stdio client launched by the developer,
using a scoped research API token via an OS-supported credential store or a
dedicated environment variable. No credentials in agent prompt text or
committed configuration. Calls only the published HTTPS API; no direct DB or
kubeconfig.

**Hosted MCP:** own isolated Streamable HTTP resource server with authenticated
discovery and read-only tools, backed by exactly the same authorization
service as REST. Use OAuth with metadata discovery, issuer and audience
validation, short-lived tokens, PKCE for public clients, and explicit consent.
Do not assume all agent clients have identical OAuth setup or MCP features;
publish tested client versions and compatibility results.

Both integrations should expose only:
`list_datasets`, `describe_dataset`, `get_coverage`,
`query_timeseries`, and `get_usage`.
No shell, arbitrary SQL, file read/write, Kubernetes, Vault, trading, portfolio,
order execution, or generic URL-fetch tools.

## Phase 3 — real historical data (requires Work's security GO)

The existing ClickHouse and trading cluster should stay private. First
consider legally redistributable, immutable snapshots copied into isolated
research storage; this reduces live production load and blast radius.

If a direct database-backed service is necessary, require all of:

- Formal source-by-source license approval (raw/derived/API/MCP/download,
  attribution, retention, recipients, commercial use).
- Dedicated product views or controlled exports rather than raw tables.
- Dedicated SELECT-only identity with row/byte/time/memory/concurrency
  enforcement at database and gateway layers; no shared operator role.
- TLS verification and isolated service-to-data connectivity only; no
  Kubernetes API credential or Vault read permission in the public workload.
- Per-user quota, audit and revocation; non-sensitive logs only.
- Independent network testing, privilege and cross-tenant isolation tests,
  denial of default routing to trading and internal MCP endpoints.
- Rollback, incident response, observability and a measured compute budget.

Anonymous contributor code must never execute in the production trading
cluster. Use declarative strategy specs evaluated by trusted code or independent
ephemeral VM isolation; validate external CI fork behavior.

## Go/no-go questions to incorporate from Work

1. Does Vault have an externally reachable ingress or telemetry path?
2. Are External Secrets roles/policies narrower than the high-impact secret
   groups they can read, and is their effective live state verified?
3. Does the internal MCP reader require real client authentication? Is its
   effective live RBAC identical to GitOps declarations?
4. Can the research service operate entirely on synthetic and/or approved
   isolated data, without a production network path?
5. Are quotas, key revocation and OAuth metadata tested end-to-end?
6. Have the dataset rights review and a separate production change approval
   actually occurred?

**No public-data keys, login service, hosted MCP, or public deployment should
be enabled merely because the static portal passes its checks.**
