# commit-skill DESIGN

## 设计目标

- 将 `commit` 技能从本地目录抽离为可独立托管的 GitHub 仓库
- 保持与 cc-switch 技能发现 / 安装 / 更新流程兼容
- 同时兼容 Codex 与 Claude Code
- 通过 message-only AI + plan JSON + 多脚本架构，进一步降低 prompt token 消耗并提高维护性
- 将 `$commit` 的提交边界固定为“启动时扫描到的路径与内容快照”，避免执行期重复扫描直到全部提交

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

3. **以 `plan JSON` + `messages JSON` 作为 AI 与脚本的中介协议**
 - `plan` 负责生成结构化候选计划，并固定默认 commit 数量
 - `message-template` 负责把 plan 缩成 AI 专用的最小 message 模板
 - AI 只填写 `id/type/title/bullets`
 - `apply-plan --messages-file` 负责 merge、校验与执行
 - `prepare` 将 plan summary 与 message template 合并为一次脚本调用，同时把完整 JSON 写 `/tmp/commit-plan-<repo_hash>.json`
 - 真正的 `git add/commit` 始终由 `apply-plan` 内部脚本执行，AI 不直接执行 Git 命令

4. **固定默认提交边界**
   - 单项目根仓改动统一收为 1 个根仓 commit
   - 多子模块改动按 dirty submodule 拆成多个 internal commit
   - 父仓 gitlink pointer 统一收为 1 个根仓 commit，避免残留脏树

5. **message coverage audit**
   - `message-template` 为每个 commit 生成 `must_cover`
   - AI 可直接复用这些 bullets，也可自行压缩表达
   - `apply-plan` merge message 后会自动补齐遗漏的关键变更面，确保提交说明不失真

6. **保留单入口 `scripts/commit_skill.py`，内部拆成多模块**
   - 对 AI 保持稳定调用面
   - 对维护者暴露清晰边界：inventory / signing / coverage / executor / planner

7. **统一错误码**
   - 让 Codex 与 Claude Code 都能稳定消费脚本返回
   - 避免把错误处理逻辑塞回 prompt

8. **增强 submodule 支持**
   - `plan` 显式产生 `submodule_internal` 提交项，并将多个 pointer 更新并入一个根仓提交
   - 让 AI 与执行器都能识别父仓库 / 子模块仓库的边界

9. **固定单次快照边界**
   - `plan` 生成的 `coverage_baseline` 即本次 `$commit` 唯一合法输入集合
   - `coverage` 不仅检查“是否漏提”，还检查“是否夹带快照外路径”与“同路径内容是否漂移”
   - `apply-plan` 仅解析并提交快照内文件，不再重复扫描工作区以追赶后续新增改动

10. **默认禁用过程型 AI 编排**
   - 默认不再让 AI 编辑完整 plan JSON、讨论 split/merge、或启动子代理
   - AI 仅消费 `message-template`，返回最小 messages JSON
   - 其余步骤全部由脚本执行，减少 prompt 噪声与生成延迟

11. **plan 保留 sign_mode=auto**
   - `auto` 不在 plan 阶段固化为 `signed`，只写 `effective_sign_mode_hint`
   - apply 阶段再做完整 GPG 探测，auto 签名失败时允许单次 fallback

12. **渐进披露文档结构**
   - 高频触发的 `SKILL.md` 只保留主流程与引用导航
   - schema / signing / submodule / error codes / safety 细则拆入 `references/`，按需读取

13. **模板调试准备阶段**
   - `prepare` 在同一进程内完成 inventory、candidate 固化、plan 落盘与 message template 生成
   - `message-template` 与 `plan --summary-only` 仍保留作为调试与兼容入口

14. **默认 one-process session**
   - `commit-session` 先固化 snapshot，再通过首行 `phase=prepared` 输出 message template
   - AI 通过同一进程 stdin 回写最小 messages JSON；脚本随后完成 merge、coverage、snapshot drift、signing 与 `git commit`
   - session messages 文件由脚本放在 `/tmp/commit-messages-<random>.json`，随机后缀至少 6 位，成功后清理
   - `fast-commit` 保留为宿主无法保持 stdin 时的非交互兼容入口

15. **内建 transaction gates**
   - `phase=prepared` 内嵌有界 semantic diff，AI 不再另跑 `git diff`
   - preflight 用临时 Git index 执行 `git diff --check`，并在等待 AI message 时并行运行 `.commit-skill.json` 配置的 tests
   - explicit `signed` 直接尝试 `git commit -S`，成功后在 session 内执行 `git verify-commit`；`auto` 保留完整探测与 fallback
   - `phase=complete` 内嵌最终 inventory、clean-tree 与 fingerprint 复核；后写入路径以 `post_snapshot_changes` 返回
   - `$commit` 外层只消费 prepared/complete，不再读取 memory/doctrine/loop 或补跑 coverage/inventory/验签
   - clean tree 的 noop 路径不解析 GPG；只有存在 candidate commit 时才进入 signing context

