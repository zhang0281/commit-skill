from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "commit_skill.py"


def host_model_env() -> dict[str, str]:
    """Keep host-stdin tests independent from the developer shell's model config."""
    return {name: value for name, value in os.environ.items() if not name.startswith(("commit_", "COMMIT_"))}


class ModelResponseHandler(BaseHTTPRequestHandler):
    received: dict[str, object] = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("Content-Length", "0"))
        self.received["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "commits": [
                                    {
                                        "id": "repo:single",
                                        "type": "feat",
                                        "title": "使用自定义模型生成提交消息",
                                        "bullets": ["保留脚本校验与提交边界"],
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


class DoctorProbeHandler(BaseHTTPRequestHandler):
    received: dict[str, object] = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("Content-Length", "0"))
        self.received.update(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": json.loads(self.rfile.read(length).decode("utf-8")),
            }
        )
        encoded = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


class FailingModelResponseHandler(BaseHTTPRequestHandler):
    requests = 0

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        type(self).requests += 1
        encoded = b'{"error":"temporary model outage"}'
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


def run_custom_model_session(repo: Path, env: dict[str, str]) -> tuple[dict[str, object], dict[str, object], str]:
    process = subprocess.Popen(
        [
            "python3",
            "-B",
            str(SCRIPT),
            "commit-session",
            "--repo",
            str(repo),
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
        env=env,
    )
    assert process.stdout is not None
    prepared = json.loads(process.stdout.readline())
    trailing = process.stdout.read().splitlines()
    stderr = process.stderr.read() if process.stderr else ""
    if process.stdin:
        process.stdin.close()
    if process.stdout:
        process.stdout.close()
    if process.stderr:
        process.stderr.close()
    returncode = process.wait(timeout=10)
    if returncode:
        raise AssertionError(f"custom model session failed ({returncode}): {stderr}")
    return prepared, json.loads(trailing[-1]), stderr


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
            env=host_model_env(),
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
            env=host_model_env(),
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
            env=host_model_env(),
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
            env=host_model_env(),
        )
        self.assertIsNotNone(process.stdin)
        self.assertIsNotNone(process.stdout)
        prepared = json.loads(process.stdout.readline())
        self.assertEqual(prepared["phase"], "prepared")
        self.assertEqual(prepared["message_source"], "stdin")
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
            env=host_model_env(),
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
            env=host_model_env(),
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

    def test_commit_session_uses_custom_model_backend_when_configured(self) -> None:
        received: dict[str, object] = {}
        ModelResponseHandler.received = received
        server = ThreadingHTTPServer(("127.0.0.1", 0), ModelResponseHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        env = os.environ.copy()
        env.update(
            {
                "commit_url": f"http://127.0.0.1:{server.server_port}",
                "commit_key": "test-secret-key",
                "commit_model": "test-model",
            }
        )
        prepared, complete, _ = run_custom_model_session(self.repo, env)
        self.assertEqual(prepared["message_source"], "custom-model")
        self.assertEqual(prepared["model_config"]["model"], "test-model")
        self.assertTrue(received)
        request_body = received["body"]
        self.assertEqual(request_body["model"], "test-model")
        self.assertEqual(complete["phase"], "complete")
        self.assertTrue(complete["ok"])
        log = subprocess.run(["git", "-C", str(self.repo), "log", "--oneline", "-1"], capture_output=True, text=True, check=True)
        self.assertIn("feat: 使用自定义模型生成提交消息", log.stdout)

    def test_commit_session_retries_custom_model_then_falls_back_to_host(self) -> None:
        FailingModelResponseHandler.requests = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), FailingModelResponseHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        env = os.environ.copy()
        env.update(
            {
                "commit_url": f"http://127.0.0.1:{server.server_port}",
                "commit_key": "fallback-secret-key",
                "commit_model": "fallback-model",
            }
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
                "--sign-mode",
                "unsigned",
                "--json",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self.assertIsNotNone(process.stdin)
        self.assertIsNotNone(process.stdout)
        prepared = json.loads(process.stdout.readline())
        self.assertEqual(prepared["message_source"], "custom-model")
        fallback = json.loads(process.stdout.readline())
        self.assertEqual(fallback["phase"], "fallback")
        self.assertEqual(fallback["message_source"], "stdin")
        self.assertEqual(fallback["model_attempts"], 3)
        self.assertEqual(fallback["retry_count"], 2)
        process.stdin.write(
            json.dumps(
                {
                    "commits": [
                        {
                            "id": "repo:single",
                            "type": "feat",
                            "title": "回退到宿主模型生成提交消息",
                            "bullets": ["自定义模型重试失败后继续原有提交流程"],
                        }
                    ]
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        process.stdin.close()
        trailing = process.stdout.read().splitlines()
        stderr = process.stderr.read()
        process.stdout.close()
        process.stderr.close()
        returncode = process.wait(timeout=10)
        self.assertEqual(returncode, 0, stderr)
        self.assertEqual(FailingModelResponseHandler.requests, 3)
        complete = json.loads(trailing[-1])
        self.assertEqual(complete["phase"], "complete")
        self.assertTrue(complete["ok"])
        self.assertEqual(complete["message_source"], "stdin")
        self.assertEqual(complete["message_fallback"]["retry_count"], 2)
        log = subprocess.run(
            ["git", "-C", str(self.repo), "log", "--oneline", "-1"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("feat: 回退到宿主模型生成提交消息", log.stdout)

    def test_require_custom_model_does_not_fallback_after_retries(self) -> None:
        FailingModelResponseHandler.requests = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), FailingModelResponseHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        env = os.environ.copy()
        env.update(
            {
                "commit_url": f"http://127.0.0.1:{server.server_port}",
                "commit_key": "required-secret-key",
                "commit_model": "required-model",
            }
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
                "--require-custom-model",
                "--sign-mode",
                "unsigned",
                "--json",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self.assertIsNotNone(process.stdout)
        prepared = json.loads(process.stdout.readline())
        self.assertEqual(prepared["message_source"], "custom-model")
        failure_text = process.stdout.read()
        stderr = process.stderr.read()
        if process.stdin:
            process.stdin.close()
        process.stdout.close()
        process.stderr.close()
        returncode = process.wait(timeout=10)
        self.assertEqual(returncode, 60, stderr)
        self.assertEqual(FailingModelResponseHandler.requests, 3)
        failure = json.loads(failure_text)
        self.assertEqual(failure["error_code"], "MODEL_REQUEST_FAILED")
        self.assertEqual(failure["details"]["retry_count"], 2)
        self.assertEqual(failure["details"]["fallback"], "disabled")

    def test_doctor_probe_makes_minimal_live_request(self) -> None:
        received: dict[str, object] = {}
        DoctorProbeHandler.received = received
        server = ThreadingHTTPServer(("127.0.0.1", 0), DoctorProbeHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        env = os.environ.copy()
        env.update(
            {
                "commit_url": f"http://127.0.0.1:{server.server_port}/v1",
                "commit_key": "probe-secret-key",
                "commit_model": "probe-model",
            }
        )
        result = subprocess.run(
            ["python3", "-B", str(SCRIPT), "doctor", "--probe", "--json"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["config"]["probe"], {"status": "passed", "response": "ok"})
        self.assertEqual(received["path"], "/v1/chat/completions")
        self.assertEqual(received["authorization"], "Bearer probe-secret-key")
        body = received["body"]
        self.assertEqual(body["model"], "probe-model")
        self.assertEqual(body["max_tokens"], 3)
        self.assertNotIn(str(self.repo), json.dumps(body))
        self.assertNotIn("probe-secret-key", result.stdout)

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
            env=host_model_env(),
        )

        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        show = subprocess.run(["git", "-C", str(self.repo), "show", "--name-status", "--format=", "HEAD"], capture_output=True, text=True, check=True)
        self.assertIn("M	README.md", show.stdout)
        self.assertIn("D	obsolete.txt", show.stdout)
        status = subprocess.run(["git", "-C", str(self.repo), "status", "--short"], capture_output=True, text=True, check=True)
        self.assertEqual(status.stdout.strip(), "?? plan.json")
