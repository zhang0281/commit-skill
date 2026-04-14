from __future__ import annotations

import os
import re
import sys

from .process import gpg, gpgconf, git_get

GPG_ERROR_PATTERNS = (
    "failed to sign the data",
    "signing failed",
    "no agent running",
    "can't connect to the gpg-agent",
    "failed to start gpg-agent",
    "pinentry",
)


def current_env() -> dict[str, str]:
    env = os.environ.copy()
    if sys.stdin.isatty():
        try:
            env["GPG_TTY"] = os.ttyname(sys.stdin.fileno())
        except OSError:
            pass
    return env


def _suggested_sign_mode(
    requested_sign_mode: str | None,
    signing_available: bool,
) -> str:
    if requested_sign_mode in {"signed", "unsigned"}:
        return requested_sign_mode
    return "signed" if signing_available else "unsigned"


def peek_signing(repo: str, requested_sign_mode: str | None = None) -> dict[str, object]:
    repo_gpgsign = git_get(repo, "commit.gpgsign")
    global_gpgsign = git_get(repo, "commit.gpgsign", global_scope=True)
    repo_signingkey = git_get(repo, "user.signingkey")
    global_signingkey = git_get(repo, "user.signingkey", global_scope=True)
    signing_available = bool(
        repo_gpgsign == "true"
        or global_gpgsign == "true"
        or repo_signingkey
        or global_signingkey
    )
    return {
        "probe_mode": "config-only",
        "has_tty": sys.stdin.isatty(),
        "gpg_tty": os.environ.get("GPG_TTY", ""),
        "gpg_agent_launch_ok": None,
        "gpg_agent_launch_stderr": "",
        "secret_key_ids": [],
        "repo_commit_gpgsign": repo_gpgsign,
        "global_commit_gpgsign": global_gpgsign,
        "repo_signingkey": repo_signingkey,
        "global_signingkey": global_signingkey,
        "suggested_sign_mode": _suggested_sign_mode(requested_sign_mode, signing_available),
        "signing_available": signing_available,
    }


def detect_signing(repo: str, requested_sign_mode: str | None = None) -> dict[str, object]:
    env = current_env()
    launch = gpgconf("--launch", "gpg-agent", env=env)
    secret_keys = gpg("--list-secret-keys", "--keyid-format", "LONG", env=env)
    key_ids: list[str] = []
    for line in secret_keys.stdout.splitlines():
        if not line.startswith("sec"):
            continue
        match = re.search(r"/([0-9A-F]{16,40})\s", line)
        if match:
            key_ids.append(match.group(1))

    base = peek_signing(repo, requested_sign_mode=requested_sign_mode)
    signing_available = bool(key_ids) or bool(base["signing_available"])
    return {
        **base,
        "probe_mode": "full",
        "gpg_tty": env.get("GPG_TTY", ""),
        "gpg_agent_launch_ok": launch.returncode == 0,
        "gpg_agent_launch_stderr": launch.stderr.strip(),
        "secret_key_ids": key_ids,
        "suggested_sign_mode": _suggested_sign_mode(requested_sign_mode, signing_available),
        "signing_available": signing_available,
    }


def resolve_sign_mode(requested: str, sign_context: dict[str, object]) -> str:
    return requested if requested != "auto" else str(sign_context["suggested_sign_mode"])


def is_gpg_failure(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(pattern in lowered for pattern in GPG_ERROR_PATTERNS)
