"""Check the public static portal without network, credentials, or browser dependencies."""

import hashlib
import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from scripts.build_portal_catalog import FIELDS, ROOT, build_catalog, serialize

PORTAL = ROOT / "portal"


class SiteParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.links = []
        self.stylesheets = []
        self.scripts = []
        self.tabs = []
        self.panels = []
        self.meta_csp = ""
        self.forms = []
        self.inline_events = []
        self.copy_targets = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if attr.get("id"):
            self.ids.add(attr["id"])
        if tag == "a":
            self.links.append(attr.get("href", ""))
        if tag == "script":
            self.scripts.append(attr.get("src"))
        if tag == "link" and attr.get("rel") == "stylesheet":
            self.stylesheets.append(attr.get("href"))
        if tag == "meta" and attr.get("http-equiv") == "Content-Security-Policy":
            self.meta_csp = attr.get("content", "")
        if tag == "form":
            self.forms.append(attr)
        if attr.get("role") == "tab":
            self.tabs.append(attr)
        if attr.get("role") == "tabpanel":
            self.panels.append(attr)
        if attr.get("data-copy-target"):
            self.copy_targets.append(attr["data-copy-target"])
        self.inline_events.extend(name for name in attr if name.lower().startswith("on"))


class PortalTests(unittest.TestCase):
    def test_catalog_is_an_exact_bounded_derivative_of_the_fixture_manifest(self):
        manifest = json.loads((ROOT / "data/synthetic-v1/manifest.json").read_text())
        catalog = json.loads((PORTAL / "catalog.json").read_text())
        self.assertEqual((PORTAL / "catalog.json").read_text(), serialize(build_catalog(ROOT)))
        self.assertEqual(catalog["dataset_id"], manifest["dataset_id"])
        self.assertEqual(catalog["venue"], "NONE")
        self.assertEqual(catalog["source_kind"], "synthetic_generated")
        self.assertEqual(catalog["api_availability"], "not_available")
        self.assertEqual(catalog["mcp_availability"], "not_available")
        self.assertIs(catalog["requires_key"], False)
        self.assertEqual(catalog["embargo_bars"], manifest["embargo_bars"])
        for name, split in catalog["splits"].items():
            original = manifest["splits"][name]
            self.assertEqual(split["rows"], original["rows"])
            self.assertEqual(split["sha256"], original["sha256"])
            fixture = ROOT / split["source_path"]
            self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), split["sha256"])
        self.assertEqual(
            [f["name"] for f in catalog["fields"]], list(FIELDS),
        )

    def test_catalog_builder_rejects_non_synthetic_or_drifted_columns(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "data/synthetic-v1"
            source.mkdir(parents=True)
            original = json.loads((ROOT / "data/synthetic-v1/manifest.json").read_text())
            (source / "development.csv").write_text(
                (ROOT / "data/synthetic-v1/development.csv").read_text()
            )
            (source / "manifest.json").write_text(json.dumps(original))
            self.assertEqual(build_catalog(root)["source_kind"], "synthetic_generated")
            original["venue"] = "PRIVATE_DB"
            (source / "manifest.json").write_text(json.dumps(original))
            with self.assertRaisesRegex(ValueError, "synthetic"):
                build_catalog(root)
            original["venue"] = "NONE"
            (source / "manifest.json").write_text(json.dumps(original))
            (source / "development.csv").write_text("timestamp,secret_column\n")
            with self.assertRaisesRegex(ValueError, "fields"):
                build_catalog(root)

    def test_page_has_content_security_policy_and_no_external_runtime(self):
        page = (PORTAL / "index.html").read_text()
        parser = SiteParser()
        parser.feed(page)
        self.assertEqual(parser.scripts, ["./app.js"])
        self.assertEqual(parser.stylesheets, ["./styles.css"])
        self.assertEqual(parser.forms, [])
        self.assertEqual(parser.inline_events, [])
        self.assertIn("default-src 'none'", parser.meta_csp)
        self.assertIn("script-src 'self'", parser.meta_csp)
        self.assertIn("connect-src 'self'", parser.meta_csp)
        self.assertNotIn("unsafe-inline", parser.meta_csp)
        self.assertNotIn("unsafe-eval", parser.meta_csp)
        self.assertIn("form-action 'none'", parser.meta_csp)
        for link in parser.links:
            self.assertTrue(
                link.startswith("#")
                or link.startswith("https://github.com/wrightpt/open-market-research-lab"),
                link,
            )
        app = (PORTAL / "app.js").read_text()
        self.assertEqual(app.count('fetch("./catalog.json"'), 1)
        for disallowed in ("XMLHttpRequest", "eval(", "new Function(", "document.write(", "innerHTML", "localStorage", "sessionStorage"):
            self.assertNotIn(disallowed, app)
        self.assertNotIn("@import", (PORTAL / "styles.css").read_text())
        self.assertNotIn("https://", app)

    def test_every_control_targets_an_accessible_panel_or_copy_source(self):
        parser = SiteParser()
        parser.feed((PORTAL / "index.html").read_text())
        self.assertEqual(len(parser.tabs), 3)
        self.assertEqual(len(parser.panels), 3)
        self.assertEqual(
            {tab["aria-controls"] for tab in parser.tabs},
            {panel["id"] for panel in parser.panels},
        )
        self.assertTrue(all(target in parser.ids for target in parser.copy_targets))
        self.assertTrue({"datasets", "workflow", "agents", "roadmap", "get-started"} <= parser.ids)

    def test_site_is_synthetic_only_and_documented_as_not_deployed(self):
        page = (PORTAL / "index.html").read_text()
        self.assertIn("SYNTHETIC RESEARCH PREVIEW", page)
        self.assertIn("No signup. No API keys.", page)
        self.assertIn("no production connectivity", page.lower())
        self.assertIn("no production", page.lower())
        self.assertNotIn("data-kubeconfig", page.lower())
        docs = (PORTAL / "README.md").read_text()
        self.assertIn("not deployed", (ROOT / "docs/PORTAL_ARCHITECTURE.md").read_text().lower())
        self.assertIn("no login form", docs.lower())
        self.assertIn("--bind 127.0.0.1", docs)
        self.assertEqual((ROOT / "portal/catalog.json").is_file(), True)


if __name__ == "__main__":
    unittest.main()
