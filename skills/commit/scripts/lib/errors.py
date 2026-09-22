from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ErrorCode(IntEnum):
    OK = 0
    INVALID_ARGUMENT = 10
    NOT_GIT_REPO = 11
    PLAN_FILE_INVALID = 12
    MESSAGE_FILE_INVALID = 13
    MODEL_CONFIG_INVALID = 14
    GIT_STATUS_FAILED = 20
    GIT_DIFF_FAILED = 21
    GIT_ADD_FAILED = 22
    GIT_COMMIT_FAILED = 23
    COVERAGE_GAP = 30
    PLAN_APPLY_FAILED = 31
    PREFLIGHT_FAILED = 32
    GPG_REQUIRED_FAILED = 40
    GPG_AUTO_FAILED = 41
    SIGNATURE_VERIFY_FAILED = 42
    SUBMODULE_SCAN_FAILED = 50
    MODEL_REQUEST_FAILED = 60


@dataclass
class SkillError(Exception):
    code: ErrorCode
    message: str
    details: dict[str, object] | None = None

    @property
    def name(self) -> str:
        return self.code.name


def ok_payload(**extra: object) -> dict[str, object]:
    payload = {"ok": True, "error_code": ErrorCode.OK.name, "exit_code": int(ErrorCode.OK)}
    payload.update(extra)
    return payload


def error_payload(error: SkillError) -> dict[str, object]:
    payload = {
        "ok": False,
        "error_code": error.name,
        "exit_code": int(error.code),
        "message": error.message,
    }
    if error.details:
        payload["details"] = error.details
    return payload
