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
            cli.write_json_file({"x": 1}, str(out))
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), {"x": 1})
            cli.write_json_file({"x": 2}, None)
            self.assertIn("commit-plan-", cli.default_plan_file("/repo/path"))
            self.assertEqual(cli.default_plan_file("/repo/path"), cli.default_plan_file("/repo/path"))
        parser = cli.build_parser()
        args = parser.parse_args(["inventory", "--repo", "/tmp/x"])
        self.assertEqual(args.command, "inventory")
        args_doctor = parser.parse_args(["doctor", "--json"])
        self.assertEqual(args_doctor.command, "doctor")
        self.assertFalse(args_doctor.probe)
        args_doctor_probe = parser.parse_args(["doctor", "--probe", "--json"])
        self.assertTrue(args_doctor_probe.probe)
        args2 = parser.parse_args(["commit", "--repo", "/tmp/x", "--file", "a.py", "--type", "feat", "--title", "x"])
        self.assertEqual(args2.command, "commit")
        args3 = parser.parse_args(["plan", "--repo", "/tmp/x", "--summary-only"])
        self.assertTrue(args3.summary_only)
        args_prepare = parser.parse_args(["prepare", "--repo", "/tmp/x"])
        self.assertEqual(args_prepare.command, "prepare")
        args_fast = parser.parse_args(["fast-commit", "--repo", "/tmp/x", "--messages-file", "/tmp/commit-messages-Ab12Cd.json"])
        self.assertEqual(args_fast.command, "fast-commit")
        args_session = parser.parse_args(["commit-session", "--repo", "/tmp/x"])
        self.assertEqual(args_session.command, "commit-session")
        self.assertFalse(args_session.require_custom_model)
        args_session_custom = parser.parse_args(["commit-session", "--repo", "/tmp/x", "--require-custom-model"])
        self.assertTrue(args_session_custom.require_custom_model)
        args4 = parser.parse_args(["message-template", "--plan-file", "/tmp/p.json"])
        self.assertEqual(args4.command, "message-template")

        summary = cli.plan_summary(
            {
                "ok": True,
                "error_code": "OK",
                "exit_code": 0,
                "repo": "/repo",
                "branch": "main",
                "requested": {"split_mode": "auto", "sign_mode": "auto"},
                "sign_context": {"suggested_sign_mode": "signed"},
                "inventory": {
                    "changed_files": ["a.py", "b.py"],
                    "root_changed_files": ["a.py"],
                    "submodules": [{"path": "sub"}],
                    "top_level_groups": {"src": ["a.py"]},
                },
                "commits": [
                    {"id": "1", "kind": "repo", "category": "code", "repo_path": "/repo", "paths": ["a.py"], "type_hint": "feat", "title_hint": "x"}
                ],
            },
            "/tmp/plan.json",
        )
        self.assertEqual(summary["plan_file"], "/tmp/plan.json")
        self.assertEqual(summary["candidate_count"], 1)
        self.assertTrue(summary["message_only"])
        self.assertFalse(summary["plan_editing_allowed"])

    def test_command_functions(self) -> None:
        ns = argparse.Namespace(repo="/repo", include=[], exclude=[], split_mode="auto", sign_mode="auto", out=None, json=True)
        with mock.patch.object(cli, "repo_root", return_value="/repo"), \
             mock.patch.object(cli, "build_inventory", return_value={"x": 1}), \
             mock.patch.object(cli, "maybe_write_output") as writer:
            self.assertEqual(cli.command_inventory(ns), 0)
            writer.assert_called()

        with mock.patch.object(cli, "doctor_report", return_value={"mode": "existing", "active": False}), \
             mock.patch.object(cli, "maybe_write_output") as writer:
            self.assertEqual(cli.command_doctor(argparse.Namespace(out=None, json=True)), 0)
            writer.assert_called_once()

        with mock.patch.object(cli, "doctor_report", return_value={"mode": "existing", "active": False}) as doctor, \
             mock.patch.object(cli, "probe_model") as probe, \
             mock.patch.object(cli, "maybe_write_output") as writer:
            self.assertEqual(cli.command_doctor(argparse.Namespace(out=None, json=True, probe=True)), 0)
            probe.assert_not_called()
            self.assertEqual(writer.call_args.args[0]["config"]["probe"]["status"], "skipped")
            doctor.assert_called_once()

        custom_report = {"mode": "custom-api", "active": True}
        model_config = mock.sentinel.model_config
        with mock.patch.object(cli, "doctor_report", return_value=custom_report), \
             mock.patch.object(cli, "require_usable_model_config", return_value=model_config), \
             mock.patch.object(cli, "probe_model", return_value={"status": "passed", "response": "ok"}) as probe, \
             mock.patch.object(cli, "maybe_write_output") as writer:
            self.assertEqual(cli.command_doctor(argparse.Namespace(out=None, json=True, probe=True)), 0)
            probe.assert_called_once_with(model_config)
            self.assertEqual(writer.call_args.args[0]["config"]["probe"]["status"], "passed")

        probe_error = SkillError(ErrorCode.MODEL_REQUEST_FAILED, "严格响应失败", {"response": "OK"})
        with mock.patch.object(cli, "doctor_report", return_value={"mode": "custom-api", "active": True}), \
             mock.patch.object(cli, "require_usable_model_config", return_value=model_config), \
             mock.patch.object(cli, "probe_model", side_effect=probe_error):
            with self.assertRaises(SkillError) as context:
                cli.command_doctor(argparse.Namespace(out=None, json=True, probe=True))
        self.assertEqual(context.exception.code, ErrorCode.MODEL_REQUEST_FAILED)
        self.assertEqual(context.exception.details["probe"]["status"], "failed")

        with mock.patch.object(cli, "doctor_report", return_value={"mode": "custom-api", "active": False}):
            with self.assertRaises(SkillError) as context:
                cli.command_doctor(argparse.Namespace(out=None, json=True))
            self.assertEqual(context.exception.code, ErrorCode.MODEL_CONFIG_INVALID)

        with mock.patch.object(cli, "require_usable_model_config", return_value=None):
            with self.assertRaises(SkillError) as context:
                cli.command_commit_session(
                    argparse.Namespace(
                        require_custom_model=True,
                        repo="/repo",
                        plan_file=None,
                        include=[],
                        exclude=[],
                        split_mode="auto",
                        sign_mode="auto",
                        out=None,
                        json=True,
                    )
                )
        self.assertEqual(context.exception.code, ErrorCode.MODEL_CONFIG_INVALID)

        with mock.patch.object(cli, "repo_root", return_value="/repo"), \
             mock.patch.object(cli, "build_plan", return_value={"commits": [], "inventory": {"changed_files": [], "root_changed_files": [], "submodules": [], "top_level_groups": {}}, "repo": "/repo", "branch": "main", "requested": {"split_mode": "auto", "sign_mode": "auto"}, "sign_context": {}, "ok": True, "error_code": "OK", "exit_code": 0}), \
             mock.patch.object(cli, "maybe_write_output") as write_out, \
             mock.patch.object(cli, "write_json_file") as write_json:
            self.assertEqual(cli.command_plan(ns), 0)
            write_out.assert_called_once()
            write_json.assert_called_once()

        ns_prepare = argparse.Namespace(repo="/repo", include=[], exclude=[], split_mode="auto", sign_mode="auto", out=None, json=True)
        with mock.patch.object(cli, "repo_root", return_value="/repo"), \
             mock.patch.object(cli, "build_plan", return_value={"commits": [], "inventory": {"changed_files": [], "root_changed_files": [], "submodules": [], "top_level_groups": {}}, "repo": "/repo", "branch": "main", "requested": {"split_mode": "auto", "sign_mode": "auto"}, "sign_context": {}, "ok": True, "error_code": "OK", "exit_code": 0}), \
             mock.patch.object(cli, "build_message_template", return_value={"mode": "message-only"}), \
             mock.patch.object(cli, "maybe_write_output") as write_out, \
             mock.patch.object(cli, "write_json_file") as write_json:
            self.assertEqual(cli.command_prepare(ns_prepare), 0)
            write_out.assert_called_once()
            write_json.assert_called_once()

        ns_fast = argparse.Namespace(
            repo="/repo",
            messages_file="/tmp/commit-messages-Ab12Cd.json",
            plan_file="/tmp/plan.json",
            include=[],
            exclude=[],
            split_mode="auto",
            sign_mode="auto",
            out=None,
            json=True,
        )
        ns_fast_same_path = argparse.Namespace(**{**vars(ns_fast), "plan_file": "/tmp/commit-messages-Ab12Cd.json"})
        with mock.patch.object(cli, "repo_root", return_value="/repo"):
            with self.assertRaises(SkillError) as ctx:
                cli.command_fast_commit(ns_fast_same_path)
            self.assertEqual(ctx.exception.code, ErrorCode.INVALID_ARGUMENT)

        ns_fast_bad_path = argparse.Namespace(**{**vars(ns_fast), "messages_file": "/tmp/messages.json"})
        with mock.patch.object(cli, "repo_root", return_value="/repo"):
            with self.assertRaises(SkillError) as ctx:
                cli.command_fast_commit(ns_fast_bad_path)
            self.assertEqual(ctx.exception.code, ErrorCode.INVALID_ARGUMENT)

        with mock.patch.object(cli, "repo_root", return_value="/repo"), \
             mock.patch.object(cli, "build_snapshot_plan", return_value={"repo": "/repo", "commits": [], "exclude": [], "inventory": {}}), \
             mock.patch.object(cli, "validate_plan_file", side_effect=lambda data, require_messages=False: data), \
             mock.patch.object(cli, "load_message_file", return_value={"commits": []}), \
             mock.patch.object(cli, "merge_message_file", return_value={"repo": "/repo", "commits": []}), \
             mock.patch.object(cli, "detect_signing", return_value={"suggested_sign_mode": "unsigned"}), \
             mock.patch.object(cli, "capture_dirty_state", return_value={}), \
             mock.patch.object(cli, "start_preflight", return_value=mock.Mock()), \
             mock.patch.object(cli, "apply_with_session_gates", return_value={"ok": True}), \
             mock.patch.object(cli, "apply_plan", return_value={"ok": True}), \
             mock.patch.object(cli, "maybe_write_output") as write_out:
            self.assertEqual(cli.command_fast_commit(ns_fast), 0)
            write_out.assert_called_once()

        ns_summary = argparse.Namespace(repo="/repo", include=[], exclude=[], split_mode="auto", sign_mode="auto", out="/tmp/plan.json", json=True, summary_only=True)
        with mock.patch.object(cli, "repo_root", return_value="/repo"), \
             mock.patch.object(cli, "build_plan", return_value={"commits": [], "inventory": {"changed_files": [], "root_changed_files": [], "submodules": [], "top_level_groups": {}}, "repo": "/repo", "branch": "main", "requested": {"split_mode": "auto", "sign_mode": "auto"}, "sign_context": {}, "ok": True, "error_code": "OK", "exit_code": 0}), \
             mock.patch.object(cli, "maybe_write_output") as write_out, \
             mock.patch.object(cli, "write_json_file") as write_json:
            self.assertEqual(cli.command_plan(ns_summary), 0)
            write_out.assert_called_once()
            write_json.assert_called_once()

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

        cov_plan_msg_args = argparse.Namespace(plan_file="/tmp/p.json", messages_file="/tmp/m.json", repo=None, planned=[], exclude=[], out=None, json=True)
        with mock.patch.object(cli, "load_plan_file", return_value={"repo": "/repo", "commits": [{"repo_path": "/repo", "paths": ["a"], "type": "", "title": "", "bullets": []}], "exclude": []}), \
             mock.patch.object(cli, "validate_plan_file", side_effect=lambda data, require_messages=False: data), \
             mock.patch.object(cli, "load_message_file", return_value={"commits": []}), \
             mock.patch.object(cli, "merge_message_file", return_value={"repo": "/repo", "commits": []}), \
             mock.patch.object(cli, "run_coverage_from_plan", return_value={"passed": True}), \
             mock.patch.object(cli, "maybe_write_output"):
            self.assertEqual(cli.command_coverage(cov_plan_msg_args), 0)

        msg_args = argparse.Namespace(plan_file="/tmp/p.json", out=None, json=True)
        with mock.patch.object(cli, "load_plan_file", return_value={"repo": "/repo", "commits": [], "exclude": []}), \
             mock.patch.object(cli, "validate_plan_file", side_effect=lambda data, require_messages=False: data), \
             mock.patch.object(cli, "build_message_template", return_value={"mode": "message-only"}), \
             mock.patch.object(cli, "maybe_write_output") as writer:
            self.assertEqual(cli.command_message_template(msg_args), 0)
            writer.assert_called_once()

        args = argparse.Namespace(plan_file="/tmp/p.json", messages_file=None, repo="/repo2", sign_mode="auto", out=None, json=True)
        with mock.patch.object(cli, "load_plan_file", return_value={"repo": "/repo1", "commits": [{"repo_path": "/repo1", "paths": ["a"], "type": "feat", "title": "x", "bullets": []}], "exclude": []}), \
             mock.patch.object(cli, "validate_plan_file", side_effect=lambda data, require_messages=False: data), \
             mock.patch.object(cli, "repo_root", return_value="/repo2"):
            with self.assertRaises(SkillError):
                cli.command_apply_plan(args)

        args_ok = argparse.Namespace(plan_file="/tmp/p.json", messages_file=None, repo="/repo1", sign_mode="auto", out=None, json=True)
        with mock.patch.object(cli, "load_plan_file", return_value={"repo": "/repo1", "commits": [{"repo_path": "/repo1", "paths": ["a"], "type": "feat", "title": "x", "bullets": []}], "exclude": []}), \
             mock.patch.object(cli, "validate_plan_file", side_effect=lambda data, require_messages=False: data), \
             mock.patch.object(cli, "repo_root", return_value="/repo1"), \
             mock.patch.object(cli, "detect_signing", return_value={"suggested_sign_mode": "signed"}), \
             mock.patch.object(cli, "apply_plan", return_value={"ok": True}), \
             mock.patch.object(cli, "maybe_write_output") as writer:
            self.assertEqual(cli.command_apply_plan(args_ok), 0)
            writer.assert_called_once()

        args_plan_signed = argparse.Namespace(plan_file="/tmp/p.json", messages_file=None, repo="/repo1", sign_mode="auto", out=None, json=True)
        signed_plan = {"repo": "/repo1", "requested": {"sign_mode": "signed"}, "commits": [{"repo_path": "/repo1", "paths": ["a"], "type": "feat", "title": "x", "bullets": []}], "exclude": []}
        with mock.patch.object(cli, "load_plan_file", return_value=signed_plan), \
             mock.patch.object(cli, "validate_plan_file", side_effect=lambda data, require_messages=False: data), \
             mock.patch.object(cli, "repo_root", return_value="/repo1"), \
             mock.patch.object(cli, "signed_signing_context", return_value={"suggested_sign_mode": "signed"}) as signed_context, \
             mock.patch.object(cli, "apply_plan", return_value={"ok": True}) as apply, \
             mock.patch.object(cli, "maybe_write_output"):
            self.assertEqual(cli.command_apply_plan(args_plan_signed), 0)
            signed_context.assert_called_once_with()
            self.assertIsNone(apply.call_args.kwargs["sign_mode_override"])

        args_msg_ok = argparse.Namespace(plan_file="/tmp/p.json", messages_file="/tmp/m.json", repo="/repo1", sign_mode="auto", out=None, json=True)
        with mock.patch.object(cli, "load_plan_file", return_value={"repo": "/repo1", "commits": [{"repo_path": "/repo1", "paths": ["a"], "type": "", "title": "", "bullets": []}], "exclude": []}), \
             mock.patch.object(cli, "validate_plan_file", side_effect=lambda data, require_messages=False: data), \
             mock.patch.object(cli, "load_message_file", return_value={"commits": []}), \
             mock.patch.object(cli, "merge_message_file", return_value={"repo": "/repo1", "commits": [{"repo_path": "/repo1", "paths": ["a"], "type": "feat", "title": "x", "bullets": []}], "exclude": []}), \
             mock.patch.object(cli, "repo_root", return_value="/repo1"), \
             mock.patch.object(cli, "detect_signing", return_value={"suggested_sign_mode": "signed"}), \
             mock.patch.object(cli, "apply_plan", return_value={"ok": True}), \
             mock.patch.object(cli, "maybe_write_output") as writer:
            self.assertEqual(cli.command_apply_plan(args_msg_ok), 0)
            writer.assert_called_once()

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
