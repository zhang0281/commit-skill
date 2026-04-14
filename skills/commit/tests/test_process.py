from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.errors import ErrorCode, SkillError
from lib.models import CmdResult
from lib import process


class ProcessTest(unittest.TestCase):
    def test_run_cmd(self) -> None:
        result = process.run_cmd([sys.executable, "-c", "print('ok')"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_repo_root_success_and_head_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main", td], check=True, capture_output=True, text=True)
            subprocess.run(["git", "-C", td, "config", "commit.gpgsign", "false"], check=True)
            subprocess.run(["git", "-C", td, "config", "user.name", "tester"], check=True)
            subprocess.run(["git", "-C", td, "config", "user.email", "tester@example.com"], check=True)
            self.assertEqual(process.repo_root(td), td)
            self.assertFalse(process.head_exists(td))
            Path(td, "a.txt").write_text("x\n", encoding="utf-8")
            subprocess.run(["git", "-C", td, "add", "a.txt"], check=True)
            subprocess.run(["git", "-C", td, "commit", "-m", "init"], check=True, capture_output=True, text=True)
            self.assertTrue(process.head_exists(td))

    def test_repo_root_failure_and_git_get(self) -> None:
        with mock.patch.object(process, "git", return_value=CmdResult([], 1, "", "fatal")):
            with self.assertRaises(SkillError) as ctx:
                process.repo_root("/nope")
            self.assertEqual(ctx.exception.code, ErrorCode.NOT_GIT_REPO)
            self.assertEqual(process.git_get("/repo", "x"), "")

        fake = CmdResult([], 0, "value\n", "")
        with mock.patch.object(process, "git", return_value=fake) as mocked:
            self.assertEqual(process.git_get("/repo", "user.signingkey", global_scope=True), "value")
            mocked.assert_called_once()
