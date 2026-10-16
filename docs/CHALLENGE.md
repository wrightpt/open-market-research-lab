# Challenge 001: deterioration and deleveraging before drawdowns

**Question:** Can a predeclared alert based on worsening liquidity and declining
open interest identify later adverse price moves, while accounting for false
alarms, missed events, unknown observations, and economic friction?

This prototype only makes the question runnable on scripted data. The generator
deliberately creates lead warnings, false warnings, unwarned shocks, and late
warnings. Any association is partly constructed by that generator. It cannot
establish market predictability or a profitable strategy.

## Fixed baseline

The [submission](../submissions/baseline.json) declares a 12-bar lookback. At close t,
count spread >= 1.8 times the trailing median, depth <= 0.6 times its trailing
median, and OI decline >= 8% since t-12. Two flags cause an alert. All references
are causal; missing required features mean unknown/cash. Target long otherwise,
with execution at the following open and no leverage.

Fees are 5 bps and adverse slippage 3 bps on each fill. No threshold search or
performance target chose these values. They exercise accounting and rule behavior.

## Outcomes and controls

At non-overlapping 12-bar anchors after warmup, label whether any of the next
12 closes is at least 3% below the anchor close. Retain incomplete horizons as
unknown. Record true/false positives and negatives, precision, recall, and the
first-breach lead time of true positives. Always disclose evaluable sample count
and excluded feature/outcome counts; a zero denominator remains null.

The toy long/cash ledger and always-long/always-cash controls report net return,
close drawdown, fees, slippage, fills, and round trips. These describe simulated
accounting, not actual trades, fills, PnL, or an alpha claim. Detector diagnostics
and portfolio accounting answer different questions and must remain separate.

## Acceptance and falsification

Engineering acceptance requires exact fixture custody, causal-prefix invariance,
correct next-open timing through price gaps, two-sided cost reconciliation,
non-overlapping outcome windows, preserved unknown tails, bounded submissions,
and working freeze/consumption checks. A failing invariant rejects the implementation
until fixed; favorable synthetic numerical metrics cannot override it.

A later, separately authorized market study would need a mechanism and data
availability audit, a complete development search log, frozen economic and
statistical criteria, fresh holdout custody, uncertainty/power analysis, robust
controls and cost assumptions, and independent review. If it cannot distinguish
signal from base rates, controls, selection, or data artifacts, it must report
non-demonstration. No such market study is performed or authorized here.
