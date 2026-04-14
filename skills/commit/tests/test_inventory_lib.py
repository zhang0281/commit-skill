from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.errors import ErrorCode, SkillError
from lib.models import CmdResult
from lib import inventory


class InventoryLibTest(unittest.TestCase):
    def test_path_helpers(self) -> None:
        self.assertEqual(inventory.classify_path("docs/a.md"), "docs")
        self.assertEqual(inventory.classify_path("tests/test_x.py"), "tests")
        self.assertEqual(inventory.classify_path("config/app.yaml"), "config")
        self.assertEqual(inventory.classify_path("src/main.py"), "code")
        self.assertTrue(inventory.matches_pattern("src/a.py", ["src"]))
        self.assertTrue(inventory.matches_pattern("src/a.py", ["src/*.py"]))
        self.assertFalse(inventory.matches_pattern("src/a.py", [""]))
        self.assertFalse(inventory.matches_pattern("src/a.py", ["src/*.js"]))
        filtered, excluded = inventory.filtered_paths(["src/a.py", "docs/a.md"], ["src"], ["docs"])
        self.assertEqual(filtered, ["src/a.py"])
        self.assertEqual(excluded, [])
        self.assertEqual(inventory.top_level_groups(["README.md", "src/a.py"]), {".": ["README.md"], "src": ["src/a.py"]})
        self.assertEqual(inventory.expand_targets(["src/a.py"], ["src", "none.txt"]), ["none.txt", "src/a.py"])

    def test_parse_helpers(self) -> None:
        entries = inventory.parse_status_lines(["", "R  old.py -> new.py"])
        self.assertEqual(entries[0]["path"], "new.py")
        self.assertEqual(inventory.changed_file_paths, inventory.changed_file_paths)
        self.assertEqual(inventory.parse_submodule_status_output("\n-abc vendor/x\nshort\n"), [{"prefix": "-", "sha": "abc", "path": "vendor/x"}])
        blocks = inventory.parse_named_blocks("=== a ===\n1\n=== b ===\n2\n")
        self.assertEqual(blocks, {"a": ["1"], "b": ["2"]})

    def test_parse_status_and_submodules_and_build_inventory(self) -> None:
        with mock.patch.object(inventory, "git", return_value=CmdResult([], 1, "", "boom")):
            with self.assertRaises(SkillError) as ctx:
                inventory.parse_status("/repo")
            self.assertEqual(ctx.exception.code, ErrorCode.GIT_STATUS_FAILED)

        with mock.patch.object(inventory, "parse_status", return_value=[{"path": "a.py"}]):
            self.assertEqual(inventory.changed_file_paths("/repo"), ["a.py"])

        status_map = CmdResult([], 0, " abc vendor/sub\n", "")
        dirty_map = CmdResult([], 0, "=== vendor/sub ===\n M inner.py\n", "")
        ahead_map = CmdResult([], 0, "=== vendor/sub ===\n123 commit\n", "")
        git_results = [status_map, dirty_map, ahead_map]
        with mock.patch.object(inventory, "git", side_effect=git_results):
            status_entries, dirty_blocks, ahead_blocks = inventory.collect_submodule_maps("/repo")
            self.assertIn("vendor/sub", status_entries)
            self.assertIn("vendor/sub", dirty_blocks)
            self.assertIn("vendor/sub", ahead_blocks)

        with mock.patch.object(inventory, "git", return_value=CmdResult([], 2, "", "bad submodule")):
            with self.assertRaises(SkillError) as ctx:
                inventory.collect_submodule_maps("/repo")
            self.assertEqual(ctx.exception.code, ErrorCode.SUBMODULE_SCAN_FAILED)

        state = {"status_map": {"vendor/sub": {"prefix": "-", "sha": "abc", "path": "vendor/sub"}}, "dirty_blocks": {"vendor/sub": [" M inner.py"]}, "ahead_blocks": {"vendor/sub": ["123 commit"]}}
        record = inventory.build_submodule_record("/repo", "vendor/sub", state)
        self.assertTrue(record["dirty"])
        self.assertTrue(record["requires_pointer_update"])

        with mock.patch.object(inventory, "parse_status", return_value=[{"path": "README.md", "category": "docs"}, {"path": "vendor/sub", "category": "code"}]), \
             mock.patch.object(inventory, "detect_signing", return_value={"suggested_sign_mode": "signed"}), \
             mock.patch.object(inventory, "collect_submodules", return_value=[{"path": "vendor/sub"}]), \
             mock.patch.object(inventory, "git", return_value=CmdResult([], 0, "main\n", "")), \
             mock.patch.object(inventory, "head_exists", return_value=True):
            built = inventory.build_inventory("/repo", [], [], "auto", "auto")
            self.assertEqual(built["root_changed_files"], ["README.md"])
            self.assertEqual(built["categories"]["docs"], ["README.md"])
