from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.errors import ErrorCode, SkillError
from lib import cli


class CliLibTest(unittest.TestCase):
    def test_maybe_write_output_and_build_parser(self) -> None:
        with tempfile.TemporaryDirectory() as td, mock.patch("sys.stdout", new_callable=io.StringIO) as buf:
            out = Path(td, "out.json")
            cli.maybe_write_output({"ok": True}, str(out))
            self.assertTrue(out.exists())
            self.assertIn('"ok": true', buf.getvalue())
        parser = cli.build_parser()
        args = parser.parse_args(["inventory", "--repo", "/tmp/x"])
        self.assertEqual(args.command, "inventory")
        args2 = parser.parse_args(["commit", "--repo", "/tmp/x", "--file", "a.py", "--type", "feat", "--title", "x"])
        self.assertEqual(args2.command, "commit")

    def test_command_functions(self) -> None:
        ns = argparse.Namespace(repo="/repo", include=[], exclude=[], split_mode="auto", sign_mode="auto", out=None, json=True)
        with mock.patch.object(cli, "repo_root", return_value="/repo"), \
             mock.patch.object(cli, "build_inventory", return_value={"x": 1}), \
             mock.patch.object(cli, "maybe_write_output") as writer:
            self.assertEqual(cli.command_inventory(ns), 0)
            writer.assert_called()

        with mock.patch.object(cli, "repo_root", return_value="/repo"), \
             mock.patch.object(cli, "build_plan", return_value={"commits": []}), \
             mock.patch.object(cli, "maybe_write_output"):
            self.assertEqual(cli.command_plan(ns), 0)

        cov_args = argparse.Namespace(plan_file=None, repo="/repo", planned=["a.py"], exclude=[], out=None, json=True)
        with mock.patch.object(cli, "repo_root", return_value="/repo"), \
             mock.patch.object(cli, "changed_file_paths", return_value=["a.py"]), \
             mock.patch.object(cli, "run_coverage_from_args", return_value={"passed": True}), \
             mock.patch.object(cli, "maybe_write_output"):
            self.assertEqual(cli.command_coverage(cov_args), 0)

        cov_plan_args = argparse.Namespace(plan_file="/tmp/p.json", repo=None, planned=[], exclude=[], out=None, json=True)
        with mock.patch.object(cli, "load_plan_file", return_value={"repo": "/repo", "commits": [{"repo_path": "/repo", "paths": ["a"], "type": "feat", "title": "x", "bullets": []}], "exclude": []}), \
             mock.patch.object(cli, "validate_plan_file", side_effect=lambda data, require_messages=False: data), \
             mock.patch.object(cli, "run_coverage_from_plan", return_value={"passed": False}), \
             mock.patch.object(cli, "maybe_write_output"):
            self.assertEqual(cli.command_coverage(cov_plan_args), int(ErrorCode.COVERAGE_GAP))

        args = argparse.Namespace(plan_file="/tmp/p.json", repo="/repo2", sign_mode="auto", out=None, json=True)
        with mock.patch.object(cli, "load_plan_file", return_value={"repo": "/repo1", "commits": [{"repo_path": "/repo1", "paths": ["a"], "type": "feat", "title": "x", "bullets": []}], "exclude": []}), \
             mock.patch.object(cli, "validate_plan_file", side_effect=lambda data, require_messages=False: data), \
             mock.patch.object(cli, "repo_root", return_value="/repo2"):
            with self.assertRaises(SkillError):
                cli.command_apply_plan(args)

        commit_args = argparse.Namespace(repo="/repo", file=["a.py"], type="feat", title="x", bullet=["b"], sign_mode="auto", dry_run=True, out=None, json=True)
        with mock.patch.object(cli, "repo_root", return_value="/repo"), \
             mock.patch.object(cli, "changed_file_paths", return_value=["a.py"]), \
             mock.patch.object(cli, "detect_signing", return_value={"suggested_sign_mode": "signed"}), \
             mock.patch.object(cli, "maybe_write_output"):
            self.assertEqual(cli.command_commit(commit_args), 0)

        commit_args2 = argparse.Namespace(repo="/repo", file=["a.py"], type="feat", title="x", bullet=["b"], sign_mode="auto", dry_run=False, out=None, json=True)
        with mock.patch.object(cli, "repo_root", return_value="/repo"), \
             mock.patch.object(cli, "changed_file_paths", return_value=["a.py"]), \
             mock.patch.object(cli, "detect_signing", return_value={"suggested_sign_mode": "signed"}), \
             mock.patch.object(cli, "apply_plan", return_value={"ok": True}), \
             mock.patch.object(cli, "maybe_write_output") as writer:
            self.assertEqual(cli.command_commit(commit_args2), 0)
            writer.assert_called()

        with mock.patch.object(cli, "changed_file_paths", return_value=["a.py"]):
            plan = cli.build_manual_commit_plan("/repo", commit_args)
        self.assertEqual(plan["commits"][0]["paths"], ["a.py"])

    def test_main_error_handler(self) -> None:
        fake_args = argparse.Namespace(func=lambda: None, out=None)
        fake_parser = mock.Mock()
        fake_parser.parse_args.return_value = argparse.Namespace(
            func=lambda args: (_ for _ in ()).throw(SkillError(ErrorCode.INVALID_ARGUMENT, "bad")),
            out=None,
        )
        with mock.patch.object(cli, "build_parser", return_value=fake_parser), \
             mock.patch.object(cli, "maybe_write_output") as writer:
            rc = cli.main()
            self.assertEqual(rc, int(ErrorCode.INVALID_ARGUMENT))
            writer.assert_called()
