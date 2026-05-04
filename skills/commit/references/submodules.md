# Submodule Rules

Read this when plan includes `submodule_internal` / `submodule_pointer`, when include/exclude touches submodule paths, or when coverage reports submodule gaps.

## Commit kinds

`plan` may emit two submodule commit kinds:

1. `submodule_internal`
   - `repo_path` is the submodule's absolute repo path.
   - `paths` are dirty files inside that submodule.
   - Must run before the parent pointer commit.
2. `submodule_pointer`
   - `repo_path` is the parent repo.
   - `paths` contain the submodule path/gitlink, e.g. `vendor/lib`.
   - Records the child HEAD in the parent repo.

## Ordering

- Always commit `submodule_internal` before its corresponding `submodule_pointer`.
- Pointer commits for multiple submodules may be merged into one `chore` commit if the message remains clear.
- The executor validates ordering; wrong order is `PLAN_FILE_INVALID`.

## Include / exclude

- include/exclude applies to root files and submodule paths.
- Excluding `vendor/sub` excludes its dirty files and pointer/ahead update.
- Including `vendor/sub/inner.py` may include only that dirty file inside the submodule.
- If a submodule internal commit is created, the parent pointer commit must remain in the same run.

## Coverage fields

- `coverage_baseline.submodule_changes[]`: submodule dirty-file snapshot and fingerprints.
- `coverage_baseline.required_pointer_updates[]`: parent gitlink updates required by dirty/ahead/pointer changes.
- `submodule_uncovered`: internal dirty files not assigned to a submodule commit.
- `missing_pointer_updates`: child changes exist but parent pointer path is not planned.
- `out_of_snapshot_submodule_paths`: planned paths not in the initial submodule snapshot.
