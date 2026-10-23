# Local x402 v2-shaped payment sandbox — Issue #14

**Status:** zero real funds, no external identity provider, no blockchain RPC,
no live wallet or merchant, no public service, no Kubernetes, no customer data.
This is strictly a protocol-shaped development test against **original
deterministic synthetic development data**, NOT a real x402 verifier.

## Try one fake exchange

From the isolated repository checkout:

    python3 -m research_commons.sandbox_demo
    python3 -m research_commons.sandbox_demo --sku synthetic_backtest.v1
    python3 -m unittest tests.test_x402_sandbox -v

The command starts an ephemeral HTTP server bound to literal 127.0.0.1 on
a random port, mints a test-only signed bearer in-process, receives HTTP
402 with a base64-encoded PAYMENT-REQUIRED header, and constructs one
fake HMAC proof in the trusted test harness. The retry includes
PAYMENT-SIGNATURE, and a simulated successful exchange returns HTTP 200
with PAYMENT-RESPONSE. No chain RPC or money transfer happens. The
server stops after the exercise; audit receipts are retained under
an ignored artifacts/x402-sandbox-demo-*/ directory.

Those header names and object structures follow the x402 **v2 HTTP
transport**, for reference:
https://github.com/x402-foundation/x402/blob/main/specs/transports-v2/http.md
Core specification:
https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md

The sandbox follows the version 2 object shapes (x402Version, resource,
accepts, scheme, network, amount, asset, payTo and extensions in a
challenge; x402Version, accepted, payload and extensions in a payment).
Actual EVM signatures, official facilitator verification and blockchain
settlement are **NOT** implemented, so it is not protocol conformance.

## Threat model and identity boundary

DevTokenIssuer creates JWT-shaped HS256 **fixture** tokens with a random
ephemeral per-process signing key. It verifies strict issuer, audience,
tenant, subject, scope, iat, nbf, exp, algorithm, JTI and signature,
plus in-memory revocation. Lifetime is at most five minutes; restart
invalidates existing tokens. No HTTP endpoint issues credentials.

This is **not an OAuth/OIDC provider**. It has no real users, authorization
code flow, PKCE, JWKS, public key validation, account verification,
GitHub identity, consent, refresh or durable revocation service. The
existing Commons selectable personas cannot authorize paid requests.

StubFacilitator creates only in-process non-transferable HMAC test proofs,
NOT EIP-712/EIP-3009 signed wallet payments. The advertised network,
eip155:84532, is Base Sepolia's CAIP-2 identifier used as a fixture.
The fake asset 0x0000000000000000000000000000000000000001 is NOT USDC;
recipient 0x0000000000000000000000000000000000000002 is NOT a merchant.
FAKE-USDC-UNSPENDABLE labels deliberately non-transferable units.
Prices use integer synthetic cents (six-decimal-unit arithmetic is
illustrative). The sandbox-no-chain transaction string is an audit label,
**never an on-chain transaction hash**.

## Challenge, payment and execution boundaries

Each challenge binds one verified fixture tenant, source/manifest identity,
versioned SKU, canonical request body, idempotency key, nonce, challenge ID,
amount, network, fake asset, recipient, exact resource URL and 60-second
expiry. The verifier rejects changed/under/overpayment, network, asset,
tenant, body, wrong signature, stale challenge and cross-request proof reuse.

SandboxExchange atomically records a unique proof digest, then claims
executing in the existing OfflineLedger within the **same SQLite
transaction**. The fixed synthetic data sample or baseline development
run and same-engine replay execute **only after that claim**. There is no
arbitrary code, user-selected strategy, SQL, private data, holdout scoring,
cluster broker or external compute.

A same-tenant exact-proof retry returns the cached settled receipt without
a second run/charge. Proof reuse on a different request/tenant is rejected.
If the stub verifier is unavailable, HTTP 503 retains a time-limited
reservation without charge. Failed execution or fake settlement releases
the held credit with a failed receipt. A crash after claim becomes
uncertain at restart: it is never silently replayed. A fresh request
requires a different key and remains subject to the budget/quota.

The sandbox has its own hash-chained SQLite event log and immutable
proof-use records. No raw bearer tokens, HMAC signatures, API credentials,
card details or wallets are saved there. The operator OS account could
still manipulate all data: the audit is not externally witnessed custody.

## HTTP isolation

The optional test HTTP server uses 127.0.0.1 only. It exposes the fixed
POST /sandbox/resource and tenant-authenticated receipt GET route, denies
cross-origin browser requests, validates the literal Host, requires a
signed development Bearer token, and caps JSON bodies at 4 KiB. There
are no session cookies, CORS permissions, token minting route, webhook,
payment settlement callback, public ingress, proxy or tunnel. The
existing developer portal, research API and MCP remain unchanged.

## Acceptance

    python3 -m unittest discover -s tests -q
    python3 -m market_lab verify-data
    python3 -m market_lab validate submissions/baseline.json
    git diff --check

Adversarial coverage: issuer/audience/expiry/scope/tenant, token revocation,
wrong amount/network/asset/payee, replay and idempotency, cross-tenant
receipts, stale reservations, provider/settlement outage, concurrent claims,
crash recovery, oversized/malformed requests, Host/Origin, webhook rejection,
and audit tampering. Tests never evaluate held-out strategy outcomes.

## Separate release gates — NOT granted by this merge

- Independently audited OAuth/OIDC identities, tenant approval, audience,
  scopes, persistent revocation and customer billing entitlements.
- Real facilitator and onchain authorization, exact USDC asset/chain
  validation, payer confirmation, payment anti-replay, charge/settlement
  reconciliation, refunds, treasury management and compliance review.
- Market-data acquisition and redistribution rights, clocks/lineage and
  provider-specific contracts.
- Isolated per-tenant workers, OS/Kubernetes deny-by-default policies,
  independent resource quotas, recovery, backups, observability and alerts.
  Outsiders gain **no Kubernetes, Vault, ClickHouse or trading access**.
- Independent security review and explicit financial/deployment approval.
  Passing CI and merging source is not authority to accept funds or host
  external agents.

The Kimi Code API key is not accessed, duplicated or logged. It is not
needed for these deterministic protocol/security tests.