16. **preflight trust boundary**
   - `.commit-skill.json` 的 `preflight.commands[].argv` 由目标仓库维护者提供，脚本以 `shell=False`、目标仓库为 cwd 启动；它不是 sandbox，能以当前用户权限执行测试程序
   - 配置损坏、命令无法启动、超时或非零退出均以 `PREFLIGHT_FAILED` 阻止提交；不把命令字符串拼入 shell，避免额外 shell injection 面
   - `semantic_diff` 只向 AI 提供当前 snapshot 的有界文本，不改变候选路径、repo boundary 或提交权限

17. **可选 custom model backend**
   - `commit_url` / `commit_key` / `commit_model`（及大写别名）全部存在时，`commit-session` 可调用 OpenAI-compatible `/chat/completions` 生成 message JSON；未配置时保持宿主 stdin 逻辑
   - 外部模型只返回 `type/title/bullets`，结果仍经既有 message schema、coverage、snapshot、signing 与 postflight；配置不完整 fail closed，请求/响应/schema 失败重试 2 次后默认回到宿主 stdin，`--require-custom-model` 才保持 fail closed
   - 普通 `doctor` 只输出 endpoint/model/source 与脱敏 key preview，不联网；显式 `doctor --probe` 才发送不含仓库数据的最小请求，并严格校验回复为小写 `ok`
   - 该 backend 是 commit skill 的可选数据外发路径，不修改已启动 Codex/Claude 外层模型选择，文档明确提醒 endpoint 数据边界

18. **`$commit` 入口分流**
   - 只将首个非空 token 严格为 `doctor` 的输入路由至只读诊断；其余 suffix 保持原有自然语言提交语义
   - `doctor` 后的自然语言只能选择已定义的静态诊断或 `--probe` 行为，不作为 commit scope 或任意脚本参数透传
   - 该机制属于 skill-level routing，不声称提供 zsh `compdef`/Tab completion；底层调试子命令继续使用绝对脚本路径

19. **custom model 的宿主边界**
   - custom backend 成功时，message 生成由配置 endpoint 完成；inventory、coverage、signing、commit 与 postflight 保持本地确定性，不引入额外模型调用；连续失败后通过显式 `phase=fallback` 回到宿主 stdin
   - `--require-custom-model` 将环境未继承从兼容性回退改为 `MODEL_CONFIG_INVALID`，并将模型连续失败后的宿主回退改为 `MODEL_REQUEST_FAILED`，保证不会等待 host-AI stdin
   - 环境变量属于进程级状态；修改 `zshrc` 不会更新已运行的 Codex/Claude，文档要求重启宿主或使用新的 login shell

### 2026-09-22 - custom model 全链路边界

**变更内容**: 明确 custom backend 覆盖唯一的 AI 任务 message generation；请求失败最多重试两次，仍失败时显式回退 host-AI stdin；`--require-custom-model` 在进程未继承配置或模型连续失败时 fail closed。

**变更理由**: 兼顾自定义模型的短暂网络/服务波动与原有 Codex 提交流程；同时保留强制 custom model 场景的确定性失败边界。

**边界**: `$commit` 本身仍由 Codex/Claude 负责 skill dispatch；要完全绕过宿主 AI，应在新的 login shell 直接运行 `commit-session --require-custom-model`。

### 2026-09-22 - `$commit` 子命令入口分流

**变更内容**: 将首 token 严格为 `doctor` 的 `$commit doctor` 请求分流到只读诊断，并保留其他 `$commit <自然语言>` 的原有提交语义；支持 `doctor` 后追加自然语言选择静态检查或 `--probe`。

**变更理由**: 避免 `doctor` 被默认 commit-session 当成提交范围，同时不牺牲 `$commit 只提交 ...` 等自然语言入口。

**边界**: 这是 skill-level 路由，不是 zsh shell completion；其他脚本调试子命令不提升为 `$commit` 一级入口。

### 2026-09-22 - 可选 custom model backend 与 doctor

**变更内容**: 新增 `commit_*` / `COMMIT_*` 环境变量解析、脱敏 `doctor` 子命令与 OpenAI-compatible message backend；`doctor --probe` 可用极短上下文实际验证 endpoint/auth/model；`commit-session` 在三项配置齐全时自动生成并校验 message JSON。

**变更理由**: 允许操作者通过 `zshrc` 为 commit message 选择独立模型，同时在未配置时保留原有宿主 stdin 流程，避免误改变现有行为。

