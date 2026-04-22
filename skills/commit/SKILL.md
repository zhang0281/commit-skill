---
name: commit
description: 拆分并创建规范 Git 提交。Use when Codex or Claude Code needs to inspect working tree changes, build an editable commit plan JSON, decide commit boundaries, handle submodule internal commits and pointer updates, generate Chinese Conventional Commit messages, or execute a safe commit workflow from a finalized plan.
---

# Commit

将当前仓库改动整理成一个或多个“每次只做一件事”的 Git 提交。

## 核心定位

- **AI 负责**：语义拆分、标题与 bullets、残余提交裁决
- **脚本负责**：inventory、plan JSON、签名探测、coverage audit、submodule 扫描、实际 `git add` / `git commit`
- **默认流**：`plan` 自动先跑；用户可手动调用，但 `$commit` 本身也必须先调它
- **铁律**：不改工作区文件内容、不做 partial staging、不遗漏未显式排除的改动

## 兼容性

- **Codex**：通过 `agents/openai.yaml` 触发；执行 `scripts/commit_skill.py`
- **Claude Code**：通过 `.claude-plugin/marketplace.json` 暴露 skill；执行同一份 `scripts/commit_skill.py`
- 脚本仅依赖 Python stdlib + `git` / `gpg` / `gpgconf`，避免平台专属依赖

## 使用方式

- `$commit`
- `$commit 只提交 src/api.py 和 src/utils.py`
- `$commit 不提交 docs`
- `$commit 单次提交`
- `$commit 分开提交`
- `$commit 签名提交`
- `$commit 不签名`

## 边界归一

- “只提交 xxx” → 仅处理指定文件/目录
- “不提交 xxx” → 排除指定文件/目录
- “单次提交” / “合并提交” → `split_mode=single`
- “分开提交” → `split_mode=split`
- “签名提交” / “启用 GPG” → `sign_mode=signed`
- “不签名” / “禁用 GPG” → `sign_mode=unsigned`
- 未指定时：`split_mode=auto`、`sign_mode=auto`

## 默认执行链

### 1) 自动先跑 `plan`

`$commit` 默认在 root 仓后立即执行：

```bash
python3 scripts/commit_skill.py plan --repo . --out /tmp/commit-plan.json --summary-only
```

`plan` 会在**第一时间**收集 facts、产出 summary-only JSON，并将完整 plan 写入 `/tmp/commit-plan.json`：

- inventory 收集（含 `git status --porcelain -z`）
- submodule dirty / pointer / ahead 检测
- sign_mode 探测（仅读取 Git config，推迟 GPG 探测至 later steps）
- 路径分类与候选 `commit` 分组
- 统一错误码输出
- 同时生成供 AI 直接编辑的 **可编辑 plan JSON**

### 2) AI 基于 plan JSON 做裁决

AI 只做这些高价值判断：

1. 这些候选分组是否服务于同一个目的
2. 是否应拆成多个纯语义 commit
3. 是否需要合并 docs / tests / config 到同一个语义单元
4. 若无法纯语义拆分，降级为模块级或文件级 residual commit
5. 填写中文 Conventional Commit 的 `type` / `title` / `bullets`

AI 不应手写 Git 命令，而应编辑 plan JSON 的 `commits` 列表。

### 多子代理并行分析（仅限 gpt-5.4）

仅当**当前主模型为 `gpt-5.4`**，且 `plan` 发现多个候选 commit 或同时存在 root 仓与一个以上 submodule 的改动时，主线程才可启动 `explorer` 子代理；非 `gpt-5.4` 模型一律退化为主线程串行 fact-gathering，不得 `spawn_agent`。

- 每个 candidate commit 或 submodule 分支都分配一个子代理，且固定 `model=gpt-5.4`，仅读对应 `paths` / `repo_path`
- 子代理只运行 `git status --porcelain -z` / `git diff --name-status` / `git log -1` / `git submodule status`；禁止写、禁止 `git add/commit/reset`
- 子代理返回：该 candidate 的实际 changed files、top-level grouping、sign hints、依赖 submodule 状态
- 主线程在收集所有子代理汇报后更新 plan JSON，确保 commit candidates 与 submodule internal/pointer 条目都覆盖真实 facts
- 多子代理仅用于 fact-gathering，最终 coverage 与 apply 仍在主线程执行

这样确保大型仓在 plan 阶段就把 facts 并行拾起，再由 AI 编辑最终 plan JSON；若不满足 `gpt-5.4` 条件，则走串行路径，避免错误使用子代理。

### 3) 执行前跑 coverage

对最终 plan JSON 做覆盖校验：

```bash
python3 scripts/commit_skill.py coverage --plan-file /tmp/commit-plan.json --json
```

若 `passed=false`：

- 继续补 `commits`
- 或在 `exclude` 中加入用户显式排除项
- 直到 `uncovered` 归零

### 4) 最后用 `apply-plan` 落地

```bash
python3 scripts/commit_skill.py apply-plan --plan-file /tmp/commit-plan.json --json
```

