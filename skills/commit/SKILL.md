---
name: commit
description: 拆分并创建规范 Git 提交。Use when Codex needs to inspect working tree changes, decide commit boundaries, handle git submodule updates, generate Chinese Conventional Commits style messages, or execute a safe commit workflow from the current repository. Invoke explicitly with $commit when the user wants “提交当前改动”“帮我 commit”“分开提交”“只提交某些文件”“排除某些文件”。
---

# Commit

## Overview

将当前仓库改动整理成一个或多个“每次只做一件事”的 Git 提交。优先处理 submodule，再处理主仓库改动。提交信息使用中文，并遵循 Conventional Commits 风格标题 + 正文。

核心执行原则：

- 主线程负责：收集轻量 inventory、裁决提交边界、生成最终提交计划、执行全部 `git add` / `git commit`
- 子代理负责：只读侦察与分组分析，禁止修改 Git 状态与任何文件内容
- 优先轻量命令 + path-scoped diff，避免一开始就对整仓库执行全量 `git diff HEAD`
- 需要并行时，自动使用 `explorer` 子代理；最终分析、暂存与提交必须回到主线程串行完成
- 默认目标是：一次 `$commit` 调用覆盖全部修改。除非用户显式排除某些文件，否则不允许留下未提交文件
- 本 skill 永不修改工作区文件内容，不做 partial staging；若无法纯语义拆分，则降级为模块级 / 文件级综合提交，而不是笼统快照
- 主线程必须执行 coverage audit：确认全部变更文件都已被提交计划覆盖，或被用户显式排除
- 多行提交信息必须使用多个 `-m` 传入：标题一个 `-m`，每条正文 bullet 一个 `-m`；禁止在 message 参数中使用字面 `\n`

## Invocation

- 在 Codex 中显式使用 `$commit`，而不是 `/commit`
- 示例：
  - `$commit`
  - `$commit 只提交 src/api.py 和 src/utils.py`
  - `$commit 不提交 docs`
  - `$commit 单次提交`
  - `$commit 分开提交`

## Boundary normalization

如果用户提供了额外限制，先把限制转成操作边界：

- “只提交 xxx” → 仅处理指定文件或模块
- “不提交 xxx” → 排除指定文件或模块
- “单次提交” / “合并提交” → 不拆分
- “分开提交” → 强制按逻辑单元拆分
- “并行分析” / “加速” → 提高并行侦察优先级

若 include / exclude 规则冲突，以更窄的边界优先。

默认情况下，`$commit` 应覆盖当前工作区全部修改；只有用户显式 exclude 的文件或模块才允许不提交。

## Execution mode selection

满足任意一项时，自动启用**只读并行侦察**：

- 用户明确要求并行、加速、委派、子代理分析之一
- 变更文件数 `> 5`
- 顶层模块 / 服务 / 包 `>= 2`
- 存在 dirty submodule 或 submodule pointer 变更
- 预估需要 `>= 2` 个独立分析工作流

满足以下全部条件时可直接串行：

- 变更文件数 `<= 5`
- 无 submodule 改动
- 文件集中在单一模块
- 预估仅需 `1` 个分析工作流

并行模式只用于**读取与归类**。所有真正改变 Git 状态的动作仍由主线程串行执行。

## Required context collection

开始前，主线程先执行轻量 inventory：

```bash
git status --short
git diff --name-status HEAD
git diff --stat HEAD
git branch --show-current
git log --oneline -10
git submodule status 2>/dev/null || echo "无子模块"
git submodule foreach --quiet 'DIRTY=$(git status --short 2>/dev/null); if [ -n "$DIRTY" ]; then echo "=== $displaypath ==="; echo "$DIRTY"; fi' 2>/dev/null || echo "无子模块"
git submodule foreach --quiet 'AHEAD=$(git log --oneline @{u}..HEAD 2>/dev/null | head -5); if [ -n "$AHEAD" ]; then echo "=== $displaypath (unpushed) ==="; echo "$AHEAD"; fi' 2>/dev/null || true
```

