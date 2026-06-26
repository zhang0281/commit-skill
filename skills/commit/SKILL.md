---
name: commit
description: 拆分并创建规范 Git 提交。Use when Codex or Claude Code needs to inspect working tree changes, let AI generate only commit messages, then hand the remaining plan validation, coverage audit, submodule ordering, signing, and actual git commit execution entirely to scripts under hard constraints.
---

# Commit

将执行 `$commit` 当下扫描到的路径与内容快照，整理成固定数量的 Git 提交。

## Core Constraints

- **AI 只负责**：生成每个固定 candidate commit 的 `type/title/bullets`。
- **脚本负责**：扫描、候选 commit 固化、message template、message merge、coverage、signing、submodule 顺序、`git add/commit`。
- **默认快路**：`plan --summary-only → message-template → AI 填 messages.json → apply-plan --messages-file`。
- **默认边界**：
  - 单项目根仓改动：固定 **1 个 commit**
  - 多子模块改动：固定为 **每个 dirty 子模块 1 个 internal commit**，再加 **1 个根仓 pointer commit** 统一记录 gitlink
- **硬限制**：不得让 AI 改 `paths/repo_path/sign_mode/coverage_baseline`，不得让 AI 合并、拆分、增删、重排 commit。
- **执行约束**：不要手写 Git 命令；不要启用子代理；不要输出冗长过程说明。

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

## 默认执行链

### 1) 固定候选 commit

```bash
python3 "$COMMIT_SKILL_SCRIPT" plan --repo . --summary-only
```

要点：

- `summary.plan_file` 是后续唯一计划文件。
- `candidate_commits` 已固定本轮 commit 边界；默认不再让 AI 讨论是否合并/拆分。
- 根仓默认只生成一个 commit；子模块默认每个 dirty submodule 一个 internal commit，最后根仓再统一提交 gitlink pointer。
- `changed_count=0` 时直接结束。

### 2) 生成 AI message template

```bash
python3 "$COMMIT_SKILL_SCRIPT" message-template --plan-file /tmp/commit-plan-<repo_hash>.json
```

让 AI **只返回**：

```json
{
  "commits": [
    {
      "id": "repo:single",
      "type": "feat",
      "title": "新增 Slint 原生 GUI 替代 Tauri 部署界面",
      "bullets": [
        "使用 Slint 1.9 + Fluent 主题，软件渲染器零 GPU 依赖",
        "四步向导界面：路径选择 → 环境检测 → 确认配置 → 进度日志",
        "EventSink bridge 模式实现 backend → UI 异步更新"
      ]
    }
  ]
}
```

message 建议：

- title 必须准确概括本次变更的核心意图，不可使用 "整理改动"、"更新文档" 等泛化描述
- bullets 基于 `diff_summary` 提炼变更的语义：做了什么、为什么做、影响了什么
- **禁止**直接使用 "涉及 X"、"处理 N 个文件改动"、"包含 X 改动" 这类结构性元数据作为 bullets
- 以 **1 个 title + 1~4 个 bullets** 为默认；大改动可适当增加 bullets
- 若变更涉及新增能力、架构调整、行为变化，bullets 应说明具体新增/调整了什么
- `diff_summary.file_actions` 列出了每个文件的新增/修改/删除状态，用于理解变更范围
- `diff_summary.stat_lines` 提供了变更行数统计，用于判断改动量级

### 3) 交给脚本执行

```bash
python3 "$COMMIT_SKILL_SCRIPT" apply-plan \
  --plan-file /tmp/commit-plan-<repo_hash>.json \
  --messages-file /tmp/commit-messages.json \
  --json
```

`apply-plan` 会自动完成：

- merge `messages.json`
- 校验 id 集合、字段白名单、message 合法性
- 执行 message coverage audit：若关键变更面（路径覆盖、分类覆盖）未被 title/bullets 覆盖，脚本会自动追加结构性兜底 bullets
- coverage audit
- submodule 顺序校验
- signing / fallback
- 真正的 `git commit`

## 手动调试子命令

```bash
python3 "$COMMIT_SKILL_SCRIPT" inventory --repo . --json
python3 "$COMMIT_SKILL_SCRIPT" plan --repo . --out /tmp/commit-plan-<repo_hash>.json --json
python3 "$COMMIT_SKILL_SCRIPT" message-template --plan-file /tmp/commit-plan-<repo_hash>.json --json
python3 "$COMMIT_SKILL_SCRIPT" coverage --plan-file /tmp/commit-plan-<repo_hash>.json --messages-file /tmp/commit-messages.json --json
python3 "$COMMIT_SKILL_SCRIPT" commit --repo . \
  --file src/api.py \
  --type fix \
  --title '修复接口参数透传' \
  --bullet '修正请求参数映射' \
  --sign-mode auto
```

## 何时读取 references

- `message-template` 之外还想手改完整 plan：读 `references/plan-schema.md`。此路仅作调试，不是默认快路。
- 签名、GPG、fallback、`sign_mode`：读 `references/signing.md`。
- submodule internal / pointer、submodule include/exclude：读 `references/submodules.md`。
- 非零错误码、`ok=false`、`passed=false`：读 `references/error-codes.md`。
- 手动恢复、命令边界、staged cleanup：读 `references/safety.md`。

## Response Format

最终回答尽量短，使用工程化字段：

- `summary`：一句话说明执行结果
- `plan`：candidate commits、执行步骤、coverage 结果
- `result`：commit SHA / title / files / signed / fallback
- `remaining`：剩余未提交项或失败点
- `next_step`：下一步
