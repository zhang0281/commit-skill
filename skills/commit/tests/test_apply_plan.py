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
        messages_file = Path(tempfile.gettempdir()) / f"commit-messages-{self.repo.name}Apply.json"
        self.addCleanup(messages_file.unlink, missing_ok=True)
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

    def test_fast_commit_prepares_and_applies_in_one_invocation(self) -> None:
        messages_file = Path(tempfile.gettempdir()) / f"commit-messages-{self.repo.name}Merge.json"
        self.addCleanup(messages_file.unlink, missing_ok=True)
        messages_file.write_text(
            json.dumps(
                {
                    "repo": str(self.repo),
                    "commits": [
                        {
                            "id": "repo:single",
                            "type": "feat",
                            "title": "初始化测试仓库",
                            "bullets": ["新增 README 与 demo 脚本"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        plan_file = self.repo.parent / f"{self.repo.name}-fast-plan.json"
        result = subprocess.run(
            [
                "python3",
                "-B",
                str(SCRIPT),
                "fast-commit",
                "--repo",
                str(self.repo),
                "--messages-file",
                str(messages_file),
                "--plan-file",
                str(plan_file),
                "--exclude",
                "plan.json",
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
        self.assertEqual(payload["plan_file"], str(plan_file))
        log = subprocess.run(["git", "-C", str(self.repo), "log", "--oneline", "-1"], capture_output=True, text=True, check=True)
        self.assertIn("feat: 初始化测试仓库", log.stdout)
        self.assertIn("message_coverage_audit", payload)
        self.assertTrue(payload["message_coverage_audit"])

    def test_commit_session_round_trip_uses_one_process(self) -> None:
        plan_file = Path(tempfile.gettempdir()) / f"{self.repo.name}-session-plan.json"
        self.addCleanup(plan_file.unlink, missing_ok=True)
        process = subprocess.Popen(
            [
                "python3",
                "-B",
                str(SCRIPT),
                "commit-session",
                "--repo",
                str(self.repo),
                "--plan-file",
                str(plan_file),
                "--exclude",
                "plan.json",
                "--sign-mode",
                "unsigned",
                "--json",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.assertIsNotNone(process.stdin)
        self.assertIsNotNone(process.stdout)
        prepared = json.loads(process.stdout.readline())
        self.assertEqual(prepared["phase"], "prepared")
        self.assertEqual(prepared["message_template"]["mode"], "message-only")
        messages_file = Path(prepared["messages_file"])
        self.assertEqual(messages_file.parent, Path(tempfile.gettempdir()))
        self.assertRegex(messages_file.name, r"^commit-messages-[A-Za-z0-9_-]{6,}\.json$")
        process.stdin.write(
            json.dumps(
                {
                    "commits": [
                        {
                            "id": "repo:single",
                            "type": "feat",
                            "title": "初始化测试仓库",
                            "bullets": ["新增 README 与 demo 脚本"],
                        }
                    ]
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        process.stdin.flush()
        process.stdin.close()
        trailing = process.stdout.read().splitlines()
        process.stdout.close()
        returncode = process.wait(timeout=10)
        stderr = process.stderr.read()
        process.stderr.close()
        self.assertEqual(returncode, 0, stderr)
        complete = json.loads(trailing[-1])
        self.assertEqual(complete["phase"], "complete")
        self.assertTrue(complete["messages_file_removed"])
        self.assertFalse(messages_file.exists())
        self.assertTrue(complete["preflight"]["passed"])
        self.assertFalse(complete["postflight"]["clean"])
        self.assertEqual(complete["postflight"]["post_snapshot_changes"], [])
        log = subprocess.run(["git", "-C", str(self.repo), "log", "--oneline", "-1"], capture_output=True, text=True, check=True)
        self.assertIn("feat: 初始化测试仓库", log.stdout)

    def test_commit_session_prepared_contains_semantic_diff(self) -> None:
        process = subprocess.Popen(
            [
                "python3",
                "-B",
                str(SCRIPT),
                "commit-session",
                "--repo",
                str(self.repo),
                "--exclude",
                "plan.json",
                "--sign-mode",
                "unsigned",
                "--json",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())
        self.addCleanup(lambda: process.stdin and process.stdin.close())
        self.addCleanup(lambda: process.stdout and process.stdout.close())
        self.addCleanup(lambda: process.stderr and process.stderr.close())
        prepared = json.loads(process.stdout.readline())
        semantic = prepared["message_template"]["commits"][0]["diff_summary"]["semantic_diff"]
        self.assertIn("README.md", semantic["text"])
        self.assertIn("src/demo.py", semantic["text"])
        process.kill()
        process.wait(timeout=5)

    def test_commit_session_runs_configured_tests_during_message_wait(self) -> None:
        marker = self.repo / "preflight.marker"
        (self.repo / ".commit-skill.json").write_text(
            json.dumps(
                {
                    "preflight": {
                        "commands": [
                            {
                                "name": "marker",
                                "argv": ["python3", "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('ok')"],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        process = subprocess.Popen(
            [
                "python3",
                "-B",
                str(SCRIPT),
                "commit-session",
                "--repo",
                str(self.repo),
                "--exclude",
                "plan.json",
                "--exclude",
                ".commit-skill.json",
                "--exclude",
                "preflight.marker",
                "--sign-mode",
                "unsigned",
                "--json",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())
        self.addCleanup(lambda: process.stdin and process.stdin.close())
        self.addCleanup(lambda: process.stdout and process.stdout.close())
        self.addCleanup(lambda: process.stderr and process.stderr.close())
        prepared = json.loads(process.stdout.readline())
        self.assertEqual(prepared["preflight"]["tests"][0]["status"], "running")
        for _ in range(100):
            if marker.exists():
                break
            import time
            time.sleep(0.01)
        self.assertTrue(marker.exists())
        process.kill()
        process.wait(timeout=5)

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
