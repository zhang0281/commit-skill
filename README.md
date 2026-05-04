# commit-skill

用于托管 `commit` 技能的独立 GitHub 仓库；现约束为**只提交执行 `$commit` 当下扫描到的路径与内容快照**。

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
        ├── references/
        │   ├── plan-schema.md
        │   ├── signing.md
        │   ├── submodules.md
        │   ├── error-codes.md
        │   └── safety.md
        ├── scripts/
        │   ├── commit_skill.py
        │   └── lib/
        └── tests/
```

## 架构

本仓库的 `commit` skill 采用 **AI 判定 + 代码执行** 的混合模式：

- **AI**：做语义拆分、残余提交裁决、中文提交信息生成
- **脚本**：做 inventory、plan JSON、coverage audit、统一错误码、submodule 扫描、签名探测与真正的 `git commit`
- **多子代理**：默认自动判断；多文件、多候选、多 repo/submodule 时启动只读 explorer 子代理按 candidate/submodule 并行收集 facts；不可用则串行退化。
- **plan 默认 summary-only**：`plan` 自动先跑、输出 summary 供模型、同时写出完整 `/tmp/commit-plan-<repo_hash>.json` 供后续 `coverage`/`apply-plan`。
- **单次快照原则**：`coverage_baseline` 固定本轮 `$commit` 起手时的路径与 fingerprint；后续新路径或同路径内容漂移不会被顺带提交。
- **渐进披露**：`SKILL.md` 只保留主流程，schema / signing / submodule / error codes / safety 细则拆入 `skills/commit/references/`。

## 兼容性

- **Codex**：通过 `skills/commit/agents/openai.yaml` 暴露 metadata
- **Claude Code**：通过仓库根 `.claude-plugin/marketplace.json` 暴露 marketplace 信息
- 两端共享同一份 `skills/commit/SKILL.md` 与 `skills/commit/scripts/` 逻辑

## 默认工作流

1. `plan --summary-only`：默认先写 summary 供 AI，完整计划存 `/tmp/commit-plan-<repo_hash>.json`
2. AI 基于计划 JSON 做语义裁决，补全 `type/title/bullets`
3. `coverage --plan-file`：仅校验本次快照覆盖度，并拒绝快照外路径
4. `apply-plan --plan-file`：统一执行 commit，仅落地本次快照内改动

## 多子代理并行分析（默认自动判断）

当 plan 产出多个 commit 条目、多文件改动，或既有 submodule 又有根仓改动时，主线程默认启动只读 explorer 子代理：

- 按 candidate commit / submodule path 分派
- 子代理只读：`git status --porcelain -z`、`git diff --name-status`、`git log -1`、`git submodule status`
- 子代理回报：files、sign hints、top-level group、submodule 状态
- 主线程汇总后更新 plan JSON，确保 coverage/execute 以真实 facts 运行
- 若运行环境不可用子代理，自动退化为主线程串行采集
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
- include/exclude 同时作用于 root 与 submodule path
- 统一错误码便于 Codex 与 Claude Code 都稳定消费脚本结果
- `sign-mode=auto` 在 plan 中保留 auto，apply 时若 GPG 可用则优先 signed commit，失败可 fallback
