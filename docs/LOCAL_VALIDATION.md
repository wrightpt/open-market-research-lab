# Local validation receipt — 2026-10-15

Scope: local engineering only, Python **3.14.4**, standard library, no installed
dependencies. The commands below completed without network, database, account,
cluster, or credential access. No hosted CI execution is claimed.

| Command | Actual result |
| --- | --- |
| `python3 -m unittest discover -s tests -v` | **43 tests passed**, 0 failures/errors, 1.882 seconds |
| `python3 -m market_lab verify-data` | Verified 384 development rows and 192 holdout rows against exact hashes and structure |
| `python3 -m market_lab validate submissions/baseline.json` | Valid |
| `python3 -m market_lab backtest submissions/baseline.json --output artifacts/reviewed-development.json` | Completed development; 10 fills, 5 round trips, final units 0 |
| `python3 -m market_lab freeze submissions/baseline.json --development artifacts/reviewed-development.json --output artifacts/reviewed-freeze.json` | Frozen successfully; holdout remains unconsumed |

The suite includes byte-identical repeated development reports, all 384 causal
prefixes, future-mutation invariance, price-gap execution, open/close timestamp
semantics, both transaction costs, terminal drawdown accounting, unknown outcome
exclusion, schema/path limits, freeze drift, failed-attempt retention, concurrent
holdout admission, workflow permissions, and source exposure checks. Holdout gate
tests stub report generation; they do not calculate holdout strategy outcomes.

## Reproduction identities

- Source/contract SHA-256: `4ad7fdfa20171548d591e92bafc9f70778e3688e27277a073ecca6aad6e7731d`
- Submission SHA-256: `1673b1bdc7992d87a0b41654f9571a6fcb30bc565680528228bcca1652e58854`
- Development report SHA-256: `7a5cc4aa1100e413aa270ff0699b4b5c9d4f27d574f8ee3d77bf90ce0df09732`
- Freeze receipt checksum: `fed9cb026afc2e72354779415cf19049a630854829210bc5942549fd44082e78`

The report and freeze remain local ignored artifacts. The earlier pre-review
`artifacts/local-development.json` is retained; review corrected its fill timestamp
ambiguity. The reviewed report uses opening timestamps for next-open fills and
explicit source-bar close timestamps. No parameters were retuned.

## Accounting and alert diagnostics

The toy ledger began at 10,000 and ended at 8,498.420367634199, with modeled fees
47.15939626743636 and slippage cost 28.295509409234196. Maximum close drawdown was
0.15842711484552896. These numbers are synthetic bookkeeping observations only.

The detector had 28 evaluable non-overlapping windows: 1 true positive, 1 false
positive, 24 true negatives, and 2 false negatives. Two sampled windows had unknown
features; one had an unavailable future horizon. There is no statistical or market
predictability conclusion. The checked-in holdout was structurally verified but
its outcomes were not evaluated.

## Review and release boundary

Source and documentation review found no copied private history/code, private host
paths, private IP endpoints, or recognizable credential material. The automated
scan covers common private-key/token and host-path patterns; it is not a general
secret-detection guarantee. The workflow has read-only token permissions, hosted
runners, pinned actions, no PR secrets, and no privileged PR trigger. Python 3.11
syntax is checked locally; its configured hosted matrix run has not occurred.

Local implementation is complete. At the time of this validation receipt, public release still required the owner's
publication decision, an approved private security intake, and a hosting/settings/CI
review. See docs/PUBLIC_RELEASE.md for the later release-candidate state. Outreach files are
unpublished. Show HN additionally requires an actual licensed public clone-and-run
demo. No placeholder GitHub URLs are present. No push, deployment, trade, or
Kubernetes access is authorized by this receipt.
