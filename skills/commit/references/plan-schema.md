# Plan JSON Schema

Read this when editing `/tmp/commit-plan-<repo_hash>.json`, fixing coverage gaps, or validating whether a path belongs to the initial snapshot.

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

AI may edit only these semantic fields unless fixing coverage:

- `commits`: split, merge, reorder semantic units while preserving snapshot constraints.
- `type`: one of `feat|fix|docs|refactor|test|chore|style|perf`.
- `title`: non-empty Chinese Conventional Commit title body after `type:`.
- `bullets`: string array used as extra `-m` paragraphs.
- `exclude`: only for user-explicit exclusions from the initial snapshot.

Do not rewrite `repo`, `coverage_baseline`, `sign_context`, fingerprints, or `sign_mode=auto` into `signed` just because `effective_sign_mode_hint` says signed.

## Snapshot constraints

- `paths` are relative to each commit's `repo_path`.
- Every planned path must resolve into `coverage_baseline`.
- New paths added after `plan` are out-of-snapshot and must not be included.
- Same path may not appear in more than one commit for the same `repo_path`.
- `coverage_baseline.root_fingerprints` and submodule fingerprints detect same-path content drift; if drift appears, rerun `plan`.
- `repo_path` must be root repo or a submodule repo recorded in `coverage_baseline.submodule_changes`.

## Typical fixes

- `root_uncovered_files`: add those snapshot paths to an existing semantic commit or create a residual commit.
- `out_of_snapshot_*`: remove those paths from plan; they belong to a later `$commit` run.
- `snapshot_drift`: stop and rerun `plan`; do not update fingerprints by hand.
- duplicate path error: keep the file in only one semantic commit.