读取 inventory 后，再构造分析分组：

- 每个 dirty / ahead submodule 单独成组
- 主仓库按顶层模块、服务、package、feature 目录分组
- `docs/`、`tests/`、配置文件、构建文件单独分组
- 若多个小文件明显服务于同一件事，可合并为一个分析组
- 若某组跨越多个目的，继续细分

只有在主线程准备确认某个提交候选时，才对该候选执行定向 diff：

```bash
git diff --name-status HEAD -- <paths...>
git diff HEAD -- <paths...>
```

## Workflow

### 1. 主线程建立 inventory 与分组

1. 执行轻量 inventory
2. 应用 include / exclude / 单次提交 / 分开提交 等用户边界
3. 识别：
   - 是否有 submodule 提交流程
   - 是否值得启用并行侦察
   - 初步分组清单

### 2. 并行侦察（仅在需要时启用）

若进入并行模式，为每个分析组派发 `explorer` 子代理。子代理必须遵循以下硬约束：

- 只读分析，禁止执行 `git add` / `git commit` / `git reset`
- 只分析分配到的路径或 submodule，禁止扩域
- 优先使用 path-scoped diff，避免读取无关改动
- 禁止任何文件内容写入、格式化、补丁生成、自动修复
- 若发现单文件内混有多件事且无法纯语义拆分，必须标记为 `residual_group`
- 回报分析结论与验证命令，不得直接提交

推荐给子代理的任务模板：

```text
只读分析分配给你的 Git 改动组。

硬约束：
- 只分析以下路径：<paths...>
- 禁止扩域
- 禁止执行 git add / git commit / git reset / 任何写操作
- 禁止修改任何工作区文件内容
- 只使用 git status / git diff / git log / git submodule status / git -C <abs-path> status|diff|log
- 必须回报你实际使用的验证命令

输出：
1. 该组改动的单一句子目的
2. 涉及文件清单
3. 建议 commit type
4. 建议 commit title
5. 建议正文 bullets
6. 与其他组是否存在强耦合
7. 是否应独立提交
8. 哪些文件或分组需要降级为 residual commit，以及原因
```

主线程负责：

- `spawn_agent` 创建只读分析子代理
- `wait_agent` 长等待收敛结果，避免忙轮询
- 汇总所有分析结论
- `close_agent` 回收全部子代理

### 3. Submodule 流程

读取 “Submodule dirty files” 与 “Submodule unpushed commits”，按下列规则执行：

#### 情形 A：子模块内有未提交修改

1. 获取子模块相对路径：

   ```bash
   git submodule foreach --quiet 'echo "$displaypath"'
   ```

2. 为每个目标子模块构造绝对路径，并在**主线程**内检查：

   ```bash
   git -C /absolute/path/to/submodule status
   git -C /absolute/path/to/submodule diff
   ```

3. 仅在**主线程**内提交与同一件事相关的文件。若单文件内混有多件事且不能纯语义拆分，则降级为子模块级 / 文件级综合提交；除非用户显式排除，否则不得遗漏该子模块内改动：

   ```bash
   git -C /absolute/path/to/submodule add <files...>
   git -C /absolute/path/to/submodule commit -m '<类型>: <描述>' -m '- <变更点1>' -m '- <变更点2>'
   ```

4. 子模块内部提交完成后，把需要更新引用的子模块路径记入 `updated_submodules`，暂不立即提交父仓库 pointer。

#### 情形 B：子模块内没有脏文件，但主仓库出现 `new commits`

把该子模块路径记入 `updated_submodules`，与其他子模块引用更新一起在父仓库聚合提交。

#### 情形 C：没有子模块改动

跳过 submodule 流程，进入主仓库提交分析。

#### 情形 D：父仓库聚合提交 submodule 引用

若 `updated_submodules` 非空，在**主线程**内一次性暂存全部相关 submodule path，并聚合提交：

