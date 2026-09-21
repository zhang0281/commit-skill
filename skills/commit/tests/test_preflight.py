from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.errors import ErrorCode, SkillError
from lib.preflight import finish_preflight, start_preflight


class PreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name)
        subprocess.run(["git", "init", "-b", "main", str(self.repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        (self.repo / "a.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "a.txt"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "init"], check=True, capture_output=True)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def plan(self) -> dict[str, object]:
        return {
            "repo": str(self.repo),
            "coverage_baseline": {
                "root_changed_files": ["a.txt"],
                "required_pointer_updates": [],
                "submodule_changes": [],
            },
            "commits": [{"repo_path": str(self.repo), "paths": ["a.txt"]}],
        }

    def test_runs_configured_command_and_diff_check_without_touching_index(self) -> None:
        (self.repo / "a.txt").write_text("changed\n", encoding="utf-8")
        (self.repo / ".commit-skill.json").write_text(
            json.dumps({"preflight": {"commands": [{"name": "ok", "argv": ["python3", "-c", "print('ok')"]}]}}),
            encoding="utf-8",
        )
        run = start_preflight(self.plan())
        payload = finish_preflight(run)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["tests"][0]["stdout"].strip(), "ok")
        cached = subprocess.run(["git", "-C", str(self.repo), "diff", "--cached", "--name-only"], capture_output=True, text=True, check=True)
        self.assertEqual(cached.stdout, "")

    def test_rejects_whitespace_error(self) -> None:
        (self.repo / "a.txt").write_text("bad trailing space  \n", encoding="utf-8")
        with self.assertRaises(SkillError) as ctx:
            start_preflight(self.plan())
        self.assertEqual(ctx.exception.code, ErrorCode.PREFLIGHT_FAILED)

    def test_rejects_malformed_preflight_config(self) -> None:
        (self.repo / "a.txt").write_text("changed\n", encoding="utf-8")
        (self.repo / ".commit-skill.json").write_text(json.dumps({"preflight": []}), encoding="utf-8")
        with self.assertRaises(SkillError) as ctx:
            start_preflight(self.plan())
        self.assertEqual(ctx.exception.code, ErrorCode.PREFLIGHT_FAILED)
