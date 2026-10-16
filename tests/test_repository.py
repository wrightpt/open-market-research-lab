"""Local policy checks complement human review; they are not a security sandbox."""

import ast
import json
import re
import sys
import unittest

from market_lab.io import ROOT


class RepositoryTests(unittest.TestCase):
    def test_runtime_is_stdlib_and_has_no_external_execution_clients(self):
        prohibited = {"subprocess", "socket", "urllib", "http", "sqlite3", "importlib", "ctypes"}
        for path in (ROOT / "market_lab").glob("*.py"):
            tree = ast.parse(path.read_text(), feature_version=(3, 11))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    modules = [node.module.split(".")[0]]
                else:
                    modules = []
                for module in modules:
                    self.assertIn(module, sys.stdlib_module_names)
                    self.assertNotIn(module, prohibited)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"eval", "exec", "__import__"})

    def test_workflow_has_read_only_hosted_pr_boundary(self):
        workflow_paths = sorted((ROOT / ".github/workflows").glob("*"))
        self.assertEqual([p.name for p in workflow_paths], ["ci.yml"])
        workflow = json.loads(workflow_paths[0].read_text())
        self.assertEqual(set(workflow["on"]), {"pull_request", "workflow_dispatch"})
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(set(workflow["jobs"]), {"stdlib", "synthetic-mcp"})
        for job in workflow["jobs"].values():
            self.assertEqual(job["runs-on"], "ubuntu-24.04")
            self.assertEqual(job["permissions"], {"contents": "read"})
            self.assertLessEqual(job["timeout-minutes"], 5)
            self.assertNotIn("environment", job)
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], r"^actions/(checkout|setup-python|setup-node)@[a-f0-9]{40}$")
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertIs(step["with"]["persist-credentials"], False)
                if "run" in step:
                    self.assertNotIn("${{", step["run"])
                    self.assertNotIn("market_lab holdout", step["run"])
                    self.assertNotIn("market_lab freeze", step["run"])
        mcp_steps = workflow["jobs"]["synthetic-mcp"]["steps"]
        self.assertEqual(
            [s["run"] for s in mcp_steps if "run" in s],
            ["npm ci --ignore-scripts --no-audit --no-fund", "npm run check"],
        )
        self.assertTrue(all(s.get("working-directory", "").startswith("integrations/synthetic-mcp")
                            for s in mcp_steps if "run" in s))
        serialized = json.dumps(workflow)
        for token in ("secrets.", "self-hosted", "pull_request_target", "workflow_run", "id-token", "write-all"):
            self.assertNotIn(token, serialized)

    def test_python_syntax_and_source_whitespace(self):
        for directory in ("market_lab", "tests"):
            for path in (ROOT / directory).glob("*.py"):
                payload = path.read_bytes()
                self.assertTrue(payload.endswith(b"\n"), path)
                self.assertNotIn(b"\r", payload, path)
                ast.parse(payload, filename=path.name, feature_version=(3, 11))
                for line in payload.splitlines():
                    self.assertEqual(line.rstrip(), line, path)
                    self.assertFalse(line.startswith(b"\t"), path)

    def test_required_documents_and_relative_links_exist(self):
        required = (
            "README.md", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md", "DATA_POLICY.md",
            "docs/ARCHITECTURE.md", "docs/CHALLENGE.md", "docs/RELEASE_GATES.md",
            "outreach/REDDIT_DRAFT.md", "outreach/FORUM_LAUNCH_CHECKLIST.md",
            ".github/pull_request_template.md",
        )
        for name in required:
            path = ROOT / name
            self.assertTrue(path.is_file(), name)
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                if "://" not in target and not target.startswith("#"):
                    self.assertTrue((path.parent / target.split("#")[0]).exists(), (name, target))
        instructions = (ROOT / "AGENTS.md").read_text()
        for term in ("Claude Code", "Codex", "OpenCode", "zero Kubernetes access"):
            self.assertIn(term, instructions)

    def test_source_tree_has_no_obvious_secrets_or_private_hostpaths(self):
        patterns = (
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b",
            r"\bgithub_pat_[A-Za-z0-9_]{60,}\b",
            r"/home/[A-Za-z0-9._-]+/", r"/Users/[A-Za-z0-9._-]+/",
            r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b",
        )
        # Worktree .git pointers and local Git metadata are not distributable source.
        paths = [p for p in ROOT.iterdir() if p.is_file() and p.name != ".git"]
        for name in ("market_lab", "tests", "docs", "data", "schemas", "submissions", "outreach", ".github", "integrations"):
            paths.extend(p for p in (ROOT / name).rglob("*") if p.is_file() and "__pycache__" not in p.parts and "node_modules" not in p.parts)
        for path in paths:
            content = path.read_text()
            for pattern in patterns:
                self.assertIsNone(re.search(pattern, content), path.relative_to(ROOT))
