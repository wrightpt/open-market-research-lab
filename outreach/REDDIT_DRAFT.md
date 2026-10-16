# Reddit draft — unpublished

Status: **unpublished forum draft**. No Reddit post or forum account action has
occurred. The synthetic benchmark is now public and Apache-2.0 licensed at
https://github.com/wrightpt/open-market-research-lab; its source and test run are
available for independent reproduction.

For r/algotrading, the known moderator rule prohibits simply asking
others to share strategies. This draft presents an implementation and specific
review questions. It must not ask which strategies work or solicit alpha. Verify
the community's current complete rules before any separately authorized posting.

## Proposed title

A reproducible liquidity/deleveraging benchmark: synthetic OHLCV and a stdlib baseline

## Draft body

I've built an inspectable benchmark and runnable baseline for a concrete
microstructure research question: when quoted spreads widen, near-mid depth
shrinks, and open interest falls, can a causally timed alert distinguish a later
adverse price move from a false warning? The initial benchmark tests the mechanics
of answering that question, including leakage and cost accounting.

The demonstration uses entirely scripted hourly OHLCV plus synthetic spread,
depth, open interest, and liquidation fields. The scenarios include early warnings,
false warnings, unwarned shocks, and late warnings. These are test fixtures; an
alert that works on them is not evidence that it predicts a market.

The core is standard-library Python and a declarative JSON submission. To reproduce
the local demonstration from a reviewed checkout:

```bash
python3 -m market_lab verify-data
python3 -m market_lab validate submissions/baseline.json
python3 -m unittest discover -s tests -v
python3 -m market_lab backtest submissions/baseline.json
```

The baseline compares current spread/depth with trailing medians and measures
open-interest change over a fixed lookback. A close-t decision can first fill at
open t+1. The toy long/cash ledger applies fees and adverse slippage on entry and
exit, including terminal liquidation. The report contains the actual decision and
fill rows, not just a headline metric.

The most useful checks are deliberately small: changing the future must leave
earlier signals unchanged; a price gap must fill at the next open; a flat-price
round trip must lose exactly its modeled fees and slippage. Missing features stay
unknown. Incomplete forward horizons stay unknown too, and do not enter the alert
metric denominator. Always-cash and always-long controls use the same costs.

There is also a freeze receipt and one-attempt holdout exercise. Both synthetic
files and the generator are visible, so this is a custody/workflow demonstration,
not a blind statistical test. The local guard cannot stop someone with filesystem
access from tampering with it.

Public source: https://github.com/wrightpt/open-market-research-lab

The requested feedback is code review and reproducibility critique: can you
reproduce the fixture hashes and reports; find a future-data leak, cost
reconciliation error, misleading denominator, or invalid inference from the
synthetic construction? No one is being asked to share a strategy, reveal an
edge, suggest profitable parameters, or answer which strategies work. There are no return,
predictability, or live-trading claims. No real historical data, accounts, or
infrastructure are needed to review it, and contributors receive no Kubernetes
access.

## Before this draft could be posted

Replace this editorial section only after completing
[FORUM_LAUNCH_CHECKLIST.md](FORUM_LAUNCH_CHECKLIST.md) and receiving explicit posting
approval for the exact destination and text. Do not add performance claims,
promotional links, recruiting language, private data, or a call to trade.
