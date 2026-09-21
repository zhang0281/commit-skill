from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import postflight


class PostflightTest(unittest.TestCase):
    def test_reports_new_and_mutated_post_snapshot_paths(self) -> None:
        plan = {
            "repo": "/repo",
            "commits": [{"repo_path": "/repo", "paths": ["a.py", "drift.py"]}],
        }
        initial = {
            "/repo\0a.py": {"sha256": "dirty"},
            "/repo\0drift.py": {"sha256": "before"},
            "/repo\0late.py": {"sha256": "before"},
        }
        inventory = {
            "repo": "/repo",
            "branch": "main",
            "changed_files": ["a.py", "drift.py", "late.py", "new.py"],
            "root_changed_files": ["a.py", "drift.py", "late.py", "new.py"],
            "submodules": [],
        }
        final = {
            "/repo\0a.py": {"sha256": "dirty"},
            "/repo\0drift.py": {"sha256": "after"},
            "/repo\0late.py": {"sha256": "after"},
            "/repo\0new.py": {"sha256": "new"},
        }
        with mock.patch.object(postflight, "build_inventory", return_value=inventory), \
             mock.patch.object(postflight, "capture_dirty_state", return_value=final):
            payload = postflight.build_postflight(plan, initial)
        reasons = {item["path"]: item["reason"] for item in payload["post_snapshot_changes"]}
        self.assertEqual(reasons["a.py"], "planned_path_remains_dirty")
        self.assertEqual(reasons["drift.py"], "content_changed_after_snapshot")
        self.assertEqual(reasons["late.py"], "content_changed_after_snapshot")
        self.assertEqual(reasons["new.py"], "new_path_after_snapshot")
        self.assertFalse(payload["clean"])
