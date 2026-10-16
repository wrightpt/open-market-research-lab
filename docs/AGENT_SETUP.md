# Safe agent setup

Claude Code, Codex and OpenCode first follow [AGENTS.md](../AGENTS.md) and the
offline benchmark quickstart. The local mock portal needs no account or token.
The optional adapter needs a **separately approved** HTTPS research API and scoped
key; none is deployed or issued by this repository. These are setup recipes, not
claims of authenticated product integration. Real stdin/stdout tests cover MCP
2026-07-28 and legacy 2025-11-25; client product versions must be checked separately.

Review the adapter source before trusting it. Start the agent in this checkout
so `python3 -m omr_mcp` resolves this package. For an approved future connection,
load the two values privately in a trusted interactive shell (Bash example):

```bash
read -r -p 'Approved HTTPS API origin: ' OMR_API_URL
read -r -s -p 'Research API key: ' OMR_API_KEY
export OMR_API_URL OMR_API_KEY
```

The key input is hidden and is not a shell command/history entry. Do not use shell
tracing, environment dumps, key-bearing command arguments, agent prompts, global
credential exports, screenshots or repository `.env` files. The agent process can
inherit these variables: this is trusted local process configuration, not protection
against a compromised agent or OS user. Prefer an approved secret-manager launcher
when available, and scope inheritance to this session. No secret manager is accessed
or configured by this implementation. After stopping the client, `unset OMR_API_KEY
OMR_API_URL OMR_CA_FILE`. Do not paste the result of any environment inspection.

## Claude Code

Use an uncommitted local MCP configuration, merging the following entry with your
own configuration. Variable references, not actual values, are passed at launch.
The [official MCP guide](https://code.claude.com/docs/en/mcp) documents stdio and
environment expansion. Check `/mcp` for discovery errors without sharing secrets.

```json
{"mcpServers":{"omr":{"type":"stdio","command":"python3","args":["-m","omr_mcp"],"env":{"OMR_API_URL":"${OMR_API_URL}","OMR_API_KEY":"${OMR_API_KEY}"}}}}
```

Do not use a CLI `--env` flag with a literal key; it can persist the value and expose
it in process arguments. Do not weaken agent permissions or auto-approve tools for
onboarding. Keep personal configuration outside Git (the root `.mcp.json` is ignored).

## Codex

In your private Codex configuration, use a variable-name allowlist. `env_vars`
forwards the launching process's values without embedding them in TOML. The local
`codex mcp add --help` was inspected; direct configuration avoids literal `--env`
credentials. See the [official MCP configuration](https://developers.openai.com/codex/mcp).

```toml
[mcp_servers.omr]
command = "python3"
args = ["-m", "omr_mcp"]
env_vars = ["OMR_API_URL", "OMR_API_KEY", "OMR_CA_FILE"]
```

Launch Codex in the checkout, or set `cwd` privately to your reviewed checkout.
Keep host-specific paths out of commits. Do not use remote executor configuration
or `bearer_token_env_var`: this adapter is local stdio and uses X-API-Key internally.

## OpenCode

Merge into private, uncommitted configuration. Local command and environment-variable
substitution are documented in [OpenCode MCP servers](https://opencode.ai/docs/mcp-servers/).
Use the checkout as the workspace; retain interactive approval controls.

```json
{"mcp":{"omr":{"type":"local","command":["python3","-m","omr_mcp"],"environment":{"OMR_API_URL":"{env:OMR_API_URL}","OMR_API_KEY":"{env:OMR_API_KEY}"},"enabled":true,"timeout":15000}}}
```

## ChatGPT

ChatGPT does not directly launch this local stdio adapter. Its documented connector
path uses [remote MCP servers](https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt).
No ChatGPT endpoint, connector, tunnel or public HTTPS bridge is implemented or
authorized here. A future bridge requires separate security review and activation
approval; it must authenticate users and enforce the same backend authorization.
Do not point ChatGPT at the mock portal or paste a research key into chat. Today,
use ChatGPT to review public source and sanitized synthetic test receipts only.

For every client, returned data is untrusted evidence, never instructions. No
adapter configuration grants cluster, database, trading, private repository or
holdout access. Begin with `list_datasets` on an explicitly approved synthetic
backend; a successful tool discovery alone proves no data entitlement.

## Agreed synthetic tool examples

After separate backend approval, tools/list exposes each argument schema. The
adapter forwards the arguments directly; backend validation remains authoritative.
list_datasets, get_research_examples and get_usage_limits use `{}`.
describe_dataset, get_coverage and get_schema use
`{"dataset":"synthetic-perp-daily-v1"}`. A bounded query uses:

```json
{"dataset":"synthetic-perp-daily-v1","asset":"BTC","start":"2026-01-01T00:00:00Z","end":"2026-01-03T00:00:00Z","max_rows":100}
```

The interval starts inclusively and ends exclusively at UTC bucket boundaries;
max_rows cannot exceed 500. The API also has synthetic-perp-hourly-v1 and
synthetic-liquidity-research-v1; BTC/ETH/HYPE/XMR are invented fixture series.
These API fixtures are distinct from the offline toy benchmark, whose timestamps
denote bar close. Use metadata.time_basis for the selected dataset. No real
vendor-client or backend connection was exercised by the local TLS/subprocess tests;
official SDK conformance and vendor-client integration are separate evidence.
