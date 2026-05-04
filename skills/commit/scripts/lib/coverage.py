from __future__ import annotations

import json
from pathlib import Path

from .errors import ErrorCode, SkillError
from .inventory import expand_targets, file_fingerprint, matches_pattern

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
    kind = commit.get("kind", "repo")
    if kind not in {"repo", "submodule_internal", "submodule_pointer"}:
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "commit kind 非法", {"commit": commit})
    if require_messages:
        validate_message_fields(commit)


def validate_plan_file(data: dict[str, object], require_messages: bool) -> dict[str, object]:
    repo = data.get("repo")
    if not isinstance(repo, str) or not repo:
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "计划 JSON 缺少 repo")
    commits = data.get("commits")
    if not isinstance(commits, list):
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "计划 JSON 缺少 commits 列表")
    for commit in commits:
        validate_commit_entry(commit, require_messages=require_messages)
    exclude = data.get("exclude", [])
    if not isinstance(exclude, list):
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "exclude 必须为数组")
    validate_repo_paths(data)
    validate_commit_path_uniqueness_and_order(data)
    return data


def allowed_repo_paths(plan: dict[str, object]) -> set[str]:
    allowed = {str(plan["repo"])}
    baseline = plan.get("coverage_baseline", {})
    for entry in baseline.get("submodule_changes", []):
        allowed.add(str(entry["repo_path"]))
    return allowed


def validate_repo_paths(plan: dict[str, object]) -> None:
    allowed = allowed_repo_paths(plan)
    invalid = [str(commit["repo_path"]) for commit in plan.get("commits", []) if str(commit["repo_path"]) not in allowed]
    if invalid:
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "commit repo_path 不属于本次快照允许仓库", {"invalid_repo_paths": sorted(set(invalid)), "allowed_repo_paths": sorted(allowed)})


def validate_commit_path_uniqueness_and_order(plan: dict[str, object]) -> None:
    seen: set[tuple[str, str]] = set()
    duplicates: list[dict[str, str]] = []
    internal_seen: set[str] = set()
    pointer_before_internal: list[str] = []
    dirty_submodules = {str(entry.get("submodule_path", "")) for entry in plan.get("coverage_baseline", {}).get("submodule_changes", [])}
    for commit in plan.get("commits", []):
        repo_path = str(commit["repo_path"])
        for path in commit["paths"]:
            key = (repo_path, str(path))
            if key in seen:
                duplicates.append({"repo_path": repo_path, "path": str(path)})
            seen.add(key)
        kind = commit.get("kind", "repo")
        if kind == "submodule_internal":
            submodule_path = str(commit.get("submodule_path") or str(commit.get("id", "")).removeprefix("submodule-internal:"))
            internal_seen.add(submodule_path)
        if kind == "submodule_pointer":
            for path in commit["paths"]:
                path_str = str(path)
                if path_str in dirty_submodules and path_str not in internal_seen:
                    pointer_before_internal.append(path_str)
    if duplicates:
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "同一路径不可出现在多个 commit 中", {"duplicates": duplicates})
    if pointer_before_internal:
        raise SkillError(ErrorCode.PLAN_FILE_INVALID, "submodule pointer commit 必须晚于 internal commit", {"submodules": sorted(set(pointer_before_internal))})


def current_fingerprint_map(repo_path: str, paths: list[str]) -> dict[str, dict[str, object]]:
    return {item["path"]: item for item in [file_fingerprint(repo_path, path) for path in paths]}