- 只有 1 个子模块时：

  ```bash
  git add <submodule-path>
  git commit -m 'chore: 更新子模块 <子模块名> 引用' -m '- 更新 <子模块名>'
  ```

- 有多个子模块时：

  ```bash
  git add <submodule-path-1> <submodule-path-2> <submodule-path-N>
  git commit -m 'chore: 更新子模块' -m '- 更新 <子模块名1>' -m '- 更新 <子模块名2>' -m '- 更新 <子模块名N>'
  ```

### 4. 主线程裁决提交边界

主线程必须遵循 **Coverage-first Planner**：

1. 优先生成纯语义 commit
2. 若纯语义拆分会导致文件遗漏，则降级为模块级综合 commit
3. 若模块级仍无法完整覆盖，则降级为文件级综合 commit
4. 除用户显式 exclude 外，不允许以 `skip` 结束

推荐的降级命名方式：

- 模块级：`refactor: 整理 auth 模块改动`
- 文件级：`refactor: 整理 user_service.py 改动`
- 配置级：`chore: 整理构建配置改动`

正文 bullets 必须具体枚举真实变化，不能写成“提交待整理改动快照”之类空泛描述。

按“每个提交只做一件事”切分：

- 一个新功能 = 一个提交
- 一个 bug 修复 = 一个提交
- 文档更新 = 单独提交
- 重构 = 单独提交
- 测试 = 单独提交，除非与对应功能强耦合
- 配置 / 依赖 / 构建变更 = 单独提交

用以下问题判断是否应该拆分：

- 这些文件是否服务于同一个目的？
- 移除其中一部分后，其余修改是否仍完整且有意义？
- 是否存在强耦合，必须在同一个提交中才能保持语义完整？
- 是否存在单文件混杂改动，导致无法在 file-level 安全提交？
- 若无法纯语义拆分，这批改动是否能诚实地归纳为模块级主题？
- 若模块级仍不清晰，是否能至少诚实地归纳为文件级主题？

如果答案表明“不是同一件事”，则拆分提交。
如果答案表明“该文件无法纯语义拆分”，则把它整体纳入最小可接受的 residual commit，而不是跳过。

主线程合并子代理结论时，以以下顺序裁决：

1. 用户边界
2. submodule 先于主仓库
3. 语义完整性
4. 风险隔离（docs/test/config 尽量独立）
5. 最小可回滚单元

在执行前，主线程必须完成 coverage audit：

```text
all_changed_files
= planned_commit_files
+ explicit_excluded_files
+ submodule_internal_commits 对应的 pointer 更新
```

若 coverage audit 不成立，必须继续补充 residual commit，直到全覆盖。

如果需要多个提交，先给出提交计划，再逐个执行。

### 5. 执行提交（仅主线程）

执行每个提交前，主线程必须再次验证该提交候选：

```bash
git diff --name-status HEAD -- <paths...>
git diff HEAD -- <paths...>
```

优先精确暂存具体文件，不要无差别全量暂存。
只允许 **file-level staging**。若一个文件同时包含多件事，不允许部分暂存，不允许修改文件内容整理后再提；必须把该文件整体放入最合适的纯语义 / 模块级 / 文件级 commit。

单个提交示例：

```bash
git add <files...>
git commit -m 'feat: 简短描述' -m '- 变更点1' -m '- 变更点2' -m '- 变更点3'
```

多个提交时：

1. 输出计划：每个提交的范围、文件、类型、理由
2. 主线程逐个 `git add <files...>` + `git commit`
3. 若误暂存文件，仅允许使用 `git reset HEAD <file>`
4. 若发现计划未覆盖的文件，必须补充 residual commit，直到全覆盖
5. 完成后运行 coverage audit 与 `git status --short`
6. 汇总 commit SHA、标题、涉及文件

## Recommended subagent report format

子代理回报时，尽量使用以下结构，便于主线程合并：

