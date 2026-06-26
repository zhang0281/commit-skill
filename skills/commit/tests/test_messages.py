from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.errors import ErrorCode, SkillError
from lib.messages import apply_message_coverage, build_message_template, load_message_file, merge_message_file, validate_message_file


def mock_diff_stat_lines(repo_path: str, paths: list[str]) -> list[str]:
    return [f" {path} | 10 +++" for path in paths[:20]]


def mock_diff_name_status(repo_path: str, paths: list[str]) -> list[dict[str, str]]:
    return [{"status": "M", "path": path} for path in paths]


class MessageLibTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = {
            "repo": "/repo",
            "branch": "main",
            "commits": [
                {
                    "id": "repo:docs",
                    "kind": "repo",
                    "repo_path": "/repo",
                    "paths": ["README.md"],
                    "category": "docs",
                    "type_hint": "docs",
                    "title_hint": "更新文档",
                    "bullet_hints": ["补齐说明"],
                },
                {
                    "id": "repo:code:src",
                    "kind": "repo",
                    "repo_path": "/repo",
                    "paths": ["src/app.py"],
                    "category": "code",
                    "type_hint": "refactor",
                    "title_hint": "整理代码改动",
                    "bullet_hints": ["处理代码改动"],
                },
            ],
            "exclude": [],
            "coverage_baseline": {
                "root_changed_files": ["README.md", "src/app.py"],
                "root_fingerprints": [],
                "explicit_excluded_files": [],
                "submodule_changes": [],
                "required_pointer_updates": [],
            },
        }

    @patch("lib.messages.diff_stat_lines", side_effect=mock_diff_stat_lines)
    @patch("lib.messages.diff_name_status", side_effect=mock_diff_name_status)
    def test_build_message_template(self, mock_ns, mock_stat) -> None:
        payload = build_message_template(self.plan)
        self.assertEqual(payload["mode"], "message-only")
        self.assertEqual([item["id"] for item in payload["commits"]], ["repo:docs", "repo:code:src"])
        self.assertEqual(payload["commits"][0]["type"], "")
        self.assertIn("diff_summary", payload["commits"][0])
        self.assertNotIn("must_cover", payload["commits"][0])
        self.assertTrue(payload["commits"][0]["diff_summary"]["file_actions"])
        self.assertTrue(payload["commits"][0]["diff_summary"]["stat_lines"])

    def test_validate_and_merge_message_file(self) -> None:
        messages = {
            "repo": "/repo",
            "commits": [
                {"id": "repo:docs", "type": "docs", "title": "更新文档", "bullets": ["补齐说明"]},
                {"id": "repo:code:src", "type": "refactor", "title": "整理代码改动", "bullets": []},
            ],
        }
        validated = validate_message_file(messages, self.plan)
        self.assertEqual(list(validated), ["repo:docs", "repo:code:src"])
        merged = merge_message_file(self.plan, messages)
        self.assertEqual(merged["commits"][0]["type"], "docs")
        self.assertEqual(merged["commits"][1]["title"], "整理代码改动")
        self.assertIn("message_coverage_audit", merged)
        # commits[0] has non-empty bullets from AI → no structural fallback appended
        self.assertEqual(merged["commits"][0]["bullets"], ["补齐说明"])
        # commits[1] has empty bullets → structural fallback appended
        self.assertTrue(any("涉及" in bullet or "包含" in bullet for bullet in merged["commits"][1]["bullets"]))

    def test_validate_rejects_reordered_ids(self) -> None:
        messages = {
            "commits": [
                {"id": "repo:code:src", "type": "refactor", "title": "整理代码改动", "bullets": []},
                {"id": "repo:docs", "type": "docs", "title": "更新文档", "bullets": []},
            ]
        }
        with self.assertRaises(SkillError) as ctx:
            validate_message_file(messages, self.plan)
        self.assertEqual(ctx.exception.code, ErrorCode.MESSAGE_FILE_INVALID)

    def test_load_message_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td, "messages.json")
            payload = {"commits": []}
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(load_message_file(str(path)), payload)
            with self.assertRaises(SkillError):
                load_message_file(str(Path(td, "missing.json")))

    def test_apply_message_coverage_appends_missing_bullets(self) -> None:
        merged = apply_message_coverage(
            {
                **self.plan,
                "commits": [
                    {
                        "id": "repo:docs",
                        "kind": "repo",
                        "repo_path": "/repo",
                        "paths": ["README.md"],
                        "type": "docs",
                        "title": "更新文档",
                        "bullets": [],
                    }
                ],
            }
        )
        self.assertIn("message_coverage_audit", merged)
        self.assertTrue(merged["commits"][0]["bullets"])

    @patch("lib.messages.diff_stat_lines", side_effect=mock_diff_stat_lines)
    @patch("lib.messages.diff_name_status", side_effect=mock_diff_name_status)
    def test_diff_summary_contains_semantic_info(self, mock_ns, mock_stat) -> None:
        payload = build_message_template(self.plan)
        commit = payload["commits"][0]
        self.assertIn("diff_summary", commit)
        ds = commit["diff_summary"]
        self.assertIn("stat_lines", ds)
        self.assertIn("file_actions", ds)
        self.assertIn("summary", ds)
        self.assertEqual(ds["file_actions"], ["修改 README.md"])
        self.assertIn("README.md", ds["summary"])

    @patch("lib.messages.diff_stat_lines", side_effect=mock_diff_stat_lines)
    @patch("lib.messages.diff_name_status", side_effect=mock_diff_name_status)
    def test_rules_forbid_structural_bullets(self, mock_ns, mock_stat) -> None:
        payload = build_message_template(self.plan)
        rules_text = " ".join(payload["rules"])
        self.assertIn("禁止", rules_text)
        self.assertIn("涉及 X", rules_text)
        self.assertNotIn("must_cover", rules_text)
        self.assertNotIn("优先直接复用", rules_text)
