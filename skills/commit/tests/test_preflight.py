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

    def plan(self, paths: list[str] | None = None) -> dict[str, object]:
        paths = ["a.txt"] if paths is None else paths
        return {
            "repo": str(self.repo),
            "coverage_baseline": {
                "root_changed_files": paths,
                "required_pointer_updates": [],
                "submodule_changes": [],
            },
            "commits": [{"repo_path": str(self.repo), "paths": paths}],
        }

    def check_staged_deletion(self, regenerate: bool) -> None:
        (self.repo / "a.txt").unlink()
        subprocess.run(["git", "-C", str(self.repo), "add", "a.txt"], check=True)
        (self.repo / ".gitignore").write_text("a.txt\n", encoding="utf-8")
        if regenerate:
            (self.repo / "a.txt").write_text("regenerated  \n", encoding="utf-8")
        before = (self.repo / ".git" / "index").read_bytes()
        payload = finish_preflight(start_preflight(self.plan([".gitignore", "a.txt"])))
        self.assertTrue(payload["passed"])
        self.assertEqual((self.repo / ".git" / "index").read_bytes(), before)
        cached = subprocess.run(["git", "-C", str(self.repo), "diff", "--cached", "--name-status"], capture_output=True, text=True, check=True)
        self.assertEqual(cached.stdout, "D\ta.txt\n")
        if regenerate:
            self.assertEqual((self.repo / "a.txt").read_text(), "regenerated  \n")

    def test_preserves_staged_deletion_of_regenerated_ignored_file(self) -> None:
        self.check_staged_deletion(regenerate=True)

    def test_handles_already_staged_missing_file(self) -> None:
        self.check_staged_deletion(regenerate=False)

    def test_handles_unstaged_missing_file(self) -> None:
        (self.repo / "a.txt").unlink()
        payload = finish_preflight(start_preflight(self.plan()))
        self.assertTrue(payload["passed"])
        cached = subprocess.run(["git", "-C", str(self.repo), "diff", "--cached", "--name-only"], capture_output=True, text=True, check=True)
        self.assertEqual(cached.stdout, "")

    def test_checks_tracked_file_even_when_ignore_rule_matches(self) -> None:
        (self.repo / ".gitignore").write_text("a.txt\n", encoding="utf-8")
        (self.repo / "a.txt").write_text("bad trailing space  \n", encoding="utf-8")
        with self.assertRaises(SkillError) as ctx:
            start_preflight(self.plan())
        self.assertEqual(ctx.exception.code, ErrorCode.PREFLIGHT_FAILED)

    def test_rejects_ignored_file_without_staged_deletion(self) -> None:
        (self.repo / ".gitignore").write_text("cache.pyc\n", encoding="utf-8")
        (self.repo / "cache.pyc").write_bytes(b"cache")
        with self.assertRaises(SkillError) as ctx:
            start_preflight(self.plan(["cache.pyc"]))
        self.assertEqual(ctx.exception.code, ErrorCode.PREFLIGHT_FAILED)
        self.assertEqual(ctx.exception.details["staging_phase"], "add_existing")

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
