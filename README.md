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
        └── agents/
            └── openai.yaml
```

## 包含内容

- `skills/commit/SKILL.md`：`commit` 技能主指令
- `skills/commit/agents/openai.yaml`：技能展示与默认提示词
- `.claude-plugin/marketplace.json`：参考 `anthropics/skills` 的 marketplace 元数据

## 用途

- 作为 GitHub 技能仓库供后续接入 cc-switch
- 作为 Claude 风格 marketplace 仓库骨架

## 后续建议

1. 初始化 Git 仓库并关联远端 `zhang0281/commit-skill`
2. 提交并 push 到 GitHub
3. 在 cc-switch 中添加该技能仓库后再安装 `commit`
