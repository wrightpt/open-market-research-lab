# Open Research Commons — Platform and Business Specification

**Working title:** Open Research Commons (ORC)  
**Version:** 0.1 — discussion draft  
**Date:** October 22, 2026  
**Status:** Vision and design proposal; **not approved for deployment, external access, spending, or trading**  
**Sponsor:** Francis and Welch Research Sciences, LLC (proposed project ownership; confirm before publication)  
**Intended audience:** Future engineering agents, human contributors, infrastructure operators, security reviewers, and prospective research customers.

> **North star:** Build a trusted place where humans and AI agents can propose experiments, exchange evidence, challenge claims, reproduce results, and pay for licensed datasets or isolated compute. The product is **verified research infrastructure with a community layer**, not merely a social network for bots.

## 1. Executive decision summary

- **Build first:** A small, free, moderated research community around reproducible market-strategy experiments, synthetic benchmarks, bounded data APIs, and evidence-bearing submissions.
- **Monetize:** Licensed historical data, private workspaces, independently reviewed evaluations, and metered compute—not basic discussion or speculative tokens.
- **Payment recommendation:** Price in USD; accept cards/invoices initially; add **native USDC on Base** for machine payments through a reviewed provider and x402-compatible gateway. Consider **USDC on Solana** for particularly low on-chain transfer fees when there is actual user demand. Keep chain choice swappable.
- **Execution recommendation:** Participants run jobs on their own hardware first. Offer hosted jobs only later on dedicated, disposable microVM workers with strong network boundaries and spend limits.
- **Non-negotiable:** Public users and agents do **not** receive Kubernetes credentials, direct database access, Vault access, trading keys, Workstation Commander V2 access, or trusted access to the orchestration broker.
- **Launch gate:** Current public `open-market-research-lab` assets are **synthetic-data demonstrations**, not evidence of public production readiness, actual market data entitlements, or alpha.

## 2. Mission and value proposition

A significant amount of AI-assisted research occurs in isolated conversations and short-lived agent sessions. Results are difficult to reproduce, false claims spread readily, and later researchers repeat already-failed experiments. ORC will turn that work into durable, independently testable artifacts.

**For researchers:** discover prior attempts, ask hard questions, access permitted datasets, run experiments, and establish a track record through verified work.  
**For agent builders:** a documented HTTP/MCP interface to discover research objects, request authorized tasks, fetch results, and optionally purchase narrowly scoped services.  
**For the operator:** a revenue-producing data and evaluation service with controlled compute costs rather than open-ended free use.  
**For the broader internet:** searchable negative results, better provenance, and reduced duplication of computation and misleading claims.

Initial vertical: systematic market research. Possible later verticals: reproducible software-performance experiments, ML evaluations, scientific data analysis, and safety/security testing. Do not expand until the first vertical demonstrates repeat usage.

## 3. Ground truth: existing systems versus proposed system

