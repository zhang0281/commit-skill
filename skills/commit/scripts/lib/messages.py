from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from .inventory import classify_path, top_level_groups
from .coverage import validate_message_fields, validate_plan_file
from .errors import ErrorCode, SkillError

MESSAGE_SCHEMA_VERSION = 1
TEMPLATE_ONLY_KEYS = {
    "kind",
    "scope_hint",
    "paths_count",
    "paths_preview",
    "type_hint",
    "title_hint",
    "bullet_hints",
    "must_cover",
}
ALLOWED_MESSAGE_KEYS = {"id", "type", "title", "bullets"} | TEMPLATE_ONLY_KEYS
MAX_SCOPE_LABELS = 3


def format_cn_list(items: list[str]) -> str:
    values = [item for item in items if item]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]}、{values[1]}"
    return "、".join(values[:-1]) + f"、{values[-1]}"


def scope_labels(paths: list[str]) -> list[str]:
    groups = list(top_level_groups(paths))
    if len(groups) <= MAX_SCOPE_LABELS:
        return groups
    return groups[:MAX_SCOPE_LABELS]


def category_labels(paths: list[str], pointer_paths: set[str]) -> list[str]:
    labels: list[str] = []
    root_paths = [path for path in paths if path not in pointer_paths]
    categories = {classify_path(path) for path in root_paths}
    mapping = {"docs": "文档", "tests": "测试", "config": "配置", "code": "代码"}
    for key in ("docs", "tests", "config", "code"):
        if key in categories:
            labels.append(mapping[key])
    if any(path in pointer_paths for path in paths):
        labels.append("子模块引用")
    return labels


def build_commit_must_cover(plan: dict[str, object], commit: dict[str, object]) -> dict[str, object]:
    paths = [str(path) for path in commit.get("paths", [])]
    pointer_paths = {
        str(item["submodule_path"])
        for item in plan.get("coverage_baseline", {}).get("required_pointer_updates", [])
    }
    bullets: list[str] = []
    commit_id = str(commit.get("id", ""))
    kind = str(commit.get("kind", "repo"))
    submodule_path = str(commit.get("submodule_path", ""))

    if kind == "submodule_internal" and submodule_path:
        bullets.append(f"涉及子模块 {submodule_path}")
        bullets.append(f"处理子模块 {submodule_path} 内部 {len(paths)} 个文件改动")
    else:
        labels = scope_labels(paths)
        if labels:
            suffix = "" if len(set(labels)) == len(labels) == len(list(top_level_groups(paths))) else f" 等 {len(list(top_level_groups(paths)))} 处路径"
            bullets.append(f"涉及 {format_cn_list(labels)}{suffix}")
        root_paths = [path for path in paths if path not in pointer_paths]
        if root_paths:
            bullets.append(f"处理 {len(root_paths)} 个根仓文件改动")
        pointer_count = len([path for path in paths if path in pointer_paths])
        if pointer_count:
            bullets.append(f"同步 {pointer_count} 个子模块 gitlink 指针")

    labels = category_labels(paths, pointer_paths)
    if labels:
        bullets.append(f"包含 {format_cn_list(labels)} 改动")

    deduped: list[str] = []
    for bullet in bullets:
        if bullet and bullet not in deduped:
            deduped.append(bullet)
    return {
        "id": commit_id,
        "bullets": deduped,
        "recommended_max_bullets": max(2, len(deduped)),
    }


def apply_message_coverage(plan: dict[str, object]) -> dict[str, object]:
    audited = deepcopy(plan)
    audits: list[dict[str, object]] = []
    for commit in audited.get("commits", []):
        must_cover = build_commit_must_cover(audited, commit)
        combined = "\n".join([str(commit.get("title", "")), *[str(item) for item in commit.get("bullets", [])]])
        existing_bullets = [str(item) for item in commit.get("bullets", [])]
        missing = [bullet for bullet in must_cover["bullets"] if bullet not in combined]
        for bullet in missing:
            if bullet not in existing_bullets:
                existing_bullets.append(bullet)
        commit["bullets"] = existing_bullets
        commit["must_cover"] = must_cover
        audits.append(
            {
                "id": str(commit.get("id", "")),
                "auto_appended_bullets": missing,
                "final_bullets": existing_bullets,
            }
        )
    audited["message_coverage_audit"] = audits
    return audited


