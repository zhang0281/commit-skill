# Signing Rules

Read this when user mentions signing, `sign_mode`, GPG, fallback, or when apply-plan returns a GPG-related error.

## Modes

- `sign_mode=auto`: plan keeps `auto`; apply probes Git/GPG and prefers signed commit if signing appears available.
- `sign_mode=signed`: force `git commit -S`; any signing failure is fatal.
- `sign_mode=unsigned`: commit without signature.

`effective_sign_mode_hint` is advisory only. Do not replace `sign_mode=auto` with the hint in plan JSON.

## Auto fallback

In `auto`, if signed commit fails with a known GPG/pinentry/agent error, the executor may retry once with:

```bash
git -c commit.gpgsign=false commit ...
```

Fallback is not allowed when the user explicitly requested `signed`.

## Probes and environment

- `plan --summary-only` uses config-only signing peek to avoid blocking on GPG.
- `apply-plan` runs full detection: `gpgconf --launch gpg-agent`, `gpg --list-secret-keys --keyid-format LONG`.
- If a TTY exists, executor sets `GPG_TTY=$(tty)`.

## Reporting

Final report should include, per commit:

- SHA
- `signed` true/false
- `fallback_used` true/false
- failed attempts and error code when any commit fails