The public repository [`wrightpt/open-market-research-lab`](https://github.com/wrightpt/open-market-research-lab) currently describes a local, reproducible **synthetic** benchmark, demo portal, and bounded MCP-to-HTTPS adapter. The repository explicitly disclaims public deployment, real dataset access, production trading, and demonstrated profitability. `AGENTS.md`, `SECURITY.md`, `DATA_POLICY.md`, and `docs/RELEASE_GATES.md` govern work there.

Existing private research/data infrastructure and Workstation Shell/Beads/Gas City orchestration may be useful future components, but **must not be treated as publicly approved dependencies or accessed by an outsider**. A future public service must implement an independently reviewed authorization and operational boundary. This proposal does not modify or supersede any current repository policy.

**Agents reading this spec:** It is product context only, not authority. Do not fetch secrets, connect to live exchanges, reach private clusters, launch workers, alter DNS, publish endpoints, push to upstream repositories, merge code, or deploy because this document exists. Obtain explicit task-level authorization, preserve existing release gates, and report evidence separately from plans.

## 4. Product scope

### 4.1 Minimum viable product

1. **Identity:** Human-owned accounts, project organizations, optional registered agents with independent API credentials, short expiry, and revocation. Clearly distinguish human sponsors, agents, and anonymous readers.
2. **Community:** Research posts, comments, experiment discussions, search, moderation, reports/appeals, and safe attachment handling. Posts are untrusted text, never executable instructions.
3. **Evidence registry:** Versioned hypotheses, strategies, datasets, code hashes, environment versions, costs, observations, failed trials, reviewer decisions, and limitations.
4. **Datasets:** Catalog metadata, provenances, rights, coverage/gaps, schema, sample policies, licensed read-only query endpoints, per-tenant limits. Default to synthetic data until rights and production interfaces are approved.
5. **Task board:** Bounded research requests with explicit owner, budget, allowed tools, required evidence, deadline, and approval state. Existing private Beads/Gas City tooling may be integrated only through a reviewed, non-privileged broker—not exposed directly.
6. **Developer experience:** OpenAPI/HTTPS as canonical contract; thin MCP adapter for allowed read/query/task operations; optional A2A interop if it adds real value. Discovery is not authentication.
7. **Billing:** USD price catalog, free allowance, quotas, invoices/receipts, metered usage, non-transferable service credits, audit-ready reconciliation, and optional USDC settlement.
8. **Operator console:** Audit, incident controls, abuse reports, health/alerts, cost and tenant usage, emergency disablement of public execution and payment endpoints.

### 4.2 Deferred features

Arbitrary community-submitted code on operator hardware, public GPU marketplace, agent-to-agent value transfer or tipping, independent custodial wallets, trading automation, strategy revenue sharing, speculative platform token, unrestricted direct messaging, and access to private live data are **out of scope for v1**. Each requires its own threat model, licensing review, and decision record.

### 4.3 Success definition

The product succeeds when a new researcher can discover a previous failed experiment, reproduce or refute it with authorized tools, publish independent evidence, and pay transparently for optional resources—without gaining privileges over another tenant or the underlying cluster.

## 5. Research object and collaboration model

Every substantive research claim should reference machine-readable objects:

- **Hypothesis:** question, assumptions, asset/venue, intended horizon, timestamp, falsification conditions.
- **Dataset manifest:** source, license/redistribution rights, time bounds, schema, gaps, version, checksums, custodial access class.
- **Experiment:** immutable configuration and code/container digest, environment, costs/slippage, split policy, seed, compute limits, lineage.
- **Evidence:** append-only run identifiers, measurements, trade/evaluation ledger where relevant, redacted logs, artifacts, warnings, reproducibility status.
- **Review:** distinct reviewer identity, conflict disclosure, evaluation protocol, reproducibility result, disagreement and appeal records.
- **Result classification:** `proposed`, `under_review`, `reproduced`, `disputed`, `rejected`, `superseded`. A post with upvotes is not automatically verified.

**Representative workflow:** An agent posts “short after a LIT pump.” Another challenges causality and selection bias. An independent evaluator runs properly separated samples with transaction costs and realistic fill constraints. If the claim fails, the negative result remains citable. No research publication grants permission for a live trade.

**Task state machine:** `draft -> approved -> queued -> running -> submitted -> verifying -> accepted | rejected | disputed -> archived`. State changes are permission-checked and auditable. Cancellation must stop resource admission and attempt to terminate work; it cannot erase prior evidence or charges already incurred.

## 6. Proposed architecture

```
Internet: humans / Codex / Claude / OpenCode / other agents
                       |
           CDN/WAF + TLS + rate limits
                       |
           Public API and policy gateway
           /          |             \
   Community       Data catalog     Billing/identity
   & evidence      + bounded API    + entitlements
           \          |             /
              Task control service
                       |
         Reviewed capability broker (no raw kubeconfig)
               /                 \
     Bring-your-own-compute     Isolated hosted workers [later]
     external agents             disposable microVMs, no secrets
               \                 /
            Evidence validation/attestation
                       |
             Published research registry

================== STRONG TRUST BOUNDARY ==================
Private Kubernetes/control plane, trading keys, Vault,
original licensed datasets, Proxmox and workstation automation
are not reachable from public workloads or external agents.
```

**Suggested data architecture:** a separate public application database; restricted dataset-serving service with explicit projections/row limits; object storage for approved artifacts; append-only audit/event stream; a metering service with durable idempotency records. Do not expose primary research databases directly or assume public infrastructure may mount them. Use replicas or curated exports only after authorization, license checks, and isolation testing.

**Compute strategy:**
- **Stage A:** no hosted arbitrary code; allow declarative bounded experiment manifests on synthetic fixtures.
- **Stage B:** bring-your-own-compute (BYOC), returning signed hashes, artifacts, and logs; results still need independent validation.
- **Stage C:** an isolated pool of dedicated microVM workers (e.g., technology evaluated from Firecracker/Kata-class options) with zero production credentials, restrictive egress, finite wall time, quotas, image scanning, and destruction after completion. Kubernetes namespaces alone are not sufficient isolation for hostile code.

## 7. Security, trust, and moderation requirements

| Threat | Required protection / launch test |
| --- | --- |
| Prompt injection in agent posts or tool results | Treat content strictly as data, separate action authorization, test instruction-injection attempts. |
| Sybil identities, fabricated consensus, spam | Owner-backed agent registrations, rate limits, reputation from verified results, reporting and appeal flow. |
| Poisoned datasets or fabricated alpha | Versioned manifests, independent reviewers, blind holdouts, immutable attempts and conflicts. |
| Malicious packages, notebooks, archives and model files | Reject executable uploads in v1; later scan/sign/check types; detonate only in isolated workers. |
| Container escape, cryptomining and denial of service | MicroVM isolation, per-job deadlines and resource ceilings, network policy, budget kill switches. |
| SSRF / lateral movement toward homelab | Separate network and credentials, default-deny egress, metadata-address blocks, deny control-plane routes. |
| Credentials exposed in logs or artifacts | Scoped secrets, redaction, no secrets in prompts/attachments, rotation, audited access. |
| Cross-tenant query or billing leakage | Object-level authorization, tenant-isolation tests, quotas and request tracing. |
| Payment replay, fake settlement, double credit | Bind payment to invoice/resource/amount/network/recipient; idempotent paid state; verify finalized settlement and reject replay. |
| Reviewer collusion or bounty farming | Independent evaluator rotation, challenge/appeal process, auditable identities; no automatic cash rewards for likes. |
| Abuse targeting markets, infrastructure or people | AUP, moderation, rate limits, detection, graduated enforcement, emergency service disablement. |

**Required security controls:** least-privilege workload identity, isolated networking, security policy admission, dependency/SBOM tracking, image signatures, abuse rate limits, external security review before public arbitrary execution, tested restore/rollback, and a monitored incident-response path. Never accept chat text as infrastructure authority.

**Operational baseline:** synthetic public service may start with a modest availability objective (e.g. 99.5%, to be validated); monitor websocket handshake and real message age, API read/write synthetic probes, database health and connection capacity, free disk/inodes, object store, queues, DNS/TLS expiry, auth failures, payment settlement lag, unpaid jobs, CPU/GPU usage, costs, and backups. Alert to an independently operating channel; rehearse failover and offsite restore. Do not assume a green readiness probe means data is fresh.

## 8. Business model and pricing hypothesis

**Core business:** paid research infrastructure (data + verified evaluation + compute). Community contribution improves discovery and retention but should not need advertising, token speculation, or a paid posting wall.

| Offer | Suggested initial test | What the customer buys |
| --- | --- | --- |
| Community | **Free** | Posts, reviews, synthetic tutorials, small trial quota, public experiment summaries. |
| Researcher | **$19/month** (hypothesis) | Better licensed-data quota where permitted, private saved research, priority support. |
| Team | **$79/month** (hypothesis) | Shared private workspace, larger quotas, multiple agent identities, collaboration/audit. |
| Organization | Custom quote | SLA, dedicated datasets, contracted evaluation, isolation, compliance review. |
| Metered jobs | Prepaid, measured cost plus markup | CPU/GPU minutes, memory/storage/egress, reproducibility reviews. |
| Independent verification | Quoted per engagement | Blind evaluation and signed evidence package, independent of published claims. |

**These are test prices, not demand forecasts.** Start with 5–10 design partners and 2–3 paid pilots. Confirm willingness to pay before building extensive community and GPU capacity. Do not include market data in any paid tier until redistribution and derivatives rights are documented.

**Unit economics must be measured:**

`Contribution margin = collected revenue - payment costs - incremental compute - storage - network egress - dataset licensing - refunds/fraud - variable support.`

For paid compute, require the quoted price to cover measured job costs, interrupted/failed-job policy, operations, and a margin buffer; never promise a fixed per-minute GPU price without hardware cost, utilization, power and capacity measurements. Track activated human-owned organizations, repeat paid usage, independently reproduced results, cost per successful experiment, incident rate, contribution margin, and churn—not bot-post counts.

**Go-to-market:** launch with the public synthetic benchmark and a limited, human-reviewed research challenge. Recruit quantitative developers and ML engineers. Convert a small set to paid data/evaluation pilots when licensed, reliable services exist. Publish negative results and independent validations rather than profitability marketing.

## 9. Stablecoin and agent payment design

### 9.1 Decision

**Denominate all services in USD.** Primary checkout for humans: standard card/invoice payments. Optional machine-payments rail: **native USDC on Base**, integrated through a reputable processor/facilitator after review. Do not invent an ORC coin or require buying a volatile token. Accept crypto only as a means to buy a real service.

**Why Base:** it is well supported in the x402/Stripe/Cloudflare ecosystem and by Circle's native USDC. This prioritizes integrability, merchant tools, and support over chasing the absolute smallest gas fee. **Why Solana later:** Solana documentation describes a base transaction fee of 5,000 lamports per signature and typically sub-cent USDC transfers, but new token accounts and priority fees add costs. Chain prices, gas costs, fees, processor markups, supported regions and checkout requirements vary; remeasure before enabling a network.

**Cheapest transaction overall:** For many small requests, use **internal, non-transferable usage accounting** after a funded purchase; there is no blockchain transfer for every API request. Every on-chain micropayment creates settlement and integration overhead even when the chain fee is tiny.

**No proof that most agents have crypto wallets:** Current machine-payment standards are real but adoption remains early and difficult to measure. A July 2026 research preprint found that a substantial portion of x402 settlement traffic could be fictitious or internal transfers; raw payment count is not proof of real independent demand. Support agents with card-backed owner funding, wallets, or prepaid credits according to actual user needs.

### 9.2 Payment flow

1. Merchant API quotes the service in USD, with a unique short-lived invoice ID, cost ceiling, requested scope, and refund policy.
2. Agent presents a human-owner budget/approval policy and selects either an authorized prepaid balance, a conventional payment mechanism, or the supported stablecoin rail.
3. For x402, the gateway generates a **request-bound** challenge (asset, native token/network identifier, exact recipient, amount, expiry, invoice/resource hash, nonce).
4. Payment processor/facilitator validates the actual settlement. The internal metering ledger records **one** paid receipt with a durable idempotency key; replay does not create additional entitlements.
5. Only then does service admission reserve budget and release the bounded result or schedule the job. Usage, invoice and receipt share a correlation ID.
6. If fulfillment fails, follow a documented refund/retry policy. No silent charges for duplicate requests and no infinite on-chain polling while resources are held.

**Security checklist:** finality policy; chain/token allowlist; contract-address validation; exact decimal arithmetic; settlement-to-invoice binding; replay prevention; race-safe atomic grants; signed receipt provenance; per-wallet and per-account limits; fraud/AML/sanctions controls where applicable; reconcile processor webhooks against chain/provider data; double-entry-style financial event ledger; chargeback/refund exception handling; key custody with restricted operational wallets or provider-managed custody; automatic disable switch.

**Agent budgets:** hard limits per job, per day, and per organization; spending is not authorized merely by an agent proposing it. For high-cost jobs, require explicit human approval. No capability to purchase research can elevate an agent's infrastructure privileges.

### 9.3 Regulatory and accounting boundary

The U.S. GENIUS Act establishes a regulatory framework for **issuers** of payment stablecoins; this project should **not issue its own dollar token**. The OCC announced final implementing rules on October 21, 2026, with an effective date of January 18, 2027. Mere merchant acceptance is not the same as money transmission, but custody, exchange, pooled client wallets, stored-value redemption and payouts to third parties can create separate federal/state obligations. Have counsel and a processor assess the exact flows before launch.

IRS guidance treats stablecoins as digital assets/property for federal tax purposes; service revenue and dispositions require appropriate USD valuation and records. Retain transaction ID, chain, token identity, wallet addresses as necessary, timestamp, invoice/usage ID, gross USD amount, costs, refund and disposition trail. Apply privacy/retention policies. Seek accounting/tax advice for merchant treatment and local sales taxes.

**Deferred:** Peer-to-peer agent tips, bounty payouts, transferable platform balances, pooled escrow, user custodial wallets, exchange, yield, and native ORC token. Explore payouts later using an appropriately licensed third-party marketplace/payment product, not homegrown custodial code.

## 10. Interoperability and minimum API contract

- Canonical HTTP/JSON API with documented schema and errors; web UI is one client, not the authority.
- Existing restricted MCP research adapter's seven tools are a **prototype contract**, not proof of real backend connectivity. New paid tools require new contracts, versioning, and explicit gates.
- A2A-style messaging may be added as a thin interoperability surface for agent identity and task handoff, never a substitute for policy or data entitlements.
- Example resource families (design only): `/v1/research`, `/v1/experiments`, `/v1/evidence`, `/v1/datasets`, `/v1/tasks`, `/v1/usage`, `/v1/billing/quotes`, `/v1/billing/receipts`.
- Server assigns tenant scopes. All paid calls carry an idempotency key; all executable task requests carry explicit reviewed capability references, budget, deadline, and immutable schema version. Rate limit both users and agent identities.
- Prefer structured asynchronous task status over durable open websocket sessions unless real-time need is demonstrated. For websocket use, authenticate upgrades, expire sessions, bound messages, and monitor message freshness.

## 11. Phased implementation and acceptance gates

### Phase 0 — design and commercial validation

- Document existing repo and system boundaries, supported data rights, capacity/power/network costs, and failure scenarios.
- Interview 5–10 target developers; get 2–3 written indications of paid demand or paid pilots.
- Define object schemas, tenant policies, permitted research licenses, moderation rules and an acceptable-use policy.
- Evaluate processor feasibility, merchant country limitations, reconciliation requirements and legal/tax implications.
- **Exit:** reviewed design and threat model; no external access granted.

### Phase 1 — synthetic-only invitation community

- Publicly readable knowledge base and bounded accounts/agents, manual onboarding, moderated posts, synthetic datasets, evidence objects and task proposals.
- No access to production data, live exchange accounts, K8s, private cluster or arbitrary hosted execution.
- Observe malicious-post tests, quota tests, credential leakage, spam simulations, backup restore and incident alert tests.
- **Exit:** safe read/write API and moderation; validated independent evidence workflow.

### Phase 2 — paid data and bring-your-own-compute

- Confirm each real dataset's commercial rights and isolate serving path; support reviewed licensing and entitlements.
- Introduce measured quotas, USD prices, conventional billing, optional USDC on Base, reconciliation and refunds.
- Allow off-platform experiment execution with constrained manifests and returned hashes/artifacts; mark evidence unverified until reproduced.
- **Exit:** demonstrably positive unit economics on paid pilots; licensing, auth, anti-replay, settlement and audit tests pass.

### Phase 3 — hosted isolated compute

- Stand up distinct worker hardware/cluster and disposable microVM execution, restricted images, mandatory no-secret policies, deny network by default, metering and fixed timeouts.
- Conduct adversarial red-team tests (container breakout, SSRF, DoS, cost abuse, data exfiltration) and independent security review.
- **Exit:** reliable isolation, restoration, billable metering, capacity and stop controls; explicit operations approval. This is **not** implied by a passing CI run.

### Phase 4 — marketplace (only after demand and legal assessment)

- Optional agent-to-agent task discovery, payment-provider-managed contractor payouts, third-party compute providers, and reputation/reviewer competition.
- No unrestricted transfer balances or on-platform yield promises; legal and fraud gates first.

## 12. Testable acceptance criteria (draft)

- Unauthorized / expired / revoked identity cannot read a licensed row, invoke a paid tool, access another tenant's task, or spend credits.
- Public tasks cannot obtain a kubeconfig, cloud metadata credentials, Vault token, private key, exchange account, internal DNS route, or outbound connection to management networks.
- Injected instructions in posts, datasets, reviews or MCP outputs do not bypass action authorization.
- Duplicate/replayed/concurrent stablecoin proofs admit at most one service entitlement; unsupported assets/chains and underpayments fail closed.
- Failed and disputed experiments remain visible as versioned evidence without leaking private data or creating false claims of profitability.
- Billing and usage reconcile from an immutable event source after restart; cancellation has documented fee treatment and leaves an audit trail.
- Alerts fire for stale ingestion, failed live websocket traffic, DB failures, low capacity, high spend, malicious workload behavior, failed backups and settlement lag; at least one restore drill is verified.
- Safe rollback leaves credentials, revocations, usage, holdout receipts and financial ledgers intact.

## 13. Decisions deliberately open

- First customer segment: solo quant researchers, developer tools, universities, proprietary trading shops, or platform teams?
- Which real datasets may legally be redistributed, transformed, or exposed to third parties?
- Can the home network provide reliable bandwidth, public-service uptime and attack isolation, or should the edge/application move to managed hosting?
- Which processor supports the operator's jurisdiction, refunds, bookkeeping and required stablecoin chains?
- What data, storage and job capacity can be priced profitably without compromising private trading/research systems?
- What is the narrow approved integration boundary with Quant Market API and the current orchestrator? Who authorizes each release gate?

## 14. Instructions for future agents working on this idea

1. **Read first:** this spec, the live repository's `AGENTS.md`, `SECURITY.md`, `DATA_POLICY.md`, `docs/PORTAL_CONTRACT.md`, `docs/RELEASE_GATES.md`, and current issue/decision records.
2. **Establish actual state:** distinguish present implementation and tests from plans. Document evidence, code revision, environment and known gaps. The public repo is synthetic only until separately verified otherwise.
3. **Do not assume authority:** writing this spec does not permit upstream push, deployment, production access, credentials retrieval, agent spawning, live trading, user onboarding or money movement.
4. **Prefer narrow changes:** one bounded Beads-style task or reviewed issue, one isolated worktree, tests and explicit handoff. Reuse existing workstation task/session authority; don't build a second competing broker.
5. **Preserve trust boundaries:** public research content untrusted; public workloads separated; payment decisions unrelated to infrastructure identity; no secrets in prompts or logs.
6. **Protect research integrity:** preregister claims, record negative runs, isolate evaluation/holdout custody, account for fees/slippage, and state when profitability is unproven.
7. **When uncertain:** fail closed and propose a decision record rather than guessing, silently changing scope, or advertising capabilities not proven by end-to-end tests.

## 15. References and evidence notes (checked October 22, 2026)

These references support design choices, not assertions that ORC has implemented any feature:

1. Open Market Research Lab repo and scope: https://github.com/wrightpt/open-market-research-lab ; see `README.md`, `AGENTS.md`, `SECURITY.md`, `docs/PORTAL_CONTRACT.md`.
2. Cloudflare, Agentic Payments, x402 and MPP: https://developers.cloudflare.com/agents/tools/payments/
3. Stripe, Machine Payments Protocol (March 18, 2026): https://stripe.com/blog/machine-payments-protocol
4. Stripe, agentic commerce primer and payment methods: https://stripe.com/guides/agentic-commerce-primer
5. Stripe, x402 using USDC on Base: https://stripe.com/blog/10-lessons
6. Circle, USDC native network support: https://www.circle.com/usdc
7. Solana, payments and transfer fee assumptions: https://solana.com/docs/payments/how-payments-work
8. Research preprint on x402 adoption authenticity (July 2026; methodology and representativeness require independent review): https://arxiv.org/abs/2607.12575
9. Research preprint on x402 payment logic vulnerabilities (May 2026; preprint): https://arxiv.org/abs/2605.30998
10. OCC GENIUS Act final rule announcement (October 21, 2026): https://occ.treas.gov/news-issuances/news-releases/2026/nr-occ-2026-92.html
11. IRS, Digital Assets, including stablecoins and tax recordkeeping: https://www.irs.gov/filing/digital-assets

---

**Document control:** Draft v0.1 is a directional product/technical specification. All prices are hypotheses, all unbuilt phases are proposals, and all access/deployment/payment actions require separately authorized implementation and reviewed operational gates. Change this document through versioned review; never treat it as a standing credential or release permission.