def load_message_file(path: str) -> dict[str, object]:
    message_path = Path(path)
    if not message_path.exists():
        raise SkillError(ErrorCode.MESSAGE_FILE_INVALID, "提交消息 JSON 文件不存在", {"messages_file": path})
    try:
        data = json.loads(message_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SkillError(ErrorCode.MESSAGE_FILE_INVALID, f"提交消息 JSON 解析失败: {exc}", {"messages_file": path}) from exc
    if not isinstance(data, dict):
        raise SkillError(ErrorCode.MESSAGE_FILE_INVALID, "提交消息 JSON 顶层必须为对象", {"messages_file": path})
    return data


def build_message_template(plan: dict[str, object]) -> dict[str, object]:
    validated = validate_plan_file(plan, require_messages=False)
    commits: list[dict[str, object]] = []
    for commit in validated["commits"]:
        paths = [str(path) for path in commit.get("paths", [])]
        commits.append(
            {
                "id": str(commit.get("id", "")),
                "kind": str(commit.get("kind", "repo")),
                "scope_hint": str(commit.get("submodule_path") or commit.get("category") or commit.get("kind") or "repo"),
                "paths_count": len(paths),
                "paths_preview": paths[:12],
                "type_hint": str(commit.get("type_hint", "")),
                "title_hint": str(commit.get("title_hint", "")),
                "bullet_hints": [str(item) for item in commit.get("bullet_hints", [])[:6]],
                "must_cover": build_commit_must_cover(validated, commit),
                "type": "",
                "title": "",
                "bullets": [],
            }
        )
    return {
        "schema_version": MESSAGE_SCHEMA_VERSION,
        "tool": "commit-skill",
        "mode": "message-only",
        "repo": validated["repo"],
        "branch": validated.get("branch", ""),
        "rules": [
            "只填写 commits[].id/type/title/bullets。",
            "不得新增、删除、合并、拆分或重排 commit。",
            "title 只写 Conventional Commit 冒号后的中文标题正文。",
            "bullets 为字符串数组，可留空。",
            "优先直接复用 must_cover.bullets；若遗漏，脚本会在 apply-plan 前自动补齐。",
        ],
        "commits": commits,
    }


def validate_message_file(data: dict[str, object], plan: dict[str, object]) -> dict[str, dict[str, object]]:
    if "repo" in data and data["repo"] != plan["repo"]:
        raise SkillError(
            ErrorCode.MESSAGE_FILE_INVALID,
            "提交消息 JSON 的 repo 与计划不一致",
            {"message_repo": data["repo"], "plan_repo": plan["repo"]},
        )

    commits = data.get("commits")
    if not isinstance(commits, list):
        raise SkillError(ErrorCode.MESSAGE_FILE_INVALID, "提交消息 JSON 缺少 commits 列表", {"messages_file": data})

    expected_ids = [str(commit.get("id", "")) for commit in plan.get("commits", [])]
    seen_ids: list[str] = []
    by_id: dict[str, dict[str, object]] = {}
    for entry in commits:
        if not isinstance(entry, dict):
            raise SkillError(ErrorCode.MESSAGE_FILE_INVALID, "提交消息条目必须为对象", {"entry": entry})
        extra_keys = sorted(set(entry) - ALLOWED_MESSAGE_KEYS)
        if extra_keys:
            raise SkillError(ErrorCode.MESSAGE_FILE_INVALID, "提交消息条目包含非法字段", {"entry": entry, "extra_keys": extra_keys})
        commit_id = entry.get("id")
        if not isinstance(commit_id, str) or not commit_id:
            raise SkillError(ErrorCode.MESSAGE_FILE_INVALID, "提交消息条目缺少 id", {"entry": entry})
        if commit_id in by_id:
            raise SkillError(ErrorCode.MESSAGE_FILE_INVALID, "提交消息条目 id 重复", {"id": commit_id})
        minimal_entry = {
            "id": commit_id,
            "type": entry.get("type"),
            "title": entry.get("title"),
            "bullets": entry.get("bullets"),
        }
        validate_message_fields(minimal_entry)
        seen_ids.append(commit_id)
        by_id[commit_id] = minimal_entry

    missing_ids = [commit_id for commit_id in expected_ids if commit_id not in by_id]
    unexpected_ids = [commit_id for commit_id in by_id if commit_id not in set(expected_ids)]
    if seen_ids != expected_ids or missing_ids or unexpected_ids:
        raise SkillError(
            ErrorCode.MESSAGE_FILE_INVALID,
            "提交消息 JSON 与计划中的 commit 集合或顺序不一致",
            {
                "expected_ids": expected_ids,
                "seen_ids": seen_ids,
                "missing_ids": missing_ids,
                "unexpected_ids": unexpected_ids,
            },
        )
    return by_id


def merge_message_file(plan: dict[str, object], data: dict[str, object]) -> dict[str, object]:
    validated_plan = validate_plan_file(plan, require_messages=False)
    messages_by_id = validate_message_file(data, validated_plan)
    merged = deepcopy(validated_plan)
    for commit in merged["commits"]:
        payload = messages_by_id[str(commit["id"])]
        commit["type"] = payload["type"]
        commit["title"] = payload["title"]
        commit["bullets"] = payload["bullets"]
    audited = apply_message_coverage(merged)
    return validate_plan_file(audited, require_messages=True)
