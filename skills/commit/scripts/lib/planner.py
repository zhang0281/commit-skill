from __future__ import annotations

from pathlib import Path

from .inventory import build_inventory, top_level_groups
from .signing import resolve_sign_mode

SCHEMA_VERSION = 1


def repo_commit_template(commit_id: str, repo: str, paths: list[str], category: str, sign_mode: str) -> dict[str, object]:
    type_hint_map = {
        "docs": "docs",
        "tests": "test",
        "config": "chore",
        "code": "refactor",
        "mixed": "refactor",
    }
    title_hint_map = {
        "docs": "更新文档",
        "tests": "补充测试",
        "config": "整理配置",
        "code": "整理代码改动",
        "mixed": "整理相关改动",
    }
    return {
        "id": commit_id,
        "kind": "repo",
        "repo_path": repo,
        "paths": paths,
        "category": category,
        "type": "",
        "title": "",
        "bullets": [],
        "type_hint": type_hint_map.get(category, "refactor"),
        "title_hint": title_hint_map.get(category, "整理改动"),
        "bullet_hints": [f"处理 {len(paths)} 个文件的相关改动"],
        "reason": "由 plan 子命令按路径与类别归组，待 AI 做最终语义裁决。",
        "sign_mode": sign_mode,
    }


def submodule_internal_template(submodule: dict[str, object], sign_mode: str) -> dict[str, object]:
    path = str(submodule["path"])
    return {
        "id": f"submodule-internal:{path}",
        "kind": "submodule_internal",
        "repo_path": str(submodule["absolute_path"]),
        "paths": list(submodule["dirty_files"]),
        "category": "submodule",
        "type": "",
        "title": "",
        "bullets": [],
        "type_hint": "chore",
        "title_hint": f"更新子模块 {path} 内部改动",
        "bullet_hints": [f"处理子模块 {path} 内部文件变更"],
        "reason": "submodule dirty files 需先在子模块仓库内提交。",
        "sign_mode": sign_mode,
    }


def submodule_pointer_template(repo: str, submodule: dict[str, object], sign_mode: str) -> dict[str, object]:
    path = str(submodule["path"])
    return {
        "id": f"submodule-pointer:{path}",
        "kind": "submodule_pointer",
        "repo_path": repo,
        "paths": [path],
        "category": "submodule_pointer",
        "type": "",
        "title": "",
        "bullets": [],
        "type_hint": "chore",
        "title_hint": f"更新子模块 {Path(path).name} 引用",
        "bullet_hints": [f"同步子模块 {path} 的 gitlink 指针"],
        "reason": "子模块内部提交或已前进 HEAD 后，父仓库需更新 pointer。",
        "sign_mode": sign_mode,
    }


def build_repo_commit_templates(repo: str, inventory: dict[str, object], split_mode: str, sign_mode: str) -> list[dict[str, object]]:
    root_changed = list(inventory["root_changed_files"])
    if not root_changed:
        return []
    if split_mode == "single":
        return [repo_commit_template("repo:single", repo, root_changed, "mixed", sign_mode)]

    categories = inventory["categories"]
    templates: list[dict[str, object]] = []
    for commit_id, category_key in (("repo:docs", "docs"), ("repo:tests", "tests"), ("repo:config", "config")):
        if categories[category_key]:
            templates.append(repo_commit_template(commit_id, repo, categories[category_key], category_key, sign_mode))

    for group_name, paths in top_level_groups(categories["code"]).items():
        templates.append(repo_commit_template(f"repo:code:{group_name}", repo, paths, "code", sign_mode))
    return templates if split_mode == "split" else (templates or [repo_commit_template("repo:auto", repo, root_changed, "mixed", sign_mode)])


def build_submodule_templates(repo: str, submodules: list[dict[str, object]], sign_mode: str) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    commits: list[dict[str, object]] = []
    submodule_changes: list[dict[str, object]] = []
    required_pointer_updates: list[dict[str, object]] = []
    for submodule in submodules:
        if submodule["dirty"]:
            commits.append(submodule_internal_template(submodule, sign_mode))
            submodule_changes.append(
                {
                    "repo_path": submodule["absolute_path"],
                    "submodule_path": submodule["path"],
                    "changed_files": submodule["dirty_files"],
                }
            )
        if submodule["requires_pointer_update"]:
            commits.append(submodule_pointer_template(repo, submodule, sign_mode))
            required_pointer_updates.append({"repo_path": repo, "submodule_path": submodule["path"]})
    return commits, submodule_changes, required_pointer_updates


def build_plan(
    repo: str,
    includes: list[str],
    excludes: list[str],
    split_mode: str,
    sign_mode: str,
    *,
    lazy_signing: bool = False,
) -> dict[str, object]:
    inventory = build_inventory(
        repo,
        includes,
        excludes,
        split_mode,
        sign_mode,
        lazy_signing=lazy_signing,
    )
    resolved_sign_mode = resolve_sign_mode(sign_mode, inventory["sign_context"])
    commits = build_repo_commit_templates(repo, inventory, split_mode, resolved_sign_mode)
    submodule_commits, submodule_changes, required_pointer_updates = build_submodule_templates(
        repo,
        inventory["submodules"],
        resolved_sign_mode,
    )
    commits.extend(submodule_commits)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "commit-skill",
        "repo": repo,
        "branch": inventory["branch"],
        "requested": {"split_mode": split_mode, "sign_mode": sign_mode},
        "sign_context": inventory["sign_context"],
        "inventory": inventory,
        "commits": commits,
        "exclude": list(inventory["explicit_excluded_files"]),
        "coverage_baseline": {
            "root_changed_files": list(inventory["root_changed_files"]),
            "explicit_excluded_files": list(inventory["explicit_excluded_files"]),
            "submodule_changes": submodule_changes,
            "required_pointer_updates": required_pointer_updates,
        },
        "notes": [
            "AI 应先运行 plan，再基于 commits 列表做语义合并、拆分与中文标题/正文裁决。",
            "执行前应再次运行 coverage --plan-file，确保无 uncovered 项。",
            "Codex 与 Claude Code 均调用同一组 Python 脚本；差异只在外层 skill metadata。",
        ],
    }
