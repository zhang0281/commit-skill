---
name: commit
description: 拆分并创建规范 Git 提交。Use when Codex or Claude Code needs to inspect working tree changes, let AI generate only commit messages, then hand the remaining plan validation, coverage audit, submodule ordering, signing, and actual git commit execution entirely to scripts under hard constraints.
---

# Commit

将执行 `$commit` 当下扫描到的路径与内容快照，整理成固定数量的 Git 提交。

## Core Constraints

- **AI 只负责（默认 host mode）**：生成每个固定 candidate commit 的 `type/title/bullets`；若 `message_source=custom-model`，该生成步骤由配置的 endpoint 完成，宿主 AI 不得回写 message，除非脚本随后明确输出 `phase=fallback`。
- **脚本负责**：扫描、候选 commit 固化、message template、message merge、coverage、signing、submodule 顺序、`git add/commit`。
- **默认快路**：`commit-session` 单进程交互链；脚本先固化 snapshot 并输出 template，AI 回写 message 后同一进程完成 apply 与最终核验。
- **默认边界**：
  - 单项目根仓改动：固定 **1 个 commit**
  - 多子模块改动：固定为 **每个 dirty 子模块 1 个 internal commit**，再加 **1 个根仓 pointer commit** 统一记录 gitlink
- **硬限制**：不得让 AI 改 `paths/repo_path/sign_mode/coverage_baseline`，不得让 AI 合并、拆分、增删、重排 commit。
- **执行约束**：不要手写会改变仓库状态的 Git 命令；只读 diff/status 可用于生成 message；不要启用子代理；不要输出冗长过程说明。
- **入口分流**：显式 `$commit` 后首个非空 token 严格为 `doctor` 时进入只读诊断路由；其他输入才进入默认提交快路。提交路由已提供完整上下文与授权，加载本 skill 后立即执行，不要先搜索 memory，不要读取 doctrine / loop-engineering / 其他 skill，也不要另跑 `git diff`、tests、coverage、inventory 或 `git verify-commit`。仅当脚本返回非零错误码时读取对应 reference。

## 资源路径解析（防止误找项目目录）

执行任何 `scripts/` 或读取 `references/` 前，先把**本 skill 根目录**解析成绝对路径，并在命令中使用该绝对路径：

- `COMMIT_SKILL_DIR` = 当前 `SKILL.md` 所在目录的绝对路径（来自已加载的 skill path 或实际打开的 `SKILL.md` 文件路径）。
- `COMMIT_SKILL_SCRIPT="$COMMIT_SKILL_DIR/scripts/commit_skill.py"`。
- 不要写死某台机器上的安装路径；不要假定 `scripts/commit_skill.py` 位于启动 Codex 的项目目录。
- 启动 Codex 的项目目录只作为目标仓库传给 `--repo`，例如在任意 repo 内执行时仍使用 `--repo .`。
- 若向用户说明执行细节，须注明调用的 Python 脚本位于 commit skill 安装目录下，而非当前项目目录；涉及脚本或 reference 文件时尽量给出已解析后的完整路径。

## `$commit` 入口与子命令分流

这是 skill-level 的参数路由，不是 zsh 的 `compdef`/Tab completion。只检查 `$commit` 后的**第一个非空 token**，因此既能保留自然语言，又不会把 prose 中偶然出现的 `doctor` 当成子命令：

- 首 token 严格为 `doctor`：执行 `python3 "$COMMIT_SKILL_SCRIPT" doctor --json`，不启动 `commit-session`，不扫描或修改仓库。
- `$commit doctor --probe`：执行 `doctor --probe --json`，做短上下文实际探测；`doctor` 后的自然语言只作为诊断意图，须映射到已有选项，不得当作 commit scope 或任意 CLI 参数转发。
- `$commit doctor 请实际请求模型并要求只回复 ok` 等价于 `doctor --probe --json`；`$commit doctor 只查看当前配置` 等价于静态 `doctor --json`。
- 首 token 不是 `doctor`：整段 suffix 继续按原有自然语言提交要求处理，例如 `$commit 只提交 src/api.py`。
- 若要提交名为 `doctor` 的路径，使用明确动词，例如 `$commit 提交 doctor`；不要把单独的 `$commit doctor` 当作提交范围。

当前仅将 `doctor` 暴露为 `$commit` 一级子命令；`inventory`、`plan`、`prepare`、`fast-commit`、`commit-session`、`coverage`、`message-template`、`apply-plan`、`commit` 仍是脚本调试子命令，按下文绝对路径直接调用。

## 可选模型 backend 与配置诊断

默认情况下，`commit-session` 仍由宿主 Codex/Claude 生成 message JSON，不读取任何模型 API 环境变量。若希望由 commit skill 自行调用 OpenAI-compatible Chat Completions，可在 `zshrc` 中导出以下三项：

