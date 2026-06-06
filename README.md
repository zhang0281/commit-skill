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

本仓库的 `commit` skill 采用 **AI 仅生成 commit message + 脚本执行** 的混合模式：

- **AI**：只填写固定 candidate commits 的 `type/title/bullets`
- **脚本**：负责 inventory、candidate 固化、message template、message merge、message coverage audit、coverage audit、统一错误码、submodule 扫描、签名探测与真正的 `git commit`
- **默认 fast path**：`plan --summary-only` 自动先跑、输出 summary 并写出完整 `/tmp/commit-plan-<repo_hash>.json`；随后 `message-template` 生成 AI 专用最小 JSON；最终 `apply-plan --messages-file` 一步落地
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

1. `plan --summary-only`：固定 candidate commits，完整计划存 `/tmp/commit-plan-<repo_hash>.json`
2. `message-template --plan-file`：生成只允许填写 `id/type/title/bullets` 的最小 JSON
3. AI 只回填 messages JSON，不再编辑完整 plan，也不再参与 split/merge
4. `apply-plan --plan-file --messages-file`：脚本完成 merge、coverage 与实际提交

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

- `plan` 子命令既可手动调用，也会在 `$commit` 默认流程中自动先跑
- include/exclude 同时作用于 root 与 submodule path
- 统一错误码便于 Codex 与 Claude Code 都稳定消费脚本结果
- `sign-mode=auto` 在 plan 中保留 auto，apply 时若 GPG 可用则优先 signed commit，失败可 fallback
