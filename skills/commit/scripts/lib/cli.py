from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from .coverage import load_plan_file, run_coverage_from_args, run_coverage_from_plan, validate_plan_file
from .errors import ErrorCode, SkillError, error_payload, ok_payload
from .executor import apply_plan
from .inventory import build_inventory, changed_file_paths, expand_targets, fingerprint_paths
from .messages import build_message_template, load_message_file, merge_message_file
from .planner import build_plan
from .process import repo_root
from .signing import detect_signing


FAST_MESSAGES_FILE_PATTERN = re.compile(r"commit-messages-[A-Za-z0-9_-]{6,}\.json\Z")
FAST_MESSAGES_DIR = Path("/tmp")


def maybe_write_output(payload: dict[str, object], out_path: str | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if out_path:
        Path(out_path).write_text(text + "\n", encoding="utf-8")
    print(text)


def write_json_file(payload: dict[str, object], out_path: str | None) -> None:
    if not out_path:
        return
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def default_plan_file(repo: str) -> str:
    repo_hash = hashlib.sha256(repo.encode("utf-8", "surrogateescape")).hexdigest()[:12]
    return str(Path(tempfile.gettempdir(), f"commit-plan-{repo_hash}.json"))


def allocate_temp_json(prefix: str) -> str:
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".json", dir=str(FAST_MESSAGES_DIR))
    os.close(fd)
    return path


def default_session_plan_file(repo: str) -> str:
    repo_hash = hashlib.sha256(repo.encode("utf-8", "surrogateescape")).hexdigest()[:12]
    return allocate_temp_json(f"commit-plan-{repo_hash}-")


def plan_summary(plan_payload: dict[str, object], plan_file: str | None = None) -> dict[str, object]:
    inventory = plan_payload["inventory"]
    candidates = []
    for commit in plan_payload["commits"]:
        candidates.append(
            {
                "id": commit["id"],
                "kind": commit["kind"],
                "category": commit.get("category", ""),
                "repo_path": commit["repo_path"],
                "paths_count": len(commit["paths"]),
                "paths_preview": commit["paths"][:4],
                "type_hint": commit.get("type_hint", ""),
                "title_hint": commit.get("title_hint", ""),
            }
        )
    return {
        "ok": plan_payload["ok"],
        "error_code": plan_payload["error_code"],
        "exit_code": plan_payload["exit_code"],
        "repo": plan_payload["repo"],
        "branch": plan_payload["branch"],
        "plan_file": plan_file,
        "requested": plan_payload["requested"],
        "sign_context": plan_payload["sign_context"],
        "changed_count": len(inventory["changed_files"]),
        "root_changed_count": len(inventory["root_changed_files"]),
        "submodule_count": len(inventory["submodules"]),
        "candidate_count": len(plan_payload["commits"]),
        "top_level_groups": list(inventory["top_level_groups"].keys()),
        "candidate_commits": candidates,
        "message_only": True,
        "plan_editing_allowed": False,
    }


def command_inventory(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    payload = ok_payload(**build_inventory(repo, args.include, args.exclude, args.split_mode, args.sign_mode))
    maybe_write_output(payload, args.out)
    return 0


def build_snapshot_plan(
    repo: str,
    args: argparse.Namespace,
    plan_file: str,
) -> dict[str, object]:
    full_payload = ok_payload(
        **build_plan(
            repo,
            args.include,
            args.exclude,
            args.split_mode,
            args.sign_mode,
            lazy_signing=True,
        )
    )
    write_json_file(full_payload, plan_file)
    return full_payload


def validate_fast_messages_file(path: str) -> None:
    message_path = Path(path)
    if message_path.parent != FAST_MESSAGES_DIR or not FAST_MESSAGES_FILE_PATTERN.fullmatch(message_path.name):
        raise SkillError(
            ErrorCode.INVALID_ARGUMENT,
            "fast-commit 的 --messages-file 必须位于 /tmp 且包含随机后缀",
            {"messages_file": path, "expected": "/tmp/commit-messages-<random>.json"},
        )


def write_session_payload(payload: dict[str, object], out_path: str | None = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if out_path:
        Path(out_path).write_text(text + "\n", encoding="utf-8")
    print(text, flush=True)


@contextmanager
def muted_stdin_echo():
    if not sys.stdin.isatty():
        yield
        return
    try:
        import termios

        fd = sys.stdin.fileno()
        attributes = termios.tcgetattr(fd)
        muted = attributes.copy()
        muted[3] &= ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSADRAIN, muted)
    except (ImportError, OSError):
        yield
        return
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, attributes)