```zsh
export commit_url='http://127.0.0.1:23000/v1'
export commit_key='your-api-key'
export commit_model='your-model'
# 可选：默认 90 秒，允许 0 < timeout <= 600
export commit_timeout='90'
```

也兼容 `COMMIT_URL`、`COMMIT_KEY`、`COMMIT_MODEL`、`COMMIT_TIMEOUT` 及 `COMMIT_BASE_URL` / `COMMIT_API_KEY` 等大写别名；同一字段同时存在时，文档中的小写名称优先。必须使用 `export`，仅在 `zshrc` 中赋值而未导出时，Python 子进程不可见。

- 三项 `url/key/model` 均存在且有效时，`commit-session` 的 `phase=prepared` 会标记 `message_source=custom-model`，将当前受限 `message_template` 发送到 `{url}/v1/chat/completions`（若 URL 已含 `/v1` 或完整 `/chat/completions`，不会重复拼接）。请求、响应或 message schema 失败会重试 2 次（共最多 3 次）；仍失败时输出 `phase=fallback`，再把 message 生成交回宿主 AI，随后仍由脚本执行 message schema、coverage、签名、提交与 postflight。
- 三项均未设置时，继续现有 `message_source=stdin` 逻辑，不发网络请求，也不改变宿主模型。
- 仅设置部分变量或 URL/timeout 无效时，立即返回 `MODEL_CONFIG_INVALID`，不会提交；先运行 `doctor` 检查。
- 如需把“未继承环境变量”或 custom model 连续失败也变成硬失败，可直接加 `--require-custom-model`；配置缺失时返回 `MODEL_CONFIG_INVALID`，模型三次失败时返回 `MODEL_REQUEST_FAILED`，均不会等待宿主 AI stdin：

  ```bash
  zsh -lic 'python3 "$HOME/.codex/skills/commit/scripts/commit_skill.py" commit-session --repo . --require-custom-model --json'
  ```

- 环境变量只存在于启动脚本的进程环境。修改 `zshrc` 后，已经运行的 Codex/Claude 进程不会自动获得新变量；请重启宿主，或在新的 login shell 中直接执行上面的命令。
- 该 backend 只控制 commit skill 自己生成 message 的 API 请求，不会修改已经启动的 Codex/Claude 外层模型选择；请求会包含当前 diff 摘要，请确认 endpoint 的数据边界。
- `commit_key` 只从环境读取，不出现在命令行；`doctor` 仅显示是否设置及脱敏 preview，不打印完整 key、URL query 或 fragment。

诊断当前生效配置：

```bash
python3 "$COMMIT_SKILL_SCRIPT" doctor --json
python3 "$COMMIT_SKILL_SCRIPT" doctor --probe --json
```

返回 `mode=existing` 表示沿用旧逻辑；返回 `mode=custom-api` 且 `active=true` 表示配置静态校验通过。普通 `doctor` 不联网；显式 `--probe` 才发送不含仓库内容的极短请求，并要求模型严格回复小写 `ok`。探测通过时返回 `probe.status=passed`；未配置 custom backend 时返回 `skipped`；请求失败或响应不是严格的 `ok` 时返回 `MODEL_REQUEST_FAILED`。

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

### 1) 启动 commit-session 并固化 snapshot

此命令必须运行在能保持 stdin/stdout 的交互进程中（例如持久 terminal 或带 `stdin=PIPE` 的 `Popen`）。不要用会在首个工具调用结束时关闭 stdin 的一次性 `exec` 启动：

```bash
python3 "$COMMIT_SKILL_SCRIPT" commit-session --repo . --json
```

配置了 custom backend 且希望完全禁止 host-AI message 回写时，使用：

```bash
python3 "$COMMIT_SKILL_SCRIPT" commit-session --repo . --require-custom-model --json
```

脚本首行输出 `phase=prepared` JSON，内含固定 `plan_file`、位于 `/tmp` 且带随机后缀的 `messages_file`，以及供 AI 阅读的 `message_template`。`message_template.commits[].diff_summary.semantic_diff` 已携带有界 patch / untracked text；不得再调用独立 `git diff`。此时 snapshot 已经固化，`git diff --check` 已使用临时 index 完成，配置的 tests 已并行启动。若 `message_source=custom-model`，脚本会自行调用配置 endpoint；宿主只需等待后续 phase。若收到 `phase=complete`，不得生成或写入 messages JSON；若收到 `phase=fallback` 且 `message_source=stdin`，才向同一进程 stdin 回写 messages JSON，然后等待 `phase=complete`。

若 `changed_count=0`，脚本直接输出 `phase=complete` 的 `noop` 结果，不等待 stdin，也跳过无意义的 GPG signing probe。

### 2) AI 回写 messages JSON

AI 读取 `phase=prepared` 后，只向同一进程 stdin 写入一个 messages JSON 对象：

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

