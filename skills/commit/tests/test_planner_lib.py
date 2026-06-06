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
        root_only = planner.root_single_commit_template("/repo", ["README.md", "src/a.py"], [], "auto")
        self.assertEqual(root_only["id"], "repo:single")
        pointer_only = planner.root_single_commit_template("/repo", [], ["vendor/x"], "auto")
        self.assertEqual(pointer_only["id"], "repo:submodule-pointers")
        mixed = planner.root_single_commit_template("/repo", ["README.md"], ["vendor/x"], "auto")
        self.assertEqual(mixed["id"], "repo:single")
        self.assertIsNone(planner.root_single_commit_template("/repo", [], [], "auto"))

    def test_build_submodule_templates_and_plan(self) -> None:
        sub = [{"path": "vendor/x", "absolute_path": "/repo/vendor/x", "dirty": True, "dirty_files": ["a.py"], "requires_pointer_update": True}]
        commits, changes, pointer_paths, pointers = planner.build_submodule_templates("/repo", sub, "signed")
        self.assertEqual(len(commits), 1)
        self.assertEqual(changes[0]["submodule_path"], "vendor/x")
        self.assertEqual(pointer_paths, ["vendor/x"])
        self.assertEqual(pointers[0]["submodule_path"], "vendor/x")

        mixed_sub = [
            {"path": "vendor/y", "absolute_path": "/repo/vendor/y", "dirty": False, "dirty_files": [], "requires_pointer_update": True},
            {"path": "vendor/z", "absolute_path": "/repo/vendor/z", "dirty": False, "dirty_files": [], "requires_pointer_update": False},
        ]
        commits2, changes2, pointer_paths2, pointers2 = planner.build_submodule_templates("/repo", mixed_sub, "signed")
        self.assertEqual(len(changes2), 0)
        self.assertEqual(pointer_paths2, ["vendor/y"])
        self.assertEqual(len(pointers2), 1)
        self.assertEqual(len(commits2), 0)

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
            self.assertEqual([item["kind"] for item in plan["commits"]], ["submodule_internal", "repo"])
