# Developer portal prototype

This is a **static, synthetic-only** developer website, not an authenticated
product. It can be reviewed offline before the Kubernetes/Vault security audit
finishes. It contains **no login form, key issuance, database connection, hosted
MCP endpoint, third-party JavaScript, analytics, or registration service**.

## Preview on your own machine

From the repository root:

```sh
python3 scripts/build_portal_catalog.py --check
python3 -m http.server 8765 --bind 127.0.0.1 --directory portal
```

Open `http://127.0.0.1:8765` in your browser. The server binds to loopback only.
Stop it with Ctrl+C. Do not forward port 8765 outside your workstation.

The only browser fetch is same-origin `catalog.json`, which is deterministically
generated from `data/synthetic-v1/manifest.json`. The catalog intentionally has
no private DB/table names and cannot resolve real venue datasets.

## Reproduce the static catalog

```sh
python3 scripts/build_portal_catalog.py --write  # only when the manifest changes
python3 scripts/build_portal_catalog.py --check
python3 -m unittest discover -s tests -v
```

The builder is Python stdlib only, fails closed on a non-synthetic venue, checks
CSV header semantics, and copies the exact manifest row counts / SHA-256 hashes.
The checked-in development and holdout fixtures remain unchanged.

## Future publication

The static site could be hosted under a separately approved GitHub Pages path
or behind a dedicated static site. **Do not enable Pages, publish a custom
domain, introduce client authentication, or connect to internal services as
part of this PR.** Review the eventual public URL and deployment permissions
before publication. The current site is a local preview.

## Accessibility, security, and limitations

- Semantic HTML, keyboard-driven agent tabs, labelled filter input and copy
  feedback; responsive layout and reduced-motion support.
- Content Security Policy allows only self-hosted script, stylesheet, images and
  same-origin catalog fetches. No externally hosted resources.
- All catalog fields render with `textContent` rather than HTML injection.
- Buttons offering downloads/open-source code link only to the real public
  repository. No fake signup, simulated key, or future service hostname is shown.
- The terminal and metrics are illustrative of the deterministic test suite,
  **not live market profitability or data service availability**.
- Only one dataset (`synthetic-liquidity-v1`) exists in the catalog. Real
  historical data and OAuth-based MCP depend on separate release gates.

See [the product architecture proposal](../docs/PORTAL_ARCHITECTURE.md).