`id` 必须遵循 planner 的确定性规则：根仓文件或根仓文件 + pointer 为 `repo:single`；子模块内部提交为 `submodule-internal:<path>`；仅根仓 pointer 为 `repo:submodule-pointers`。AI 不得自行增删、合并、拆分或重排 candidate。

若命令在输出 `phase=prepared` 后立即返回 `MESSAGE_FILE_INVALID` / `commit-session 未收到 messages JSON`，这是宿主关闭 stdin 的 transport failure，不是提交完成。不要再次盲目启动 `commit-session`；应依据刚才的 `message_template` 写入一个新的、符合 `/tmp/commit-messages-<random>.json` 命名规则的 messages 文件，再执行下方的 `fast-commit` 兼容入口。失败的 session 会清理其临时 messages 文件。

message 建议：

- title 必须准确概括本次变更的核心意图，不可使用 "整理改动"、"更新文档" 等泛化描述
- bullets 基于只读 diff 提炼变更的语义：做了什么、为什么做、影响了什么
- **禁止**直接使用 "涉及 X"、"处理 N 个文件改动"、"包含 X 改动" 这类结构性元数据作为 bullets
- 以 **1 个 title + 1~4 个 bullets** 为默认；大改动可适当增加 bullets
- 若变更涉及新增能力、架构调整、行为变化，bullets 应说明具体新增/调整了什么
- 需要脚本提供 `diff_summary` 时，切回 `prepare` + `message-template` 调试路径

### 3) 同一进程完成 apply-plan

将上述 JSON 通过同一 `commit-session` 进程的 stdin 写回后，脚本输出 `phase=complete`，并自动完成：

- merge `/tmp/commit-messages-<random>.json`
- 校验 id 集合、字段白名单、message 合法性
- 执行 message coverage audit：若关键变更面（路径覆盖、分类覆盖）未被 title/bullets 覆盖，脚本会自动追加结构性兜底 bullets
- coverage audit
- preflight：临时 index `git diff --check` + 仓库 `.commit-skill.json` 配置的 tests
- submodule 顺序校验
- signing / fallback
- 最终 coverage / snapshot drift 核验
- 真正的 `git add/commit`
- signed commit 的 `git verify-commit`
- 最终 inventory、clean-tree 与 fingerprint 复核；后写入改动直接返回 `postflight.post_snapshot_changes`

`phase=complete` 已是最终核验结果，AI 不得再独立调用 `inventory`、`git verify-commit`、`git status` 或 coverage。只有 `ok=false` 或 `postflight.clean=false` 时，按返回字段直接报告；不要自行补跑诊断命令。

仓库可用根目录 `.commit-skill.json` 配置 tests；脚本会在等待 AI message 时并行执行，以隐藏大部分测试耗时：

```json
{
  "preflight": {
    "commands": [
      {
        "name": "unit-tests",
        "argv": ["python3", "-B", "-m", "unittest", "discover", "-s", "tests"],
        "timeout_seconds": 120
      }
    ]
  }
}
```

`argv` 必须是字符串数组，不经 shell；未配置时仍执行 `git diff --check`，并在结果中明确 `tests_configured=false`。

若宿主无法保持 stdin 进程，可退回一次性兼容入口：

```bash
python3 "$COMMIT_SKILL_SCRIPT" fast-commit \
  --repo . \
  --messages-file /tmp/commit-messages-<random>.json \
  --json
```

该兼容入口会重新固化一次 snapshot；写入 messages 文件后，必须等待其输出 `phase=complete`，并以其中的 `ok`、commit 与 `postflight` 字段作为最终结果。

## 手动调试子命令

```bash
python3 "$COMMIT_SKILL_SCRIPT" inventory --repo . --json
python3 "$COMMIT_SKILL_SCRIPT" prepare --repo . --out /tmp/commit-plan-<repo_hash>.json --json
python3 "$COMMIT_SKILL_SCRIPT" commit-session --repo . --json
python3 "$COMMIT_SKILL_SCRIPT" fast-commit --repo . --messages-file /tmp/commit-messages-<random>.json --json
python3 "$COMMIT_SKILL_SCRIPT" plan --repo . --out /tmp/commit-plan-<repo_hash>.json --json
python3 "$COMMIT_SKILL_SCRIPT" message-template --plan-file /tmp/commit-plan-<repo_hash>.json --json
python3 "$COMMIT_SKILL_SCRIPT" coverage --plan-file /tmp/commit-plan-<repo_hash>.json --messages-file /tmp/commit-messages-<random>.json --json
python3 "$COMMIT_SKILL_SCRIPT" commit --repo . \
  --file src/api.py \
  --type fix \
  --title '修复接口参数透传' \
  --bullet '修正请求参数映射' \
  --sign-mode auto
```

## 何时读取 references

- 需要静态调试完整 plan 时，使用 `prepare` + `apply-plan`；需要非交互一次性执行时，使用 `fast-commit`；均非默认快路。
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
