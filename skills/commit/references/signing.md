# Signing Rules

Read this when user mentions signing, `sign_mode`, GPG, fallback, or when apply-plan returns a GPG-related error.

## Modes

- `sign_mode=auto`: plan keeps `auto`; apply probes Git/GPG and prefers signed commit if signing appears available.
- `sign_mode=signed`: directly attempt `git commit -S` without a preliminary GPG inventory; any signing failure is fatal, and success is immediately checked by `git verify-commit`.
- `sign_mode=unsigned`: force an unsigned commit with `git -c commit.gpgsign=false commit`, even when repository/global config enables signing.

`effective_sign_mode_hint` is advisory only. Do not replace `sign_mode=auto` with the hint in plan JSON.

## Auto fallback

In `auto`, if signed commit fails with a known GPG/pinentry/agent error, the executor may retry once with:

```bash
git -c commit.gpgsign=false commit ...
```

Fallback is not allowed when the user explicitly requested `signed`.

## Probes and environment

- `plan --summary-only` uses config-only signing peek to avoid blocking on GPG.
- explicit `signed` skips the separate `gpgconf` / `gpg --list-secret-keys` probe and lets `git commit -S` be the authoritative capability test.
- `auto` still runs full detection: `gpgconf --launch gpg-agent`, `gpg --list-secret-keys --keyid-format LONG`.
- If a TTY exists, executor sets `GPG_TTY=$(tty)`.

## Reporting

Final report should include, per commit:

- SHA
- `signed` true/false
- `fallback_used` true/false
- failed attempts and error code when any commit fails
- `signature_verification.verified` from the in-session `git verify-commit`
