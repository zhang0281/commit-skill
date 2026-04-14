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

## 兼容性

- **Codex**：通过 `skills/commit/agents/openai.yaml` 暴露 metadata
- **Claude Code**：通过仓库根 `.claude-plugin/marketplace.json` 暴露 marketplace 信息
- 两端共享同一份 `skills/commit/SKILL.md` 与 `skills/commit/scripts/` 逻辑

## 默认工作流

1. `plan`：自动生成可编辑 commit 计划 JSON
2. AI 基于计划 JSON 做语义裁决，补全 `type/title/bullets`
3. `coverage --plan-file`：校验计划覆盖度
4. `apply-plan --plan-file`：统一执行 commit

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
