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
