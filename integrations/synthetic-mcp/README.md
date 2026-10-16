# Open Market Research — synthetic MCP prototype

**Status: local, read-only prototype. Not deployed. Not connected to ChatGPT yet.**

This standalone package demonstrates the Model Context Protocol (MCP) tools we
would eventually publish in the ChatGPT/Codex plugin directory. It uses **only**
the public `synthetic-liquidity-v1` development CSV in this repository. It
cannot query real exchanges, Vault, Kubernetes, ClickHouse, or trading systems.

## Run locally

Requires Node.js 22+ and npm. From the public repository root:

```sh
cd integrations/synthetic-mcp
npm ci --ignore-scripts
npm run check
npm start
```

The process listens at **http://127.0.0.1:8787/mcp**. It is deliberately
loopback-only and does not offer an externally routable hostname. In another
terminal, `curl http://127.0.0.1:8787/healthz` returns a synthetic-only
status. Stop the server with Ctrl+C.

The `npm run check` command tests the service through the official MCP
client, rather than just checking the data helpers.

## Available tools

| MCP tool | What it returns | Bounds |
| --- | --- | --- |
| `list_datasets` | Only the synthetic dataset ID, provenance and known extent | One public fixture |
| `describe_dataset` | Units, field meanings, SHA-256, coverage and known limitations | Metadata only |
| `get_sample` | Closed-hour synthetic development observations | Maximum 20 rows per call, row offset 0–383 |

All three tools declare `readOnlyHint=true`, `destructiveHint=false`,
`idempotentHint=true` and `openWorldHint=false`. Only the development
split is readable via the tools; even though the synthetic holdout CSV is also
in the public Git repository, it is not exposed by this MCP demonstration.

There are no write, shell, arbitrary SQL, filesystem-path, URL-fetch, trade,
Vault, Kubernetes or database tools. Malformed or out-of-bounds arguments
are rejected by strict Zod schemas.

## How to test it in ChatGPT Work later

A browser-hosted ChatGPT session cannot connect directly to your workstation's
`127.0.0.1` address. When **separate authorization** approves a dedicated,
isolated public HTTPS deployment of this synthetic-only server, follow the
official ChatGPT plugin quickstart:

1. Go to ChatGPT **Plugins** and select **Add custom MCP server**.
2. Give the connection a recognizable name and provide the *verified*
   HTTPS endpoint ending in `/mcp`.
3. Select **No authentication** only for the explicitly public synthetic
   demo. Restricted datasets must instead use reviewed OAuth.
4. Review the requested connection, create the private plugin, and install it.
5. In a new ChatGPT **Work** chat, select the plugin with `@` and ask:
   - "List your available research datasets."
   - "Describe the synthetic liquidity benchmark fields."
   - "Return ten development observations and their SHA-256 provenance."

A public directory submission requires a separate identity, security, policy
and usability review. This proof of concept does not create or publish a
ChatGPT plugin, and a hosted endpoint has **not** been set up.

## Security design

- Uses the official `@modelcontextprotocol/server` and Node transport SDK.
- Binds **only** to loopback; no `HOST` override or public ingress.
- Verifies the original development CSV SHA-256 before starting; fails closed.
- Rejects unapproved fixture paths/IDs, malformed arguments, and unbounded rows.
- Uses explicit loopback Host and Origin validation against DNS rebinding.
- No credentials, service-account tokens, kubeconfigs, database drivers, dynamic
  code evaluation, subprocesses, analytics or external network fetches.
- Request deadlines and request-size limits; additionally require a dedicated
  proxy/API gateway if the service ever becomes internet-facing.
- CI uses GitHub-hosted ephemeral workers, read-only GitHub permissions and
  pinned Actions, with dependency installation lifecycle scripts disabled.
- The runtime dependencies are locked. Audit them on each release; no
  security scan guarantees absence of unknown vulnerabilities.

**Important:** The server is *not* production hardened. In particular, a public
deployment needs TLS, authenticated/authorized user identity for any nonpublic
data, global request and concurrency budgets, DoS protection, monitored errors,
correct proxy Host/Origin policy, incident response, and independent review.
Never simply change the bind address to `0.0.0.0`.

See [the public research lab](https://github.com/wrightpt/open-market-research-lab)
and the repository's [data policy](../../DATA_POLICY.md).
