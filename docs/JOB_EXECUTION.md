# Bounded synthetic research jobs — source-only vertical slice

This is a local Linux engineering prototype. It is not a public service,
production identity system, real payment system, customer sandbox, or cluster
deployment. Every result is `synthetic_engineering_only`.

## What is reused

- `OfflineLedger` remains the only credit/reservation/settlement authority.
- Existing `FixtureRegistry` and `DevTokenIssuer` provide explicitly fake test
  identities; no token-minting HTTP route is introduced.
- `market_lab` validates configuration and computes the existing causal strategy
  and same-engine replay. The pure report function is separated from file I/O.
- The new queue is a small execution adapter for one fixed trusted runner. It
  has no generic task DAG, agent launch, shell tool, plugin loader or payment
  processor. Future execution adapters must preserve this job contract and
  ledger; do not create another accounting or engineering orchestrator.

The existing OIDC and x402 labs remain separate. No x402 charge or settlement
is invoked. The 50 simulated cents reuse the existing backtest price and do
not establish actual costs, market pricing or money owed.

## Run and inspect

Requirements: Python 3.11+, Linux with libseccomp.so.2, permission to apply
seccomp and CPU affinity. No package installation or external connection is
needed. Other platforms fail worker execution closed.

```bash
python3 -m unittest discover -s tests -p 'test_jobs*.py' -v
python3 -m research_commons.job_demo --state-dir artifacts/jobs-demo-unique
python3 -m unittest discover -s tests -v
python3 -m market_lab verify-data
python3 -m market_lab validate submissions/baseline.json
git diff --check
```

Use a fresh demonstration directory. The finite demo starts a literal-loopback
HTTP server, submits two tenants' jobs plus an exact duplicate and a cancelled
job, waits for actual completion, saves `demo-receipt.json`, and stops all its
services. Tokens remain in memory and are not printed or saved. Its result
files and SQLite history remain under that directory. This command installs
no service and creates no ongoing supervision after it exits.

`JobHTTPServer` can be embedded by a trusted test/operator. Tokens are issued
only by its in-process fixture issuer. The caller cannot select a tenant in a
request body or acquire any internal workstation or cluster capability.

## Contract and API

The submission spec is described by `schemas/job.schema.json`, using the
existing strategy schema. Only `liquidity_guard_v1` with bounded numeric
parameters is admitted. Only the immutable development split is evaluated.
The holdout digest is structural metadata in the existing submission; no
holdout outcome computation is performed.

| Method and path | Input / result |
| --- | --- |
| GET /v1/catalog | Entitled synthetic dataset/version, strategy and ceilings |
| POST /v1/quote | `{ "spec": SPEC }`; fixed simulated price, source/data hashes |
| POST /v1/jobs | `{ "key": IDEMPOTENCY_KEY, "spec": SPEC }`; durable job receipt |
| GET /v1/jobs | At most 64 own jobs |
| GET /v1/jobs/JOB_ID | Own status, failure reason, charge and evidence identity |
| GET /v1/jobs/JOB_ID/history | Own append-only transition receipts |
| GET /v1/jobs/JOB_ID/result | Own full hash-verified report after success/refund |
| POST /v1/jobs/JOB_ID/cancel | `{}`; queued cancellation or durable stop request |
| GET /v1/credits | Own simulated budget, holds and charges |

Every route needs a valid fixture Bearer credential. Exact literal Host and
same-origin-or-absent Origin are enforced. No cookies, CORS, token route,
webhook, arbitrary URLs or public binding is supported. Eight request handlers
are admitted at once; bodies are bounded and connections close after replies.
This is test authentication, not OAuth for customers. Production must reuse
the established product identity/entitlement authority behind a separately
reviewed authentication adapter.

The idempotency namespace is tenant plus key; the key binds the complete
canonical spec, including price ceiling, resources, configuration and dataset
hashes. Exact retries observe the original outcome even while paused or full.
They never reset a failed, cancelled, expired or uncertain attempt.

## Resource and financial bounds

| Resource | Enforced prototype ceiling |
| --- | --- |
| Active workers | One globally; exclusive ledger process lock |
| Tenant active reservations | Two, including running and cancelling |
| Global active reservations | Eight |
| Tenant lifetime attempts | 64; evidence is not discarded to reset the cap |
| CPU | One affinity core; at most 2 CPU seconds per process |
| Memory | RLIMIT_AS at most 256 MiB; not a claim about resident-set metering |
| Wall time | At most 10 seconds before kill, plus bounded reap confirmation |
| GPU | Zero |
| Worker output | At most 512 KiB, bounded while streaming |
| Worker filesystem writes | No file opens after preload; zero file-size limit |
| Controller state | 64 MiB admission budget including outstanding result reserves |
| Disk floor | 64 MiB free plus outstanding reservations |
| Credits | 200 simulated cents per default tenant; exactly 50 reserved per job |
| Reservation lifetime | Existing 60-second TTL; expiry is terminal, zero charge |

Prices never authorize resource expansion. Higher resource input is rejected
before reservation. The full 50 cents are reserved transactionally; successful
settlement charges that amount once. Failed, cancelled, expired and uncertain
work is not charged. A trusted in-process synthetic refund preserves result
evidence and restores the charge once. No public refund/payment route is added.

