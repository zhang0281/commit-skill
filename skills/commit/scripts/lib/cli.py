from __future__ import annotations

import argparse
import json
from pathlib import Path

from .coverage import load_plan_file, run_coverage_from_args, run_coverage_from_plan, validate_plan_file
from .errors import ErrorCode, SkillError, error_payload, ok_payload
from .executor import apply_plan
from .inventory import build_inventory, changed_file_paths, expand_targets
from .planner import build_plan
from .process import repo_root
from .signing import detect_signing


def maybe_write_output(payload: dict[str, object], out_path: str | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if out_path:
        Path(out_path).write_text(text + "\n", encoding="utf-8")
    print(text)


def write_json_file(payload: dict[str, object], out_path: str | None) -> None:
    if not out_path:
        return
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    }


def command_inventory(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    payload = ok_payload(**build_inventory(repo, args.include, args.exclude, args.split_mode, args.sign_mode))
    maybe_write_output(payload, args.out)
    return 0


def command_plan(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
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
    write_json_file(full_payload, args.out)
    if getattr(args, "summary_only", False):
        maybe_write_output(plan_summary(full_payload, args.out), None)
        return 0
    maybe_write_output(full_payload, args.out)
    return 0


def command_coverage(args: argparse.Namespace) -> int:
    if args.plan_file:
        plan = validate_plan_file(load_plan_file(args.plan_file), require_messages=False)
        payload = ok_payload(**run_coverage_from_plan(plan))
        maybe_write_output(payload, args.out)
        return 0 if payload["passed"] else int(ErrorCode.COVERAGE_GAP)

    repo = repo_root(args.repo)
    changed = changed_file_paths(repo)
    payload = ok_payload(repo=repo, **run_coverage_from_args(changed, args.planned, args.exclude))
    maybe_write_output(payload, args.out)
    return 0 if payload["passed"] else int(ErrorCode.COVERAGE_GAP)


def command_apply_plan(args: argparse.Namespace) -> int:
    plan = validate_plan_file(load_plan_file(args.plan_file), require_messages=True)
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


def add_coverage_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("coverage", help="Audit coverage by args or plan-file")
    parser.add_argument("--repo")
    parser.add_argument("--planned", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--plan-file")
    add_common_flags(parser)
    parser.set_defaults(func=command_coverage)


def add_apply_plan_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("apply-plan", help="Execute a finalized plan JSON")
    parser.add_argument("--plan-file", required=True)
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
    add_coverage_parser(sub)
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
