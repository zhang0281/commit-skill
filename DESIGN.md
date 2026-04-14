# commit-skill DESIGN

## 设计目标

- 将 `commit` 技能从本地目录抽离为可独立托管的 GitHub 仓库
- 保持与 cc-switch 技能发现 / 安装 / 更新流程兼容
- 参考 `anthropics/skills` 提供最小可用 marketplace 元数据

## 方案选择

### 方案 A：仓库根直接放 `commit/`
- 优点：结构更短
- 缺点：与 `anthropics/skills` 风格不一致，后续扩展多技能仓库时不够统一

### 方案 B：使用 `skills/commit/`
- 优点：与 `anthropics/skills` 风格一致，便于后续扩展多个技能
- 缺点：目录层级略深

**最终选择：方案 B**

## 关键决策

1. **技能主体放在 `skills/commit/`**
   - 便于后续扩展为多技能仓库
   - 更接近现有 skills 仓库生态

2. **保留 `agents/openai.yaml`**
   - 复用当前 `commit` 技能的展示名、摘要与默认提示词

3. **增加 `.claude-plugin/marketplace.json`**
   - 用于对齐 `anthropics/skills` 的 marketplace 组织方式
   - 为将来在支持 marketplace 的客户端中复用做准备

## 已知限制

- 当前仓库只包含一个技能：`commit`
- `marketplace.json` 中的邮箱仍是占位值，需要魔尊后续替换
- 是否能被 cc-switch 自动发现，仍取决于远端 GitHub 仓库可见性与发布状态

## 变更历史

### 2026-04-14 - 初始化 commit-skill 仓库骨架

**变更内容**: 创建 README、DESIGN、marketplace.json 与 `skills/commit` 目录

**变更理由**: 为 `commit` 技能提供独立 GitHub 仓库结构，支撑后续接入 cc-switch

**影响范围**: `commit-skill` 仓库根目录与 `skills/commit` 技能目录

**决策依据**: 优先兼容 `anthropics/skills` 风格与 cc-switch 仓库化管理需求
