from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "commit_skill.py"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def normalize_payload(payload: object, replacements: dict[str, str]) -> object:
    if isinstance(payload, dict):
        normalized: dict[str, object] = {}
        for key, value in payload.items():
            if key == "sign_context":
                normalized[key] = {"normalized": True}
                continue
            if key == "recorded_sha":
                normalized[key] = "<SUBMODULE_SHA>"
                continue
            normalized[key] = normalize_payload(value, replacements)
        return normalized
    if isinstance(payload, list):
        return [normalize_payload(item, replacements) for item in payload]
    if isinstance(payload, str):
        result = payload
        for raw, placeholder in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            result = result.replace(raw, placeholder)
        return result
    return payload


def load_golden(name: str) -> object:
    return json.loads(Path(GOLDEN_DIR, name).read_text(encoding="utf-8"))


class GoldenOutputTest(unittest.TestCase):
    maxDiff = None

    def run_json(self, *args: str) -> object:
        result = subprocess.run(
            ["python3", "-B", str(SCRIPT), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_single_project_plan_and_message_template(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True, text=True)
            subprocess.run(["git", "-C", str(repo), "config", "commit.gpgsign", "false"], check=True)
            (repo / "README.md").write_text("# demo\n", encoding="utf-8")
            (repo / "docs").mkdir()
            (repo / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
            (repo / "src").mkdir()
            (repo / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")

            plan_file = repo / "plan.json"
            plan_payload = self.run_json("plan", "--repo", str(repo), "--out", str(plan_file), "--json", "--sign-mode", "unsigned")
            message_payload = self.run_json("message-template", "--plan-file", str(plan_file), "--json")

            replacements = {str(repo): "<REPO>"}
            self.assertEqual(normalize_payload(plan_payload, replacements), load_golden("single_project.plan.json"))
            self.assertEqual(normalize_payload(message_payload, replacements), load_golden("single_project.message-template.json"))

    def test_submodule_project_plan_and_message_template(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td) / "parent"
            child = Path(td) / "child"
            parent.mkdir()
            child.mkdir()

            subprocess.run(["git", "init", "-b", "main", str(child)], check=True, capture_output=True, text=True)
            subprocess.run(["git", "-C", str(child), "config", "commit.gpgsign", "false"], check=True)
            subprocess.run(["git", "-C", str(child), "config", "user.name", "tester"], check=True)
            subprocess.run(["git", "-C", str(child), "config", "user.email", "tester@example.com"], check=True)
            (child / "module.txt").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(child), "add", "module.txt"], check=True)
            subprocess.run(["git", "-C", str(child), "commit", "-m", "init child"], check=True, capture_output=True, text=True)

            subprocess.run(["git", "init", "-b", "main", str(parent)], check=True, capture_output=True, text=True)
            subprocess.run(["git", "-C", str(parent), "config", "commit.gpgsign", "false"], check=True)
            subprocess.run(["git", "-C", str(parent), "config", "user.name", "tester"], check=True)
            subprocess.run(["git", "-C", str(parent), "config", "user.email", "tester@example.com"], check=True)
            subprocess.run(
                ["git", "-C", str(parent), "-c", "protocol.file.allow=always", "submodule", "add", str(child), "vendor/child"],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(["git", "-C", str(parent), "commit", "-m", "add submodule"], check=True, capture_output=True, text=True)
            (parent / "vendor/child/module.txt").write_text("hello world\n", encoding="utf-8")

            plan_file = parent / "plan.json"
            plan_payload = self.run_json("plan", "--repo", str(parent), "--out", str(plan_file), "--json", "--sign-mode", "unsigned")
            message_payload = self.run_json("message-template", "--plan-file", str(plan_file), "--json")

            replacements = {str(parent): "<REPO>", str(child): "<CHILD_SOURCE_REPO>"}
            self.assertEqual(normalize_payload(plan_payload, replacements), load_golden("submodule_project.plan.json"))
            self.assertEqual(normalize_payload(message_payload, replacements), load_golden("submodule_project.message-template.json"))
