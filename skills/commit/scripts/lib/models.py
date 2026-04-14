from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CmdResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class CommitPlan:
    repo_path: str
    files: list[str]
    commit_type: str
    title: str
    bullets: list[str]
    requested_sign_mode: str
    effective_sign_mode: str

    @property
    def message_args(self) -> list[str]:
        args = ["-m", f"{self.commit_type}: {self.title}"]
        for bullet in self.bullets:
            args.extend(["-m", bullet])
        return args


@dataclass
class CommitRun:
    result: CmdResult
    attempts: list[dict[str, object]]
    signed: bool
    fallback_used: bool
