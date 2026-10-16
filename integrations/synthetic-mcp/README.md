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

ChatGPT running in the cloud cannot connect directly to the workstation's
`127.0.0.1` address. **For a private test, prefer OpenAI Secure MCP Tunnel**
(https://developers.openai.com/api/docs/guides/secure-mcp-tunnels). It routes
MCP requests outbound through OpenAI without opening public inbound ports.

After approving the limited synthetic-only scope:

1. Create a **dedicated test tunnel** in OpenAI Platform tunnel settings and
   associate it with the ChatGPT workspace intended to use the plugin. Ensure
   the operator has Tunnels Read + Use and the creator Tunnels Manage.
2. Start this server locally (`npm start`). Have the operator configure
   `tunnel-client` to forward only to `http://127.0.0.1:8787/mcp`. Provide
   the restricted runtime API key through a secure local credential mechanism;
   never paste it into chat, a command argument, Git, or output logs.
3. Run `tunnel-client doctor --profile <chosen-profile> --explain`, then
   `tunnel-client run --profile <chosen-profile>`. Do not claim it is connected
   until readiness and active polling are verified.
4. Go to ChatGPT **Plugins → Add custom MCP server → Connection: Tunnel**,
   select the intended tunnel, choose an appropriate auth mode for this
   *synthetic-only* demonstration, review the tools, and install the resulting
   **private** plugin.
5. In a new ChatGPT **Work** chat, select the plugin using `@` and ask:
   - "List your available research datasets."
   - "Describe the synthetic liquidity benchmark fields."
   - "Return ten development observations and their SHA-256 provenance."
6. Stop the tunnel client and local server when testing is complete.

Alternatively, a separately reviewed, isolated **public HTTPS** synthetic MCP
endpoint can be used instead of the private tunnel. A stable public HTTPS
endpoint is **required for public plugin-directory submission**; Secure MCP
Tunnel is intended for private testing only. Real datasets require per-user
authorization and reviewed OAuth before exposure.

This proof of concept has **not** created a ChatGPT plugin, opened a tunnel,
used API credentials, or deployed a public endpoint.

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