**安全边界**: key 永不打印；URL userinfo/query/fragment 不进入诊断；普通 `doctor` 不联网，probe 不发送仓库内容；配置不完整直接阻断，模型请求失败按两次重试后回退宿主的策略处理，`--require-custom-model` 下仍直接阻断；正式生成 message 前由操作者确认自定义 endpoint 可接收仓库 diff 摘要。

**影响范围**: `skills/commit/scripts/lib/{cli,errors,model_config,model_backend}.py`、`skills/commit/tests/test_{cli_lib,apply_plan,model_config,model_backend}.py`、`skills/commit/{SKILL.md,agents/openai.yaml,references/error-codes.md}`、根 `README.md` 与 `DESIGN.md`。

### 2026-09-21 - 内建 preflight、验签与 postflight

**变更内容**: 将 semantic diff、临时 index `git diff --check`、可配置 tests、signed commit 验签、最终 inventory 与 post-snapshot fingerprint 检查纳入 `commit-session`；explicit signed 取消事前 GPG inventory。

**变更理由**: 把原先由 Agent 多次调用的只读分析与最终核验并回唯一脚本进程，同时让 tests 与 AI message 生成并行，缩短端到端提交用时并消除遗漏核验。

**影响范围**: `.commit-skill.json`、`skills/commit/{SKILL.md,agents/openai.yaml,references/signing.md}`、`skills/commit/scripts/lib/{cli,errors,executor,inventory,messages,postflight,preflight,process,signing}.py`、tests 与 golden snapshots、`README.md`、`DESIGN.md`。

### 2026-09-21 - 默认 one-process commit session

**变更内容**: 新增 `commit-session` 子命令，先输出固定 snapshot 与 message template，再从同一 stdin 接收 AI message，并在同一进程中完成 merge、coverage、签名与真正的 `git add/commit`；保留 `fast-commit` 作为非交互兼容路径。

**变更理由**: 消除 AI 生成 message 与 snapshot 固化之间的竞态，并减少进程启动与 plan/template 重复传递；随机临时文件名避免并发与残留文件冲突。

**影响范围**: `skills/commit/scripts/lib/cli.py`、`skills/commit/tests/test_cli_lib.py`、`skills/commit/tests/test_apply_plan.py`、`skills/commit/SKILL.md`、`skills/commit/agents/openai.yaml`、`README.md`、`DESIGN.md`。

## 已知限制

- 复杂跨模块语义拆分不再交给默认快路；若 planner 的固定候选不理想，只能显式切回手改 plan 的调试路径
- submodule merge 策略仍偏保守，默认先 internal 再 pointer
- `sign-mode=auto` 在无 TTY 沙箱下可能探测不到完整 GPG 灵脉，但结构已允许 fallback
- 若 `$commit` 执行过程中用户又修改了工作区，这些新路径将留待下一次 `$commit`；若同路径内容漂移，本轮会中止并要求重跑 plan
- 质量扫描仍报告既有 `coverage/inventory/executor/messages` 的复杂度与长函数 warning；这些模块承载 snapshot、submodule、coverage 与提交事务的顺序约束，本轮未做无收益拆分。新增 `preflight` 的分支用于配置校验、超时和子进程清理，保持显式错误边界优先于压缩行数。

### 2026-06-06 - 收紧为 message-only AI 快路

**变更内容**: 新增 `message-template` 子命令与 `messages-file` 校验/merge 流程；`apply-plan` 支持直接消费 AI 生成的最小 message JSON；skill prompt 改为默认禁止 AI 编辑完整 plan、禁止子代理、禁止过程长思考。

**变更理由**: 将 AI 参与面收敛到“仅生成 commit message”，把 plan 固化、coverage、签名、submodule 顺序与实际提交全部下沉到脚本，以降低 token 消耗和响应时延。

**影响范围**: `skills/commit/scripts/lib/{cli,messages,errors}.py`、`skills/commit/tests/`、`skills/commit/SKILL.md`、`skills/commit/agents/openai.yaml`、`README.md`、`DESIGN.md`。

**决策依据**: 目标是硬限制而非软提示；只有把 AI 的输入输出收敛为固定 JSON 契约，才能真正缩小推理空间与执行路径。

### 2026-06-06 - 固定为单项目 1 commit / 多子模块按模块拆分

**变更内容**: 调整 planner：根仓默认只生成 1 个 commit；若存在多个 dirty submodule，则每个子模块生成 1 个 internal commit，父仓所有 gitlink pointer 更新并入 1 个根仓 commit。

**变更理由**: 继续压缩 AI 决策面与 candidate 数量，让提交数量更可预测，同时保持父仓最终干净。

**影响范围**: `skills/commit/scripts/lib/planner.py`、`skills/commit/tests/test_{plan,submodule_plan}.py`、`skills/commit/SKILL.md`、`README.md`、`DESIGN.md`。