def fingerprint_drift(expected: list[dict[str, object]], current: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    drift: list[dict[str, object]] = []
    for item in expected:
        path = str(item.get("path", ""))
        now = current.get(path)
        if now != item:
            drift.append({"path": path, "expected": item, "current": now})
    return drift


def collect_snapshot_drift(plan: dict[str, object]) -> dict[str, object]:
    baseline = plan.get("coverage_baseline", {})
    root_expected = [item for item in baseline.get("root_fingerprints", []) if str(item.get("path", "")) in set(baseline.get("root_changed_files", []))]
    root_current = current_fingerprint_map(str(plan["repo"]), [str(item.get("path", "")) for item in root_expected])
    root_drift = fingerprint_drift(root_expected, root_current)
    submodule_drift: list[dict[str, object]] = []
    for entry in baseline.get("submodule_changes", []):
        expected = list(entry.get("fingerprints", []))
        current = current_fingerprint_map(str(entry["repo_path"]), [str(item.get("path", "")) for item in expected])
        drift = fingerprint_drift(expected, current)
        if drift:
            submodule_drift.append({"repo_path": entry["repo_path"], "submodule_path": entry.get("submodule_path", ""), "drift": drift})
    return {"root_drift": root_drift, "submodule_drift": submodule_drift}


def collect_plan_paths(plan: dict[str, object], repo_path: str) -> list[str]:
    collected: list[str] = []
    for commit in plan["commits"]:
        if commit["repo_path"] == repo_path:
            collected.extend(commit["paths"])
    return sorted(dict.fromkeys(collected))


def allowed_root_snapshot_paths(plan: dict[str, object]) -> list[str]:
    baseline = plan.get("coverage_baseline", {})
    root_changed = [str(path) for path in baseline.get("root_changed_files", [])]
    pointer_paths = [str(item["submodule_path"]) for item in baseline.get("required_pointer_updates", [])]
    return sorted(dict.fromkeys(root_changed + pointer_paths))


def allowed_submodule_snapshot_paths(plan: dict[str, object]) -> dict[str, list[str]]:
    baseline = plan.get("coverage_baseline", {})
    allowed: dict[str, list[str]] = {}
    for entry in baseline.get("submodule_changes", []):
        repo_path = str(entry["repo_path"])
        allowed[repo_path] = [str(path) for path in entry.get("changed_files", [])]
    return allowed


def resolve_snapshot_paths(allowed_paths: list[str], requested_paths: list[str]) -> tuple[list[str], list[str]]:
    resolved: list[str] = []
    invalid: list[str] = []
    for requested in requested_paths:
        matched = [path for path in allowed_paths if matches_pattern(path, [requested])]
        if matched:
            resolved.extend(matched)
            continue
        invalid.append(requested)
    return sorted(dict.fromkeys(resolved)), sorted(dict.fromkeys(invalid))


def resolve_commit_paths(plan: dict[str, object], repo_path: str, requested_paths: list[str]) -> tuple[list[str], list[str]]:
    plan_repo = str(plan["repo"])
    if repo_path == plan_repo:
        return resolve_snapshot_paths(allowed_root_snapshot_paths(plan), requested_paths)
    allowed_map = allowed_submodule_snapshot_paths(plan)
    return resolve_snapshot_paths(allowed_map.get(repo_path, []), requested_paths)


def collect_resolved_plan_paths(plan: dict[str, object], repo_path: str) -> tuple[list[str], list[str]]:
    resolved: list[str] = []
    invalid: list[str] = []
    for commit in plan["commits"]:
        if commit["repo_path"] != repo_path:
            continue
        commit_resolved, commit_invalid = resolve_commit_paths(
            plan,
            repo_path,
            [str(path) for path in commit["paths"]],
        )
        resolved.extend(commit_resolved)
        invalid.extend(commit_invalid)
    return sorted(dict.fromkeys(resolved)), sorted(dict.fromkeys(invalid))


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
    root_planned, out_of_snapshot_root_paths = collect_resolved_plan_paths(plan, str(plan["repo"]))
    root_excluded = expand_targets(root_changed, explicit_excluded + list(plan.get("exclude", [])))
    root_uncovered = [path for path in root_changed if path not in set(root_planned + root_excluded)]

    submodule_uncovered: list[dict[str, object]] = []
    out_of_snapshot_submodule_paths: list[dict[str, object]] = []
    for entry in baseline.get("submodule_changes", []):
        repo_path = entry["repo_path"]
        changed_files = list(entry.get("changed_files", []))
        planned_files, invalid_paths = collect_resolved_plan_paths(plan, repo_path)
        uncovered = [path for path in changed_files if path not in planned_files]
        if uncovered:
            submodule_uncovered.append({
                "repo_path": repo_path,
                "submodule_path": entry.get("submodule_path", ""),
                "uncovered_files": uncovered,
            })
        if invalid_paths:
            out_of_snapshot_submodule_paths.append({
                "repo_path": repo_path,
                "submodule_path": entry.get("submodule_path", ""),
                "paths": invalid_paths,
            })

    required_pointer_updates = [item["submodule_path"] for item in baseline.get("required_pointer_updates", [])]
    pointer_planned = root_planned
    missing_pointer_updates = [path for path in required_pointer_updates if path not in pointer_planned]

    drift = collect_snapshot_drift(plan)
    passed = (
        not root_uncovered
        and not submodule_uncovered
        and not missing_pointer_updates
        and not out_of_snapshot_root_paths
        and not out_of_snapshot_submodule_paths
        and not drift["root_drift"]
        and not drift["submodule_drift"]
    )
    return {
        "repo": plan["repo"],
        "root_changed_files": root_changed,
        "planned_root_files": root_planned,
        "excluded_root_files": root_excluded,
        "root_uncovered_files": root_uncovered,
        "out_of_snapshot_root_paths": out_of_snapshot_root_paths,
        "submodule_uncovered": submodule_uncovered,
        "out_of_snapshot_submodule_paths": out_of_snapshot_submodule_paths,
        "missing_pointer_updates": missing_pointer_updates,
        "snapshot_drift": drift,
        "passed": passed,
    }
