# Isolated Keycloak + official x402 facilitator read-only integration

**Status:** local development integration demonstrated October 23, 2026.
This is NOT a public API, production identity provider, real payment flow,
chain settlement, paid user onboarding or Kubernetes deployment.

The original synthetic evidence runner, Commons local personas, and the
zero-funds x402 stub are unchanged for their existing tests. This is an
**opt-in**, separately-hosted provider verification path.

## Integration A — actual Keycloak RS256/JWKS identity

Requirements: Docker, Python 3.11+, and the optional cryptography package.
Keycloak image: quay.io/keycloak/keycloak:26.8.1.

From this repository root:

    python3 -m devtools.keycloak_oidc_integration --run

The command creates a temporary directory under ignored artifacts/, creates
**new random** secrets for two test OAuth2 confidential service-account clients,
starts Keycloak on a random port mapped to literal 127.0.0.1, imports one
isolated realm, and obtains OAuth2 **client_credentials** access tokens.
The resource verifier fetches the REAL OIDC discovery document and JWKS,
checks RS256 signatures, exact issuer and resource audience, time claims,
allowed client ID (azp), required scope and token type.

The server-owned tenant map is:
- orc-agent-a -> demo-alpha
- orc-agent-b -> demo-beta

The caller cannot claim another tenant merely by adding a tenant string.
The scope is research:purchase:synthetic and resource audience is
orc-x402-resource. The Keycloak audience mapper requires the target
resource client to exist; it is present as a non-login bearer-only client.
Keycloak omits nbf by default; the verifier correctly treats it as optional
while still requiring bounded iat and exp and checking nbf when present.

Each service account exercises a literal-loopback synthetic 402 -> 200 flow
through the existing StubFacilitator and OfflineLedger, debiting precisely
two FAKE cents. The script denies a revoked client, verifies the journal,
stops exactly its owned Keycloak container and deletes the generated realm
import/client secrets. A sanitized local receipt remains under artifacts/.
Neither the admin password nor any client secret is committed or printed.

This **does not** test browser authorization-code PKCE, human login, SSO,
consent, multi-issuer federation, production JWKS lifecycle, online token
revocation, IdP HA, or actual money. It is valid service-to-service OAuth2
client-credentials integration with an OIDC issuer.

Code paths:
- research_commons/oidc_loopback.py: optional RS256/JWKS verifier
- research_commons/sandbox_http.py: explicit injected identity verifier,
  backward-compatible test-only fixtures by default
- devtools/keycloak_oidc_integration.py: one-shot independent provider lab
- tests/test_oidc_loopback.py: signed-JWT negative cases, JWKS rotation,
  tenant mapping, expiry, revocation, provider failure

The only allowed provider origin is a literal 127.0.0.1 issuer ending
/realms/orc-dev. Metadata and JWKS URLs are pinned to that issuer;
redirects, proxies and arbitrary URLs are disabled. JWKS fetch has size,
key-count, timeout, modulus, algorithm and cache bounds. No public tunnel
or internal Kubernetes cluster endpoint is involved.

## Integration B — official SDK and public testnet facilitator

This checks the actual upstream protocol implementation, independently
of the x402 HMAC fixture. Requires Node.js 22+, npm, and outbound HTTPS
to the explicit public testnet facilitator.

    npm ci --ignore-scripts --no-audit --prefix devtools/x402_official
    npm run --prefix devtools/x402_official check

The dev-only dependency is pinned in package-lock.json to
@x402/core version 2.28.0. The script verifies official SDK
PAYMENT-REQUIRED and PAYMENT-SIGNATURE header roundtrips, then uses
HTTPFacilitatorClient to contact the public development facilitator:

    https://x402.org/facilitator

It calls ONLY:
1. GET /supported to discover advertised schemes and networks
2. POST /verify with an intentionally INVALID all-zero EIP-3009-style
   signature on Base Sepolia (eip155:84532)

The October 23 live probe reported 11 capabilities, including the
Base Sepolia exact scheme, and an explicit isValid=false rejection of
the forged payment. There was NO POST /settle, wallet, signing key,
spending, transfer, RPC transaction or positive-payment claim. The
payer/recipient of the forged signature are non-funded zero-style
test literals. A later live testnet settlement would require explicit
separate approval and a fully controlled faucet-funded test wallet.

The upstream reference paths are:
- https://github.com/x402-foundation/x402
- https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md
- https://github.com/x402-foundation/x402/blob/main/specs/transports-v2/http.md
- https://www.keycloak.org/getting-started/getting-started-docker

**Important separation:** the Python sandbox's successful mock receipt
is produced by StubFacilitator; the official facilitator tested only a
negative signature via /verify. They are not a single positive upstream
x402 payment flow. Do not represent these tests as proof of actual
settlement, provider conformance, or production readiness.

## Validation

The new optional unit tests cover:
- signed RS256 validation and JWK refresh/rotation
- wrong signature, alg=none, audience, issuer, scope, token type and azp
- missing/expired/future timestamps, revoked token/client
- server-owned tenant mapping against a forged tenant claim
- fail-closed JWKS outage
- literal-loopback issuer restrictions

The base repository remains standard-library-only; no third-party imports
are required for its original research engine or browser UI. The OIDC
verifier imports cryptography only when invoked. The optional tests
skip explicitly when that dependency is not installed.

Use the full repository acceptance commands:

    python3 -m unittest discover -s tests -q
    python3 -m market_lab verify-data
    python3 -m market_lab validate submissions/baseline.json
    git diff --check

## Remaining production release gates

1. A REAL approved identity architecture (production TLS and DNS,
   PKCE where human login matters, client onboarding, consent,
   persistent revocation and IdP/JWKS HA).
2. Independent threat-model and external authentication review:
   no trust of unverified headers, unsigned JWTs or spoofed tenant IDs.
3. Official x402 SDK conformance with a legitimately signed testnet
   authorization, facilitator verify + settle, anti-replay and finality,
   verified testnet asset/payee, refunds, reconciliation and hard budgets.
   Any transfer is separately authorized; mainnet remains out of scope.
4. Provider-approved market-data redistribution, licensed datasets,
   reliable quotas, customer tenancy, costs, customer-facing products.
5. Dedicated network-isolated execution tier, audited GitOps and
   Kubernetes authorization. **No outsiders receive cluster access.**
6. Explicit operator approval of the exact deployment, credentials
   and financial path before exposure.

No Kimi Code API token was accessed or disclosed for this integration.
