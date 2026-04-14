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

4. **采用 AI + Script 混合执行**
   - AI 负责语义拆分、中文提交信息、残余提交裁决
   - `scripts/commit_skill.py` 负责 inventory、coverage audit、签名探测与提交落地
   - 目标是减少长 prompt token 消耗，提高 `$commit` 执行稳定性与速度

## 已知限制

- 当前仓库只包含一个技能：`commit`
- `marketplace.json` 当前使用公开联系邮箱 `qq814608@163.com`
- 是否能被 cc-switch 自动发现，仍取决于远端 GitHub 仓库可见性与发布状态
- 语义拆分仍依赖 AI 裁决，脚本只处理确定性逻辑

## 变更历史

### 2026-04-14 - 初始化 commit-skill 仓库骨架

**变更内容**: 创建 README、DESIGN、marketplace.json 与 `skills/commit` 目录

**变更理由**: 为 `commit` 技能提供独立 GitHub 仓库结构，支撑后续接入 cc-switch

**影响范围**: `commit-skill` 仓库根目录与 `skills/commit` 技能目录

**决策依据**: 优先兼容 `anthropics/skills` 风格与 cc-switch 仓库化管理需求

### 2026-04-14 - 重构为 AI + Script 混合模式

**变更内容**: 新增 `skills/commit/scripts/commit_skill.py`，并将 `SKILL.md` 压缩为薄 prompt，改由脚本承接 inventory、签名与提交执行逻辑

**变更理由**: 降低 prompt token 消耗，加快 `$commit` 响应，并让 GPG/coverage 逻辑更稳定

**影响范围**: `skills/commit/SKILL.md`、`skills/commit/agents/openai.yaml`、`skills/commit/scripts/commit_skill.py`

**决策依据**: 采用“AI 判定 + 代码执行”的混合架构，保留语义灵活性，同时将确定性流程下沉到脚本
