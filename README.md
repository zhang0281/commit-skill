# commit-skill

用于托管 `commit` 技能的独立 GitHub 仓库。

## 目录结构

```text
commit-skill/
├── README.md
├── .claude-plugin/
│   └── marketplace.json
└── skills/
    └── commit/
        ├── SKILL.md
        ├── agents/
        │   └── openai.yaml
        ├── scripts/
        │   ├── commit_skill.py
        │   └── lib/
        └── tests/
```

## 架构

本仓库的 `commit` skill 采用 **AI 判定 + 代码执行** 的混合模式：

- **AI**：做语义拆分、残余提交裁决、中文提交信息生成
- **脚本**：做 inventory、plan JSON、coverage audit、统一错误码、submodule 扫描、签名探测与真正的 `git commit`
- **多子代理**：仅当当前主模型为 `gpt-5.4`，且 plan 产出多个候选 commit 或存在 submodule 与根仓混合改动时，主线程才 spawn explorer 子代理按 candidate/submodule 并行只读收集 facts；否则退化为主线程串行收集。
- **plan 默认 summary-only**：`plan` 自动先跑、输出 summary 供模型、同时写出完整 `/tmp/commit-plan.json` 供后续 `coverage`/`apply-plan`。

## 兼容性

- **Codex**：通过 `skills/commit/agents/openai.yaml` 暴露 metadata
- **Claude Code**：通过仓库根 `.claude-plugin/marketplace.json` 暴露 marketplace 信息
- 两端共享同一份 `skills/commit/SKILL.md` 与 `skills/commit/scripts/` 逻辑

## 默认工作流

1. `plan --summary-only`：默认先写 summary 供 AI，完整计划存 `/tmp/commit-plan.json`
2. AI 基于计划 JSON 做语义裁决，补全 `type/title/bullets`
3. `coverage --plan-file`：校验计划覆盖度
4. `apply-plan --plan-file`：统一执行 commit

## 多子代理并行分析（仅限 gpt-5.4）

当且仅当当前主模型为 `gpt-5.4`，且 plan 产出多个 commit 条目或既有 submodule 又有根仓改动时，主线程会：

- `spawn_agent agent_type=explorer, model=gpt-5.4`：按 candidate commit / submodule path 分派
- 子代理只读：`git status --porcelain -z`、`git diff --name-status`、`git log -1`、`git submodule status`
- 子代理回报：files、sign hints、top-level group、submodule状态
- 主线程汇总后更新 plan JSON，确保 coverage/execute 以真实 facts 运行

若当前模型不是 `gpt-5.4`，则禁止启用子代理，统一退化为主线程串行采集；后续的 coverage/apply-plan 仍在主线程执行。
## 脚本子命令

- `inventory`：调试库存信息
- `plan`：生成可编辑计划 JSON
- `coverage`：按参数或 plan JSON 执行覆盖校验
- `apply-plan`：执行最终计划
- `commit`：直接执行单个 commit（调试用途）

## 测试

```bash
python3 -m unittest discover -s skills/commit/tests -p 'test_*.py'
```

## 说明

- `plan` 子命令既可手动调用，也会在 `$commit` 默认流程中自动先跑
- 统一错误码便于 Codex 与 Claude Code 都稳定消费脚本结果
- `sign-mode=auto` 下，若 GPG 可用则优先 signed commit
