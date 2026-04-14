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



def git_get(repo: str, key: str, global_scope: bool = False) -> str:
    args = ["config"]
    if global_scope:
        args.append("--global")
    args.extend(["--get", key])
    result = git(repo, *args)
    return result.stdout.strip() if result.returncode == 0 else ""
