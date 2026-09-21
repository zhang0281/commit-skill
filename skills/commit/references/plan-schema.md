# Plan JSON Schema

Read this when editing `/tmp/commit-plan-<repo_hash>.json`, fixing coverage gaps, or validating whether a path belongs to the initial snapshot. Default fast path should prefer `commit-session`; `/tmp/commit-messages-<random>.json` + `fast-commit` is the non-interactive fallback. Full plan editing is now the debug path.

## Core shape

```json
{
  "schema_version": 1,
  "tool": "commit-skill",
  "repo": "/abs/repo",
  "branch": "main",
  "requested": {
    "split_mode": "auto",
    "sign_mode": "auto"
  },
  "sign_context": {},
  "inventory": {},
  "commits": [
    {
      "id": "repo:docs",
      "kind": "repo",
      "repo_path": "/abs/repo",
      "paths": ["README.md"],
      "type": "",
      "title": "",
      "bullets": [],
      "type_hint": "docs",
      "title_hint": "更新文档",
      "bullet_hints": ["..."],
      "sign_mode": "auto",
      "effective_sign_mode_hint": "signed"
    }
  ],
  "exclude": [],
  "coverage_baseline": {
    "root_changed_files": ["README.md"],
    "root_fingerprints": [],
    "explicit_excluded_files": [],
    "excluded_submodules": [],
    "submodule_changes": [],
    "required_pointer_updates": []
  }
}
```

## Editable fields

In the default `commit-session` path AI may edit only these semantic fields:

- `type`: one of `feat|fix|docs|refactor|test|chore|style|perf`.
- `title`: non-empty Chinese Conventional Commit title body after `type:`.
- `bullets`: string array used as extra `-m` paragraphs.

Candidate count, ids, paths, repository boundaries, ordering, `exclude`, and all snapshot fields are script-owned. The debug-only `plan` / `apply-plan` path may be used by a human or an explicitly authorized repair workflow, but it is not part of the AI fast path.

Do not rewrite `repo`, `coverage_baseline`, `sign_context`, fingerprints, or `sign_mode=auto` into `signed` just because `effective_sign_mode_hint` says signed.

## Snapshot constraints

- `paths` are relative to each commit's `repo_path`.
- Every planned path must resolve into `coverage_baseline`.
- New paths added after `plan` are out-of-snapshot and must not be included.
- Same path may not appear in more than one commit for the same `repo_path`.
- `coverage_baseline.root_fingerprints` and submodule fingerprints detect same-path content drift; if drift appears, rerun `plan`.
- `repo_path` must be root repo or a submodule repo recorded in `coverage_baseline.submodule_changes`.

## Session-only gates

`commit-session` adds runtime fields without changing the immutable plan schema:

- `phase=prepared.preflight`: temporary-index `git diff --check` result and running configured test commands.
- `phase=prepared.message_template.commits[].diff_summary.semantic_diff`: bounded patch/untracked text for message generation; this is informational and cannot change candidate paths.
- `phase=complete.preflight`: final test results.
- `phase=complete.results[].signature_verification`: `git verify-commit` result when a signed commit was made.
- `phase=complete.postflight`: final inventory, remaining dirty paths, and `post_snapshot_changes` with fingerprints/reasons.

The optional repository-root `.commit-skill.json` has this shape:

```json
{
  "preflight": {
    "commands": [
      {"name": "unit-tests", "argv": ["python3", "-m", "unittest"], "timeout_seconds": 120}
    ]
  }
}
```

Commands are argv arrays, never shell strings. They run as the current user and are not a sandbox; use this file only in a trusted repository. `git diff --check` runs regardless of this file; no configured tests is reported as `tests_configured=false`.

## Typical fixes

- `root_uncovered_files`: add those snapshot paths to an existing semantic commit or create a residual commit.
- `out_of_snapshot_*`: remove those paths from plan; they belong to a later `$commit` run.
- `snapshot_drift`: stop and rerun `plan`; do not update fingerprints by hand. In `commit-session`, the script runs this check internally before `phase=complete`.
- duplicate path error: keep the file in only one semantic commit.
