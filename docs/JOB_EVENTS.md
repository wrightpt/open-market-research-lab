# Resumable synthetic job events

This source-only increment builds on the bounded job prototype. The existing
`OfflineLedger` remains the sole owner of job state, reservations and simulated
charges. Its audit events already commit in the same SQLite transaction as each
transition: there is no separate outbox enqueue window and no second scheduler.

Run a finite HTTP demonstration in a **new** evidence directory:

```sh
python3 -m research_commons.job_event_demo --state-dir artifacts/event-demo-001
```

It submits one bounded synthetic job, observes automatic local execution, loses
an acknowledgment response, restarts the local server, retries the original job
and acknowledgment, resumes remaining events, verifies the result manifest and
one simulated charge, then closes all servers/workers. Old fixture credentials
are rejected after restart. The retained receipt contains no bearer credentials.
It does not contact another service or run the holdout.

## Tenant API

All routes retain the prototype's fixture Bearer authentication, literal loopback
Host/origin checks, body/connection limits and tenant authorization.

Before submission, `GET /v1/catalog` lists only the tenant's server-authorized
synthetic development dataset and fixed configuration-only strategy. Revoked
entitlement produces empty lists. Quant Market snapshots remain explicitly
unadmitted; the request cannot supply a data URL, private source, holdout or
caller-selected entitlement. `POST /v1/admission` with `{"spec": <job spec>}`
validates the same contract and reports current budget/capacity/pause blockers,
the server-owned fixture price and a versioned policy digest. It creates no
reservation, job, event or charge and guarantees no future capacity. Actual
submission rechecks the same limits under the existing controller lock and the
ledger's atomic reservation. Exact existing submissions remain observable even
when capacity is full. The policy retains one worker, eight global reservations,
two per tenant and the existing finite budgets/timeouts. Only verified result
settlement spends fixture credits; event reads, acknowledgments and preflight
cannot spend them. SQLite failures return a bounded unavailable response without
reflecting internal storage details.

| Operation | Request | Result |
|---|---|---|
| `POST /v1/events/read` | `{"consumer":"research-ui","limit":16}` | Resume after this consumer's last durable acknowledgment |
| Same read, explicit cursor | Add `"after":"start"` or a returned event ID | Replay own history; never change the acknowledgment |
| `POST /v1/events/ack` | `{"consumer":"research-ui","event_id":"<returned hash>"}` | Acknowledge the next contiguous event; exact retries return the original receipt |
| `GET /v1/jobs/<id>/manifest` | No body | Stable, hash-bound execution evidence for a successful retained result |

Pages contain at most 32 events. A cursor is an own-event digest, not a global
sequence number. Forged/foreign cursors and out-of-order acknowledgments fail
closed. Three fixed consumer labels (`research-ui`, `workstation-handoff`,
`runtime-simulation`) bound receipt cardinality; labels are **not** independent
principals or delegated service credentials. They share the authenticated
tenant's authority. An actual operator integration needs separate scopes.

Reads do not acknowledge. A lost response can be read again. A committed but
lost acknowledgment response returns the same receipt after restart. Delivery
is **at least once**, with idempotent acknowledgment and submission; this is
not a claim of exactly-once network delivery. A consumer must persist its own
side effect/idempotency decision before acknowledging. The local observation
receipt cannot prove a remote task mutation, message delivery, or human reading.
It never creates a `REPORTED` acknowledgment, reruns an uncertain job, or charges.

