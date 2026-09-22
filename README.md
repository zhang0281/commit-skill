# commit-skill

用于托管 `commit` 技能的独立 GitHub 仓库；现约束为**只提交执行 `$commit` 当下扫描到的路径与内容快照**。

## 目录结构

```text
commit-skill/
├── README.md
├── .commit-skill.json       # 可选：session 内并行运行的 preflight tests
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
        │       ├── preflight.py
        │       └── postflight.py
        └── tests/
```

## 架构

本仓库的 `commit` skill 采用 **AI 仅生成 commit message + 脚本执行** 的混合模式：

- **AI**：只填写固定 candidate commits 的 `type/title/bullets`
- **脚本**：负责 inventory、candidate 固化、semantic diff、message merge、preflight、coverage、submodule、签名、`git commit`、验签与最终 clean-tree/fingerprint 核验
- **提交责任边界**：外层 AI 启动一次 `commit-session` 后只回写 message JSON；真正的 `prepare`、coverage、`git add/commit` 均由同一脚本进程执行
- **默认 fast path**：`commit-session` 先固化 snapshot 并输出 template，AI 回写 messages JSON 后，同一进程完成 merge、coverage 与真实提交
- **固定 commit 数**：
  - 单项目根仓改动：1 个 commit
  - 多子模块改动：每个 dirty submodule 1 个 internal commit，另加 1 个根仓 pointer commit
- **message coverage audit**：`message-template` 会给出 `must_cover`，`apply-plan` 若发现 title/bullets 未覆盖关键变更面，会自动补齐必要 bullets
- **单次快照原则**：`coverage_baseline` 固定本轮 `$commit` 起手时的路径与 fingerprint；后续新路径或同路径内容漂移不会被顺带提交。
- **渐进披露**：`SKILL.md` 只保留主流程，schema / signing / submodule / error codes / safety 细则拆入 `skills/commit/references/`。

## `$commit` 入口分流

`$commit` 的一级子命令由首 token 区分，不会吞掉原有自然语言：

- `$commit doctor`：只读查看当前 custom model 配置，不启动提交流程。
- `$commit doctor --probe`：发送不含仓库内容的短请求，要求模型严格回复 `ok`。
- `$commit doctor 请实际验证模型`：自然语言仅用于选择 doctor 行为，等价于 `doctor --probe`。
- `$commit 只提交 src/api.py`：首 token 不是保留子命令，继续走原有自然语言提交路由。
- 要提交名为 `doctor` 的路径，请写 `$commit 提交 doctor`，避免与诊断子命令混淆。

这属于 skill-level 路由，并非 zsh shell 的 Tab completion；后者需要另行提供 shell completion 函数。当前只把 `doctor` 暴露为 `$commit` 一级子命令，其余脚本命令仍按“脚本子命令”章节直接调用。

## 可选模型配置

`commit-session` 默认沿用宿主 AI 的 stdin message 流程。需要让 skill 自行调用 OpenAI-compatible Chat Completions 时，在 `zshrc` 中导出：

```zsh
export commit_url='http://127.0.0.1:23000/v1'
export commit_key='your-api-key'
export commit_model='your-model'
```

可选 `commit_timeout`（默认 90 秒，最大 600 秒）；同时支持对应的大写 `COMMIT_*` 别名。三项 `url/key/model` 齐全才启用 custom backend；全部未设置则完全保持现有逻辑，部分设置或非法值会以 `MODEL_CONFIG_INVALID` fail closed。环境变量必须 `export`，否则 Python 子进程不可见。

诊断（API key 只显示脱敏 preview）：

```bash
python3 "$COMMIT_SKILL_SCRIPT" doctor --json
python3 "$COMMIT_SKILL_SCRIPT" doctor --probe --json
```

普通 `doctor` 只做本地配置检查，不发送网络请求。`mode=existing` 表示使用宿主 stdin；`mode=custom-api` 且 `active=true` 表示静态配置有效。显式 `doctor --probe` 会发送一个不含仓库内容的极短 Chat Completions 请求，并要求模型严格回复小写 `ok`；成功时返回 `probe.status=passed`，未配置 custom backend 时为 `skipped`，请求或响应不符则返回 `MODEL_REQUEST_FAILED`。

