from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.errors import ErrorCode, SkillError
from lib import coverage as cov


class CoverageLibTest(unittest.TestCase):
    def test_load_and_validate_plan_errors(self) -> None:
        with self.assertRaises(SkillError) as ctx:
            cov.load_plan_file("/tmp/does-not-exist.json")
        self.assertEqual(ctx.exception.code, ErrorCode.PLAN_FILE_INVALID)

        with tempfile.TemporaryDirectory() as td:
            bad = Path(td, "bad.json")
            bad.write_text("{", encoding="utf-8")
            with self.assertRaises(SkillError):
                cov.load_plan_file(str(bad))
            arr = Path(td, "arr.json")
            arr.write_text("[]", encoding="utf-8")
            with self.assertRaises(SkillError):
                cov.load_plan_file(str(arr))

        with self.assertRaises(SkillError):
            cov.validate_commit_entry([], require_messages=False)
        with self.assertRaises(SkillError):
            cov.validate_commit_entry({}, require_messages=False)
        with self.assertRaises(SkillError):
            cov.validate_commit_entry({"repo_path": "/x", "paths": []}, require_messages=False)
        with self.assertRaises(SkillError):
            cov.validate_commit_entry({"repo_path": "/x", "paths": ["a"], "type": "bad", "title": "", "bullets": []}, require_messages=True)
        with self.assertRaises(SkillError):
            cov.validate_commit_entry({"repo_path": "/x", "paths": ["a"], "type": "feat", "title": "", "bullets": []}, require_messages=True)
        with self.assertRaises(SkillError):
            cov.validate_commit_entry({"repo_path": "/x", "paths": ["a"], "type": "feat", "title": "ok", "bullets": [1]}, require_messages=True)

        with self.assertRaises(SkillError):
            cov.validate_plan_file({"commits": [{"repo_path": "/x", "paths": ["a"]}]}, require_messages=False)
        with self.assertRaises(SkillError):
            cov.validate_plan_file({"repo": "/x", "exclude": []}, require_messages=False)
        with self.assertRaises(SkillError):
            cov.validate_plan_file({"repo": "/x", "commits": [{"repo_path": "/x", "paths": ["a"]}], "exclude": {}}, require_messages=False)

    def test_validate_and_coverage(self) -> None:
        plan = {
            "repo": "/repo",
            "commits": [
                {"repo_path": "/repo", "paths": ["a.py"], "type": "feat", "title": "ok", "bullets": ["x"]}
            ],
            "exclude": [],
            "coverage_baseline": {
                "root_changed_files": ["a.py", "b.py"],
                "explicit_excluded_files": [],
                "submodule_changes": [{"repo_path": "/sub", "submodule_path": "vendor/x", "changed_files": ["m.py"]}],
                "required_pointer_updates": [{"submodule_path": "vendor/x"}],
            },
        }
        validated = cov.validate_plan_file(plan, require_messages=True)
        self.assertEqual(validated["repo"], "/repo")
        self.assertEqual(cov.collect_plan_paths(plan, "/repo"), ["a.py"])

        payload = cov.run_coverage_from_args(["a.py", "b.py"], ["a.py"], ["b.py"])
        self.assertTrue(payload["passed"])

        gap = cov.run_coverage_from_plan(plan)
        self.assertFalse(gap["passed"])
        self.assertEqual(gap["root_uncovered_files"], ["b.py"])
        self.assertEqual(gap["missing_pointer_updates"], ["vendor/x"])
        self.assertEqual(gap["submodule_uncovered"][0]["uncovered_files"], ["m.py"])

        ok_plan = {
            "repo": "/repo",
            "commits": [
                {"repo_path": "/repo", "paths": ["a.py"], "type": "feat", "title": "ok", "bullets": ["x"]},
                {"repo_path": "/sub", "paths": ["m.py"], "type": "chore", "title": "ok", "bullets": ["x"]},
                {"repo_path": "/repo", "paths": ["vendor/x"], "type": "chore", "title": "ok", "bullets": ["x"]},
            ],
            "exclude": ["b.py"],
            "coverage_baseline": {
                "root_changed_files": ["a.py", "b.py"],
                "explicit_excluded_files": [],
                "submodule_changes": [{"repo_path": "/sub", "submodule_path": "vendor/x", "changed_files": ["m.py"]}],
                "required_pointer_updates": [{"submodule_path": "vendor/x"}],
            },
        }
        ok_gap = cov.run_coverage_from_plan(ok_plan)
        self.assertTrue(ok_gap["passed"])

    def test_plan_paths_must_belong_to_initial_snapshot(self) -> None:
        plan = {
            "repo": "/repo",
            "commits": [
                {"repo_path": "/repo", "paths": ["a.py", "new.py"], "type": "feat", "title": "ok", "bullets": ["x"]},
                {"repo_path": "/sub", "paths": ["m.py", "later.py"], "type": "chore", "title": "ok", "bullets": ["x"]},
            ],
            "exclude": [],
            "coverage_baseline": {
                "root_changed_files": ["a.py"],
                "explicit_excluded_files": [],
                "submodule_changes": [{"repo_path": "/sub", "submodule_path": "vendor/x", "changed_files": ["m.py"]}],
                "required_pointer_updates": [{"submodule_path": "vendor/x"}],
            },
        }
        root_paths, root_invalid = cov.collect_resolved_plan_paths(plan, "/repo")
        self.assertEqual(root_paths, ["a.py"])
        self.assertEqual(root_invalid, ["new.py"])

        sub_paths, sub_invalid = cov.collect_resolved_plan_paths(plan, "/sub")
        self.assertEqual(sub_paths, ["m.py"])
        self.assertEqual(sub_invalid, ["later.py"])

        gap = cov.run_coverage_from_plan(plan)
        self.assertFalse(gap["passed"])
        self.assertEqual(gap["out_of_snapshot_root_paths"], ["new.py"])
        self.assertEqual(
            gap["out_of_snapshot_submodule_paths"],
            [{"repo_path": "/sub", "submodule_path": "vendor/x", "paths": ["later.py"]}],
        )

    def test_validate_repo_paths_duplicates_order_and_snapshot_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "a.py").write_text("one\n", encoding="utf-8")
            fp = cov.file_fingerprint(str(repo), "a.py")
            base = {
                "repo": str(repo),
                "commits": [{"repo_path": str(repo), "paths": ["a.py"], "kind": "repo", "type": "feat", "title": "ok", "bullets": []}],
                "exclude": [],
                "coverage_baseline": {
                    "root_changed_files": ["a.py"],
                    "root_fingerprints": [fp],
                    "explicit_excluded_files": [],
                    "submodule_changes": [],
                    "required_pointer_updates": [],
                },
            }
            self.assertTrue(cov.run_coverage_from_plan(base)["passed"])
            (repo / "a.py").write_text("two\n", encoding="utf-8")
            drift = cov.run_coverage_from_plan(base)
            self.assertFalse(drift["passed"])
            self.assertEqual(drift["snapshot_drift"]["root_drift"][0]["path"], "a.py")

        bad_repo = dict(base)
        bad_repo["commits"] = [{"repo_path": "/elsewhere", "paths": ["a.py"], "kind": "repo"}]
        with self.assertRaises(SkillError):
            cov.validate_plan_file(bad_repo, require_messages=False)

        dup = dict(base)
        dup["commits"] = [
            {"repo_path": str(repo), "paths": ["a.py"], "kind": "repo"},
            {"repo_path": str(repo), "paths": ["a.py"], "kind": "repo"},
        ]
        with self.assertRaises(SkillError):
            cov.validate_plan_file(dup, require_messages=False)

        wrong_order = {
            "repo": "/repo",
            "commits": [
                {"id": "submodule-pointer:vendor/x", "repo_path": "/repo", "paths": ["vendor/x"], "kind": "submodule_pointer"},
                {"id": "submodule-internal:vendor/x", "repo_path": "/repo/vendor/x", "paths": ["m.py"], "kind": "submodule_internal"},
            ],
            "exclude": [],
            "coverage_baseline": {
                "root_changed_files": [],
                "explicit_excluded_files": [],
                "submodule_changes": [{"repo_path": "/repo/vendor/x", "submodule_path": "vendor/x", "changed_files": ["m.py"]}],
                "required_pointer_updates": [{"submodule_path": "vendor/x"}],
            },
        }
        with self.assertRaises(SkillError):
            cov.validate_plan_file(wrong_order, require_messages=False)

