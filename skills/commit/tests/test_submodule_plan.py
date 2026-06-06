from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "commit_skill.py"


class SubmodulePlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.parent = Path(self.tempdir.name) / "parent"
        self.child = Path(self.tempdir.name) / "child"
        self.parent.mkdir()
        self.child.mkdir()

        subprocess.run(["git", "init", "-b", "main", str(self.child)], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(self.child), "config", "commit.gpgsign", "false"], check=True)
        subprocess.run(["git", "-C", str(self.child), "config", "user.name", "tester"], check=True)
        subprocess.run(["git", "-C", str(self.child), "config", "user.email", "tester@example.com"], check=True)
        (self.child / "module.txt").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.child), "add", "module.txt"], check=True)
        subprocess.run(["git", "-C", str(self.child), "commit", "-m", "init child"], check=True, capture_output=True, text=True)

        subprocess.run(["git", "init", "-b", "main", str(self.parent)], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(self.parent), "config", "commit.gpgsign", "false"], check=True)
        subprocess.run(["git", "-C", str(self.parent), "config", "user.name", "tester"], check=True)
        subprocess.run(["git", "-C", str(self.parent), "config", "user.email", "tester@example.com"], check=True)
        subprocess.run([
            "git", "-C", str(self.parent), "-c", "protocol.file.allow=always", "submodule", "add", str(self.child), "vendor/child"
        ], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(self.parent), "commit", "-m", "add submodule"], check=True, capture_output=True, text=True)

        (self.parent / "vendor/child/module.txt").write_text("hello world\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_plan_detects_submodule_internal_and_pointer(self) -> None:
        result = subprocess.run(
            ["python3", "-B", str(SCRIPT), "plan", "--repo", str(self.parent), "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["commits"]), 2)
        self.assertEqual(payload["commits"][0]["kind"], "submodule_internal")
        self.assertEqual(payload["commits"][1]["kind"], "repo")
        self.assertEqual(payload["commits"][1]["paths"], ["vendor/child"])
        self.assertEqual(payload["commits"][1]["id"], "repo:submodule-pointers")

    def test_exclude_submodule_path(self) -> None:
        result = subprocess.run(
            ["python3", "-B", str(SCRIPT), "plan", "--repo", str(self.parent), "--exclude", "vendor/child", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["commits"], [])
        self.assertEqual(payload["coverage_baseline"]["submodule_changes"], [])
        self.assertEqual(payload["coverage_baseline"]["required_pointer_updates"], [])
        self.assertEqual(payload["coverage_baseline"]["excluded_submodules"][0]["path"], "vendor/child")
