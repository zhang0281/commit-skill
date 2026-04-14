from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from .errors import ErrorCode, SkillError
from .process import git, head_exists
from .signing import detect_signing

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
        top = path.replace("\\", "/").split("/", 1)[0] if "/" in path else "."
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


def parse_status(repo: str) -> list[dict[str, str]]:
    result = git(repo, "status", "--short", "--untracked-files=all")
    if result.returncode != 0:
        raise SkillError(ErrorCode.GIT_STATUS_FAILED, result.stderr.strip() or "无法获取 git status", {"repo": repo})
    return parse_status_lines(result.stdout.splitlines())


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


def collect_submodule_maps(repo: str) -> tuple[dict[str, dict[str, object]], dict[str, list[str]], dict[str, list[str]]]:
    status_result = git(repo, "submodule", "status")
    if status_result.returncode not in {0, 128}:
        raise SkillError(ErrorCode.SUBMODULE_SCAN_FAILED, status_result.stderr.strip() or "无法获取 submodule 状态")
    status_entries = parse_submodule_status_output(status_result.stdout) if status_result.returncode == 0 else []
    status_map = {entry["path"]: entry for entry in status_entries}
    dirty_script = (
        'DIRTY=$(git status --short 2>/dev/null); '
        'if [ -n "$DIRTY" ]; then '
        'printf "=== %s ===\n%s\n" "$displaypath" "$DIRTY"; '
        'fi'
    )
    ahead_script = (
        'AHEAD=$(git log --oneline @{u}..HEAD 2>/dev/null | head -5); '
        'if [ -n "$AHEAD" ]; then '
        'printf "=== %s ===\n%s\n" "$displaypath" "$AHEAD"; '
        'fi'
    )
    dirty_result = git(repo, "submodule", "foreach", "--quiet", dirty_script)
    ahead_result = git(repo, "submodule", "foreach", "--quiet", ahead_script)
    return status_map, parse_named_blocks(dirty_result.stdout), parse_named_blocks(ahead_result.stdout)


def build_submodule_record(repo: str, path: str, state: dict[str, object]) -> dict[str, object]:
    status_entry = state["status_map"].get(path)
    dirty_lines = state["dirty_blocks"].get(path, [])
    dirty_status = parse_status_lines(dirty_lines)
    dirty_files = [entry["path"] for entry in dirty_status]
    pointer_changed = bool(status_entry and status_entry.get("prefix") not in {None, " "})
    return {
        "path": path,
        "absolute_path": str(Path(repo, path).resolve()),
        "status_prefix": status_entry.get("prefix") if status_entry else " ",
        "recorded_sha": status_entry.get("sha") if status_entry else "",
        "dirty": bool(dirty_files),
        "dirty_files": dirty_files,
        "dirty_status": dirty_status,
        "ahead_commits": state["ahead_blocks"].get(path, []),
        "pointer_changed": pointer_changed,
        "requires_pointer_update": bool(dirty_files) or pointer_changed or bool(state["ahead_blocks"].get(path, [])),
    }


def collect_submodules(repo: str) -> list[dict[str, object]]:
    status_map, dirty_blocks, ahead_blocks = collect_submodule_maps(repo)
    state = {"status_map": status_map, "dirty_blocks": dirty_blocks, "ahead_blocks": ahead_blocks}
    paths = set(status_map) | set(dirty_blocks) | set(ahead_blocks)
    return [build_submodule_record(repo, path, state) for path in sorted(paths)]


def build_inventory(repo: str, includes: list[str], excludes: list[str], split_mode: str, sign_mode: str) -> dict[str, object]:
    status_entries = parse_status(repo)
    changed_files = sorted({entry["path"] for entry in status_entries})
    filtered, explicit_excluded = filtered_paths(changed_files, includes, excludes)
    sign_context = detect_signing(repo, sign_mode if sign_mode != "auto" else None)
    submodules = collect_submodules(repo)
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
