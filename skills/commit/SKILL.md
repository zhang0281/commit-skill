---
name: commit
description: 拆分并创建规范 Git 提交。Use when Codex or Claude Code needs to inspect working tree changes, build an editable commit plan JSON, decide commit boundaries, handle submodule internal commits and pointer updates, generate Chinese Conventional Commit messages, or execute a safe commit workflow from a finalized plan.
---

# Commit

将执行 `$commit` 当下扫描到的路径与内容快照，整理成一个或多个“每次只做一件事”的 Git 提交。

## 核心定位

- **AI 负责**：语义拆分、标题与 bullets、残余提交裁决。
- **脚本负责**：inventory、plan JSON、coverage audit、submodule 扫描、签名探测与实际 `git add` / `git commit`。
- **默认流**：`plan → 编辑 plan JSON → coverage → apply-plan`。
- **铁律**：不改工作区文件内容、不做 partial staging、只处理本次 `$commit` 起手扫描到的路径与内容快照。
- **并行默认**：多文件、多候选 commit 或多 repo/submodule 改动时，默认自动判断并启动只读子代理加速 facts 收集；不可用则串行退化。

## 资源路径解析（防止误找项目目录）

执行任何 `scripts/` 或读取 `references/` 前，先把**本 skill 根目录**解析成绝对路径，并在命令中使用该绝对路径：

- `COMMIT_SKILL_DIR` = 当前 `SKILL.md` 所在目录的绝对路径（来自已加载的 skill path 或实际打开的 `SKILL.md` 文件路径）。
- `COMMIT_SKILL_SCRIPT="$COMMIT_SKILL_DIR/scripts/commit_skill.py"`。
- 不要写死某台机器上的安装路径；不要假定 `scripts/commit_skill.py` 位于启动 Codex 的项目目录。
- 启动 Codex 的项目目录只作为目标仓库传给 `--repo`，例如在任意 repo 内执行时仍使用 `--repo .`。
- 若向用户说明执行细节，须注明调用的 Python 脚本位于 commit skill 安装目录下，而非当前项目目录；涉及脚本或 reference 文件时尽量给出已解析后的完整路径。

## 使用方式与参数归一

- `$commit`
- `$commit 只提交 src/api.py 和 src/utils.py` → `--include`
- `$commit 不提交 docs` → `--exclude`
- `$commit 单次提交` / `$commit 合并提交` → `split_mode=single`
- `$commit 分开提交` → `split_mode=split`
- `$commit 签名提交` / `$commit 启用 GPG` → `sign_mode=signed`
- `$commit 不签名` / `$commit 禁用 GPG` → `sign_mode=unsigned`
- 未指定时：`split_mode=auto`、`sign_mode=auto`

## 何时读取 references

- 编辑或修复 plan JSON schema / coverage gaps / snapshot drift：读 `references/plan-schema.md`。
- 签名、GPG、fallback、`sign_mode`：读 `references/signing.md`。
- submodule internal / pointer、submodule include/exclude：读 `references/submodules.md`。
- 非零错误码、`ok=false`、`passed=false`：读 `references/error-codes.md`。
- 手动恢复、命令边界、staged cleanup：读 `references/safety.md`。

## 默认执行链

### 1) 自动先跑 `plan`

```bash
python3 "$COMMIT_SKILL_SCRIPT" plan --repo . --summary-only
```

要点：

- summary 返回 `plan_file`，完整计划默认写入 `/tmp/commit-plan-<repo_hash>.json`。
- `coverage_baseline` 是本轮唯一路径与内容快照；后续新路径或同路径内容漂移，不得被顺带提交。
- 若 `changed_count=0`，直接报告无可提交改动；`apply-plan` 可 no-op。

### 2) AI 编辑 plan JSON

AI 只做这些判断：

1. 是否同一目的；是否拆成多个纯语义 commit。
2. docs / tests / config 是否并入对应语义单元。
3. 无法纯语义拆分时，降级为模块级或文件级 residual commit。
4. 填写中文 Conventional Commit 的 `type` / `title` / `bullets`。

不要手写 Git 命令；编辑 `commits` 列表。细则见 `references/plan-schema.md`。

### 3) 默认自动并行 facts 收集

满足任一条件即可启动只读 `explorer` 子代理：多个 candidate commit、root + submodule 混合、多个 repo_path、改动文件较多。

子代理只读：`git status --porcelain -z` / `git diff --name-status` / `git log -1` / `git submodule status`。禁止写、禁止 `git add/commit/reset`。最终 plan 编辑、coverage 与 apply 仍在主线程执行。

### 4) 执行前跑 coverage

```bash
python3 "$COMMIT_SKILL_SCRIPT" coverage --plan-file /tmp/commit-plan-<repo_hash>.json --json
```

若 `passed=false`：根据返回字段修 plan 或重跑 plan；不得把快照外路径捎带提交。错误字段说明见 `references/error-codes.md` 与 `references/plan-schema.md`。

### 5) 最后用 `apply-plan` 落地

```bash
python3 "$COMMIT_SKILL_SCRIPT" apply-plan --plan-file /tmp/commit-plan-<repo_hash>.json --json
```

`apply-plan` 会先复核 coverage，再逐个提交快照内路径，处理签名与 submodule 顺序，并返回 SHA / signed / fallback / attempts / 错误码。

## 手动调试子命令

```bash
python3 "$COMMIT_SKILL_SCRIPT" inventory --repo . --json
python3 "$COMMIT_SKILL_SCRIPT" plan --repo . --out /tmp/commit-plan-<repo_hash>.json --json
python3 "$COMMIT_SKILL_SCRIPT" commit --repo . \
  --file src/api.py \
  --type fix \
  --title '修复接口参数透传' \
  --bullet '修正请求参数映射' \
  --sign-mode auto
```

## 输出要求

最终回答保持：

- 【判词】一句话定性
- 【斩链】概述改动、submodule 判断、提交计划、coverage audit、执行动作
- 【验尸】commit SHA / 标题 / 文件 / 是否 signed / 是否 fallback
- 【余劫】本次快照中剩余未提交项（仅允许显式排除）、snapshot drift 或失败点；快照之后新增的改动不计入本轮
- 【再斩】下一步
