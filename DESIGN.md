# commit-skill DESIGN

## 设计目标

- 将 `commit` 技能从本地目录抽离为可独立托管的 GitHub 仓库
- 保持与 cc-switch 技能发现 / 安装 / 更新流程兼容
- 同时兼容 Codex 与 Claude Code
- 通过 plan JSON + 多脚本架构，进一步降低 prompt token 消耗并提高维护性

## 方案选择

### 方案 A：单脚本混合模式
- 优点：实现快
- 缺点：脚本很快膨胀，测试与 submodule 流程不易维护

### 方案 B：单入口 CLI + 多模块 lib + tests
- 优点：结构清晰、可测试、便于统一错误码与扩展 submodule
- 缺点：文件数增加

**最终选择：方案 B**

## 关键决策

1. **技能主体放在 `skills/commit/`**
   - 便于后续扩展为多技能仓库
   - 更接近现有 skills 仓库生态

2. **保留 `agents/openai.yaml` 与 `.claude-plugin/marketplace.json`**
   - 前者服务 Codex
   - 后者服务 Claude Code

3. **以 `plan JSON` 作为 AI 与脚本的中介协议**
 - `plan` 负责生成结构化候选计划
 - AI 负责编辑 `commits` 的语义字段
 - `coverage` / `apply-plan` 消费最终计划
  - 默认自动跑 `plan --summary-only`，向模型提供精简 summary，同时把完整 JSON 写 `/tmp/commit-plan.json` 供后续复用

4. **保留单入口 `scripts/commit_skill.py`，内部拆成多模块**
   - 对 AI 保持稳定调用面
   - 对维护者暴露清晰边界：inventory / signing / coverage / executor / planner

5. **统一错误码**
   - 让 Codex 与 Claude Code 都能稳定消费脚本返回
   - 避免把错误处理逻辑塞回 prompt

6. **增强 submodule 支持**
   - `plan` 显式产生 `submodule_internal` 与 `submodule_pointer` 两类提交项
   - 让 AI 与执行器都能识别父仓库 / 子模块仓库的边界

## 已知限制

- 语义拆分仍依赖 AI 裁决，脚本只处理确定性逻辑
- submodule merge 策略仍偏保守，默认先 internal 再 pointer
- `sign-mode=auto` 在无 TTY 沙箱下可能探测不到完整 GPG 灵脉，但结构已允许 fallback

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

### 2026-04-14 - 升级为多脚本 plan JSON 架构

**变更内容**: 将单脚本拆为单入口 CLI + lib 多模块 + tests，引入 `plan` / `apply-plan`、统一错误码、增强 submodule 与测试体系

**变更理由**: 让 `$commit` 默认自动调用 `plan`，同时对 Codex 与 Claude Code 暴露同一份稳定脚本协议

**影响范围**: `skills/commit/SKILL.md`、`skills/commit/agents/openai.yaml`、`skills/commit/scripts/`、`skills/commit/tests/`

**决策依据**: 用 plan JSON 作为 AI 与脚本的协作中介，进一步减少 prompt 复杂度并提升可测试性
- **恢复多子代理并行分析**：
  - `plan` 产出多个 candidate 或 root + submodule 混合时，主线程 spawn explorer 子代理按 candidate/submodule 分头只读分析 facts
  - 子代理仅允许 `git status --porcelain -z` / `git diff --name-status` / `git log -1` / `git submodule status`
  - 主线程汇总后更新 plan JSON，确保 AI 与 coverage/apply-plan 使用真实信息
