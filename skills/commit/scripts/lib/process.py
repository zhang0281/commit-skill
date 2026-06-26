from __future__ import annotations

import subprocess

from .errors import ErrorCode, SkillError
from .models import CmdResult


GIT = "git"
GPG = "gpg"
GPGCONF = "gpgconf"



def run_cmd(args: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> CmdResult:
    proc = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
    return CmdResult(args=args, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)



def git(repo: str, *extra: str, env: dict[str, str] | None = None) -> CmdResult:
    return run_cmd([GIT, "-C", repo, *extra], env=env)



def gpg(*extra: str, env: dict[str, str] | None = None) -> CmdResult:
    return run_cmd([GPG, *extra], env=env)



def gpgconf(*extra: str, env: dict[str, str] | None = None) -> CmdResult:
    return run_cmd([GPGCONF, *extra], env=env)



def repo_root(repo: str) -> str:
    result = git(repo, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise SkillError(ErrorCode.NOT_GIT_REPO, result.stderr.strip() or "无法识别 Git 仓库", {"repo": repo})
    return result.stdout.strip()



def head_exists(repo: str) -> bool:
    return git(repo, "rev-parse", "--verify", "HEAD").returncode == 0


def diff_stat_lines(repo: str, paths: list[str]) -> list[str]:
    if not paths:
        return []
    has_head = head_exists(repo)
    if has_head:
        result = git(repo, "diff", "--stat=120", "HEAD", "--", *paths)
    else:
        result = git(repo, "diff", "--stat=120", "--cached", "--", *paths)
    if result.returncode != 0 or not result.stdout.strip():
        if has_head:
            result = git(repo, "diff", "--stat=120", "--cached", "--", *paths)
        if result.returncode != 0 or not result.stdout.strip():
            return [f" {path} (new file)" for path in paths[:20]]
    lines = [line for line in result.stdout.splitlines() if line.strip() and "|" in line]
    return lines[:20]


def diff_name_status(repo: str, paths: list[str]) -> list[dict[str, str]]:
    if not paths:
        return []
    has_head = head_exists(repo)
    if has_head:
        result = git(repo, "diff", "--name-status", "HEAD", "--", *paths)
    else:
        result = git(repo, "diff", "--name-status", "--cached", "--", *paths)
    if result.returncode != 0 or not result.stdout.strip():
        if has_head:
            result = git(repo, "diff", "--name-status", "--cached", "--", *paths)
        if result.returncode != 0 or not result.stdout.strip():
            return [{"status": "A", "path": path} for path in paths]
    entries: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            entries.append({"status": parts[0].strip(), "path": parts[1].strip()})
    return entries[:30]



def git_get(repo: str, key: str, global_scope: bool = False) -> str:
    args = ["config"]
    if global_scope:
        args.append("--global")
    args.extend(["--get", key])
    result = git(repo, *args)
    return result.stdout.strip() if result.returncode == 0 else ""