Acknowledgments are an append-only projection in the same ledger file. Their
hash chain binds tenant, fixed consumer, ordinal and canonical event. SQL
triggers reject update/delete; startup and reads verify the chain against the
job audit. Combined job/ack verification runs before startup recovery, admission,
worker launch and settlement, and the transition transaction checks retained ACKs
before changing state. A detected mismatch latches the existing controller pause;
reads cannot leave admission or execution enabled. Startup refuses contradictory
evidence before expiring or reconciling jobs. Recovery requires independent
operator reconciliation, never deleting receipts or treating ACKs as permissions.
Job quotas bound total growth. Low-storage acknowledgment rejection
does not lose events; an exact acknowledgment retry remains observable.
Hashes provide local integrity checks, **not signatures or remote attestations**.
Coordinated rollback of all state and a malicious filesystem owner remain
outside this prototype's threat model. Copying/restoring an old complete ledger
requires an external recovery policy; do not infer tamper detection from hashes
alone or edit SQLite to recover an uncertain outcome.

## Results and blockers

The manifest binds the full canonical input, request digest, source content
revision, dataset manifest, result digest, replay evidence, requested limits and
observed CPU seconds, maximum RSS in KiB and wall seconds. This fixed strategy
uses no model; `model_revision` is null with an explicit explanation. A source
content digest is recorded instead of inventing a Git SHA at execution time.
Refunding fixture credits does not alter the retained execution manifest.

The trusted in-process `JobService.operator_snapshot()` reports counts, pause,
controller errors and exact uncertain-job blockers. No global operator route
is exposed to tenant HTTP credentials. An uncertain outcome requires independent
execution reconciliation and remains non-replayable. Corrupt results cannot be
turned into successful handoff proposals.

## Existing authority adapters and activation contract

`preview_handoff()` resolves a canonical own terminal/uncertain event and, for
success, revalidates the retained result. It produces a deterministic digest-only
proposal for Beads, Gas City or strategy-experiment-runtime. This is a proposed
adapter envelope, **not native protocol compatibility**. It has no transport,
callback URL, executable command, task-store mutation or enable switch. Every
proposal says `synthetic_proposal_only`, `native_dispatch=false` and lists the
missing gates. Repeated proposals do not acknowledge an event or execute work.

The production admission record must eventually bind the exact repository
revision, canonical project/task ID, current task owner and authority revision,
source-event ID, permitted action, dataset entitlement, resource policy digest,
independent review, tested backup/restore evidence, expiry and explicit operator
activation. The existing authority must verify that record and issue its own
durable acceptance receipt. Only that receipt can justify acknowledging a native
handoff. Unknown delivery must remain unknown; never blindly dispatch again.
This implementation deliberately cannot manufacture that admission record.

| Existing component | Intended boundary | Evidence needed before activation |
|---|---|---|
| Open Market Research Lab | Fixed published synthetic development fixture and read-only strategy catalog | Connected synthetic catalog contract check; no expansion to real data |
| Quant Market API | Separately entitled, bounded read-only data snapshot | Approved dataset/license, source/time/null semantics, immutable snapshot hash and synthetic/live distinction; no raw SQL or upstream credentials |
| strategy-experiment-runtime | Its existing service owns validation, submission, cancellation and run evidence | Authorized service access, pinned native schema and implementation, existing resource admission, exact accepted run receipt; never instantiate a second engine |
| Beads | Canonical engineering-task identity and ownership | Project admission and owner mapping, verified backup/restore, separate human authority cutover where required |
| Gas City | Existing admitted dispatch policy and task relay | Admitted project/profile, current owner, pause/window/capacity gates and verified native acceptance; no replacement scheduler |
| Workstation Shell / Commander | Existing broker sessions, process receipts and verified outcomes | Exact safe existing session, host permission, accepted command evidence and independently qualified outcome; idle terminal is insufficient |

No private implementation, host path, infrastructure configuration or dataset is
copied into this public module. Private integration inspections inform boundaries
only. No remote account is activated, and no other Work conversation's sessions
or recovery jobs are taken over.

## Remaining hosted-service gates

