from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from .errors import ErrorCode, SkillError
from .process import git, head_exists
from .signing import detect_signing, peek_signing

TEST_FILE_SUFFIXES = (
    "_test.py",
    ".spec.ts",
    ".test.ts",
    ".spec.js",
    ".test.js",
)

CONFIG_LIKE_FILES = {
    ".gitignore",
    ".gitattributes",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "Pipfile",
    "Pipfile.lock",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
    ".env.example",
}


def classify_path(path: str) -> str:
    posix = path.replace("\\", "/")
    name = Path(posix).name
    if posix.startswith("docs/") or name.endswith(".md"):
        return "docs"
    is_test = (
        posix.startswith(("tests/", "test/"))
        or "/tests/" in posix
        or name.startswith("test_")
        or name.endswith(TEST_FILE_SUFFIXES)
    )
    if is_test:
        return "tests"
    config_suffixes = (".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".json")
    if name in CONFIG_LIKE_FILES or name.endswith(config_suffixes):
        return "config"
    return "code"


def matches_pattern(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    for raw in patterns:
        pattern = raw.replace("\\", "/").rstrip("/")
        if not pattern:
            continue
        if any(ch in pattern for ch in "*?["):
            if fnmatch(normalized, pattern):
                return True
            continue
        if normalized == pattern or normalized.startswith(pattern + "/"):
            return True
    return False


def filtered_paths(paths: list[str], includes: list[str], excludes: list[str]) -> tuple[list[str], list[str]]:
    included = [path for path in paths if not includes or matches_pattern(path, includes)]
    excluded = [path for path in included if matches_pattern(path, excludes)]
    filtered = [path for path in included if path not in excluded]
    return sorted(filtered), sorted(excluded)


def top_level_groups(paths: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for path in paths:
        normalized = path.replace("\\", "/")
        top = normalized.split("/", 1)[0] if "/" in normalized else "."
        groups.setdefault(top, []).append(path)
    return {key: sorted(value) for key, value in sorted(groups.items())}


def expand_targets(changed: list[str], patterns: list[str]) -> list[str]:
    expanded: list[str] = []
    for pattern in patterns:
        matches = [path for path in changed if matches_pattern(path, [pattern])]
        expanded.extend(matches or [pattern])
    return sorted(dict.fromkeys(expanded))


def parse_status_lines(lines: list[str]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for line in lines:
        if not line.strip():
            continue
        status = line[:2]
        rest = line[3:]
        path = rest.split(" -> ", 1)[-1].strip()
        entries.append({"status": status, "path": path, "category": classify_path(path)})
    return entries


def _read_null_terminated(data: str, index: int) -> tuple[str, int]:
    start = index
    while index < len(data) and data[index] != "\0":
        index += 1
    value = data[start:index]
    if index < len(data) and data[index] == "\0":
        index += 1
    return value, index


def parse_status(repo: str) -> list[dict[str, str]]:
    result = git(repo, "status", "--porcelain", "-z", "--untracked-files=all")
    if result.returncode != 0:
        raise SkillError(
            ErrorCode.GIT_STATUS_FAILED,
            result.stderr.strip() or "无法获取 git status",
            {"repo": repo},
        )

    entries: list[dict[str, str]] = []
    data = result.stdout
    index = 0
    length = len(data)
    while index + 2 <= length:
        status = data[index : index + 2]
        index += 2
        while index < length and data[index] == " ":
            index += 1
        if index >= length:
            break
        first_path, index = _read_null_terminated(data, index)
        if not first_path:
            continue
        path = first_path
        if status[0] in {"R", "C"}:
            second_path, index = _read_null_terminated(data, index)
            if second_path:
                path = second_path
        entries.append({"status": status, "path": path, "category": classify_path(path)})
    return entries


def changed_file_paths(repo: str) -> list[str]:
    return sorted({entry["path"] for entry in parse_status(repo)})


def parse_submodule_status_output(text: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        prefix = line[0]
        parts = line[1:].strip().split()
        if len(parts) < 2:
            continue
        entries.append({"prefix": prefix, "sha": parts[0], "path": parts[1]})
    return entries


def parse_named_blocks(text: str) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    current_path: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("=== ") and line.endswith(" ==="):
            if current_path is not None:
                blocks[current_path] = current_lines
            current_path = line[4:-4]
            current_lines = []
            continue
        if current_path is not None:
            current_lines.append(line)
    if current_path is not None:
        blocks[current_path] = current_lines
    return blocks


def collect_submodule_status_map(repo: str) -> dict[str, dict[str, object]]:
    status_result = git(repo, "submodule", "status")
    if status_result.returncode not in {0, 128}:
        raise SkillError(
            ErrorCode.SUBMODULE_SCAN_FAILED,
            status_result.stderr.strip() or "无法获取 submodule 状态",
        )
    status_entries = parse_submodule_status_output(status_result.stdout) if status_result.returncode == 0 else []
    return {entry["path"]: entry for entry in status_entries}


def collect_submodule_maps(
    repo: str,
) -> tuple[dict[str, dict[str, object]], dict[str, list[str]], dict[str, list[str]]]:
    status_map = collect_submodule_status_map(repo)
    changed_paths = set(status_map)
    details = collect_changed_submodule_details(repo, changed_paths) if changed_paths else {}
    dirty_blocks = {
        path: [f" M {name}" for name in detail["dirty_files"]]
        for path, detail in details.items()
        if detail.get("dirty_files")
    }
    ahead_blocks = {
        path: detail["ahead_commits"]
        for path, detail in details.items()
        if detail.get("ahead_commits")
    }
    return status_map, dirty_blocks, ahead_blocks


def determine_changed_submodule_paths(
    status_entries: list[dict[str, str]],
    status_map: dict[str, dict[str, object]],
) -> set[str]:
    changed: set[str] = set()
    sub_paths = sorted(status_map)
    for entry in status_entries:
        path = entry["path"]
        if path in status_map:
            changed.add(path)
            continue
        for candidate in sub_paths:
            if path.startswith(candidate + "/"):
                changed.add(candidate)
                break
    return changed


def collect_changed_submodule_details(repo: str, paths: set[str]) -> dict[str, dict[str, object]]:
    details: dict[str, dict[str, object]] = {}
    for path in sorted(paths):
        sub_repo = str(Path(repo, path))
        dirty_result = git(sub_repo, "status", "--short", "--untracked-files=all")
        if dirty_result.returncode not in {0, 128}:
            raise SkillError(
                ErrorCode.SUBMODULE_SCAN_FAILED,
                dirty_result.stderr.strip() or "无法获取子模块状态",
                {"path": path},
            )
        dirty_status = parse_status_lines(dirty_result.stdout.splitlines()) if dirty_result.stdout else []
        dirty_files = [entry["path"] for entry in dirty_status]
        ahead_result = git(sub_repo, "log", "--oneline", "@{u}..HEAD")
        ahead_commits = ahead_result.stdout.splitlines() if ahead_result.returncode == 0 else []
        details[path] = {
            "dirty_status": dirty_status,
            "dirty_files": dirty_files,
            "ahead_commits": ahead_commits,
        }
    return details


def build_submodule_record(
    repo: str,
    path: str,
    status_map: dict[str, dict[str, object]],
    details: dict[str, dict[str, object]] | None = None,
    changed_paths: set[str] | None = None,
) -> dict[str, object]:
    if "status_map" in status_map and details is None:
        state = status_map
        status_map = state.get("status_map", {})
        details = {
            path_key: {
                "dirty_status": parse_status_lines(state.get("dirty_blocks", {}).get(path_key, [])),
                "dirty_files": [
                    entry["path"]
                    for entry in parse_status_lines(state.get("dirty_blocks", {}).get(path_key, []))
                ],
                "ahead_commits": state.get("ahead_blocks", {}).get(path_key, []),
            }
            for path_key in set(state.get("status_map", {}))
            | set(state.get("dirty_blocks", {}))
            | set(state.get("ahead_blocks", {}))
        }
        changed_paths = set(details)
    details = details or {}
    changed_paths = changed_paths or set()
    status_entry = status_map.get(path)
    path_details = details.get(path, {})
    dirty_status = path_details.get("dirty_status", [])
    dirty_files = path_details.get("dirty_files", [])
    ahead_commits = path_details.get("ahead_commits", [])
    pointer_changed = path in changed_paths and not dirty_files
    return {
        "path": path,
        "absolute_path": str(Path(repo, path).resolve()),
        "status_prefix": status_entry.get("prefix") if status_entry else " ",
        "recorded_sha": status_entry.get("sha") if status_entry else "",
        "dirty": bool(dirty_files),
        "dirty_files": dirty_files,
        "dirty_status": dirty_status,
        "ahead_commits": ahead_commits,
        "pointer_changed": pointer_changed,
        "requires_pointer_update": bool(dirty_files) or pointer_changed or bool(ahead_commits),
    }


def collect_submodules(repo: str, status_entries: list[dict[str, str]] | None = None) -> list[dict[str, object]]:
    status_map = collect_submodule_status_map(repo)
    parent_entries = status_entries or []
    changed_paths = determine_changed_submodule_paths(parent_entries, status_map)
    if not changed_paths:
        return []
    details = collect_changed_submodule_details(repo, changed_paths)
    return [
        build_submodule_record(repo, path, status_map, details, changed_paths)
        for path in sorted(changed_paths)
    ]


def build_inventory(
    repo: str,
    includes: list[str],
    excludes: list[str],
    split_mode: str,
    sign_mode: str,
    *,
    lazy_signing: bool = False,
) -> dict[str, object]:
    status_entries = parse_status(repo)
    changed_files = sorted({entry["path"] for entry in status_entries})
    filtered, explicit_excluded = filtered_paths(changed_files, includes, excludes)
    sign_context = peek_signing(repo, sign_mode if sign_mode != "auto" else None) if lazy_signing else detect_signing(repo, sign_mode if sign_mode != "auto" else None)
    submodules = collect_submodules(repo, status_entries=status_entries)
    submodule_paths = {entry["path"] for entry in submodules}
    root_changed_files = [path for path in filtered if path not in submodule_paths]
    categories = {
        "docs": [path for path in root_changed_files if classify_path(path) == "docs"],
        "tests": [path for path in root_changed_files if classify_path(path) == "tests"],
        "config": [path for path in root_changed_files if classify_path(path) == "config"],
        "code": [path for path in root_changed_files if classify_path(path) == "code"],
    }
    return {
        "repo": repo,
        "branch": git(repo, "branch", "--show-current").stdout.strip(),
        "head_exists": head_exists(repo),
        "requested_split_mode": split_mode,
        "requested_sign_mode": sign_mode,
        "changed_files": changed_files,
        "filtered_files": filtered,
        "explicit_excluded_files": explicit_excluded,
        "root_changed_files": root_changed_files,
        "top_level_groups": top_level_groups(root_changed_files),
        "categories": categories,
        "status": status_entries,
        "submodules": submodules,
        "sign_context": sign_context,
    }
