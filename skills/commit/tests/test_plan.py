from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "commit_skill.py"


class PlanCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name)
        subprocess.run(["git", "init", "-b", "main", str(self.repo)], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "commit.gpgsign", "false"], check=True)
        (self.repo / "README.md").write_text("# demo\n", encoding="utf-8")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_plan_builds_candidate_commits(self) -> None:
        result = subprocess.run(
            ["python3", "-B", str(SCRIPT), "plan", "--repo", str(self.repo), "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["repo"], str(self.repo))
        self.assertIn("commits", payload)
        kinds = {item["kind"] for item in payload["commits"]}
        self.assertIn("repo", kinds)
        self.assertIn("README.md", payload["inventory"]["root_changed_files"])
        self.assertIn("src/app.py", payload["inventory"]["root_changed_files"])
