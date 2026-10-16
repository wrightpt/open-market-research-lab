# Data policy

## v1 identity and custody

Only newly generated deterministic synthetic data is admitted. No private code,
market histories, workstation paths, account records, keys, or third-party datasets
were copied into these fixtures. `SYNTHETIC:TOY-USD` at venue `NONE` is an invented
instrument; the dates and USD-like units describe no real observations.

The authoritative checked-in identity is [manifest.json](data/synthetic-v1/manifest.json).
`market_lab.fixtures` regenerates the bytes using integer arithmetic, explicit LCG
seeds, LF newlines, a fixed column order, and six-decimal price strings.
`verify-data` checks the manifest against that generator and each file against its
SHA-256, row count, exact timestamps, and structure. Do not silently regenerate,
edit, or re-hash v1 to accommodate a result. A changed fixture needs a new version,
reviewed rationale, new hashes, and new submissions.

| Split | Rows | Close timestamps, inclusive (UTC) | SHA-256 of exact CSV bytes |
| --- | ---: | --- | --- |
| Development | 384 | 2024-01-01 01:00 to 2024-01-17 00:00 | `2f09fc34b9c7124b4d3bcdb93b8227c6c3a451b1c10d544016860d174fa6d544` |
| Holdout exercise | 192 | 2024-01-18 01:00 to 2024-01-26 00:00 | `b61c68b8ede9acf14593966cfb7a39d8306810919567cb72449801be1c7f1587` |

There are 24 omitted hourly bars between splits, matching the largest admitted
outcome horizon. Each split starts flat and warms up independently. Neither
features, open positions, nor future labels cross the split. Different seeds and
disjoint times do not make scripted synthetic scenarios independent market evidence.

## Field semantics

`timestamp` is the UTC bar close. OHLC covers the preceding hour. All market
features are assumed available at that close, never earlier. A close-t decision
first trades at open t+1, including any gap. Bar opens and prior closes share a
boundary timestamp in this hourly convention; execution still uses the next row's
open, never the current row's close.

| Fields | Meaning |
| --- | --- |
| `open`, `high`, `low`, `close` | Positive synthetic quote price per unit |
| `volume` | Nonnegative invented base-unit volume |
| `spread_bps` | Nonnegative synthetic quoted spread, a signal input |
| `depth_usd` | Positive invented aggregate near-mid depth; no actual order book |
| `open_interest_usd` | Positive invented derivative-market context |
| `liquidation_usd` | Nonnegative invented liquidation context, unused by the baseline rule |

Market-feature empty cells mean **unknown**, never zero, quiet activity, or valid
coverage. Required price/volume fields cannot be missing. A missing required
feature anywhere in its reference window makes that decision unavailable and
cash-only. No imputation, backfill, sorting repairs, or silent row drops are used.
The toy ledger holds a cash asset; derivative-like context does not model funding,
margin, liquidation risk, or an executable derivative position.

## Development versus holdout

Development allows debugging and disclosed hypothesis/parameter iteration. Keep
all trial settings, negative results, and failure evidence. The example was chosen
for mechanics, with no optimization or performance-based selection.

Before an explicit holdout attempt, freeze the exact submission, costs, feature
lookback, evaluation horizon, criteria, code/contract hash, fixture identities, and
development report hash. The CLI enforces this binding. A holdout attempt consumes
one dataset-wide local receipt before reading its data, even if evaluation fails.
No automatic retry or reset exists. Do not tune, select thresholds, rewrite a
verdict, remove receipts, or clone the repository to treat that data as fresh.

Both fixtures and their generator are available to anyone reading the checkout. Structural
validation and hash checks inspect holdout without scoring outcomes; this does
not confer blindness. Actual independent research needs a separately authorized
study with unseen data custody, licensing, frozen selection, and independent
review. This repository implements none of those external data connections.

Future labels require the entire horizon within the selected split. Incomplete
tails remain `null` with their decision metadata retained. Only complete outcomes
and available alerts enter denominators. Sampled future intervals do not overlap;
this does not assert statistical independence among samples or scenarios.

## Retention and future admission

Reports retain config, source/data hashes, decisions, fills, costs, and evaluated
and unevaluable samples. Local artifacts are ignored by Git to avoid accidental
publication, but this is not an instruction to delete them. Preserve consumed
receipts with any backup or handoff. Review provenance and sensitive content
before selecting anything for a separately approved release.

Any future real dataset would require documented acquisition authority, license
and redistribution rights, source identity, instrument mapping, event/receipt
timing, revision policy, completeness and missingness, and immutable split custody.
Real-data admission and database access are outside this prototype's authority.

The portal catalog is generated from this public synthetic manifest. Coverage and
holdout hashes are metadata, not scored holdout outcomes. Its schema includes
all ten fields, units, null meaning, hourly resolution, freshness (frozen), gaps,
retention (versioned source), original provenance and Apache-2.0 license. API
approval does not approve a real dataset: source rights, qualification, immutable
identity and an explicit release decision are separate gates.
