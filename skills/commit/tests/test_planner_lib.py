from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import planner


class PlannerLibTest(unittest.TestCase):
    def test_templates_and_builders(self) -> None:
        tpl = planner.repo_commit_template("id", "/repo", ["a.py"], "docs", "auto")
        self.assertEqual(tpl["type_hint"], "docs")
        self.assertEqual(planner.submodule_internal_template({"path": "vendor/x", "absolute_path": "/repo/vendor/x", "dirty_files": ["a.py"]}, "auto")["kind"], "submodule_internal")
        self.assertEqual(planner.submodule_pointer_template("/repo", {"path": "vendor/x"}, "auto")["kind"], "submodule_pointer")

        inventory = {"root_changed_files": ["README.md", "src/a.py"], "categories": {"docs": ["README.md"], "tests": [], "config": [], "code": ["src/a.py"]}}
        self.assertEqual(len(planner.build_repo_commit_templates("/repo", inventory, "single", "auto")), 1)
        split = planner.build_repo_commit_templates("/repo", inventory, "split", "auto")
        self.assertGreaterEqual(len(split), 2)
        self.assertEqual(planner.build_repo_commit_templates("/repo", {"root_changed_files": [], "categories": {"docs": [], "tests": [], "config": [], "code": []}}, "auto", "auto"), [])

    def test_build_submodule_templates_and_plan(self) -> None:
        sub = [{"path": "vendor/x", "absolute_path": "/repo/vendor/x", "dirty": True, "dirty_files": ["a.py"], "requires_pointer_update": True}]
        commits, changes, pointers = planner.build_submodule_templates("/repo", sub, "signed")
        self.assertEqual(len(commits), 2)
        self.assertEqual(changes[0]["submodule_path"], "vendor/x")
        self.assertEqual(pointers[0]["submodule_path"], "vendor/x")

        fake_inventory = {
            "branch": "main",
            "sign_context": {"suggested_sign_mode": "signed"},
            "explicit_excluded_files": ["docs"],
            "root_changed_files": ["README.md"],
            "categories": {"docs": ["README.md"], "tests": [], "config": [], "code": []},
            "submodules": sub,
        }
        with mock.patch.object(planner, "build_inventory", return_value=fake_inventory), mock.patch.object(planner, "resolve_sign_mode", return_value="signed"):
            plan = planner.build_plan("/repo", [], [], "auto", "auto")
            self.assertEqual(plan["repo"], "/repo")
            kinds = {item["kind"] for item in plan["commits"]}
            self.assertIn("repo", kinds)
            self.assertIn("submodule_internal", kinds)
            self.assertIn("submodule_pointer", kinds)
