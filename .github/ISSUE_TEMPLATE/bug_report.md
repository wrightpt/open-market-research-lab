---
name: Reproducibility or correctness bug
about: Report a synthetic-data, contract, causality, accounting, or CLI defect
title: "Bug: "
labels: ["bug"]
---

## Smallest reproducible problem

Describe the observed result and the expected result, without using live market
data, credentials, personal account records, or private infrastructure.

## Environment and code revision

- Python version:
- Repository commit SHA:
- Exact CLI command:
- Synthetic dataset ID and SHA-256:

## Evidence

Provide a minimal synthetic input, non-sensitive failing assertion, or test.
Explain whether future data could leak backward, fills could occur before a
decision, costs might be undercounted, or unavailable outcomes are treated as
success. Do not paste real database rows.

## Proposed bounded fix

How can a regression test prove the fix? Never request cluster access or
privileged CI.
