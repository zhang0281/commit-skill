# Error Codes

Read this when a script returns `ok=false`, `passed=false`, non-zero exit code, or the final response needs failure details.

| Code | Exit | Meaning | Usual action |
| --- | ---: | --- | --- |
| `OK` | 0 | Success | Continue workflow |
| `INVALID_ARGUMENT` | 10 | Bad CLI args | Correct invocation |
| `NOT_GIT_REPO` | 11 | `--repo` is not a Git repo | Ask for/locate repo root |
| `PLAN_FILE_INVALID` | 12 | Malformed or unsafe plan | Fix plan JSON; do not apply |
| `MESSAGE_FILE_INVALID` | 13 | Malformed or unsafe messages JSON | Fix messages JSON; do not apply |
| `MODEL_CONFIG_INVALID` | 14 | Custom model environment is incomplete or invalid | Run `doctor`; unset all custom variables to keep host-stdin mode or fix all fields |
| `GIT_STATUS_FAILED` | 20 | status scan failed | Report stderr; stop |
| `GIT_DIFF_FAILED` | 21 | diff scan failed | Report stderr; stop |
| `GIT_ADD_FAILED` | 22 | staging failed | Report pathspec/details |
| `GIT_COMMIT_FAILED` | 23 | commit failed | Report attempts; inspect index cleanup |
| `COVERAGE_GAP` | 30 | uncovered, out-of-snapshot, missing pointer, or fingerprint drift | Fix plan or rerun plan |
| `PLAN_APPLY_FAILED` | 31 | plan execution failed | Report details; stop |
| `PREFLIGHT_FAILED` | 32 | temporary-index diff check or configured test failed | Read `preflight`; do not commit |
| `GPG_REQUIRED_FAILED` | 40 | explicit signed commit failed | Do not fallback; report GPG issue |
| `GPG_AUTO_FAILED` | 41 | auto signing and fallback both failed | Report attempts |
| `SIGNATURE_VERIFY_FAILED` | 42 | signed commit created but `git verify-commit` failed | Stop and report SHA/verification output |
| `SUBMODULE_SCAN_FAILED` | 50 | submodule scan failed | Report submodule stderr |
| `MODEL_REQUEST_FAILED` | 60 | Custom OpenAI-compatible model request or response failed after retries, or `--require-custom-model` forbids host fallback | Run `doctor --probe`; ordinary `commit-session` emits `phase=fallback` and uses host stdin, while hard mode stops |

## Response guidance

- For `COVERAGE_GAP`, read the returned fields first: `root_uncovered_files`, `submodule_uncovered`, `missing_pointer_updates`, `out_of_snapshot_*`, `snapshot_drift`.
- For GPG errors, read `references/signing.md`.
- For submodule errors, read `references/submodules.md`.
- For `PLAN_FILE_INVALID`, read `references/plan-schema.md`.