```text
### Group: <name>
- scope: <paths or submodule>
- purpose: <一句话>
- files:
  - file1
  - file2
- suggested_type: <feat|fix|docs|refactor|test|chore|style|perf>
- suggested_title: <中文标题>
- body_bullets:
  - ...
  - ...
- coupling:
  - none | 与 <group> 强耦合
- should_split: yes|no
- residual_groups:
  - <scope>: <为什么不能纯语义拆分，建议降级成什么 commit>
- verification_commands:
  - git diff HEAD -- <paths...>
  - ...
```

## Commit message format

必须使用中文，且包含标题与正文两部分：

```text
<类型>: <简短描述>
- <具体变更点1>
- <具体变更点2>
- <具体变更点3>
```

约束：

- 标题不超过 50 字符
- 使用多个 `-m` 时，Git 自动插入段落空行，视为预期格式
- 正文每一条都说明“做了什么”
- 禁止在 message 参数中使用字面 `\n`
- 单行提交可使用 `git commit -m "<标题>"`
- 含正文 bullets 的多行提交必须使用多个 `-m`：标题一个 `-m`，每条 bullet 一个 `-m`

允许的类型：

- `feat`
- `fix`
- `docs`
- `refactor`
- `test`
- `chore`
- `style`
- `perf`

## Safety rules

仅使用以下安全 Git 操作：

- `git status`
- `git diff`
- `git diff --stat`
- `git diff --name-status`
- `git log`
- `git add <file>`
- `git commit -m`（可用于单行标题，或多个 `-m` 组成多行提交信息）
- `git reset HEAD <file>`（仅用于取消暂存单个文件）
- `git submodule status`
- `git submodule foreach`
- `git -C /absolute/path ...`（仅限子模块内的 `status` / `diff` / `log` / `add` / `commit`）

文件内容安全铁律：

- 本 skill 在主仓库与所有子模块内**永不修改任何工作区文件内容**
- 禁止使用 `Edit` / `Write` / `apply_patch`
- 禁止使用 `sed -i`、`perl -pi`、`python ... > file`、`node ... > file` 等任何文件改写手段
- 禁止部分暂存（partial staging / patch staging）
- 若文件边界不清、单文件混有多件事、疑似会造成代码丢失风险，必须降级为模块级 / 文件级综合提交；仅用户显式 exclude 的文件允许不提交
- 禁止因为“懒得归类”而使用空泛 snapshot 提交标题；综合提交也必须写明模块 / 文件与具体变化
- 若 coverage audit 未通过，禁止结束本次 `$commit`
- 唯一允许的“写”是 Git index 与 commit object 的变化，不得写回源码、文档、配置内容

子代理额外限制：

- 子代理只允许执行只读 Git 命令
- 子代理禁止执行任何会改变 index / working tree / commit history 的命令
- 子代理禁止调用任何会写文件的工具或命令
- 子代理不得决定最终提交边界，最终裁决权在主线程

绝不执行以下破坏性操作：

- `git restore`
- `git checkout -- <file>`
- `git reset --hard`
- `git reset --mixed`
- `git reset --soft`
- `git clean`
- `git rm`
- 任何带 `--force` 或 `-f` 的 Git 命令
- `git stash drop`
- `git stash clear`
- `git submodule update --init`
- `git submodule deinit`

所有 `git -C` 必须使用绝对路径，禁止相对路径。

## Output requirements

执行时遵循以下输出顺序：

1. 概述当前改动
2. 判断是否存在 submodule 提交流程
3. 判断是否启用并行侦察，以及分组依据
4. 给出提交计划（若只有一个提交，也简要说明理由；若有 residual commit，说明其模块 / 文件级归因）
5. 给出 coverage audit（全部变更 / 显式排除 / 待覆盖补充）
6. 执行提交
7. 汇总结果：
   - commit SHA
   - commit 标题
   - 涉及文件
   - 是否还有未提交改动（仅允许为用户显式排除项）
