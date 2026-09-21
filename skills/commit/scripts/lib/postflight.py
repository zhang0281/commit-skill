from __future__ import annotations

from pathlib import Path

from .inventory import build_inventory, file_fingerprint
from .process import git


def _submodule_head(repo: str, path: str) -> dict[str, object]:
    result = git(str(Path(repo, path)), "rev-parse", "HEAD")
    return {"kind": "submodule", "head": result.stdout.strip() if result.returncode == 0 else ""}


def capture_dirty_state(repo: str, inventory: dict[str, object]) -> dict[str, dict[str, object]]:
    submodules = {str(item["path"]): item for item in inventory.get("submodules", [])}
    excluded_submodules = {
        str(item["path"]): item for item in inventory.get("excluded_submodules", [])
    }
    all_submodule_paths = set(submodules) | set(excluded_submodules)
    state: dict[str, dict[str, object]] = {}
    for path in inventory.get("changed_files", []):
        path_str = str(path)
        key = f"{repo}\0{path_str}"
        state[key] = _submodule_head(repo, path_str) if path_str in all_submodule_paths else file_fingerprint(repo, path_str)
    for path, submodule in {**excluded_submodules, **submodules}.items():
        sub_repo = str(Path(repo, path).resolve())
        for inner in submodule.get("dirty_files", []):
            inner_str = str(inner)
            state[f"{sub_repo}\0{inner_str}"] = file_fingerprint(sub_repo, inner_str)
    return state


def planned_path_keys(plan: dict[str, object]) -> set[str]:
    return {
        f"{commit['repo_path']}\0{path}"
        for commit in plan.get("commits", [])
        for path in commit.get("paths", [])
    }


def summarize_inventory(inventory: dict[str, object]) -> dict[str, object]:
    return {
        "repo": inventory["repo"],
        "branch": inventory["branch"],
        "changed_count": len(inventory.get("changed_files", [])),
        "changed_files": inventory.get("changed_files", []),
        "root_changed_files": inventory.get("root_changed_files", []),
        "submodules": [
            {
                "path": item.get("path", ""),
                "dirty_files": item.get("dirty_files", []),
                "ahead_commits": item.get("ahead_commits", []),
                "pointer_changed": item.get("pointer_changed", False),
            }
            for item in inventory.get("submodules", [])
        ],
    }


def build_postflight(plan: dict[str, object], initial_state: dict[str, dict[str, object]]) -> dict[str, object]:
    repo = str(plan["repo"])
    inventory = build_inventory(repo, [], [], "auto", "unsigned", lazy_signing=True)
    final_state = capture_dirty_state(repo, inventory)
    planned = planned_path_keys(plan)
    remaining_changes: list[dict[str, object]] = []
    post_snapshot_changes: list[dict[str, object]] = []
    for key, fingerprint in sorted(final_state.items()):
        repo_path, path = key.split("\0", 1)
        remaining_changes.append({"repo_path": repo_path, "path": path})
        initial = initial_state.get(key)
        if initial is None:
            reason = "new_path_after_snapshot"
        elif initial != fingerprint:
            reason = "content_changed_after_snapshot"
        elif key in planned:
            reason = "planned_path_remains_dirty"
        else:
            continue
        post_snapshot_changes.append(
            {
                "repo_path": repo_path,
                "path": path,
                "reason": reason,
                "initial_fingerprint": initial,
                "current_fingerprint": fingerprint,
            }
        )
    return {
        "clean": not remaining_changes,
        "snapshot_clean": not post_snapshot_changes,
        "fingerprint_checked": True,
        "remaining_changes": remaining_changes,
        "post_snapshot_changes": post_snapshot_changes,
        "inventory": summarize_inventory(inventory),
    }
