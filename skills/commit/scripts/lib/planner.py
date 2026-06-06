from __future__ import annotations

from .inventory import build_inventory, fingerprint_paths
from .signing import resolve_sign_mode

SCHEMA_VERSION = 1


def repo_commit_template(
    commit_id: str,
    repo: str,
    paths: list[str],
    category: str,
    sign_mode: str,
    effective_sign_mode_hint: str | None = None,
    *,
    type_hint: str | None = None,
    title_hint: str | None = None,
    bullet_hints: list[str] | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    type_hint_map = {
        "docs": "docs",
        "tests": "test",
        "config": "chore",
        "code": "refactor",
        "mixed": "refactor",
        "submodule_pointer": "chore",
    }
    title_hint_map = {
        "docs": "更新文档",
        "tests": "补充测试",
        "config": "整理配置",
        "code": "整理代码改动",
        "mixed": "整理相关改动",
        "submodule_pointer": "同步子模块引用",
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
        "type_hint": type_hint or type_hint_map.get(category, "refactor"),
        "title_hint": title_hint or title_hint_map.get(category, "整理改动"),
        "bullet_hints": bullet_hints or [f"处理 {len(paths)} 个文件的相关改动"],
        "reason": reason or "由 plan 子命令固定候选提交，AI 只负责填写 commit message。",
        "sign_mode": sign_mode,
        "effective_sign_mode_hint": effective_sign_mode_hint or sign_mode,
    }


def submodule_internal_template(
    submodule: dict[str, object],
    sign_mode: str,
    effective_sign_mode_hint: str | None = None,
) -> dict[str, object]:
    path = str(submodule["path"])
    return {
        "id": f"submodule-internal:{path}",
        "kind": "submodule_internal",
        "repo_path": str(submodule["absolute_path"]),
        "submodule_path": path,
        "paths": list(submodule["dirty_files"]),
        "category": "submodule",
        "type": "",
        "title": "",
        "bullets": [],
        "type_hint": "chore",
        "title_hint": f"更新子模块 {path} 内部改动",
        "bullet_hints": [f"处理子模块 {path} 内部文件变更"],
        "reason": "submodule dirty files 需先在子模块仓库内提交；AI 仅填写该提交的 message。",
        "sign_mode": sign_mode,
        "effective_sign_mode_hint": effective_sign_mode_hint or sign_mode,
    }


def root_single_commit_template(
    repo: str,
    root_changed_files: list[str],
    pointer_paths: list[str],
    sign_mode: str,
    effective_sign_mode_hint: str | None = None,
) -> dict[str, object] | None:
    paths = sorted(dict.fromkeys(root_changed_files + pointer_paths))
    if not paths:
        return None
    if pointer_paths and not root_changed_files:
        return repo_commit_template(
            "repo:submodule-pointers",
            repo,
            paths,
            "submodule_pointer",
            sign_mode,
            effective_sign_mode_hint,
            type_hint="chore",
            title_hint=f"同步 {len(pointer_paths)} 个子模块引用",
            bullet_hints=[f"更新 {path} 的 gitlink 指针" for path in pointer_paths[:6]],
            reason="父仓需记录子模块 gitlink 变更；多个子模块指针合并为一个根仓提交。",
        )
    if pointer_paths:
        return repo_commit_template(
            "repo:single",
            repo,
            paths,
            "mixed",
            sign_mode,
            effective_sign_mode_hint,
            type_hint="chore",
            title_hint="整理根仓改动并同步子模块引用",
            bullet_hints=[
                f"处理 {len(root_changed_files)} 个根仓文件改动",
                f"同步 {len(pointer_paths)} 个子模块 gitlink 指针",
            ],
            reason="单项目根仓固定为一个提交；若伴随子模块 pointer 变更，则一并收进根仓提交。",
        )
    return repo_commit_template(
        "repo:single",
        repo,
        paths,
        "mixed",
        sign_mode,
        effective_sign_mode_hint,
        type_hint="chore",
        title_hint="整理本次改动",
        bullet_hints=[f"处理 {len(root_changed_files)} 个根仓文件改动"],
        reason="单项目默认固定为一个根仓提交；AI 仅填写 message。",
    )


def build_submodule_templates(
    repo: str,
    submodules: list[dict[str, object]],
    sign_mode: str,
    effective_sign_mode_hint: str | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str], list[dict[str, object]]]:
    commits: list[dict[str, object]] = []
    submodule_changes: list[dict[str, object]] = []
    pointer_paths: list[str] = []
    required_pointer_updates: list[dict[str, object]] = []
    for submodule in submodules:
        if submodule["dirty"]:
            commits.append(submodule_internal_template(submodule, sign_mode, effective_sign_mode_hint))
            submodule_changes.append(
                {
                    "repo_path": submodule["absolute_path"],
                    "submodule_path": submodule["path"],
                    "changed_files": submodule["dirty_files"],
                    "fingerprints": fingerprint_paths(str(submodule["absolute_path"]), list(submodule["dirty_files"])),
                }
            )
        if submodule["requires_pointer_update"]:
            pointer_paths.append(str(submodule["path"]))
            required_pointer_updates.append({"repo_path": repo, "submodule_path": submodule["path"]})
    return commits, submodule_changes, sorted(dict.fromkeys(pointer_paths)), required_pointer_updates


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
    submodule_commits, submodule_changes, pointer_paths, required_pointer_updates = build_submodule_templates(
        repo,
        inventory["submodules"],
        sign_mode,
        resolved_sign_mode,
    )
    root_commit = root_single_commit_template(
        repo,
        list(inventory["root_changed_files"]),
        pointer_paths,
        sign_mode,
        resolved_sign_mode,
    )
    commits = list(submodule_commits)
    if root_commit:
        commits.append(root_commit)
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
            "root_fingerprints": fingerprint_paths(repo, list(inventory["root_changed_files"])),
            "explicit_excluded_files": list(inventory["explicit_excluded_files"]),
            "excluded_submodules": list(inventory.get("excluded_submodules", [])),
            "submodule_changes": submodule_changes,
            "required_pointer_updates": required_pointer_updates,
        },
        "notes": [
            "默认固定提交边界：单项目一个根仓提交；多子模块时每个 dirty 子模块一个内部提交，父仓指针合并到一个根仓提交。",
            "执行前应再次运行 coverage --plan-file，确保无 uncovered 项。",
            "Codex 与 Claude Code 均调用同一组 Python 脚本；差异只在外层 skill metadata。",
        ],
    }
