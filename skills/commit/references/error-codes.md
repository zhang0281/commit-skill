# Error Codes

Read this when a script returns `ok=false`, `passed=false`, non-zero exit code, or the final response needs failure details.

| Code | Exit | Meaning | Usual action |
| --- | ---: | --- | --- |
| `OK` | 0 | Success | Continue workflow |
| `INVALID_ARGUMENT` | 10 | Bad CLI args | Correct invocation |
| `NOT_GIT_REPO` | 11 | `--repo` is not a Git repo | Ask for/locate repo root |
| `PLAN_FILE_INVALID` | 12 | Malformed or unsafe plan | Fix plan JSON; do not apply |
| `GIT_STATUS_FAILED` | 20 | status scan failed | Report stderr; stop |
| `GIT_DIFF_FAILED` | 21 | diff scan failed | Report stderr; stop |
| `GIT_ADD_FAILED` | 22 | staging failed | Report pathspec/details |
| `GIT_COMMIT_FAILED` | 23 | commit failed | Report attempts; inspect index cleanup |
| `COVERAGE_GAP` | 30 | uncovered, out-of-snapshot, missing pointer, or fingerprint drift | Fix plan or rerun plan |
| `PLAN_APPLY_FAILED` | 31 | plan execution failed | Report details; stop |
| `GPG_REQUIRED_FAILED` | 40 | explicit signed commit failed | Do not fallback; report GPG issue |
| `GPG_AUTO_FAILED` | 41 | auto signing and fallback both failed | Report attempts |
| `SUBMODULE_SCAN_FAILED` | 50 | submodule scan failed | Report submodule stderr |

## Response guidance

- For `COVERAGE_GAP`, read the returned fields first: `root_uncovered_files`, `submodule_uncovered`, `missing_pointer_updates`, `out_of_snapshot_*`, `snapshot_drift`.
- For GPG errors, read `references/signing.md`.
- For submodule errors, read `references/submodules.md`.
- For `PLAN_FILE_INVALID`, read `references/plan-schema.md`.
