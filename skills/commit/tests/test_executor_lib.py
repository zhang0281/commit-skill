from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.errors import ErrorCode, SkillError
from lib.models import CmdResult, CommitPlan, CommitRun
from lib import executor


class ExecutorLibTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = CommitPlan(repo_path="/repo", files=["a.py"], commit_type="feat", title="x", bullets=["b"], requested_sign_mode="auto", effective_sign_mode="signed")

    def test_stage_and_attempt(self) -> None:
        with mock.patch.object(executor, "git", return_value=CmdResult([], 0, "", "")):
            executor.stage_files(self.plan, {})
        with mock.patch.object(executor, "git", return_value=CmdResult([], 1, "", "boom")):
            with self.assertRaises(SkillError) as ctx:
                executor.stage_files(self.plan, {})
            self.assertEqual(ctx.exception.code, ErrorCode.GIT_ADD_FAILED)

        with mock.patch.object(executor, "git", return_value=CmdResult([], 0, "", "")) as mocked:
            _, attempt = executor.commit_attempt(self.plan, {}, "fallback")
            self.assertIn("commit.gpgsign=false", attempt["command"])
            mocked.assert_called_once()
        with mock.patch.object(executor, "git", return_value=CmdResult([], 0, "", "")) as mocked:
            _, attempt = executor.commit_attempt(self.plan, {}, "signed")
            self.assertIn("-S", attempt["command"])
            mocked.assert_called_once()

    def test_finalize_and_commit_paths(self) -> None:
        ok_run = CommitRun(CmdResult([], 0, "", ""), [], False, False)
        self.assertIs(executor.finalize_commit_result(self.plan, ok_run), ok_run)

        required = CommitRun(CmdResult([], 1, "", "err"), [], False, False)
        self.plan.requested_sign_mode = "signed"
        with self.assertRaises(SkillError) as ctx:
            executor.finalize_commit_result(self.plan, required)
        self.assertEqual(ctx.exception.code, ErrorCode.GPG_REQUIRED_FAILED)

        self.plan.requested_sign_mode = "auto"
        fallback = CommitRun(CmdResult([], 1, "", "err"), [], False, True)
        with self.assertRaises(SkillError) as ctx:
            executor.finalize_commit_result(self.plan, fallback)
        self.assertEqual(ctx.exception.code, ErrorCode.GPG_AUTO_FAILED)

        generic = CommitRun(CmdResult([], 1, "", "err"), [], False, False)
        with self.assertRaises(SkillError) as ctx:
            executor.finalize_commit_result(self.plan, generic)
        self.assertEqual(ctx.exception.code, ErrorCode.GIT_COMMIT_FAILED)

    def test_signed_unsigned_run_commit_and_apply_plan(self) -> None:
        with mock.patch.object(executor, "commit_attempt", return_value=(CmdResult([], 0, "", ""), {"command": []})):
            run = executor.unsigned_commit(self.plan, {})
            self.assertFalse(run.signed)

        with mock.patch.object(executor, "commit_attempt", return_value=(CmdResult([], 0, "", ""), {"command": []})):
            run = executor.signed_commit(self.plan, {})
            self.assertTrue(run.signed)

        with mock.patch.object(executor, "commit_attempt", side_effect=[(CmdResult([], 1, "", "failed to sign the data"), {"command": ["signed"]}), (CmdResult([], 0, "", ""), {"command": ["fallback"]})]):
            run = executor.signed_commit(self.plan, {})
            self.assertTrue(run.fallback_used)

        self.plan.requested_sign_mode = "auto"
        with mock.patch.object(executor, "commit_attempt", return_value=(CmdResult([], 1, "", "plain error"), {"command": ["signed"]})):
            with self.assertRaises(SkillError) as ctx:
                executor.signed_commit(self.plan, {})
            self.assertEqual(ctx.exception.code, ErrorCode.GIT_COMMIT_FAILED)

        self.plan.requested_sign_mode = "signed"
        with mock.patch.object(executor, "commit_attempt", return_value=(CmdResult([], 1, "", "failed to sign the data"), {"command": ["signed"]})):
            with self.assertRaises(SkillError) as ctx:
                executor.signed_commit(self.plan, {})
            self.assertEqual(ctx.exception.code, ErrorCode.GPG_REQUIRED_FAILED)

        self.plan.effective_sign_mode = "unsigned"
        with mock.patch.object(executor, "current_env", return_value={}), \
             mock.patch.object(executor, "stage_files"), \
             mock.patch.object(executor, "unsigned_commit", return_value=CommitRun(CmdResult([], 0, "", ""), [], False, False)):
            run = executor.run_commit(self.plan)
            self.assertFalse(run.signed)

        self.plan.effective_sign_mode = "signed"
        with mock.patch.object(executor, "current_env", return_value={}), \
             mock.patch.object(executor, "stage_files"), \
             mock.patch.object(executor, "signed_commit", return_value=CommitRun(CmdResult([], 0, "", ""), [], True, False)):
            run = executor.run_commit(self.plan)
            self.assertTrue(run.signed)

        bad_plan = {"repo": "/repo"}
        with mock.patch.object(executor, "run_coverage_from_plan", return_value={"passed": False}):
            with self.assertRaises(SkillError) as ctx:
                executor.apply_plan(bad_plan, {"suggested_sign_mode": "signed"})
            self.assertEqual(ctx.exception.code, ErrorCode.COVERAGE_GAP)

        good_plan = {"repo": "/repo", "requested": {"sign_mode": "auto"}, "commits": [{"id": "1", "repo_path": "/repo", "paths": ["a.py"], "type": "feat", "title": "x", "bullets": ["b"], "sign_mode": "auto"}]}
        with mock.patch.object(executor, "run_coverage_from_plan", return_value={"passed": True}), \
             mock.patch.object(executor, "resolve_sign_mode", side_effect=lambda mode, ctx: "signed" if mode == "auto" else mode), \
             mock.patch.object(executor, "run_commit", return_value=CommitRun(CmdResult([], 0, "done", ""), [{"command": []}], True, False)), \
             mock.patch.object(executor, "git", return_value=CmdResult([], 0, "deadbeef\n", "")):
            payload = executor.apply_plan(good_plan, {"suggested_sign_mode": "signed"})
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["results"][0]["sha"], "deadbeef")
