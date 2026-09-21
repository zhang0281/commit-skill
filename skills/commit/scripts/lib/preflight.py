from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .coverage import resolve_commit_paths
from .errors import ErrorCode, SkillError


CONFIG_NAME = ".commit-skill.json"
OUTPUT_LIMIT = 6000


@dataclass
class RunningCheck:
    name: str
    argv: list[str]
    cwd: str
    process: subprocess.Popen[str]
    stdout_file: object
    stderr_file: object
    timeout_seconds: float


@dataclass
class PreflightRun:
    diff_checks: list[dict[str, object]]
    tests: list[RunningCheck]

    def prepared_summary(self) -> dict[str, object]:
        return {
            "diff_check": self.diff_checks,
            "tests": [
                {"name": item.name, "argv": item.argv, "cwd": item.cwd, "status": "running"}
                for item in self.tests
            ],
            "tests_configured": bool(self.tests),
        }


def _read_commands(repo: str) -> list[dict[str, object]]:
    path = Path(repo, CONFIG_NAME)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillError(ErrorCode.PREFLIGHT_FAILED, f"{CONFIG_NAME} 解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise SkillError(ErrorCode.PREFLIGHT_FAILED, f"{CONFIG_NAME} 顶层必须为对象")
    preflight = payload.get("preflight", {})
    if not isinstance(preflight, dict):
        raise SkillError(ErrorCode.PREFLIGHT_FAILED, "preflight 必须为对象")
    commands = preflight.get("commands", [])
    if not isinstance(commands, list):
        raise SkillError(ErrorCode.PREFLIGHT_FAILED, "preflight.commands 必须为数组")
    normalized: list[dict[str, object]] = []
    for index, entry in enumerate(commands):
        if not isinstance(entry, dict):
            raise SkillError(ErrorCode.PREFLIGHT_FAILED, "preflight command 必须为对象", {"index": index})
        argv = entry.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(value, str) and value for value in argv):
            raise SkillError(ErrorCode.PREFLIGHT_FAILED, "preflight command argv 必须为非空字符串数组", {"index": index})
        timeout = entry.get("timeout_seconds", 300)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise SkillError(ErrorCode.PREFLIGHT_FAILED, "preflight command timeout_seconds 非法", {"index": index})
        normalized.append(
            {
                "name": str(entry.get("name") or f"test-{index + 1}"),
                "argv": argv,
                "timeout_seconds": float(timeout),
            }
        )
    return normalized


def _candidate_paths(plan: dict[str, object]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for commit in plan.get("commits", []):
        repo_path = str(commit["repo_path"])
        resolved, invalid = resolve_commit_paths(plan, repo_path, [str(path) for path in commit["paths"]])
        if invalid:
            raise SkillError(
                ErrorCode.COVERAGE_GAP,
                "preflight 遇到快照外路径",
                {"repo_path": repo_path, "paths": invalid},
            )
        grouped.setdefault(repo_path, []).extend(resolved)
    return {repo: sorted(dict.fromkeys(paths)) for repo, paths in grouped.items()}


def _diff_check(repo: str, paths: list[str]) -> dict[str, object]:
    if not paths:
        return {"repo_path": repo, "paths": [], "passed": True, "output": ""}
    git_dir = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--git-dir"],
        text=True,
        capture_output=True,
        check=False,
    )
    if git_dir.returncode != 0:
        raise SkillError(ErrorCode.PREFLIGHT_FAILED, git_dir.stderr.strip() or "无法定位 Git index")
    index_path = Path(git_dir.stdout.strip())
    if not index_path.is_absolute():
        index_path = Path(repo, index_path)
    source_index = index_path / "index" if index_path.is_dir() else index_path
    fd, temp_index = tempfile.mkstemp(prefix="commit-index-", dir=tempfile.gettempdir())
    os.close(fd)
    try:
        if source_index.exists():
            shutil.copyfile(source_index, temp_index)
        else:
            Path(temp_index).unlink(missing_ok=True)
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = temp_index
        add = subprocess.run(
            ["git", "-C", repo, "add", "-A", "--", *paths],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if add.returncode != 0:
            raise SkillError(ErrorCode.PREFLIGHT_FAILED, add.stderr.strip() or "临时 index staging 失败")
        head = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "HEAD"], capture_output=True, check=False)
        args = ["git", "-C", repo, "diff", "--cached", "--check"]
        if head.returncode == 0:
            args.append("HEAD")
        args.extend(["--", *paths])
        result = subprocess.run(args, env=env, text=True, capture_output=True, check=False)
        output = (result.stdout + result.stderr).strip()
        return {"repo_path": repo, "paths": paths, "passed": result.returncode == 0, "output": output[:OUTPUT_LIMIT]}
    finally:
        Path(temp_index).unlink(missing_ok=True)


def start_preflight(plan: dict[str, object]) -> PreflightRun:
    grouped = _candidate_paths(plan)
    diff_checks = [_diff_check(repo, paths) for repo, paths in grouped.items()]
    failed = [item for item in diff_checks if not item["passed"]]
    if failed:
        raise SkillError(ErrorCode.PREFLIGHT_FAILED, "git diff --check 未通过", {"diff_check": failed})

    running: list[RunningCheck] = []
    for repo in grouped:
        for command in _read_commands(repo):
            stdout_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
            stderr_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
            try:
                process = subprocess.Popen(
                    command["argv"],
                    cwd=repo,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    text=True,
                )
            except OSError as exc:
                stdout_file.close()
                stderr_file.close()
                cancel_preflight(PreflightRun(diff_checks=diff_checks, tests=running))
                raise SkillError(
                    ErrorCode.PREFLIGHT_FAILED,
                    f"无法启动 preflight command: {exc}",
                    {"name": command["name"], "argv": command["argv"], "repo": repo},
                ) from exc
            running.append(
                RunningCheck(
                    name=str(command["name"]),
                    argv=list(command["argv"]),
                    cwd=repo,
                    process=process,
                    stdout_file=stdout_file,
                    stderr_file=stderr_file,
                    timeout_seconds=float(command["timeout_seconds"]),
                )
            )
    return PreflightRun(diff_checks=diff_checks, tests=running)


def cancel_preflight(run: PreflightRun) -> None:
    for item in run.tests:
        if item.process.poll() is None:
            item.process.kill()
            item.process.wait()
        item.stdout_file.close()
        item.stderr_file.close()


def finish_preflight(run: PreflightRun) -> dict[str, object]:
    results: list[dict[str, object]] = []
    for item in run.tests:
        timed_out = False
        try:
            returncode = item.process.wait(timeout=item.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            item.process.kill()
            returncode = item.process.wait()
        item.stdout_file.seek(0)
        item.stderr_file.seek(0)
        stdout = item.stdout_file.read()[-OUTPUT_LIMIT:]
        stderr = item.stderr_file.read()[-OUTPUT_LIMIT:]
        item.stdout_file.close()
        item.stderr_file.close()
        results.append(
            {
                "name": item.name,
                "argv": item.argv,
                "cwd": item.cwd,
                "returncode": returncode,
                "timed_out": timed_out,
                "passed": returncode == 0 and not timed_out,
                "stdout": stdout,
                "stderr": stderr,
            }
        )
    payload = {
        "passed": all(item["passed"] for item in run.diff_checks) and all(item["passed"] for item in results),
        "diff_check": run.diff_checks,
        "tests": results,
        "tests_configured": bool(results),
    }
    if not payload["passed"]:
        raise SkillError(ErrorCode.PREFLIGHT_FAILED, "提交前检查未通过", {"preflight": payload})
    return payload