`apply-plan` 会：

- 先复核 coverage
- 逐个执行 commit
- 自动处理 `sign_mode`
- 在 submodule 内部 repo 执行对应 commit
- 再在父仓库执行 submodule pointer commit
- 返回 SHA / signed / fallback / attempts / 错误码

## 计划 JSON 结构

`plan` 输出的是**可编辑计划**，核心字段：

```json
{
  "schema_version": 1,
  "repo": "/abs/repo",
  "requested": {
    "split_mode": "auto",
    "sign_mode": "auto"
  },
  "sign_context": {},
  "inventory": {},
  "commits": [
    {
      "id": "repo:docs",
      "repo_path": "/abs/repo",
      "kind": "repo",
      "paths": ["README.md"],
      "type": "",
      "title": "",
      "bullets": [],
      "type_hint": "docs",
      "title_hint": "更新文档",
      "bullet_hints": ["..."],
      "sign_mode": "auto"
    }
  ],
  "exclude": [],
  "coverage_baseline": {}
}
```

约束：

- `type` 必须是 `feat|fix|docs|refactor|test|chore|style|perf`
- `title` 必须非空
- `bullets` 必须是字符串数组
- `paths` 相对 `repo_path`
- plan JSON 建议写到 `/tmp/commit-plan.json`，不要写回仓库工作区

## 手动调试子命令

### 仅看 inventory

```bash
python3 scripts/commit_skill.py inventory --repo . --json
```

### 手动生成 plan JSON 文件

```bash
python3 scripts/commit_skill.py plan --repo . --json > /tmp/commit-plan.json
```

### 对单个 commit 直接执行（调试用途）

```bash
python3 scripts/commit_skill.py commit --repo . \
  --file src/api.py \
  --type fix \
  --title '修复接口参数透传' \
  --bullet '修正请求参数映射' \
  --sign-mode auto
```

## 签名规则

- `sign_mode=auto`：若探测到可用 GPG 私钥或 Git 已配置签名，则优先尝试 `git commit -S`
- `sign_mode=signed`：强制 signed commit；失败即报错
- `sign_mode=unsigned`：明确无签名提交
- 若 `auto` 路径签名失败，且错误属于 `gpg-agent` / `pinentry` / `No agent running` / `failed to sign the data`，只允许**单次** fallback 到：

```bash
git -c commit.gpgsign=false commit ...
```

脚本会：

- 若有 TTY，则设置 `GPG_TTY=$(tty)`
- 尝试 `gpgconf --launch gpg-agent`
- 探测 `gpg --list-secret-keys --keyid-format LONG`
- 返回本次是否 signed / 是否发生 fallback / 最终 SHA

## Submodule 规则

`plan` 会显式产生两类 submodule commit：

1. `submodule_internal`
   - 在子模块仓库内提交 dirty files
2. `submodule_pointer`
   - 在父仓库提交 gitlink / pointer 更新

AI 应遵循：

- submodule internal commit 先于 pointer commit
- pointer commit 可由多个子模块合并成一个 `chore`，但必须保持语义清楚

## 统一错误码

脚本所有子命令均返回结构化错误：

- `OK=0`
- `INVALID_ARGUMENT=10`
- `NOT_GIT_REPO=11`
- `PLAN_FILE_INVALID=12`
- `GIT_STATUS_FAILED=20`
- `GIT_DIFF_FAILED=21`
- `GIT_ADD_FAILED=22`
- `GIT_COMMIT_FAILED=23`
- `COVERAGE_GAP=30`
- `PLAN_APPLY_FAILED=31`
- `GPG_REQUIRED_FAILED=40`
- `GPG_AUTO_FAILED=41`
- `SUBMODULE_SCAN_FAILED=50`

## 安全边界

仅允许脚本内部使用这些 Git/GPG 动作：

- `git status`
- `git diff`
- `git diff --stat`
- `git diff --name-status`
- `git log`
- `git config --get <key>`
- `git add <file>`
- `git commit -m`
- `git commit -S -m`
- `git -c commit.gpgsign=false commit -m`（仅 signed path 明确失败后的单次降级）
- `git reset HEAD <file>`
- `git submodule status`
- `git submodule foreach`
- `git -C /absolute/path ...`
- `gpgconf --launch gpg-agent`
- `gpg --list-secret-keys --keyid-format LONG`

绝不做：

- `git restore`
- `git checkout -- <file>`
- `git reset --hard|--mixed|--soft`
- `git clean`
- `git rm`
- 任何 `--force` / `-f`
- 永久关闭仓库或全局 GPG 签名
- 工作区文件内容改写

## 输出要求

最终回答保持：

- 【判词】一句话定性
- 【斩链】概述改动、submodule 判断、提交计划、coverage audit、执行动作
- 【验尸】commit SHA / 标题 / 文件 / 是否 signed / 是否 fallback
- 【余劫】剩余未提交项（仅允许显式排除）或失败点
- 【再斩】下一步