def read_session_messages() -> dict[str, object]:
    chunks: list[str] = []
    with muted_stdin_echo():
        for line in sys.stdin:
            chunks.append(line)
            try:
                payload = json.loads("".join(chunks))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                raise SkillError(ErrorCode.MESSAGE_FILE_INVALID, "session messages JSON 顶层必须为对象")
            return payload
    raise SkillError(ErrorCode.MESSAGE_FILE_INVALID, "commit-session 未收到 messages JSON")


def command_plan(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    plan_file = args.out or default_plan_file(repo)
    full_payload = build_snapshot_plan(
        repo,
        args,
        plan_file,
    )
    if getattr(args, "summary_only", False):
        maybe_write_output(plan_summary(full_payload, plan_file), None)
        return 0
    maybe_write_output(full_payload, None)
    return 0


def command_prepare(args: argparse.Namespace) -> int:
    """Build the immutable plan and the AI-only message template in one pass."""
    repo = repo_root(args.repo)
    plan_file = args.out or default_plan_file(repo)
    full_payload = build_snapshot_plan(
        repo,
        args,
        plan_file,
    )
    template = build_message_template(full_payload)
    maybe_write_output(
        {
            "ok": full_payload["ok"],
            "error_code": full_payload["error_code"],
            "exit_code": full_payload["exit_code"],
            "plan_file": plan_file,
            "summary": plan_summary(full_payload, plan_file),
            "message_template": template,
        },
        None,
    )
    return 0


def command_fast_commit(args: argparse.Namespace) -> int:
    """Prepare a fresh snapshot, merge AI messages, and apply it atomically."""
    repo = repo_root(args.repo)
    plan_file = args.plan_file or default_plan_file(repo)
    validate_fast_messages_file(args.messages_file)
    if Path(plan_file).resolve() == Path(args.messages_file).resolve():
        raise SkillError(
            ErrorCode.INVALID_ARGUMENT,
            "--plan-file 与 --messages-file 不得指向同一路径",
            {"plan_file": plan_file, "messages_file": args.messages_file},
        )
    full_payload = build_snapshot_plan(
        repo,
        args,
        plan_file,
    )
    plan = merge_message_file(
        validate_plan_file(full_payload, require_messages=False),
        load_message_file(args.messages_file),
    )
    sign_context = detect_signing(repo, args.sign_mode if args.sign_mode != "auto" else None)
    payload = apply_plan(plan, sign_context, sign_mode_override=args.sign_mode)
    payload["plan_file"] = plan_file
    maybe_write_output(payload, args.out)
    return 0


def command_commit_session(args: argparse.Namespace) -> int:
    """Keep one process alive while the AI supplies the message JSON on stdin."""
    repo = repo_root(args.repo)
    plan_file = args.plan_file or default_session_plan_file(repo)
    full_payload = build_snapshot_plan(repo, args, plan_file)
    validated_plan = validate_plan_file(full_payload, require_messages=False)

    if not full_payload["commits"]:
        sign_context = detect_signing(repo, args.sign_mode if args.sign_mode != "auto" else None)
        payload = apply_plan(validated_plan, sign_context, sign_mode_override=args.sign_mode)
        payload.update({"phase": "complete", "plan_file": plan_file, "noop": True})
        write_session_payload(payload, args.out)
        return 0

    messages_file = allocate_temp_json("commit-messages-")
    prepared = {
        "phase": "prepared",
        "ok": True,
        "error_code": ErrorCode.OK.name,
        "exit_code": int(ErrorCode.OK),
        "plan_file": plan_file,
        "messages_file": messages_file,
        "summary": plan_summary(full_payload, plan_file),
        "message_template": build_message_template(full_payload),
    }
    write_session_payload(prepared, args.out)

    message_payload = read_session_messages()
    write_json_file(message_payload, messages_file)
    plan = merge_message_file(validated_plan, load_message_file(messages_file))
    sign_context = detect_signing(repo, args.sign_mode if args.sign_mode != "auto" else None)
    payload = apply_plan(plan, sign_context, sign_mode_override=args.sign_mode)
    try:
        Path(messages_file).unlink()
        messages_file_removed = True
    except OSError:
        messages_file_removed = False
    payload.update(
        {
            "phase": "complete",
            "plan_file": plan_file,
            "messages_file": messages_file,
            "messages_file_removed": messages_file_removed,
        }
    )
    write_session_payload(payload, args.out)
    return 0


def command_coverage(args: argparse.Namespace) -> int:
    if args.plan_file:
        plan = validate_plan_file(load_plan_file(args.plan_file), require_messages=False)
        messages_file = getattr(args, "messages_file", None)
        if messages_file:
            plan = merge_message_file(plan, load_message_file(messages_file))
        payload = ok_payload(**run_coverage_from_plan(plan))
        maybe_write_output(payload, args.out)
        return 0 if payload["passed"] else int(ErrorCode.COVERAGE_GAP)

    repo = repo_root(args.repo)
    changed = changed_file_paths(repo)
    payload = ok_payload(repo=repo, **run_coverage_from_args(changed, args.planned, args.exclude))
    maybe_write_output(payload, args.out)
    return 0 if payload["passed"] else int(ErrorCode.COVERAGE_GAP)


def command_message_template(args: argparse.Namespace) -> int:
    plan = validate_plan_file(load_plan_file(args.plan_file), require_messages=False)
    payload = ok_payload(**build_message_template(plan))
    maybe_write_output(payload, args.out)
    return 0


def command_apply_plan(args: argparse.Namespace) -> int:
    messages_file = getattr(args, "messages_file", None)
    plan = validate_plan_file(load_plan_file(args.plan_file), require_messages=not bool(messages_file))
    if messages_file:
        plan = merge_message_file(plan, load_message_file(messages_file))
    repo = repo_root(args.repo or str(plan["repo"]))
    if repo != plan["repo"]:
        raise SkillError(
            ErrorCode.PLAN_FILE_INVALID,
            "--repo 与计划 JSON 中的 repo 不一致",
            {"repo": repo, "plan_repo": plan["repo"]},
        )
    sign_context = detect_signing(repo, args.sign_mode if args.sign_mode != "auto" else None)
    payload = apply_plan(plan, sign_context, sign_mode_override=args.sign_mode)
    maybe_write_output(payload, args.out)
    return 0


def build_manual_commit_plan(repo: str, args: argparse.Namespace) -> dict[str, object]:
    files = expand_targets(changed_file_paths(repo), args.file)
    return {
        "repo": repo,
        "requested": {"sign_mode": args.sign_mode},
        "commits": [
            {
                "id": "manual:commit",
                "repo_path": repo,
                "paths": files,
                "type": args.type,
                "title": args.title,
                "bullets": args.bullet,
                "sign_mode": args.sign_mode,
            }
        ],
        "coverage_baseline": {
            "root_changed_files": files,
            "root_fingerprints": fingerprint_paths(repo, files),
            "explicit_excluded_files": [],
            "submodule_changes": [],
            "required_pointer_updates": [],
        },
        "exclude": [],
    }


def command_commit(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    plan = build_manual_commit_plan(repo, args)
    sign_context = detect_signing(repo, args.sign_mode if args.sign_mode != "auto" else None)
    if args.dry_run:
        payload = ok_payload(repo=repo, dry_run=True, sign_context=sign_context, plan=plan)
        maybe_write_output(payload, args.out)
        return 0
    payload = apply_plan(plan, sign_context, sign_mode_override=args.sign_mode)
    maybe_write_output(payload, args.out)
    return 0


def add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out")


def add_inventory_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("inventory", help="Collect repo inventory")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--split-mode", choices=["auto", "single", "split"], default="auto")
    parser.add_argument("--sign-mode", choices=["auto", "signed", "unsigned"], default="auto")
    add_common_flags(parser)
    parser.set_defaults(func=command_inventory)


def add_plan_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("plan", help="Build editable commit plan JSON")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--split-mode", choices=["auto", "single", "split"], default="auto")
    parser.add_argument("--sign-mode", choices=["auto", "signed", "unsigned"], default="auto")
    parser.add_argument("--summary-only", action="store_true")
    add_common_flags(parser)
    parser.set_defaults(func=command_plan)


def add_prepare_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "prepare",
        help="Build the immutable plan and AI message template in one invocation",
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--split-mode", choices=["auto", "single", "split"], default="auto")
    parser.add_argument("--sign-mode", choices=["auto", "signed", "unsigned"], default="auto")
    add_common_flags(parser)
    parser.set_defaults(func=command_prepare)


def add_fast_commit_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "fast-commit",
        help="Prepare a fresh snapshot and apply an AI-generated message in one invocation",
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--messages-file", required=True)
    parser.add_argument("--plan-file")
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--split-mode", choices=["auto", "single", "split"], default="auto")
    parser.add_argument("--sign-mode", choices=["auto", "signed", "unsigned"], default="auto")
    add_common_flags(parser)
    parser.set_defaults(func=command_fast_commit)


def add_commit_session_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "commit-session",
        help="Prepare a snapshot, wait for one AI message JSON, then commit in the same process",
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--plan-file")
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--split-mode", choices=["auto", "single", "split"], default="auto")
    parser.add_argument("--sign-mode", choices=["auto", "signed", "unsigned"], default="auto")
    add_common_flags(parser)
    parser.set_defaults(func=command_commit_session)


def add_coverage_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("coverage", help="Audit coverage by args or plan-file")
    parser.add_argument("--repo")
    parser.add_argument("--planned", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--plan-file")
    parser.add_argument("--messages-file")
    add_common_flags(parser)
    parser.set_defaults(func=command_coverage)


def add_message_template_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("message-template", help="Emit fixed candidate commits for AI message generation only")
    parser.add_argument("--plan-file", required=True)
    add_common_flags(parser)
    parser.set_defaults(func=command_message_template)


def add_apply_plan_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("apply-plan", help="Execute a finalized plan JSON")
    parser.add_argument("--plan-file", required=True)
    parser.add_argument("--messages-file")
    parser.add_argument("--repo")
    parser.add_argument("--sign-mode", choices=["auto", "signed", "unsigned"], default="auto")
    add_common_flags(parser)
    parser.set_defaults(func=command_apply_plan)


def add_commit_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("commit", help="Execute a single commit without a separate plan file")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--file", action="append", required=True, default=[])
    parser.add_argument(
        "--type",
        required=True,
        choices=["feat", "fix", "docs", "refactor", "test", "chore", "style", "perf"],
    )
    parser.add_argument("--title", required=True)
    parser.add_argument("--bullet", action="append", default=[])
    parser.add_argument("--sign-mode", choices=["auto", "signed", "unsigned"], default="auto")
    parser.add_argument("--dry-run", action="store_true")
    add_common_flags(parser)
    parser.set_defaults(func=command_commit)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hybrid helper for the commit skill")
    sub = parser.add_subparsers(dest="command", required=True)
    add_inventory_parser(sub)
    add_plan_parser(sub)
    add_prepare_parser(sub)
    add_fast_commit_parser(sub)
    add_commit_session_parser(sub)
    add_coverage_parser(sub)
    add_message_template_parser(sub)
    add_apply_plan_parser(sub)
    add_commit_parser(sub)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except SkillError as exc:
        maybe_write_output(error_payload(exc), getattr(args, "out", None))
        return int(exc.code)