**决策依据**: Git 子模块的 gitlink 变更无法凭空消失；要么留父仓脏树，要么补 1 个 pointer commit。后者更稳。

### 2026-06-06 - 为 commit message 增加 must-cover 与自动补漏

**变更内容**: `message-template` 现在为每个 commit 生成 `must_cover`；`merge_message_file()` 在 apply 前执行 message coverage audit，若 title/bullets 未覆盖关键模块、影响面或 pointer 信息，则自动补齐缺失 bullets，并将结果写入 `message_coverage_audit`。

**变更理由**: 目标是让单个 commit 的消息完整覆盖关键变更面；单靠 AI 自由生成不稳定，需要脚本兜底。

**影响范围**: `skills/commit/scripts/lib/messages.py`、`skills/commit/tests/test_{messages,apply_plan}.py`、`skills/commit/SKILL.md`、`README.md`、`DESIGN.md`。

**决策依据**: 完整性应是结构化覆盖问题，而非字数问题；将关键信息约束成 `must_cover`，再由脚本补漏，方可硬保证。

## 变更历史

### 2026-05-04 - 拆分 references 降低 Skill 触发成本

**变更内容**: 将 plan schema、签名规则、submodule 规则、错误码与安全边界拆入 `skills/commit/references/`，`SKILL.md` 收敛为主流程与引用导航。

**变更理由**: `commit` 是高频技能，默认加载内容应尽量短；细则仅在修 plan、处理签名/submodule/错误时按需读取。

**影响范围**: `skills/commit/SKILL.md`、`skills/commit/references/*`、`README.md`、`DESIGN.md`。

**决策依据**: 遵循 progressive disclosure：核心流程常驻，低频细则外置，既保留可审计性，又降低 token 成本。

### 2026-05-04 - 修复提交快照与执行安全边界

**变更内容**: 修复 rename/copy porcelain-z 解析；coverage 增加 fingerprint drift、repo_path 白名单、重复路径与 submodule 顺序校验；plan 保留 `sign_mode=auto` 并增加 `effective_sign_mode_hint`；include/exclude 覆盖 submodule；commit 失败后清理本轮 staged 路径；默认 plan 文件改为 repo hash；文档改为默认自动子代理 facts 收集。

**变更理由**: 让“本轮快照提交”从路径级收紧到路径+内容级，并消除 GPG auto fallback、submodule 排除与 rename 提交失败等隐患。

**影响范围**: `skills/commit/scripts/lib/{inventory,planner,coverage,executor,cli}.py`、`skills/commit/tests/`、`skills/commit/SKILL.md`、`skills/commit/agents/openai.yaml`、`README.md`、`DESIGN.md`。

**决策依据**: 正确性优先于便利性；一旦执行期状态漂移，宁可中止重跑 plan，也不暗中提交未审内容。

### 2026-05-04 - 收紧为单次扫描快照提交

**变更内容**: 将 coverage/apply-plan 改为只接受 `$commit` 起手时 `plan` 记录的快照路径；若计划混入快照外新路径则直接报错，并同步更新 skill 文档与 agent prompt

**变更理由**: 目标是避免技能在执行期重复扫描并持续追赶新改动，改为仅提交本次调用时的快照变更

**影响范围**: `skills/commit/scripts/lib/coverage.py`、`skills/commit/scripts/lib/executor.py`、`skills/commit/SKILL.md`、`skills/commit/agents/openai.yaml`、`README.md`、`DESIGN.md`、相关 tests

**决策依据**: 以 `coverage_baseline` 作为不可漂移的事实快照，最能稳住提交边界，也最便于校验与解释

### 2026-04-22 - 子代理 facts 收集策略

**变更内容**: 为大型改动引入只读 explorer 子代理 facts 收集，并保留主线程串行 fallback。

**变更理由**: 多候选、多文件、多 submodule 场景下，先并行收集 facts 可减少主线程等待。

**影响范围**: `skills/commit/SKILL.md`、`skills/commit/agents/openai.yaml`、`README.md`、`DESIGN.md`

**决策依据**: 子代理只承担只读 facts 收集，最终 plan 编辑、coverage 与 apply 仍由主线程负责，避免提交边界漂移。

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
  - 多文件、多候选或 root + submodule 混合时，主线程默认 spawn explorer 子代理按 candidate/submodule 分头只读分析 facts
  - 子代理仅允许 `git status --porcelain -z` / `git diff --name-status` / `git log -1` / `git submodule status`
  - 子代理不可用时统一退化为主线程串行采集 facts
  - 主线程汇总后更新 plan JSON，确保 AI 与 coverage/apply-plan 使用真实信息
