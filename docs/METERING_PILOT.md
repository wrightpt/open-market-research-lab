# Open Research Commons — offline metering pilot (Issue #12)

**Status:** Local synthetic engineering exercise. No actual funds, invoices,
wallets, x402 verification, cards, public ingress, customer authentication,
real market data, arbitrary jobs, or Kubernetes connections.

This feature proves usage accounting before a payment system is introduced.
It is **not connected to the Commons HTTP server or MCP adapter**. The CLI
selects local fixture personas, not authenticated customer accounts.

## Product catalog v1

| SKU | Unit | Hypothetical price | Bound |
| --- | --- | ---: | --- |
| synthetic_sample.v1 | Sample of deterministic development bars | $0.02 | 1–20 bars, no holdout |
| synthetic_backtest.v1 | One fixed run plus matching same-engine replay | $0.50 | 384 synthetic development bars, fixed baseline |

Prices are **synthetic credits in integer USD cents**, not real cash or
verified willingness-to-pay. Each fixture tenant starts with **200 simulated
cents**. There is no prepayment, wallet, token, bank account or processor.
The Apache-2.0 synthetic-data license does not authorize redistribution of
unrelated real market data.

Each tenant is capped at 64 lifetime attempts, two active reservations, a
60-second reservation TTL, and 32 KiB retained per result. The original
engine retains its own data, parameter, journal and computation limits. A
matched replay establishes only same-engine local repeatability, not independent
review, unseen-market validation or profitability.

## Run locally

From this repository on Python 3.11 or later:

    python3 -m research_commons.offline_demo quote --sku synthetic_sample.v1 --limit 2
    python3 -m research_commons.offline_demo purchase --key demo-sample-0001 --sku synthetic_sample.v1 --limit 2
    python3 -m research_commons.offline_demo purchase --key demo-backtest-0001 --sku synthetic_backtest.v1
    python3 -m research_commons.offline_demo balance

Each purchase returns a receipt ID. To inspect it or simulate a refund:

    python3 -m research_commons.offline_demo receipt --receipt RECEIPT_ID
    python3 -m research_commons.offline_demo history --receipt RECEIPT_ID
    python3 -m research_commons.offline_demo refund --receipt RECEIPT_ID

The --tenant demo-beta option chooses a different **local fixture**, not an
identity assertion. The operator runs with ordinary OS file permissions.
The --state-dir path must remain inside artifacts/ and cannot traverse symlinks.
Back up the full ledger directory while stopped; never delete evidence merely
to reset a quota.

## Durable state machine

    quote (no reservation)
      → reserved (atomic budget and quota check; source/request hashes bound)
          → executing (one durable execution claim)
              → settled (result digest and simulated charge)
              → failed (hold released, zero charge)
              → uncertain (crash after claim: zero charge; NEVER replay)
          → expired (TTL exceeded, hold released)
          → cancelled (operator cancellation or source drift, hold released)
      settled → refunded (simulated charge reversed, evidence preserved)

Every transition appends a hash-linked audit event to SQLite in the same
transaction as the receipt state update. Startup verifies the chain against
the current projection and converts interrupted executing operations to
**uncertain**, without repeating the computation. Any orphaned Commons
evidence needs separate human reconciliation. This is robust local bookkeeping,
not externally witnessed custody; an OS owner could tamper with the database.

An idempotency key binds the SKU, version and canonical request payload. Retrying
the same key returns the prior receipt, including failures and uncertain states,
without another run or charge. Reusing the key with different inputs is rejected.
SQLite BEGIN IMMEDIATE serializes concurrent reservations and an exclusive
POSIX file lock prevents multiple ledger processes.

The source and manifest fingerprints must still match at execution claim.
A changed source cancels the reserved job; a downstream execution error fails
it without simulated charge. In all cases, historical events are retained.
Simulated credits are consumed only while state is settled and are restored on
refund. This ledger does not implement token transfers or money settlement.

## Separation from externally exposed services

- In-process fixture credentials are not authentication. The existing Commons
  demo persona selector is never a customer identity or spending authorization.
- **No new HTTP route is registered**. Commons loopback session, Host, Origin,
  CSRF, body-size and other controls are unchanged; they are not a paid-user
  resource server. Public APIs require fresh multi-tenant auth and negative tests.
- Only the original synthetic development dataset is permitted. Holdout results,
  private market data, real trading and uploaded executable strategies cannot
  be bought. No untrusted script or customer-selected command reaches the engine.
- Neither live x402/USDC nor Stripe is connected. Real payment verification,
  replay defense, refunds, licensing, compliance and merchant treasury must be
  independently reviewed before any external transaction.
- Outsiders get no Kubernetes, Vault, shell, ClickHouse, task broker or exchange
  credentials by purchasing access.

## Costs and acceptance

The synthetic sample emits at most 20 rows; the fixed backtest evaluates 384
hourly development rows using one parameter set. These prices are hypotheses,
not demonstrated business margins. Before real billing, measure CPU time, peak
memory, storage growth per journal event, processor fees, refunds, fraud attempts,
failure rate and price willingness for each SKU. A hard compute limit must be
independent of customer spend.

Validation commands:

    python3 -m unittest discover -s tests -v
    python3 -m market_lab verify-data
    python3 -m market_lab validate submissions/baseline.json
    git diff --check

The metering tests cover actual synthetic operations, concurrency, tenant
isolation, unverified identity rejection, result-size and request limits,
idempotency, source drift, failure, crash recovery, expiry, cancellation,
refund, quota and hash-chain tampering. Existing HTTP tests cover loopback
Host, Origin, CSRF and session rejection without adding a billing endpoint.

### Separate release gates

Real data requires provider-specific commercial and redistribution approval
with lineage and source-clock verification. Production needs a real identity
provider, independent security assessment, tested customer entitlement and
budget controls, externally reconciled payment processor, durable backups,
observability, rate limits, isolated workers and an explicitly approved
deployment. PR #7 and PR #10 keep their distinct connector security gates.
Merging this code never authorizes payments, external agents, ingress or live
cluster access.
