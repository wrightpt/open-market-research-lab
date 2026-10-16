---
name: Research methodology question
about: Propose a falsifiable test using synthetic or separately approved datasets
title: "Research: "
labels: ["research"]
---

## Hypothesis and mechanism

State the causal market mechanism, what would falsify it, and why simpler
baseline explanations might account for the effect.

## Observations and data rights

Use the checked-in **synthetic** fixtures for code-level demonstrations. No
live market, private ClickHouse, wallet, or provider-restricted datasets belong
in issues or PRs. Identify any separately proposed dataset only by public
provenance and its license status.

## Experiment design

- Development and untouched holdout policy:
- Exact feature observation times and action latency:
- Transaction costs, slippage, and liquidity assumptions:
- Baselines and negative controls:
- Search size and failed configurations to retain:
- Reproducibility/evidence manifest:

## Safety and interpretation

No investment recommendation or profitability claim. Public code submissions
have no access to Kubernetes, private runners, production credentials or live
order execution.
