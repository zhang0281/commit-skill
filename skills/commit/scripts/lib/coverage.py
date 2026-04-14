from __future__ import annotations

import json
from pathlib import Path

from .errors import ErrorCode, SkillError
from .inventory import expand_targets

ALLOWED_TYPES = {"feat", "fix", "docs", "refactor", "test", "chore", "style", "perf"}


def load_plan_file(path: str) -> dict[str, object]:
    plan_path = Path(path)
    if not plan_path.exists():
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "计划 JSON 文件不存在", {"plan_file": path})
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, f"计划 JSON 解析失败: {exc}", {"plan_file": path}) from exc
    if not isinstance(data, dict):
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "计划 JSON 顶层必须为对象", {"plan_file": path})
    return data


def require_non_empty_str(commit: dict[str, object], field: str) -> None:
    value = commit.get(field)
    if isinstance(value, str) and value:
        return
    raise SkillError(ErrorCode.PLAN_FILE_INVALID, f"commit 缺少 {field}", {"commit": commit})


def require_non_empty_list(commit: dict[str, object], field: str) -> None:
    value = commit.get(field)
    if isinstance(value, list) and value:
        return
    raise SkillError(ErrorCode.PLAN_FILE_INVALID, f"commit 缺少 {field}", {"commit": commit})


def validate_message_fields(commit: dict[str, object]) -> None:
    if commit.get("type") not in ALLOWED_TYPES:
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "commit type 非法或为空", {"commit": commit})
    title = commit.get("title")
    if not isinstance(title, str) or not title.strip():
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "commit title 不能为空", {"commit": commit})
    bullets = commit.get("bullets")
    if not isinstance(bullets, list) or not all(isinstance(item, str) for item in bullets):
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "commit bullets 必须为字符串数组", {"commit": commit})


def validate_commit_entry(commit: object, require_messages: bool) -> None:
    if not isinstance(commit, dict):
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "commits 条目必须为对象")
    require_non_empty_str(commit, "repo_path")
    require_non_empty_list(commit, "paths")
    if require_messages:
        validate_message_fields(commit)


def validate_plan_file(data: dict[str, object], require_messages: bool) -> dict[str, object]:
    repo = data.get("repo")
    if not isinstance(repo, str) or not repo:
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "计划 JSON 缺少 repo")
    commits = data.get("commits")
    if not isinstance(commits, list) or not commits:
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "计划 JSON 缺少 commits 列表")
    for commit in commits:
        validate_commit_entry(commit, require_messages=require_messages)
    exclude = data.get("exclude", [])
    if not isinstance(exclude, list):
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "exclude 必须为数组")
    return data


def collect_plan_paths(plan: dict[str, object], repo_path: str) -> list[str]:
    collected: list[str] = []
    for commit in plan["commits"]:
        if commit["repo_path"] == repo_path:
            collected.extend(commit["paths"])
    return sorted(dict.fromkeys(collected))


def run_coverage_from_args(changed: list[str], planned: list[str], exclude: list[str]) -> dict[str, object]:
    planned_files = expand_targets(changed, planned)
    excluded_files = expand_targets(changed, exclude)
    covered = sorted(dict.fromkeys(planned_files + excluded_files))
    uncovered = [path for path in changed if path not in covered]
    return {
        "all_changed_files": changed,
        "planned_files": planned_files,
        "excluded_files": excluded_files,
        "uncovered_files": uncovered,
        "passed": not uncovered,
    }


def run_coverage_from_plan(plan: dict[str, object]) -> dict[str, object]:
    baseline = plan.get("coverage_baseline", {})
    root_changed = list(baseline.get("root_changed_files", []))
    explicit_excluded = list(baseline.get("explicit_excluded_files", []))
    root_planned = expand_targets(root_changed, collect_plan_paths(plan, str(plan["repo"])))
    root_excluded = expand_targets(root_changed, explicit_excluded + list(plan.get("exclude", [])))
    root_uncovered = [path for path in root_changed if path not in set(root_planned + root_excluded)]

    submodule_uncovered: list[dict[str, object]] = []
    for entry in baseline.get("submodule_changes", []):
        repo_path = entry["repo_path"]
        changed_files = list(entry.get("changed_files", []))
        planned_files = expand_targets(changed_files, collect_plan_paths(plan, repo_path))
        uncovered = [path for path in changed_files if path not in planned_files]
        if uncovered:
            submodule_uncovered.append({
                "repo_path": repo_path,
                "submodule_path": entry.get("submodule_path", ""),
                "uncovered_files": uncovered,
            })

    required_pointer_updates = [item["submodule_path"] for item in baseline.get("required_pointer_updates", [])]
    pointer_planned = collect_plan_paths(plan, str(plan["repo"]))
    missing_pointer_updates = [path for path in required_pointer_updates if path not in pointer_planned]

    passed = not root_uncovered and not submodule_uncovered and not missing_pointer_updates
    return {
        "repo": plan["repo"],
        "root_changed_files": root_changed,
        "planned_root_files": root_planned,
        "excluded_root_files": root_excluded,
        "root_uncovered_files": root_uncovered,
        "submodule_uncovered": submodule_uncovered,
        "missing_pointer_updates": missing_pointer_updates,
        "passed": passed,
    }
