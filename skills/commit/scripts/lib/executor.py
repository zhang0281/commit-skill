from __future__ import annotations

from .coverage import run_coverage_from_plan
from .errors import ErrorCode, SkillError, ok_payload
from .models import CommitPlan, CommitRun
from .process import git
from .signing import current_env, is_gpg_failure, resolve_sign_mode


def stage_files(plan: CommitPlan, env: dict[str, str]):
    result = git(plan.repo_path, "add", "--", *plan.files, env=env)
    if result.returncode == 0:
        return result
    details = {"repo_path": plan.repo_path, "files": plan.files}
    raise SkillError(ErrorCode.GIT_ADD_FAILED, result.stderr.strip() or "git add 失败", details)


def commit_attempt(plan: CommitPlan, env: dict[str, str], mode: str):
    cmd = ["commit", *plan.message_args]
    if mode == "signed":
        cmd.insert(1, "-S")
    if mode == "fallback":
        cmd = ["-c", "commit.gpgsign=false", *cmd]
    result = git(plan.repo_path, *cmd, env=env)
    attempt = {"command": ["git", "-C", plan.repo_path, *cmd], "returncode": result.returncode, "stderr": result.stderr.strip()}
    return result, attempt


def finalize_commit_result(plan: CommitPlan, run: CommitRun) -> CommitRun:
    if run.result.returncode == 0:
        return run
    details = {"repo_path": plan.repo_path, "files": plan.files, "attempts": run.attempts}
    if plan.requested_sign_mode == "signed":
        raise SkillError(ErrorCode.GPG_REQUIRED_FAILED, run.result.stderr.strip() or "signed commit 失败", details)
    if run.fallback_used:
        raise SkillError(ErrorCode.GPG_AUTO_FAILED, run.result.stderr.strip() or "自动签名失败且 fallback 失败", details)
    raise SkillError(ErrorCode.GIT_COMMIT_FAILED, run.result.stderr.strip() or "git commit 失败", details)


def unsigned_commit(plan: CommitPlan, env: dict[str, str]) -> CommitRun:
    result, attempt = commit_attempt(plan, env, "unsigned")
    return finalize_commit_result(plan, CommitRun(result=result, attempts=[attempt], signed=False, fallback_used=False))


def signed_commit(plan: CommitPlan, env: dict[str, str]) -> CommitRun:
    result, attempt = commit_attempt(plan, env, "signed")
    attempts = [attempt]
    if result.returncode == 0:
        return CommitRun(result=result, attempts=attempts, signed=True, fallback_used=False)
    if not is_gpg_failure(result.stderr):
        return finalize_commit_result(plan, CommitRun(result=result, attempts=attempts, signed=False, fallback_used=False))
    if plan.requested_sign_mode == "signed":
        return finalize_commit_result(plan, CommitRun(result=result, attempts=attempts, signed=False, fallback_used=False))
    fallback_result, fallback_attempt = commit_attempt(plan, env, "fallback")
    attempts.append(fallback_attempt)
    return finalize_commit_result(plan, CommitRun(result=fallback_result, attempts=attempts, signed=False, fallback_used=True))


def run_commit(plan: CommitPlan) -> CommitRun:
    env = current_env()
    stage_files(plan, env)
    if plan.effective_sign_mode == "signed":
        return signed_commit(plan, env)
    return unsigned_commit(plan, env)


def apply_plan(plan: dict[str, object], sign_context: dict[str, object], sign_mode_override: str | None = None) -> dict[str, object]:
    coverage = run_coverage_from_plan(plan)
    if not coverage["passed"]:
        raise SkillError(ErrorCode.COVERAGE_GAP, "计划 JSON 未覆盖全部改动", coverage)

    requested = sign_mode_override or str(plan.get("requested", {}).get("sign_mode", "auto"))
    effective_global = resolve_sign_mode(requested, sign_context)
    results: list[dict[str, object]] = []
    for commit_entry in plan["commits"]:
        requested_mode = str(commit_entry.get("sign_mode") or requested)
        effective_mode = resolve_sign_mode(requested_mode, sign_context)
        if requested_mode == "auto":
            effective_mode = effective_global
        commit_plan = CommitPlan(
            repo_path=str(commit_entry["repo_path"]),
            files=[str(path) for path in commit_entry["paths"]],
            commit_type=str(commit_entry["type"]),
            title=str(commit_entry["title"]),
            bullets=[str(item) for item in commit_entry.get("bullets", [])],
            requested_sign_mode=requested_mode,
            effective_sign_mode=effective_mode,
        )
        run = run_commit(commit_plan)
        sha = git(commit_plan.repo_path, "rev-parse", "HEAD").stdout.strip()
        results.append(
            {
                "id": commit_entry.get("id", ""),
                "repo_path": commit_plan.repo_path,
                "paths": commit_plan.files,
                "sha": sha,
                "signed": run.signed,
                "fallback_used": run.fallback_used,
                "attempts": run.attempts,
                "stdout": run.result.stdout.strip(),
            }
        )

    return ok_payload(repo=plan["repo"], sign_mode=requested, effective_sign_mode=effective_global, results=results)