Fairness chooses the least recently served tenant from durable execution
events, then FIFO creation order within that tenant. This is a small bounded
local approximation, not a general cluster scheduler or a latency SLA.

## Durable state and failure semantics

| Internal state | API status | Automatic next action |
| --- | --- | --- |
| reserved | queued | Admit once within TTL and frozen source/data identity |
| executing | running | Observe the exact owned child; never issue another claim |
| cancel_requested | cancelling | Stop and reap the child; retain the credit hold |
| settled | succeeded | Serve verified artifact; exact retries are reads |
| cancelled / failed / expired | same | None; preserve reason and history |
| uncertain | uncertain | None; pause admission until operator reconciliation |
| refunded | refunded | Serve retained artifact; never execute or charge again |

Cancellation wins if its transaction commits before settlement. A running
job becomes cancelled only after the controller confirms child exit. Reaching
the wall/output bound kills and reaps the owned worker before releasing its
capacity. Unexpected controller exceptions also attempt child containment.

An accepted HTTP submission sets an in-process event. The sole controller
drains admitted work; a 250 ms bounded reconciliation covers TTLs and lost
in-process notifications. Durable SQLite reservations are scanned at startup.
Started claims are changed to uncertain, never replayed. Linux parent-death
SIGKILL closes the worker's lifetime on controller death. Unknown prior claims
still pause the new controller: process safety is not fabricated as job success.

Report publication uses exclusive creation and file/directory fsync before
settlement. A crash after publication but before settlement leaves orphan
evidence and an uncertain receipt. That orphan is retained and is not served
as a successful result. Automated tests SIGKILL at both claim and publication
boundaries and verify no re-execution or charge.

## Isolation and threat model

The API authenticates a caller before every tenant-scoped query. Authorization
is derived from the verified fixture principal, never a client tenant string.
Dataset entitlements are owned by the operator. They are checked at submission
and again before execution. An unentitled tenant cannot quote or run that data.
There is no raw dataset/file-path query endpoint.

The trusted worker receives a minimal environment, standard pipes and validated
configuration. It preloads only fixed source and the hash-verified synthetic
development fixture. It then applies no-new-privileges, non-dumpability,
resource limits, CPU affinity and a seccomp filter denying sockets/network,
file opens, subprocess creation, ptrace, namespace changes and related bypasses.
No ledger handle or bearer credential is inherited. Computation uses preloaded
inputs through the existing pure engine. Network-denial tests call real socket
syscalls, not mocks; failure means this worker cannot contact any destination.

This is containment for trusted code. It is not certification of arbitrary
Python/native-code safety, kernel vulnerability resistance, malicious local
filesystem-owner isolation, persistent IdP security, or Kubernetes/Cilium
enforcement. Coordinated rollback of the ledger and its complete audit history
is outside this local threat model. A production runner needs separately
verified namespaces, non-root UID, cgroups, read-only mounts, restricted service
account, network policies and an isolated execution tier. Untrusted executable
strategies require a stronger sandbox or separate cluster.

## Operator runbook

1. **Observe:** inspect own job/status/history APIs, full retained demo receipt,
   and trusted `JobService.health()` (global counts are not exposed to tenants).
   Alert on uncertain states, controller errors, ledger verification failure,
   queue age approaching TTL, resource-limit failures and low storage reserve.
2. **Pause:** trusted `pause()` persists the admission pause. It stops new jobs
   and new execution, while allowing the current worker to finish. Cancellation
   and receipt reads remain available. Exact retries remain observational.
3. **Cancel:** call the tenant's cancellation endpoint. Wait for `cancelled` or
   another terminal state. A cancellation request is not proof of child exit.
4. **Stop:** stop accepting HTTP requests, join handlers, then call
   `server_close()`. This stops the controller, contains its active child and
   releases the writer lock only after controller shutdown. Never delete state.
5. **Restart:** open the same directory with the same fixture budgets. Validate
   the ledger and successful artifacts. Unstarted reservations remain eligible
   until TTL; started work becomes uncertain and admission pauses.
6. **Recover unknown work:** retain the complete directory and exact source;
   independently prove the old worker is absent and inspect orphan artifacts.
   There is deliberately no automatic force-settle, reset-to-queued, delete-
   receipt or uncertain-resume route. A future recovery action needs its own
   reviewed, identity-bound evidence contract. Do not edit SQLite to unblock it.
7. **Resume a normal pause:** trusted `resume()` succeeds only without uncertain
   work/controller failure. It does not override a corrupt or unknown outcome.
8. **Back up:** stop first, copy the whole directory (ledger, journal and results),
   hash the copy and test opening it at a new state path. Preserve original
   evidence. These fixture credits have no financial recovery semantics.

## Release gates

Local passing tests and a source commit authorize no public service. Before
invited compute access: independent source review; real identity and persistent
revocation; production entitlement adapter; durable backup/restore and retention;
actual destination-by-destination network denial; CPU/memory/storage pressure
and failure-domain measurements; monitored canary and separate release approval.
Before paid access: measured cost/margin, real processor reconciliation/refunds,
approved licensing, externally auditable receipts and separate financial approval.

No Workstation Shell, Commander, Beads, Gas City, Vault, Kubernetes, ClickHouse
credential or exchange capability is reachable through this API.
