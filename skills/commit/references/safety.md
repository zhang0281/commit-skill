# Safety Boundary

Read this before manual Git recovery, when an unexpected command seems necessary, or when a failure leaves staged files.

## Allowed Git/GPG actions

The skill scripts may use only:

- `git status`
- `git diff --name-status` for read-only fact gathering
- `git log`
- `git config --get <key>`
- `git rev-parse`
- `git branch --show-current`
- `git add <file>`
- `git commit -m`
- `git commit -S -m`
- `git -c commit.gpgsign=false commit -m` only for the single auto-sign fallback path
- `git reset HEAD -- <file>` only to unstage paths staged by this run after commit failure
- `git submodule status`
- `git -C /absolute/path ...`
- `gpgconf --launch gpg-agent`
- `gpg --list-secret-keys --keyid-format LONG`

## Forbidden actions

Never perform:

- `git restore`
- `git checkout -- <file>`
- `git reset --hard|--mixed|--soft`
- `git clean`
- `git rm`
- any `--force` / `-f`
- permanently disabling repo/global GPG signing
- editing working tree file contents as part of `$commit`

## Failure hygiene

- If commit fails after staging, executor attempts `git reset HEAD -- <files>` for this run's staged paths only.
- Do not use destructive cleanup to make coverage pass.
