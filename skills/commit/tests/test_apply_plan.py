from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "commit_skill.py"


class ApplyPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name)
        subprocess.run(["git", "init", "-b", "main", str(self.repo)], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "commit.gpgsign", "false"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Commit Skill Test"], check=True)
        (self.repo / "README.md").write_text("# demo\n", encoding="utf-8")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "demo.py").write_text("print('demo')\n", encoding="utf-8")
        self.plan_file = self.repo / "plan.json"
        self.plan_file.write_text(
            json.dumps(
                {
                    "repo": str(self.repo),
                    "requested": {"sign_mode": "unsigned"},
                    "coverage_baseline": {
                        "root_changed_files": ["README.md", "src/demo.py"],
                        "explicit_excluded_files": [],
                        "submodule_changes": [],
                        "required_pointer_updates": [],
                    },
                    "exclude": [],
                    "commits": [
                        {
                            "id": "repo:single",
                            "repo_path": str(self.repo),
                            "paths": ["README.md", "src/demo.py"],
                            "type": "feat",
                            "title": "初始化测试仓库",
                            "bullets": ["新增 README", "新增 demo 脚本"],
                            "sign_mode": "unsigned",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_apply_plan_executes_commit(self) -> None:
        result = subprocess.run(
            [
                "python3",
                "-B",
                str(SCRIPT),
                "apply-plan",
                "--plan-file",
                str(self.plan_file),
                "--repo",
                str(self.repo),
                "--sign-mode",
                "unsigned",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        status = subprocess.run(["git", "-C", str(self.repo), "status", "--short"], capture_output=True, text=True, check=True)
        self.assertEqual(status.stdout.strip(), "?? plan.json")
        log = subprocess.run(["git", "-C", str(self.repo), "log", "--oneline", "-1"], capture_output=True, text=True, check=True)
        self.assertIn("feat: 初始化测试仓库", log.stdout)

    def test_apply_plan_accepts_messages_file(self) -> None:
        self.plan_file.write_text(
            json.dumps(
                {
                    "repo": str(self.repo),
                    "requested": {"sign_mode": "unsigned"},
                    "coverage_baseline": {
                        "root_changed_files": ["README.md", "src/demo.py"],
                        "explicit_excluded_files": [],
                        "submodule_changes": [],
                        "required_pointer_updates": [],
                    },
                    "exclude": [],
                    "commits": [
                        {
                            "id": "repo:single",
                            "repo_path": str(self.repo),
                            "paths": ["README.md", "src/demo.py"],
                            "type": "",
                            "title": "",
                            "bullets": [],
                            "sign_mode": "unsigned",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        messages_file = self.repo / "messages.json"
        messages_file.write_text(
            json.dumps(
                {
                    "repo": str(self.repo),
                    "commits": [
                        {
                            "id": "repo:single",
                            "type": "feat",
                            "title": "初始化测试仓库",
                            "bullets": ["新增 README", "新增 demo 脚本"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                "python3",
                "-B",
                str(SCRIPT),
                "apply-plan",
                "--plan-file",
                str(self.plan_file),
                "--messages-file",
                str(messages_file),
                "--repo",
                str(self.repo),
                "--sign-mode",
                "unsigned",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        log = subprocess.run(["git", "-C", str(self.repo), "log", "--oneline", "-1"], capture_output=True, text=True, check=True)
        self.assertIn("feat: 初始化测试仓库", log.stdout)
        self.assertIn("message_coverage_audit", payload)
        self.assertTrue(payload["message_coverage_audit"])

    def test_apply_plan_handles_already_staged_deletions(self) -> None:
        (self.repo / "obsolete.txt").write_text("old\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "README.md", "src/demo.py", "obsolete.txt"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "init"], check=True, capture_output=True, text=True)

        (self.repo / "README.md").write_text("# demo\n\nupdated\n", encoding="utf-8")
        (self.repo / "obsolete.txt").unlink()
        subprocess.run(["git", "-C", str(self.repo), "add", "obsolete.txt"], check=True)
        self.plan_file.write_text(
            json.dumps(
                {
                    "repo": str(self.repo),
                    "requested": {"sign_mode": "unsigned"},
                    "coverage_baseline": {
                        "root_changed_files": ["README.md", "obsolete.txt"],
                        "explicit_excluded_files": [],
                        "submodule_changes": [],
                        "required_pointer_updates": [],
                    },
                    "exclude": [],
                    "commits": [
                        {
                            "id": "repo:staged-delete",
                            "repo_path": str(self.repo),
                            "paths": ["README.md", "obsolete.txt"],
                            "type": "fix",
                            "title": "处理已暂存删除路径",
                            "bullets": ["提交已暂存删除与普通文件修改"],
                            "sign_mode": "unsigned",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                "python3",
                "-B",
                str(SCRIPT),
                "apply-plan",
                "--plan-file",
                str(self.plan_file),
                "--repo",
                str(self.repo),
                "--sign-mode",
                "unsigned",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        show = subprocess.run(["git", "-C", str(self.repo), "show", "--name-status", "--format=", "HEAD"], capture_output=True, text=True, check=True)
        self.assertIn("M	README.md", show.stdout)
        self.assertIn("D	obsolete.txt", show.stdout)
        status = subprocess.run(["git", "-C", str(self.repo), "status", "--short"], capture_output=True, text=True, check=True)
        self.assertEqual(status.stdout.strip(), "?? plan.json")
