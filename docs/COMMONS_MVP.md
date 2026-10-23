# Open Research Commons — local evidence MVP

This implementation turns the discussion spec into one working loop: write a
synthetic research claim, run or import its evidence, replay the exact submission,
and record a reviewer decision. It is a local application, not a hosted community.

## Run

```bash
python3 -m research_commons --seed-demo
```

Open `http://127.0.0.1:8787/commons/`. Python 3.11+ standard library on a POSIX
system (Linux or macOS, for the file lock); no
installation, account, API key, database service, or network download is needed.
State is retained under `artifacts/commons/`. Restarting preserves it. Omit
`--seed-demo` for an empty workspace. `--port` and a repository-relative
`--state-dir artifacts/...` select another local instance. Never tunnel this app.

## Product decisions

An evidence registry is the first slice. A discussion-first community would not
exercise reproduction; hosted compute and payments require separate operational
designs. The MVP includes search/filtering, immutable study records, linked forks,
one synthetic dataset, bounded engine runs, imported JSON evidence, exact replay,
review notes, and portable JSON evidence packages. All examples are labeled.

The journal aesthetic emphasizes readable research, provenance and disagreement.
The application includes a dataset page and a short workflow guide.

## Meaning of a result

- **Submitted**: a report was retained; its numerical claims are unverified.
- **Replay matched**: the complete canonical report equals a new run using the
  frozen submission, current source fingerprint and development fixture. This is
  same-engine local repeatability, not independent scientific validation.
- **Disputed**: the replay and submitted report differ. Both remain retained.
- **Reviewer decision**: a separate, attributable opinion with rationale and
  conflict disclosure. Approval requires a matched replay and a different local
  persona. Switching personas is a workflow demonstration, not authentication or
  proof of reviewer independence.

Every result remains `synthetic_engineering_only`. There is no market-validity,
profitability, unseen-data or live-readiness badge. Only development is evaluated;
holdout metadata can be inspected but its outcomes are never computed here.
Criteria are written before evidence. This is not a preregistration claim about
already-public fixture data. Revisions create linked studies; old evidence stays.

## Architecture and limits

`research_commons.journal` stores an append-only sequence of hash-linked JSON
events. Writes are flushed and atomically installed before acknowledgment. An
exclusive process lock prevents two writers. Replay checks sequence and hashes;
corrupt evidence fails closed. This detects accidental corruption, not a hostile
filesystem owner. No deletion or overwrite API exists. Back up the entire state
directory while stopped; restore into a new state directory and verify on startup.

`research_commons.service` owns validation, transitions and deterministic engine
calls. `research_commons.server` exposes a fixed loopback HTTP API and local static
assets. The browser is a client; it never decides whether evidence is reproduced.
Requests are serialized, body sizes bounded, and mutations require an in-memory
session, exact Origin, CSRF token and a durable idempotency key. Reusing a key for
different input fails. Host validation prevents DNS rebinding. There are no
external scripts, fonts, fetches, arbitrary code, file paths, SQL or shell tools.

The journal is capped at 1,000 events and 128 MiB. Reports and requests are capped
at 2 MiB. One run processes the fixed 384-row development fixture. Failed and
interrupted attempts are retained; a retry uses a new request key. No worker queue,
billing, cancellation API or budget accounting is advertised in this synchronous
local slice. Agent clients can use the documented HTTP interface with a local
session; production identity and MCP integration are separate future work.

## Validation

Use `python3 -m unittest discover -s tests -v`, `python3 -m market_lab verify-data`,
and `git diff --check`. Browser checks cover creation, evidence submission, replay,
review, export, filtering, mobile layout and error states. The current receipt is
in `docs/COMMONS_VALIDATION.md` once those checks have completed.

## Next product experiments

Use the workflow with a few invited researchers before building community feeds.
Measure completed reproductions, time to resolve discrepancies and repeat use.
A paid evaluation pilot needs one explicitly licensed dataset, one buyer segment,
an independently governed evaluator and separately approved billing. Future
payment designs must reserve owner budget before payment authorization and retain
failed, expired, cancelled and refunded states. The broader discussion spec is
context; existing release gates still govern publication and deployment.
