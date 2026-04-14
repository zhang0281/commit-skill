---
name: commit
description: 拆分并创建规范 Git 提交。Use when Codex needs to inspect working tree changes, decide commit boundaries, handle submodule pointer updates, generate Chinese Conventional Commit messages, or execute a safe commit workflow. Invoke explicitly with $commit when the user wants “提交当前改动”“帮我 commit”“分开提交”“只提交某些文件”“排除某些文件”。
---

# Commit

将当前仓库改动整理成一个或多个“每次只做一件事”的 Git 提交。

## 核心定位

- **AI 负责**：语义拆分、标题与 bullets、残余提交裁决
- **脚本负责**：inventory、签名探测、coverage audit、实际 `git add` / `git commit`
- **铁律**：不改工作区文件内容、不做 partial staging、不遗漏未显式排除的改动

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

## 先跑脚本

始终先运行 inventory，优先拿结构化事实，再让 AI 裁决：

```bash
python3 scripts/commit_skill.py inventory --repo . --json
```

按需加边界：

```bash
python3 scripts/commit_skill.py inventory --repo . --json \
  --include src/api.py --include src/utils.py \
  --exclude docs \
  --split-mode auto \
  --sign-mode auto
```

inventory 输出重点：

- `changed_files`：全部改动文件
- `filtered_files`：应用 include/exclude 后的候选文件
- `top_level_groups`：按顶层路径归组
- `submodules`：dirty / pointer / ahead 情况
- `sign_context`：GPG/签名配置、建议的 `sign_mode`

## AI 裁决规则

AI 只做这些高价值判断：

1. 这些文件是否服务于同一个目的
2. 是否应拆成多个纯语义 commit
3. 若无法纯语义拆分，降级为模块级或文件级 residual commit
4. 生成中文 Conventional Commit 标题与 bullets

切分优先级：

1. 用户边界
2. submodule 内部提交先于父仓库 pointer 更新
3. 语义完整性
4. docs / tests / config 尽量独立
5. 最小可回滚单元

禁止：

- 留下未显式排除的改动
- 因“懒得归类”而做空泛 snapshot commit
- 部分暂存
- 修改源码/文档/配置内容来迎合提交边界

## 只在需要时看定向 diff

确认某个候选提交前，再看 path-scoped diff：

```bash
git diff --name-status HEAD -- <paths...>
git diff HEAD -- <paths...>
```

不要一开始就整仓库 `git diff HEAD`。

## Coverage audit

执行提交前，必须校验：

```text
all_changed_files
= planned_commit_files
+ explicit_excluded_files
+ submodule_internal_commits 对应的 pointer 更新
```

使用脚本：

```bash
python3 scripts/commit_skill.py coverage --repo . --json \
  --planned src/api.py --planned src/utils.py \
  --exclude docs
```

若 `uncovered_files` 非空，继续补 residual commit，直到归零。

## 执行提交

每个 commit 一律通过脚本执行，而不是手写 `git commit`：

```bash
python3 scripts/commit_skill.py commit --repo . \
  --file src/api.py --file src/utils.py \
  --type feat \
  --title '新增接口适配层' \
  --bullet '整理 API 调用入口' \
  --bullet '统一工具函数调用方式' \
  --sign-mode auto
```

### 签名规则

- `sign_mode=auto`：若探测到可用 GPG 私钥或 Git 已配置签名，则优先尝试 `git commit -S`
- `sign_mode=signed`：强制 signed commit；失败即报错
- `sign_mode=unsigned`：明确无签名提交
- 若 `auto` 路径签名失败，且错误属于 `gpg-agent` / `pinentry` / `No agent running` / `failed to sign the data`，脚本只允许**单次** fallback 到：

```bash
git -c commit.gpgsign=false commit ...
```

脚本会：

- 若有 TTY，则设置 `GPG_TTY=$(tty)`
- 尝试 `gpgconf --launch gpg-agent`
- 探测 `gpg --list-secret-keys --keyid-format LONG`
- 统一拼装多个 `-m`
- 返回本次是否 signed / 是否发生 fallback / 最终 SHA

## Submodule 规则

若 inventory 发现 dirty submodule：

1. 先对**子模块仓库路径**单独运行 `commit` 子命令
2. 子模块提交完成后，再在父仓库提交 submodule pointer 更新
3. pointer 更新可聚合为一个 `chore`

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
