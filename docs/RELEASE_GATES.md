# Release gates and authority

The current deliverable is a **local synthetic engineering prototype**. A green
test run is not a research verdict, a hosted release, or authority to trade.

| Gate | Required evidence | Authority / current scope |
| --- | --- | --- |
| Local source readiness | Original code, policies, bounded contract, fixture identity, reviewed diff | In scope |
| Local engineering acceptance | Tests, deterministic development CLI run, causal/cost/unknown-value checks, safe CI file review | In scope |
| Holdout workflow exercise | Frozen development evidence and unchanged identities, one consumed attempt, all failures retained | Explicit local command; no predictability conclusion |
| Real-data admission | Acquisition and redistribution rights, source/clock/coverage evidence, approved study scope | Separate owner decision; not implemented |
| Independent research evidence | Frozen hypotheses and search log, unseen custody, uncertainty and controls, independent review | Not reached by synthetic results |
| Public repository or package | Owner release approval, Apache-2.0 license, private-content review, security intake, repository settings review | Local candidate prepared; account creation and security intake remain unverified |
| Hosted CI acceptance | Separate authorization to host/run; token/runner/settings review and actual hosted checks | Local configuration only |
| Paper service, deployment, or live execution | New design and explicit operational/financial authorization | Outside this repository's prototype scope |

## Local acceptance checklist

- Run the documented stdlib tests and CLI without installation or network access.
- Verify the exact development and holdout fixture hashes, counts, and time bounds.
- Reject executable/unknown submission fields, unsafe paths, and malformed inputs.
- Verify feature/decision prefix invariance and next-bar execution on price gaps.
- Reconcile entry and exit fees, adverse slippage, terminal liquidation, and cash.
- Preserve unavailable features/outcomes and explicitly exclude them from metrics.
- Prove freeze drift rejection, failed-attempt consumption, and concurrent admission.
- Review all source and documents for private content and host-specific assumptions.
- Review the GitHub workflow independently of its tests. It must use hosted runners,
  read-only token permissions, pinned actions, no secrets, and no privileged PR event.
- Record actual command results, environment, limitations, and whether holdout was
  consumed. Do not imply hosted CI ran because local checks passed.

Local commits may follow that review. No push, remote creation, public release,
account operation, database access, or deployment follows automatically. CI policy
files and the PR template are preparation for review, not activation instructions.
