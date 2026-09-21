# commit-skill

用于托管 `commit` 技能的独立 GitHub 仓库；现约束为**只提交执行 `$commit` 当下扫描到的路径与内容快照**。

## 目录结构

```text
commit-skill/
├── README.md
├── .commit-skill.json       # 可选：session 内并行运行的 preflight tests
├── .claude-plugin/
│   └── marketplace.json
└── skills/
    └── commit/
        ├── SKILL.md
        ├── agents/
        │   └── openai.yaml
        ├── references/
        │   ├── plan-schema.md
        │   ├── signing.md
        │   ├── submodules.md
        │   ├── error-codes.md
        │   └── safety.md
        ├── scripts/
        │   ├── commit_skill.py
        │   └── lib/
        │       ├── preflight.py
        │       └── postflight.py
        └── tests/
```

## 架构

本仓库的 `commit` skill 采用 **AI 仅生成 commit message + 脚本执行** 的混合模式：

- **AI**：只填写固定 candidate commits 的 `type/title/bullets`
- **脚本**：负责 inventory、candidate 固化、semantic diff、message merge、preflight、coverage、submodule、签名、`git commit`、验签与最终 clean-tree/fingerprint 核验
- **提交责任边界**：外层 AI 启动一次 `commit-session` 后只回写 message JSON；真正的 `prepare`、coverage、`git add/commit` 均由同一脚本进程执行
- **默认 fast path**：`commit-session` 先固化 snapshot 并输出 template，AI 回写 messages JSON 后，同一进程完成 merge、coverage 与真实提交
- **固定 commit 数**：
  - 单项目根仓改动：1 个 commit
  - 多子模块改动：每个 dirty submodule 1 个 internal commit，另加 1 个根仓 pointer commit
- **message coverage audit**：`message-template` 会给出 `must_cover`，`apply-plan` 若发现 title/bullets 未覆盖关键变更面，会自动补齐必要 bullets
- **单次快照原则**：`coverage_baseline` 固定本轮 `$commit` 起手时的路径与 fingerprint；后续新路径或同路径内容漂移不会被顺带提交。
- **渐进披露**：`SKILL.md` 只保留主流程，schema / signing / submodule / error codes / safety 细则拆入 `skills/commit/references/`。

## 兼容性

- **Codex**：通过 `skills/commit/agents/openai.yaml` 暴露 metadata
- **Claude Code**：通过仓库根 `.claude-plugin/marketplace.json` 暴露 marketplace 信息
- 两端共享同一份 `skills/commit/SKILL.md` 与 `skills/commit/scripts/` 逻辑

## 默认工作流

1. `commit-session --repo .`：在可保持 stdin 的持久交互进程中启动脚本并固化 snapshot，输出 `phase=prepared` 与 message template；一次性 exec 若关闭 stdin，不适用于此步骤
2. AI 通过同一进程 stdin 回写允许填写的 `id/type/title/bullets`；messages 文件由脚本放入 `/tmp/commit-messages-<random>.json`
3. 同一进程输出 `phase=complete`，完成 merge、preflight、coverage、签名、实际提交、验签和最终 inventory
4. 宿主不支持保持 stdin，或首轮返回 `commit-session 未收到 messages JSON` 时，依据 template 写入新的 `/tmp/commit-messages-<random>.json`，退回 `fast-commit --messages-file ...`；等待其 `phase=complete`

无改动时，`commit-session` 直接输出 `phase=complete` + `noop`，不等待 stdin，也不做无意义的 GPG signing probe。

默认不需要外围 `git diff`、tests、coverage、inventory 或验签调用：`phase=prepared` 已携带有界 semantic diff，`phase=complete` 已携带 `preflight` 与 `postflight`。仓库可用 `.commit-skill.json` 的 `preflight.commands[].argv` 配置 tests；这些命令在等待 AI message 时并行执行。`git diff --check` 始终使用临时 index 自动执行，不改变真实 staging。

## message-only 硬限制

- AI 不得修改：
  - `paths`
  - `repo_path`
  - `sign_mode`
  - `coverage_baseline`
  - commit 条目数量与顺序
- `messages-file` 若缺 id、多 id、非法字段、非法 type、空 title，脚本直接拒绝执行
- `apply-plan` 会在真正提交前自动执行 coverage；快照外路径、重复路径、pointer 顺序错误、fingerprint drift 一律拦截

## 脚本子命令

- `inventory`：调试库存信息
- `plan`：生成可编辑计划 JSON
- `prepare`：一次生成固定计划与 AI message template（模板调试路径）
- `fast-commit`：消费 AI messages JSON，一次完成 prepare 与最终提交
- `commit-session`：单进程输出 template、接收 AI message 并完成最终提交（默认 fast path）
- `message-template`：生成 AI 专用的最小 message JSON 模板
- `coverage`：按参数或 plan JSON 执行覆盖校验
- `apply-plan`：执行最终计划
- `commit`：直接执行单个 commit（调试用途）

## 测试

```bash
python3 -m unittest discover -s skills/commit/tests -p 'test_*.py'
```

- `skills/commit/tests/test_golden.py`：对 `plan` 与 `message-template` 的稳定 JSON 输出做 golden snapshot 校验
- `skills/commit/tests/golden/`：保存归一化后的参考输出，避免重构后行为无意漂移

## 说明

- `commit-session` 子命令是 `$commit` 默认流程；`fast-commit`、`plan` 与 `prepare` 仍可单独用于调试
- include/exclude 同时作用于 root 与 submodule path
- 统一错误码便于 Codex 与 Claude Code 都稳定消费脚本结果
- `sign-mode=unsigned` 会以 `git -c commit.gpgsign=false commit` 强制覆盖仓库/全局签名配置；`sign-mode=signed` 直接尝试并验签；`auto` 仍保留探测与 fallback
