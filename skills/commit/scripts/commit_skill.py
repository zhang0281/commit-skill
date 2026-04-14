#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


GPG_ERROR_PATTERNS = (
    "failed to sign the data",
    "signing failed",
    "no agent running",
    "can't connect to the gpg-agent",
    "failed to start gpg-agent",
    "pinentry",
)

TEST_FILE_SUFFIXES = (
    "_test.py",
    ".spec.ts",
    ".test.ts",
    ".spec.js",
    ".test.js",
)

CONFIG_LIKE_FILES = {
    ".gitignore",
    ".gitattributes",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "Pipfile",
    "Pipfile.lock",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
    ".env.example",
}


@dataclass
class CmdResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class CommitPlan:
    root: str
    files: list[str]
    requested_sign_mode: str
    effective_sign_mode: str
    title: str
    bullets: list[str]
    message_args: list[str]


@dataclass
class CommitRun:
    result: CmdResult
    attempted: list[dict[str, object]]
    signed: bool
    fallback_used: bool


def run_cmd(args: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> CmdResult:
    proc = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
    )
    return CmdResult(args=args, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def git(repo: str, *extra: str, env: dict[str, str] | None = None) -> CmdResult:
    return run_cmd(["git", "-C", repo, *extra], env=env)


def gpg(*extra: str, env: dict[str, str] | None = None) -> CmdResult:
    return run_cmd(["gpg", *extra], env=env)


def gpgconf(*extra: str, env: dict[str, str] | None = None) -> CmdResult:
    return run_cmd(["gpgconf", *extra], env=env)


def repo_root(repo: str) -> str:
    result = git(repo, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "无法识别 Git 仓库")
    return result.stdout.strip()


def head_exists(repo: str) -> bool:
    return git(repo, "rev-parse", "--verify", "HEAD").returncode == 0


def git_get(repo: str, key: str, global_scope: bool = False) -> str:
    args = ["config"]
    if global_scope:
        args.append("--global")
    args.extend(["--get", key])
    result = git(repo, *args)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def current_env() -> dict[str, str]:
    env = os.environ.copy()
    if sys.stdin.isatty():
        try:
            env["GPG_TTY"] = os.ttyname(sys.stdin.fileno())
        except OSError:
            pass
    return env


def classify_path(path: str) -> str:
    posix = path.replace("\\", "/")
    name = Path(posix).name
    if posix.startswith("docs/") or name.endswith(".md"):
        return "docs"
    is_test_path = (
        posix.startswith(("tests/", "test/"))
        or "/tests/" in posix
        or name.startswith("test_")
        or name.endswith(TEST_FILE_SUFFIXES)
    )
    if is_test_path:
        return "tests"
    config_suffixes = (".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".json")
    if name in CONFIG_LIKE_FILES or name.endswith(config_suffixes):
        return "config"
    return "code"


def matches_pattern(path: str, patterns: Iterable[str]) -> bool:
    from fnmatch import fnmatch

    normalized = path.replace("\\", "/")
    for raw in patterns:
        pattern = raw.replace("\\", "/").rstrip("/")
        if not pattern:
            continue
        if "*" in pattern or "?" in pattern or "[" in pattern:
            if fnmatch(normalized, pattern):
                return True
            continue
        if normalized == pattern or normalized.startswith(pattern + "/"):
            return True
    return False


def parse_status(repo: str) -> list[dict[str, str]]:
    result = git(repo, "status", "--short", "--untracked-files=all")
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "无法获取 git status")

    entries: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        status = line[:2]
        rest = line[3:]
        path = rest.split(" -> ", 1)[-1].strip()
        entries.append({"status": status, "path": path, "category": classify_path(path)})
    return entries


def parse_submodule_status_output(text: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        prefix = line[0]
        parts = line[1:].strip().split()
        if len(parts) < 2:
            continue
        entries.append({"prefix": prefix, "sha": parts[0], "path": parts[1]})
    return entries


def parse_submodule_dirty_output(text: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in text.splitlines():
        if line.startswith("=== ") and line.endswith(" ==="):
            if current:
                entries.append(current)
            current = {"path": line[4:-4], "status": []}
            continue
        if current is not None:
            current["status"].append(line)
    if current:
        entries.append(current)
    return entries


def collect_submodules(repo: str) -> dict[str, list[dict[str, object]]]:
    status_result = git(repo, "submodule", "status")
    status_entries = []
    if status_result.returncode == 0:
        status_entries = parse_submodule_status_output(status_result.stdout)

    dirty_script = (
        'DIRTY=$(git status --short 2>/dev/null); '
        'if [ -n "$DIRTY" ]; then '
        'printf "=== %s ===\\n%s\\n" "$displaypath" "$DIRTY"; '
        "fi"
    )
    dirty_cmd = [
        "submodule",
        "foreach",
        "--quiet",
        dirty_script,
    ]
    dirty_result = git(repo, *dirty_cmd)
    dirty_entries = []
    if dirty_result.returncode == 0:
        dirty_entries = parse_submodule_dirty_output(dirty_result.stdout)

    return {"status": status_entries, "dirty": dirty_entries}


def detect_signing(repo: str, forced_sign_mode: str | None = None) -> dict[str, object]:
    env = current_env()
    launch = gpgconf("--launch", "gpg-agent", env=env)
    secret_keys = gpg("--list-secret-keys", "--keyid-format", "LONG", env=env)
    key_ids = []
    for line in secret_keys.stdout.splitlines():
        if line.startswith("sec"):
            match = re.search(r"/([0-9A-F]{16,40})\s", line)
            if match:
                key_ids.append(match.group(1))

    repo_gpgsign = git_get(repo, "commit.gpgsign")
    global_gpgsign = git_get(repo, "commit.gpgsign", global_scope=True)
    repo_signingkey = git_get(repo, "user.signingkey")
    global_signingkey = git_get(repo, "user.signingkey", global_scope=True)

    signing_available = bool(
        key_ids
        or repo_gpgsign == "true"
        or global_gpgsign == "true"
        or repo_signingkey
        or global_signingkey
    )

    if forced_sign_mode in {"signed", "unsigned"}:
        suggested = forced_sign_mode
    else:
        suggested = "signed" if signing_available else "unsigned"

    return {
        "has_tty": sys.stdin.isatty(),
        "gpg_tty": env.get("GPG_TTY", ""),
        "gpg_agent_launch_ok": launch.returncode == 0,
        "gpg_agent_launch_stderr": launch.stderr.strip(),
        "secret_key_ids": key_ids,
        "repo_commit_gpgsign": repo_gpgsign,
        "global_commit_gpgsign": global_gpgsign,
        "repo_signingkey": repo_signingkey,
        "global_signingkey": global_signingkey,
        "suggested_sign_mode": suggested,
        "signing_available": signing_available,
    }


def changed_file_paths(repo: str) -> list[str]:
    return sorted({entry["path"] for entry in parse_status(repo)})


def filtered_paths(paths: list[str], includes: list[str], excludes: list[str]) -> tuple[list[str], list[str]]:
    included = [p for p in paths if not includes or matches_pattern(p, includes)]
    excluded = [p for p in included if matches_pattern(p, excludes)]
    filtered = [p for p in included if p not in excluded]
    return filtered, excluded


def top_level_groups(paths: Iterable[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for path in paths:
        parts = path.replace("\\", "/").split("/", 1)
        key = parts[0] if len(parts) > 1 else "."
        groups.setdefault(key, []).append(path)
    for key in groups:
        groups[key] = sorted(groups[key])
    return dict(sorted(groups.items()))


def expand_targets(changed: list[str], patterns: list[str]) -> list[str]:
    expanded: list[str] = []
    for pattern in patterns:
        matches = [path for path in changed if matches_pattern(path, [pattern])]
        if matches:
            expanded.extend(matches)
        else:
            expanded.append(pattern)
    return sorted(dict.fromkeys(expanded))


def command_inventory(args: argparse.Namespace) -> int:
    root = repo_root(args.repo)
    changed = changed_file_paths(root)
    filtered, excluded = filtered_paths(changed, args.include, args.exclude)
    sign_context = detect_signing(root, args.sign_mode if args.sign_mode != "auto" else None)

    payload = {
        "repo": root,
        "branch": git(root, "branch", "--show-current").stdout.strip(),
        "head_exists": head_exists(root),
        "split_mode": args.split_mode,
        "requested_sign_mode": args.sign_mode,
        "changed_files": changed,
        "filtered_files": filtered,
        "excluded_files": excluded,
        "top_level_groups": top_level_groups(filtered),
        "categories": {
            "docs": [p for p in filtered if classify_path(p) == "docs"],
            "tests": [p for p in filtered if classify_path(p) == "tests"],
            "config": [p for p in filtered if classify_path(p) == "config"],
            "code": [p for p in filtered if classify_path(p) == "code"],
        },
        "submodules": collect_submodules(root),
        "sign_context": sign_context,
        "status": parse_status(root),
    }

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_coverage(args: argparse.Namespace) -> int:
    root = repo_root(args.repo)
    changed = changed_file_paths(root)
    planned = expand_targets(changed, args.planned)
    excluded = expand_targets(changed, args.exclude)
    covered = sorted(dict.fromkeys(planned + excluded))
    uncovered = [path for path in changed if path not in covered]

    payload = {
        "repo": root,
        "all_changed_files": changed,
        "planned_files": planned,
        "excluded_files": excluded,
        "uncovered_files": uncovered,
        "passed": not uncovered,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not uncovered else 1


def is_gpg_failure(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(pattern in lowered for pattern in GPG_ERROR_PATTERNS)


def resolve_effective_sign_mode(requested: str, sign_context: dict[str, object]) -> str:
    return requested if requested != "auto" else str(sign_context["suggested_sign_mode"])


def build_message_args(commit_type: str, title: str, bullets: list[str]) -> tuple[str, list[str]]:
    title = f"{commit_type}: {title}"
    message_args: list[str] = []
    message_args.extend(["-m", title])
    for bullet in bullets:
        message_args.extend(["-m", bullet])
    return title, message_args


def dry_run_payload(plan: CommitPlan) -> dict[str, object]:
    command = ["git", "-C", plan.root, "commit", *plan.message_args]
    if plan.effective_sign_mode == "signed":
        command.insert(4, "-S")
    return {
        "repo": plan.root,
        "files": plan.files,
        "requested_sign_mode": plan.requested_sign_mode,
        "effective_sign_mode": plan.effective_sign_mode,
        "title": plan.title,
        "bullets": plan.bullets,
        "attempted_commands": [command],
        "signed": False,
        "fallback_used": False,
    }


def stage_files(plan: CommitPlan, env: dict[str, str]) -> CmdResult:
    return git(plan.root, "add", "--", *plan.files, env=env)


def commit_attempt(plan: CommitPlan, env: dict[str, str], mode: str) -> tuple[CmdResult, dict[str, object]]:
    cmd = ["commit", *plan.message_args]
    if mode == "signed":
        cmd.insert(1, "-S")
    if mode == "fallback":
        cmd = ["-c", "commit.gpgsign=false", *cmd]
    result = git(plan.root, *cmd, env=env)
    attempt = {
        "command": ["git", "-C", plan.root, *cmd],
        "returncode": result.returncode,
        "stderr": result.stderr.strip(),
    }
    return result, attempt


def run_commit_flow(
    plan: CommitPlan,
    env: dict[str, str],
) -> CommitRun:
    attempted: list[dict[str, object]] = []
    if plan.effective_sign_mode != "signed":
        result, attempt = commit_attempt(plan, env, "unsigned")
        attempted.append(attempt)
        return CommitRun(result=result, attempted=attempted, signed=False, fallback_used=False)

    result, attempt = commit_attempt(plan, env, "signed")
    attempted.append(attempt)
    signed = result.returncode == 0
    fallback_used = False
    if result.returncode != 0 and plan.requested_sign_mode == "auto" and is_gpg_failure(result.stderr):
        fallback_used = True
        result, attempt = commit_attempt(plan, env, "fallback")
        attempted.append(attempt)
    return CommitRun(result=result, attempted=attempted, signed=signed, fallback_used=fallback_used)


def build_commit_payload(
    plan: CommitPlan,
    run: CommitRun,
    sign_context: dict[str, object],
) -> dict[str, object]:
    ok = run.result.returncode == 0
    sha = git(plan.root, "rev-parse", "HEAD").stdout.strip() if ok else ""
    return {
        "repo": plan.root,
        "ok": ok,
        "files": plan.files,
        "requested_sign_mode": plan.requested_sign_mode,
        "effective_sign_mode": plan.effective_sign_mode,
        "signed": run.signed,
        "fallback_used": run.fallback_used,
        "attempted_commands": run.attempted,
        "sha": sha,
        "stdout": run.result.stdout.strip(),
        "stderr": run.result.stderr.strip(),
        "sign_context": sign_context,
    }


def prepare_commit_plan(args: argparse.Namespace) -> tuple[CommitPlan, dict[str, object], dict[str, str]]:
    root = repo_root(args.repo)
    files = expand_targets(changed_file_paths(root), args.file)
    if not files:
        raise SystemExit("未指定可提交文件")
    if not args.title.strip():
        raise SystemExit("title 不能为空")

    sign_context = detect_signing(root, args.sign_mode if args.sign_mode != "auto" else None)
    requested = args.sign_mode
    effective = resolve_effective_sign_mode(requested, sign_context)
    title, message_args = build_message_args(args.type, args.title, args.bullet)
    plan = CommitPlan(
        root=root,
        files=files,
        requested_sign_mode=requested,
        effective_sign_mode=effective,
        title=title,
        bullets=args.bullet,
        message_args=message_args,
    )
    return plan, sign_context, current_env()


def command_commit(args: argparse.Namespace) -> int:
    plan, sign_context, env = prepare_commit_plan(args)
    if args.dry_run:
        payload = dry_run_payload(plan)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    add_result = stage_files(plan, env)
    if add_result.returncode != 0:
        payload = {
            "phase": "add",
            "ok": False,
            "files": plan.files,
            "stderr": add_result.stderr.strip(),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return add_result.returncode

    run = run_commit_flow(plan, env)
    payload = build_commit_payload(plan, run, sign_context)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else run.result.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hybrid helper for the commit skill")
    sub = parser.add_subparsers(dest="command", required=True)

    inventory = sub.add_parser("inventory", help="Collect repo inventory")
    inventory.add_argument("--repo", required=True)
    inventory.add_argument("--include", action="append", default=[])
    inventory.add_argument("--exclude", action="append", default=[])
    inventory.add_argument("--split-mode", choices=["auto", "single", "split"], default="auto")
    inventory.add_argument("--sign-mode", choices=["auto", "signed", "unsigned"], default="auto")
    inventory.add_argument("--json", action="store_true")
    inventory.set_defaults(func=command_inventory)

    coverage = sub.add_parser("coverage", help="Audit coverage of planned files")
    coverage.add_argument("--repo", required=True)
    coverage.add_argument("--planned", action="append", default=[])
    coverage.add_argument("--exclude", action="append", default=[])
    coverage.add_argument("--json", action="store_true")
    coverage.set_defaults(func=command_coverage)

    commit = sub.add_parser("commit", help="Create a commit from exact files")
    commit.add_argument("--repo", required=True)
    commit.add_argument("--file", action="append", required=True, default=[])
    commit_types = ["feat", "fix", "docs", "refactor", "test", "chore", "style", "perf"]
    commit.add_argument("--type", required=True, choices=commit_types)
    commit.add_argument("--title", required=True)
    commit.add_argument("--bullet", action="append", default=[])
    commit.add_argument("--sign-mode", choices=["auto", "signed", "unsigned"], default="auto")
    commit.add_argument("--dry-run", action="store_true")
    commit.add_argument("--json", action="store_true")
    commit.set_defaults(func=command_commit)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