| Gate | Required evidence and accountable decision |
|---|---|
| Compute isolation | Operator-approved namespace; restricted service account/RBAC and Pod Security; non-root/read-only filesystem; immutable image; CPU/memory/ephemeral-storage requests, limits and quotas; default-deny ingress/egress with measured destination tests; no host mounts or automatic token mounting; cancellation/reaping and pressure tests; separate deployment approval |
| Identity | Chosen hosted IdP and approved account; issuer/audience/signature/expiry validation; persistent revocation; tenant-to-entitlement mapping; scoped operator identity; two-tenant adversarial tests; no use of fixture credentials in hosting |
| Data protection | Dataset licensing and permitted redistribution, snapshot custody, retention/deletion policy, secret-free artifacts, tenant isolation and reviewed encryption/access model |
| Accounting | Server-owned price/version and resource policy, atomic reservations, measured usage, uncertain-state reconciliation, tested refunds and independent restore; current credits are fake |
| Payments | Explicit processor/account and financial approval; authenticated replay-safe provider events; idempotent authorization/capture/refund, reconciliation and disputes; no customer funds before this gate |
| Public access | Separate security review and operator authorization for DNS/TLS/ingress, rate/body/connection limits, abuse controls, audit/alerting and rollback; no public endpoint from this prototype |

Local tests and a draft PR satisfy none of the hosted-service gates. Independent
review of this increment is required before merge or any activation. The
prototype source and its original evidence remain unchanged on their branch.

## Milestone handoff (2026-10-26)

Parent prototype: `b686d383e2f25176262340629574a11d786524bf`, preserved in
[draft PR #18](https://github.com/wrightpt/open-market-research-lab/pull/18).
This event increment is coordinated in
[issue #19](https://github.com/wrightpt/open-market-research-lab/issues/19).
The full local validation passed 207 Python tests and 10 JavaScript tests,
fixture custody and submission validation, whitespace checks, and all nine
finite HTTP reconnect acceptance checks. The 17 added tests include a real
SIGKILL after acknowledgment commit, concurrent duplicate acknowledgments,
lost responses, tenant isolation, transaction failure, one-sided history
rollback, uncertain outcomes and result tampering.

The initial handoff lacked an available reviewer. The owner subsequently
authorized the exact research worktree's managed-session scope and a dedicated
source reviewer; unrelated portfolio/recovery sessions were not repurposed.
That reviewer independently ran 218 Python and 10 JavaScript tests on
`b4b90ebe2f47bc749e4c5cfedcfeba93dbae9b24`, then reported **BLOCK**, with one P1
finding and two failing additional regressions. Detected partial-history rollback
did not fence the inherited controller: cancelled work could execute and charge
fixture credits, and completed work could launch again. The original report is
retained under SHA-256
`655cde3870f6d59304a80de8bad5a885038a79101d7074714b0a6e9f4312f869`.

The corrective increment moves ACK verification into the job authority's audit
and transition boundaries, persists the existing pause on integrity refusal,
checks active-worker boundaries and adds cancellation/completion rollback,
pre-launch, post-result and startup regressions. Original source and failing
evidence remain preserved. Independent review of the exact corrective head is
required; consult [PR #20](https://github.com/wrightpt/open-market-research-lab/pull/20)
for its canonical verdict and evidence hashes. Tests alone are not approval.

Live integration evidence is intentionally incomplete. The synthetic lab
connector reported its tunnel client unavailable. Runtime Bash inspection was
denied by host policy; source-only contract inspection remained available.
Neither condition was bypassed, and no repair/restart was attempted in another
owner's service. A later integration owner must restore the existing authorized
connector, admit the exact project and verify native contracts before activation.

The follow-on admission increment passed 218 Python tests and 10 JavaScript
tests plus the same nine reconnect checks. It adds tenant-filtered catalog and
preflight routes, shared reservation checks, global eight-slot contention tests,
entitlement revocation after preview, budget exhaustion, no-charge event replay
and sanitized SQLite failures. The event-only source remains preserved at
`4d9c05d4c270a858d55c36cf2c79f95eaca16325`; the admission change is a separate
commit in draft PR #20. Independent review of the final head is still required.
