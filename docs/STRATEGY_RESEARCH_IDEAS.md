# Strategy research ideas for collaborators (synthetic-only)

**Status:** Idea backlog — **not** a portfolio, trading recommendation, or record of validated strategies.  
**Audience:** Ian and other agents working from this **public** repository.  
**Data boundary:** These are independent, high-level research questions. They do **not** reproduce private workstation research, code, configuration, live observations, licensed data, unpublished performance results, or trading parameters.

Read [AGENTS.md](../AGENTS.md), [DATA_POLICY.md](../DATA_POLICY.md), [Challenge 001](CHALLENGE.md), and [Release gates](RELEASE_GATES.md) before beginning. This repository is a deterministic **synthetic engineering benchmark**. The current public fixture does not establish market predictability, profitability, or eligibility for orders. A hypothesis appearing here does not mean it has been implemented or tested.

## Candidate hypothesis registry

| ID | Research question | Hypothesis to falsify | Data / fixture prerequisite | Control or failure condition | Public evidence status |
|---|---|---|---|---|---|
| H01 | Liquidity deterioration and deleveraging | Do worsening spread/depth and falling open interest precede adverse moves? | Current synthetic-v1 has spread, depth, OI and prices | Always-long/cash baselines, null feature coverage, next-open execution, costs | **Baseline engineering exercise only**; see Challenge 001 |
| H02 | Spike-fade versus continuation | Does a price/volume spike predict reversal, continuation, or neither after costs? | A newly reviewed synthetic event family with *causally defined* spikes | Matched random-time placebo, continuation comparator, adverse excursion and squeeze risk | **Proposed; no public results** |
| H03 | Post-spike exhaustion | Do changes in volume, range and price response distinguish exhaustion from merely strong trend? | Synthetic intrabar/event features and explicit availability timestamps | Trend-following control, sensitivity to event definition, out-of-window rejection | **Proposed; not runnable on current fixture as stated** |
| H04 | Order-book imbalance / microprice | Does a causally available depth imbalance add information beyond spread and returns? | New versioned synthetic L2/depth fixture; current aggregate depth alone is insufficient | Locked spread/depth baselines, latency, stale quote filtering, realistic fills | **Proposed; missing fixture** |
| H05 | Cross-venue lead/lag | Does one venue's price/depth move systematically lead another after timestamp and cost adjustments? | Two independently versioned synthetic venue feeds, exchange/receive clocks | Negative/shifted lags, asynchronous timestamps, multiple-testing correction, execution friction | **Proposed; missing fixture** |
| H06 | Maker fill realism | Does a candidate edge survive conservative passive-order fill and cancellation assumptions? | Synthetic queue changes, order lifecycle, spread and adverse selection data | No automatic fill at a touched price, varied fill models, taker fallback prohibited by default | **Proposed; infrastructure/control study** |
| H07 | Deleveraging maturation | Do combinations of OI contraction, liquidation activity and improved liquidity identify regime transitions? | Synthetic time-aligned OI/liquidation/depth; current fields are coarse | No future-derived regime labels, independent outcome windows, unknown coverage and missingness | **Proposed; no public result** |
| H08 | Rebound / mean reversion | Do drawdown and stabilization signals outperform unconditioned recovery or cash? | Synthetic prices and explicit stabilization features | Price-only and time-matched controls, realistic costs, no lookahead in trough selection | **Proposed; no public result** |
| H09 | Regime-aware correlation lag | Do lagged cross-asset relationships persist out of sample under a predeclared regime definition? | Multiple synthetic instruments with synchronized event/receive clocks | Predeclared lags, shuffled/placebo pairs, stable-sign and multiplicity checks | **Proposed; missing fixture** |
| H10 | Adaptive limit execution | Can a bounded, paper-only limit-order ladder reduce realized cost versus a fixed schedule? | Versioned synthetic executable order events and cost model | Never infer fills from OHLC alone, queue/wait/cancel accounting, position and loss ceilings | **Proposed; paper simulation only** |

**Ancillary engineering/evaluation topics — not trading alpha:** a safe declarative indicator-rule compiler; incident-replay risk controls; source/event-time audit; blinded independent outcome labels; reproducible strategy evidence manifests; and independent evaluator review. These belong in separate, scoped proposals rather than being misrepresented as live strategy results.

## How Ian should work through this backlog

1. Start with **H01**, since it can run against the repository's current synthetic fixture. Re-run existing verification and tests without evaluating the holdout.
2. Choose **one** next hypothesis and write a short pre-registration: precise event time, available features, action at next open, outcome horizon, economics, expected failure modes, controls, and sample-size gate.
3. For H03–H06, H09 or H10, first propose a **new deterministic synthetic fixture/version**. Never invent real market data or silently fill missing schema fields. Do not change synthetic-v1 in place.
4. Implement in an isolated branch, log *every* development attempt (including negatives), and report unknown coverage. Keep the development/holdout boundary intact and do not spend the holdout without a separate deliberate authorization.
5. Attach the test/diff/evidence record to a PR. Require independent review of any positive result and an explicit release decision before proposing a new dataset or service.

### Minimum evidence template

For each study record: `hypothesis_id`, frozen hypothesis and code/data hashes, fixture version, observation/decision/execution timestamps, excluded observations, controls, all development attempts, sample size, fees/slippage/fill model, diagnostic uncertainty, failed acceptance checks, test commands and results, follow-up owner, and an explicit outcome label:

- `NOT_TESTED` — an idea or implementation plan only.
- `ENGINEERING_VERIFIED` — tests pass on synthetic fixtures; **not** evidence of real-world effectiveness.
- `NEGATIVE` / `INCONCLUSIVE` — a reported evaluation with retained evidence and no positive claim.
- `REQUIRES_INDEPENDENT_REVIEW` — positive-looking development findings, never release-ready.

**Do not** import unpublished results or paths from private repos into this public catalog. Any richer historical results require a separately approved private-access handoff and explicit data-sharing authority. This catalog does not grant Ian or any agent workstation, cluster, exchange, credential, licensed-data, real-market, or live-trading access.