该配置不改变已启动的 Codex/Claude 外层模型；真正执行 `commit-session` 时会向自定义 endpoint 发送仓库 message template/diff 摘要，需由操作者确认数据边界。请求、响应或 message schema 失败会重试 2 次（共最多 3 次）；仍失败时输出 `phase=fallback` 并交回宿主 AI，未配置变量则直接交给宿主 AI。

`commit-session` 在 custom backend 成功时，message 生成由配置 endpoint 完成；inventory、coverage、signing、commit 与 postflight 均为本地确定性脚本，不再另调模型。若 custom model 三次失败，默认会通过 `phase=fallback` 回到宿主 AI；若要把环境变量未继承或模型失败也视为硬失败，可使用 `--require-custom-model`：

```bash
zsh -lic 'python3 "$HOME/.codex/skills/commit/scripts/commit_skill.py" commit-session --repo . --require-custom-model --json'
```

修改 `zshrc` 后，已启动的 Codex/Claude 进程不会刷新环境；请重启宿主，或在新的 login shell 中执行命令。未配置变量时 `commit-session` 会直接使用 `message_source=stdin`；配置模型连续失败时，脚本会先发出 `phase=fallback`，再由宿主 AI 回写 message。

## 兼容性

- **Codex**：通过 `skills/commit/agents/openai.yaml` 暴露 metadata
- **Claude Code**：通过仓库根 `.claude-plugin/marketplace.json` 暴露 marketplace 信息
- 两端共享同一份 `skills/commit/SKILL.md` 与 `skills/commit/scripts/` 逻辑

## 默认工作流

1. `commit-session --repo .`：在可保持 stdin 的持久交互进程中启动脚本并固化 snapshot，输出 `phase=prepared` 与 message template；一次性 exec 若关闭 stdin，不适用于此步骤
2. AI 通过同一进程 stdin 回写允许填写的 `id/type/title/bullets`；messages 文件由脚本放入 `/tmp/commit-messages-<random>.json`
3. 同一进程输出 `phase=complete`，完成 merge、preflight、coverage、签名、实际提交、验签和最终 inventory
4. 宿主不支持保持 stdin，或首轮返回 `commit-session 未收到 messages JSON` 时，依据 template 写入新的 `/tmp/commit-messages-<random>.json`，退回 `fast-commit --messages-file ...`；等待其 `phase=complete`

无改动时，`commit-session` 直接输出 `phase=complete` + `noop`，不等待 stdin，也不做无意义的 GPG signing probe。

默认不需要外围 `git diff`、tests、coverage、inventory 或验签调用：`phase=prepared` 已携带有界 semantic diff，`phase=complete` 已携带 `preflight` 与 `postflight`。仓库可用 `.commit-skill.json` 的 `preflight.commands[].argv` 配置 tests；这些命令在等待 AI message 时并行执行。`git diff --check` 始终使用临时 index 自动执行，不改变真实 staging。

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
- `prepare`：一次生成固定计划与 AI message template（模板调试路径）
- `fast-commit`：消费 AI messages JSON，一次完成 prepare 与最终提交
- `commit-session`：单进程输出 template、接收 AI message 并完成最终提交（默认 fast path）
- `doctor`：查看 custom model 环境变量的生效状态（脱敏）；`--probe` 做严格 `ok` 实际探测
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

- `commit-session` 子命令是 `$commit` 默认流程；`fast-commit`、`plan` 与 `prepare` 仍可单独用于调试
- include/exclude 同时作用于 root 与 submodule path
- 统一错误码便于 Codex 与 Claude Code 都稳定消费脚本结果
- `sign-mode=unsigned` 会以 `git -c commit.gpgsign=false commit` 强制覆盖仓库/全局签名配置；`sign-mode=signed` 直接尝试并验签；`auto` 仍保留探测与 fallback
