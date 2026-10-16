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
| Public repository or package | Owner release approval, Apache-2.0 license, private-content review, security intake, repository settings review | **GitHub source published**; private vulnerability reporting and read-only CI settings verified |
| Hosted CI acceptance | Token/runner/settings review and actual hosted checks | **Manual GitHub-hosted run passed** for Python 3.11 and 3.14; external-fork PR behavior remains to be tested |
| Paper service, deployment, or live execution | New design and explicit operational/financial authorization | Outside this repository's prototype scope |

## Local acceptance checklist

Developer portal / adapter gates are additive. Local UI and transport acceptance
does not activate a service. Review Phase 1 and Phase 2 independently using
[PORTAL_VALIDATION.md](PORTAL_VALIDATION.md) and [MCP_VALIDATION.md](MCP_VALIDATION.md).
Confirm all proposed nested envelopes, key encoding and research argument schemas
with the backend owner; prove its CSRF/session, cross-account denial, key expiry,
atomic rotation/revocation, quotas and audit with synthetic integration tests before
calling the components integrated. No such integration is claimed here. Public
hosting, production credentials, real data and deployment require Patrick's
explicit decision for the exact release and separate operations/license gates.

- Run the documented stdlib tests and CLI without external network access. Portal
  and adapter tests use disposable loopback fixtures; TLS tests require local OpenSSL.
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

Public GitHub source is live and contributions must follow PRs and required CI.
This does not authorize exchange access, data redistribution, production database
queries, Kubernetes deployment, or forum posting. Review every PR's code and
provenance; never run external PR code on local or self-hosted runners.
