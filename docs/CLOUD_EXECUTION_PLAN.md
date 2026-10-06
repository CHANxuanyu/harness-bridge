# Harness Bridge — Claude Code Cloud 项目执行书

> **历史文档：** 本文记录最初 V0.1 云端任务，不是当前执行指令或新的调用/推送授权。
> 当前统一计划见 [PROJECT_PLAN.md](PROJECT_PLAN.md)，实际状态见 `STATUS.md` / `HANDOFF.md`。
> 用户后续决定仓库保持 public，并明确 Advisor 会话 + 一个或多个跨 harness Executor 会话的产品模型。

**版本：1.0 · 日期：2026-10-06 · 负责人：Xuanyu CHAN**  
**目标仓库：`CHANxuanyu/harness-bridge`，新建独立仓库，默认 private**  
**开发模型：Claude Opus 5.5；云端开发额度：用户提供的约 100 USD bonus**

> 这是给 Claude Code Cloud 的实施任务，不是让你再写一份规划。阅读后立即从 M0 开始实现。按里程碑交付可运行代码、实际测试证据和 Git 提交，不要一次铺开整个平台。
>
> 本文中的 `hbridge` 命令、配置、状态和文件结构是待实现的产品契约，不表示这些功能现在已经存在。本文没有声称已创建远程仓库、已运行真实 harness 或已完成任何测试。

---

## 0. 任务授权与不可改变的约束

你要开发一个 **local-first、CLI-first、跨 agent harness 的任务交接与验收工具**。第一种真实用法是：用户在 Codex 中使用 Astra 做 supervisor，向本机 Claude Code / Opus 5.5 下发较完整的开发任务；executor 自主执行，supervisor 根据仓库变更和独立验证证据验收，必要时发起有限次数的修复。

用户已经决定：这是独立项目，不写进 Secretary 或其他现有项目；先在 Claude Code Cloud 开发，上传新的 GitHub 仓库，之后在本地继续。不要反复询问是否开始、是否需要新仓库、是否可以改用别的模型。

### 0.1 必须遵守

1. **开发模型保持 Opus 5.5。** 能设置精确模型名时使用 `claude-opus-5-5`，不要主动切换 Sonnet、Haiku、其他 Opus 版本或 `opusplan`。不要把模型自报身份当成运行证据。由 UI、受支持的会话配置或平台元数据确认；无法确认就记录 unknown，不伪造。平台强制回退不能绕过，应如实记录。
2. **没有额外模型 API 预算。** 不申请 API key，不调用 OpenAI/Anthropic/第三方模型 API，不启用额外付费、不充值、不绑定新账单，不注册替代服务，不下载本地大模型来充当“免费测试”。
3. **云端开发期间不启动真实嵌套 harness 推理。** 不从当前 Claude Code Cloud 再启动真实 Claude/Codex agent；不移除嵌套执行保护，不提取会话令牌，不复制浏览器登录状态，不逆向私有服务。云端 fixture/subprocess 仿真不受此限制。
4. **新建独立 GitHub 仓库。** 默认 private；未经用户另行决定，不改成 public、不发布包、不选择不可逆的开源许可、不触发部署。用户授权本项目正常 commit/push，不授权改写其他仓库。
5. **测试不得冒充真实验证。** synthetic fixture、mock integration、真实 Claude CLI、真实 Astra→Claude 闭环必须分别标注。
6. **不保证花完 100 USD，更不保证 100 USD 完成所有阶段。** 优先完成可运行的纵向切片。额度不明时不能虚构余额或美元消耗。
7. **每个里程碑可停、可接续。** 完成后提交、在权限允许时 push、更新 STATUS/HANDOFF。不得把唯一成果留在易失 VM 或对话中。
8. **不得靠放宽验收来制造完成。** 不能删失败测试、把关键测试改成 skip、放宽路径限制、把 unknown 改为 passed，或把未实现项藏在成功返回值后面。

### 0.2 允许自主决定的事项

普通函数命名、内部模块拆分、测试组织、受约束的依赖选择、可逆的小型实现取舍，由你自主决定。遇到不影响核心目标的歧义，采用最小可行默认值，并在 `docs/DECISIONS.md` 记一句理由即可，不要停下来等用户选择。

真正缺失的 GitHub 权限、模型权限、账单授权不能靠代码补齐。记录阻塞点并完成仍然可做的离线工作；不要花大量推理反复尝试同一个受限接口。

---

## 1. 项目定位与第一版边界

### 1.1 一句话定义

**Harness Bridge 把“向另一个 coding harness 委派任务、收集证据、提出修复、恢复中断”变成可记录、可测试的本地协议。**

它不是新的 LLM 客户端，不是模型聊天中转，不是 SaaS，不是通用分布式调度平台。第一版 bridge 自身不调用任何模型 API。

### 1.2 第一版的真实架构

```text
用户已登录的 Codex 会话 / Astra
  │  自己承担 planning、任务拆分和 review
  │  通过 shell 调用 hbridge；读取结构化摘要与需要的代码
  ▼
Harness Bridge：确定性本地程序
  ├─ TaskSpec / ReviewDecision
  ├─ SQLite 状态、事件、幂等检查
  ├─ 子进程生命周期与执行限额
  ├─ 独立 Git worktree、变更证据、验证命令
  └─ ClaudeCodeExecutor adapter
       │  仅本地、显式启用真实模式后
       ▼
用户已登录的 Claude Code / Opus 5.5
  └─ 在指定 worktree 自主实现、测试、修复
```

**不要在 V0.1 再造一个主动调用 Codex 的 SupervisorAdapter。** Supervisor 就是用户当前正在使用的 Codex 会话。它调用 CLI 并提交 review 文件即可。当前会话关闭后，任务应停留在明确状态，由之后的会话接手；不要假装 bridge 能自动唤醒或重新连接某个 Astra 对话。

云端对应结构：

```text
确定性的测试驱动 / 脚本化 review
  → 真实 hbridge core
  → 真实 OS subprocess 中的 fake executor
  → 真实临时 Git 仓库与文件修改
  → 真实 verifier 命令
  → 持久化状态、审查与有限修复
```

这验证的是基础设施和协议，不是模型智力或真实双 harness 兼容性。

### 1.3 第一版支持矩阵

| 项目 | V0.1 要求 |
|---|---|
| 用户/主机 | 单用户、单机 |
| 并发 | 同一任务最多一个执行 attempt；不做并行 executor 调度 |
| 平台 | 云端 Linux 实测；本地 macOS 作为目标，未实测前明确标注 |
| supervisor | 外部现有 Codex 会话或人，经 CLI/文件下发决定 |
| executor | fake subprocess 必须可运行；Claude CLI adapter 尽量实现并离线测试 |
| 持久化 | SQLite + 不进入 Git 的本地产物目录 |
| UI | CLI，结构化 JSON 输出；没有 Web dashboard |
| 通信 | 显式 task packet / artifact manifest / review decision |
| 用量 | 记录能观察到的量；缺失记 null，不能假装实时读取套餐余额 |
| 网络 | 离线测试不需要网络；安装依赖和正常 GitHub 上传是独立操作 |
| 付费 | bridge 无付费依赖；真实模型操作由用户后续本地显式授权 |

### 1.4 明确不做

本轮不做 computer use、截图轮询、MCP server、A2A 服务、模型路由 marketplace、跨机器 RPC、数据库服务、Redis、容器编排、复杂插件系统、自动账户切换、实时套餐抓取、自动等待配额重置后续跑、自动合并 PR、生产部署、完整 Secretary 集成。

允许在 `docs/BACKLOG.md` 留简短条目；不得先实现占位架构再把核心流程留空。

---

## 2. M0：仓库、权限和环境预检

### 2.1 仓库规则

目标名为 `CHANxuanyu/harness-bridge`。当前 GitHub 连接已确认用户账号为 `CHANxuanyu`，但 Cloud 内部仍须确认自己实际操作的 remote；账号可读不代表有创建仓库权限。

先检查当前 `pwd`、Git 根目录、当前 branch、经过脱敏的 remote 和工作区状态。**不得为了建新项目而删除当前仓库的 `.git`、重写 origin、清空目录、复制其他私有项目源码或 force push。**

按下列顺序处理：

- 如果已经位于用户刚创建、明确属于本任务的新仓库，直接使用。若已有本项目提交，按 STATUS 续做，不重建。
- 如果可以通过正式 GitHub 工具创建仓库，在独立路径创建 private `harness-bridge`。创建返回后验证 owner、visibility、remote，再初始化/推送。
- 如果同名仓库确实属于其他项目，不复用或覆盖。只有在能安全确认这一点时才选择 `harness-bridge-lab` 等新名称，并在交付中明确说明。
- 如果 cloud proxy 无创建权限，不换令牌、不绕过仓库 scope。将 `REMOTE_CREATE_BLOCKED` 写入交接。能在独立目录开发并交付导出文件时继续离线实施；不能保证该目录持久化时，不谎称代码已保存到 GitHub。

最可靠的启动方式是用户在开启 Cloud 会话前创建并授权新仓库。下面是**本地 GitHub CLI 命令**，只在已登录、有创建权限的用户终端执行，不能假设 Cloud 一定支持：

```bash
gh repo create CHANxuanyu/harness-bridge \
  --private \
  --add-readme \
  --description "Local-first bridge for supervised coding across agent harnesses"
```

创建后，让 Claude GitHub App 能访问这个新仓库，再在 Cloud 中选择它。该方式依据 GitHub CLI 官方 `gh repo create` 契约；Cloud 的 GitHub proxy 有仓库访问范围限制。[S1][S2][S7]

### 2.2 初始分支与保存

在新仓库创建平台允许的开发分支，如 `claude/harness-bridge-mvp`；若平台指定分支，遵守指定名称。正常 commit/push，无 force push，不删除 remote branches，不依赖 tags 或 releases 存档。

每个里程碑一个逻辑提交即可，避免为了提交数拆成几十份。推送失败时保留本地提交，写明错误类别。可以制作**仅本项目新建仓库**的 `git bundle` 作为兜底，但必须验证包含的 refs、无秘密和无其他项目历史；只有通过当前环境真正可下载的渠道导出，才能声称已交付。

### 2.3 环境记录

创建 `docs/ENVIRONMENT.md`，记录：OS、Python、Git、uv/pip、测试工具版本、工作分支、网络限制、是否能 push、新仓库身份确认方式、当前开发模型确认状态。

安装依赖采用平台允许的包源；不购买服务。只检查所需工具，不安装整套 Codex/Claude 来做云端真实推理。Claude CLI 的帮助文本/公开文档足以指导 adapter 初稿，实装版本没有就记 absent。

**禁止把完整环境变量、认证文件、GitHub token、API key、账户 cookie 写进日志。** 诊断只报告“变量存在/不存在”，不输出变量值。脱敏 origin URL 中可能含的凭据。

### 2.4 模型与预算设置

用户在 Cloud 选择 Opus 5.5。能固定精确名称时使用 `claude-opus-5-5`，记录配置来源；`opus` 是随平台/版本变化的别名，不当作精确 pin。[S5]

默认单主会话顺序实现。不主动打开 agent teams 或一批并行 Cloud tasks。需要独立检查时，最多用一个范围明确、同为 Opus 5.5 的审查 subagent；它不是另一个 harness，也不产生真实互操作证据。

默认不用 fast mode，不机械使用最高 effort；普通实现使用模型默认 effort，只有恢复一致性等难点再提高。不得为了省钱自行更换模型。

---

## 3. 技术栈与目录结构

### 3.1 默认技术选择

采用 **Python 3.11+，单包 `src` 布局**。以 Cloud 实际可用的 3.11 或更高版本锁定开发环境，并在 README 写准确版本。SQLite、subprocess、pathlib、hashlib、json、argparse 优先用标准库；schema 校验可使用一个轻量依赖（建议 Pydantic 2），不用为了零依赖自行写脆弱校验器。

开发依赖：pytest、ruff、mypy；可选 Hypothesis，只在关键状态不变量已有明确价值时引入。采用 uv 和锁文件；uv 不可用时用可复现的 pip 方案，不为换工具浪费大量额度。不得引入模型 SDK、向量库、多 agent framework 或 Web 前后端依赖。

这是实施默认选择，不需要重新对比 Python/TypeScript/Rust。只有遇到真实不可解决的环境阻塞才偏离，并留下简短 ADR。

### 3.2 建议布局

```text
harness-bridge/
├── README.md
├── pyproject.toml
├── uv.lock
├── .gitignore
├── AGENTS.md                      # 本项目开发规则，不是运行时 supervisor 身份
├── CLAUDE.md                      # 短入口，引用开发规则与计划
├── STATUS.md
├── HANDOFF.md
├── src/harness_bridge/
│   ├── cli.py
│   ├── models.py
│   ├── state.py
│   ├── store.py
│   ├── runner.py
│   ├── workspace.py
│   ├── verification.py
│   ├── artifacts.py
│   ├── policy.py
│   ├── errors.py
│   └── adapters/
│       ├── base.py
│       ├── fake.py
│       └── claude_code.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contracts/
│   ├── fixtures/                  # synthetic / docs-derived 的 provenance
│   ├── helpers/fake_executor.py
│   └── live/                      # 默认不运行；不得自动消费模型额度
├── examples/
│   ├── task.example.json
│   ├── review.example.json
│   └── supervisor-instructions.md
├── scripts/
│   ├── check.sh
│   └── demo_offline.py
├── docs/
│   ├── CLOUD_EXECUTION_PLAN.md
│   ├── ARCHITECTURE.md
│   ├── DECISIONS.md
│   ├── PROTOCOL.md
│   ├── ENVIRONMENT.md
│   ├── SECURITY.md
│   ├── TESTING.md
│   ├── VALIDATION_MATRIX.md
│   ├── LOCAL_HANDOFF.md
│   ├── EVALUATION_PLAN.md
│   └── BACKLOG.md
└── .github/workflows/ci.yml        # 默认手动触发，不擅自启用付费 CI
```

这不是要求逐一创建空文件。按纵向切片逐步生成；允许合并短模块。根目录 `AGENTS.md` 应指导开发者改本项目，不能错误地禁止 Codex 后续直接修本项目代码。

运行状态放在配置指定的 state root，默认 `~/.local/state/harness-bridge/`，不放进 executor worktree。测试总用临时 state root。文件位于 worktree 外只是减少误改，不是对同 UID 恶意进程的安全隔离。

---

## 4. 核心数据契约

所有外部输入必须经 schema 校验；拒绝未知的核心控制字段、非法状态、负数限额、越界路径和缺失必要字段。schema 带版本，不能静默解释不兼容版本。

### 4.1 TaskSpec

至少包含下列语义，不必照搬每个内部类名：

```json
{
  "schema_version": "1.0",
  "goal": "Implement the requested change and satisfy the acceptance criteria",
  "repo": {
    "path": "/absolute/local/path/to/target",
    "base_ref": "HEAD"
  },
  "requirements": ["Stable behavior on the specified edge cases"],
  "allowed_paths": ["src/**", "tests/**"],
  "forbidden_paths": [".github/**", ".env", ".env.*"],
  "verification": [
    {
      "id": "unit-tests",
      "argv": ["python", "-m", "pytest", "-q"],
      "cwd": ".",
      "timeout_seconds": 120,
      "required": true,
      "trust": "repository-tests"
    }
  ],
  "limits": {
    "max_attempts": 3,
    "max_repair_cycles": 2,
    "wall_timeout_seconds": 900,
    "max_turns_per_attempt": 20,
    "max_artifact_bytes": 10485760
  },
  "executor": {
    "kind": "fake",
    "requested_model": "claude-opus-5-5"
  }
}
```

这些限额是项目拟定的保守默认值，不是供应商保证或完成时间估计。允许用户显式更改。`base_ref` 创建时解析成具体 commit SHA，后续不能悄悄跟随移动的 HEAD/main。

`task_id`、`task_version`、`created_at`、规范化配置摘要、repo identity、resolved base SHA 由 core 生成并持久化。`create` 接受调用方的 idempotency key；相同 key + 相同规范化请求返回同一个 task；相同 key + 不同请求必须冲突。

`allowed_paths` 默认收窄，`forbidden_paths` 优先于允许规则。大小写、路径分隔符和 glob 语义须文档化。禁止隐式展开用户提供的 shell 字符串。

### 4.2 Attempt 与外部 session

每次执行有独立 `attempt_id`、序号、executor kind、requested/observed model、启动配置摘要、runner identity、开始/结束时间、exit code、结束原因和证据等级。

Vendor `session_id` 是不透明字符串，只从 adapter 可验证的响应中获得。必须绑定 executor 类型、repo、工作目录/工作区身份和已知配置；不能随机构造，也不能用别的 task 的最近会话。

**Task ID 不等于 Claude session ID。恢复 task state 不等于恢复模型会话。** 没有可用 session 时，报告“需要新 session 或本地人工处理”，不能声称 resume 成功。

### 4.3 ReviewDecision

```json
{
  "schema_version": "1.0",
  "task_id": "TASK_ID",
  "attempt_id": "ATTEMPT_ID",
  "task_version": 1,
  "snapshot_digest": "DIGEST_FROM_ARTIFACT_MANIFEST",
  "verdict": "changes_requested",
  "findings": [
    {
      "severity": "blocking",
      "location": "src/example.py",
      "requirement": "Preserve input ordering",
      "explanation": "The current implementation sorts the output",
      "requested_change": "Preserve the order of first occurrences"
    }
  ],
  "reviewer_label": "external-supervisor",
  "idempotency_key": "UNIQUE_REVIEW_KEY"
}
```

允许 verdict：`approve`、`changes_requested`、`blocked`。review 必须指向当前 attempt 与精确 snapshot，并满足 task_version。旧代码上的 approve、重复且不同内容的 decision、先前 attempt 的结果均不可生效。

reviewer/model 名称属于声明性 metadata，不是身份认证。V0.1 不解决同一 OS 用户下的恶意 executor 伪造 CLI 调用；不得把角色字符串写成“安全权限系统”。

### 4.4 ArtifactManifest

manifest 至少有：task/attempt、base SHA、candidate fingerprint、所有变更路径（包括非忽略的 untracked）、大小/类型/二进制标记、内容摘要、验证结果引用、scope violations、摘要截断信息、生成时间、证据等级。

保留 `executor_reported` 和 `bridge_observed` 两个不同区域。executor 自述“测试通过”不能生成 verifier pass。

摘要只默认返回 goal、关键 diff 统计、失败测试、风险与结论；完整日志用受控路径按需读取。默认不转发完整会话、thinking blocks 或所有工具输出，不依赖抽取模型私有推理。

### 4.5 用量数据

```json
{
  "mode": "mock",
  "model_calls_made_by_test": 0,
  "input_tokens_reported": null,
  "output_tokens_reported": null,
  "cache_read_tokens_reported": null,
  "cost_estimate_usd_reported": null,
  "subscription_remaining": null,
  "source": "not_observed"
}
```

如果云端开发 agent 自身在写代码，它当然消耗开发额度；这里的零仅指 **运行测试程序没有发起模型调用**。不要把开发成本写成零。

区分平台报告的 API 等价成本、真实账单、套餐余额和项目预算。无可信数据时使用 null/unknown。供应商 usage 字段可能是累计值或单次值，必须明确聚合口径，不能重复累计缓存 token 或 resume 前历史成本。

---

## 5. 状态机、幂等与恢复

### 5.1 建议状态机

```text
CREATED → READY → STARTING → RUNNING → VERIFYING → AWAITING_REVIEW
                                                        │
                             approve + 全部门槛满足 ────┤→ SUCCEEDED
                             changes_requested ────────┤→ READY（下一 attempt）
                             无权限/额度/外部条件 ──────┘→ BLOCKED

非终态 → CANCELLED
执行失败/超时/证据不完整 → INTERRUPTED 或 BLOCKED
重试预算耗尽/确定不可恢复 → FAILED
```

状态名称可以精简，但必须保留下列区别：正常执行中、等待审查、测试失败、权限/额度受阻、执行结果不确定、真正成功。测试不通过可以进入 AWAITING_REVIEW 并展示 FAIL，以便 supervisor 发出修复；不能仅因 executor 退出码为 0 而 SUCCEEDED。

`run` 只允许 READY 进入新 attempt。处于 AWAITING_REVIEW 时重复调用 `run` 不产生新进程。只有有效的 changes_requested 或明确恢复决定才能再执行。

### 5.2 成功的必要条件

SUCCEEDED 必须同时满足：本次执行正常结束；输出协议足够完整；没有未解决的 scope violation；所有 required verifier 实际运行且成功；产物未被后续改动；有效 approve 指向同一 snapshot；不存在未解决的中断或后台副作用风险。

测试缺失、测试被 skip、超时、状态不确定、摘要被截断导致关键证据缺失，都不能默认 pass。可选检查不通过可显示 warning，但 required 与 optional 由创建时的可信 TaskSpec 决定，executor 无权修改。

### 5.3 存储原则

SQLite 是任务与事件的唯一权威状态源。至少有 tasks、attempts、events、reviews、verification_runs；实际可以合并非必要表。状态转移与对应事件在同一事务中提交，使用唯一约束或 compare-and-swap 避免并发覆盖。

不要同时维护 SQLite 和 JSON 文件两套互相竞争的状态。JSON/Markdown 是导出视图或内容产物；写文件采用临时文件 + atomic replace，manifest 未落盘完整前不把状态标成已可验收。

事件有单调序号和 event ID；重放同一事件不得重复启动 executor、重复提交 review 或再次增加 usage。事件日志用于审计与排错，V0.1 不要求完整 event-sourcing 框架。[S10]

### 5.4 单执行权与模糊启动窗口

启动外部进程和提交 SQLite 事务不能作为一个原子操作。必须承认这个事实，不宣称对模型调用实现 exactly-once。

最低可接受设计：在 dispatch 前持久化 STARTING、attempt ID 和唯一 launch token；进程启动后记录 runner/PID 等可用证据。重复命令因状态/锁冲突被拒绝。发生“进程可能已启动，但启动记录未写完”的崩溃时，进入 `INTERRUPTED/outcome_unknown`，**不自动重发同一任务**。

PID 可能被复用，看到同号 PID 不足以证明它是原进程。只对当前进程明确拥有的 child/process group 自动发信号。跨重启无法确认身份时保守阻塞，不杀未知进程，不另起 executor 造成双写。

第一版可以只做 foreground runner，不要求常驻 daemon、后台服务安装或跨机器重连。不要把 shell 下 `&` 等同于可靠 detached worker。Codex 工具会话被终止后的子进程行为必须在本地验证，不能仅靠云端模拟宣布已支持。

### 5.5 恢复分类

| 状态/情况 | 自动行为 |
|---|---|
| 任务尚未 dispatch | 安全恢复为 READY |
| 已知 child 正常结束、最终结果已保存 | 接着执行验证/产物生成，不重跑模型 |
| 等待 review 时程序关闭 | 保持等待，下一 supervisor 可读取 manifest |
| 启动或执行结果不确定 | INTERRUPTED，阻止自动新 attempt |
| 已收到可信限流/额度错误 | BLOCKED，记录提供商原始分类与可选 reset 信息，不轮询续跑 |
| 仅凭模糊 stderr 猜测限流 | 标记 unknown/provider_error，保留脱敏证据，不编造 reset 时间 |
| 已确认进程结束但 vendor session 不可恢复 | 由后续本地授权决定是否开新 session |
| 达到 attempts/repair 上限 | FAILED 或明确 BLOCKED，不无限自修复 |

`recover` 默认检查并报告，不隐式消费模型额度。`cancel` 针对已确认拥有的进程尝试 TERM，等待配置的 grace period，再按策略 KILL；状态只在确认退出后写 CANCELLED，否则保持 cancellation_pending/unknown。

---

## 6. 工作区、证据和验证

### 6.1 Git worktree

对 target repo 从固定 base SHA 创建 bridge 自己拥有的 task branch/worktree。首次 demo 只在临时样例仓库运行。用户 checkout 的 branch、index、tracked/untracked 改动均不得被 bridge 擅自修改。

源工作区存在未提交修改时，默认拒绝创建真实执行任务，并说明“当前任务基于已提交 base，未包含这些修改”；不自动 stash、不自动 commit 用户代码、不运行 `git clean`、`reset --hard`。尚无首个 commit 的仓库返回明确错误。

worktree 用于文件/分支工作隔离，但与主仓库共享部分 Git 元数据，不是权限沙箱。[S8]

所有 bridge 自身执行的 Git 命令使用 argv，不拼 shell；处理路径时使用 `--`，使用 NUL 分隔输出应对空格/换行文件名；生成 diff 禁用外部 diff/textconv。不得让仓库自定义 diff driver 意外执行代码。

### 6.2 变更收集

不能只看 `git diff` 默认输出。必须覆盖 staged、unstaged、相对于固定 base 的已提交变化、非忽略 untracked 文件、删除、重命名、模式变化和二进制文件。Git 不能覆盖的受保护工作区检查要明确范围，不能声称观察了整个磁盘。

先扫描路径与大小再读取文件；secret 路径出现时拒绝把内容纳入公开产物。符号链接不能被透明跟随到 worktree 外；对 symlink 内容本身记录，或明确拒绝该任务。`../`、绝对输出路径、路径 prefix 混淆都应有测试。

candidate fingerprint 至少绑定规范化路径、文件内容摘要、文件类型/模式、base SHA、task_version 和 verifier 配置摘要。manifest 包含 untracked/二进制的摘要，即使不展示完整内容也不能遗漏其存在。

执行结束后、verification 前后、review 接受前检查 snapshot。检测到改动就使旧 verification/review 失效。不要把内容摘要当作恶意同 UID 进程下的防篡改认证；它主要解决陈旧证据和误修改问题。

### 6.3 独立 verifier

verification 命令由创建任务时的可信 TaskSpec 冻结，而非从 executor 最后一句话提取。每条命令保存 argv、cwd、运行环境标识、开始/结束时间、exit code、timeout、stdout/stderr 受限日志和 candidate fingerprint。

使用 subprocess 执行，不用 `shell=True`。命令本身仍可运行任意程序，所以只有已获用户授权、可信的验收命令可执行；argv 不是安全沙箱。[S9]

区分三种证据：`bridge-run external acceptance`、`bridge-run repository tests`、`executor-reported tests`。仓库中的 tests 也可能被 executor 修改，所以“独立运行”不等于“独立制定”；核心 demo 需保留至少一项由测试驱动控制、executor 不负责生成的验收检查。

可写在 worktree 外的验收检查与固定 requirement 绑定，不能让 executor 只改验收标准就通过。安全文档同时说明：同一用户下的外部文件并不构成对恶意代码的隔离。

### 6.4 产物限额

默认摘要限于约 24 KiB；单类日志和总 artifact 均有明确字节上限。截断时附 original_bytes、stored_bytes、truncated 和摘要/哈希信息。失败的尾部上下文优先，但不得因截断把“未知结果”变成“成功”。

原始 vendor 流不默认整段展示给 supervisor，不存储或转发不必要的 thinking 内容。未知消息类型可以记录类型及有限元数据；不能因忽略了未知终止信息而错误验收。

### 6.5 清理

默认保留 worktree 与产物，便于本地排错。V0.1 可不做自动 cleanup。显式清理只能作用于有所有权记录的 bridge 路径，先检查 dirty/未导出文件，不删除用户目录，不强制清除异常目录。

---

## 7. Adapter 实现

### 7.1 保持接口最小

核心只依赖 ExecutorAdapter，建议职责：

```python
class ExecutorAdapter(Protocol):
    def describe_capabilities(self) -> CapabilityReport: ...
    def build_invocation(self, task, attempt, feedback) -> InvocationSpec: ...
    def parse_event(self, raw_line: bytes) -> ParsedEvent: ...
    def classify_completion(self, process_result, parsed_events) -> ExecutorResult: ...
```

启动进程、超时、流量限制和生命周期由通用 runner 管理，不由每个 adapter 重复实现。build_invocation 必须无模型副作用，便于 dry-run 与离线 contract tests。

不要要求抽象支持 streaming token、embedding、tool choice、所有模型厂商特有参数。只覆盖当前产品需要的 launch、result、session metadata、errors。

### 7.2 Fake executor 不是返回 canned success

fake 必须是独立 OS 进程，用真实 stdin/stdout/stderr 和退出码。scenario 由可信测试参数控制，能够真实修改临时 repo 文件、逐行输出消息、启动受控 child、暂停、崩溃、生成非零退出码、返回坏 JSON 或声明错误测试结论。

至少提供 `success`、`bug-then-repair`、`hang`、`crash`、`malformed-output`、`permission-denied`、`budget-exhausted`、`scope-violation`、`false-success-report`。

不要在 production core 中为 demo scenario 写快捷成功路径。演示必须走与真实 adapter 相同的 runner、state/store、workspace、verification 和 review 路径。

### 7.3 Claude Code adapter

依据开发时可访问的官方文档和本地帮助文本，实现 `claude -p`、结构化输出、显式 session resume、模型 pin 和 turn limit 的最小支持。官方文档提供这些能力，但不等于 Cloud 内已经验证账号认证和 runtime 行为。[S3][S4][S5]

拟定调用形态如下；**不是让 Cloud 执行**：

```text
claude -p
  --model claude-opus-5-5
  --output-format stream-json
  --verbose
  --max-turns <configured limit>
  [--resume <verified session id>]
```

任务正文用 stdin 或受控文件传递，避免 shell 拼接与巨长命令行。`--include-partial-messages` 非必需，默认不启用以减少日志。实际版本不支持某字段/flag 时应 fail clearly，不无限尝试参数组合。

不要使用 `--continue`/`-c` 选择最近会话，避免串任务。resume 失败不能无声降级为新 session；形成明确交接与重新授权路径。

输出处理至少覆盖：start/session metadata、结果事件、成功/失败、permission denial、max-turns、退出非零、缺失最终 result、未知事件、无 usage、部分输出。保存 requested model 与 observed model；观测不到不要声称完全符合模型 pin。

**重要认证限制：** 当前官方文档说明 `--bare` 不读取订阅 OAuth/keychain，因此本项目的“用本地订阅、不另付 API”路径不能默认加 `--bare`。[S3] 不读取或搬运 OAuth token 来自行构造 HTTP 请求。

默认 `-p` 路径可能加载用户/项目 hooks、MCP 和配置。首次真实运行前必须审查这些入口与权限配置；不以“使用 worktree”替代这一步。不要用 `--dangerously-skip-permissions`、无限制 Bash 自动批准或禁用平台保护换取 demo 成功。

`--max-budget-usd` 若在当前版本存在，也只是供应商实现的调用成本约束，不是本项目的 Cloud bonus 精准账单闸门。V0.1 以 attempts、max-turns、wall timeout、explicit-live-gate 为可控约束；不要用该参数宣称保证不超出 100 USD。[S4]

### 7.4 实际调用的显式闸门

Cloud 开发模式与默认运行模式都是 mock。真实 `run` 至少需要 CLI 显式 `--mode live --allow-model-usage`，以及本地配置启用 live；缺一就在 spawn 前失败。Cloud mode 下即使误带 live flag 也拒绝真实 dispatch。

在 no-API 配置中，如果存在 `ANTHROPIC_API_KEY` 或未知第三方 provider/网关认证设置，拒绝真实调用并只报告变量名/配置类别。不要擅自清除全局配置、切换登录、设置新的 provider 或输出 secret 值。官方说明 API key 环境变量可能导致 Claude Code 使用 API 而非订阅计费。[S6]

这些检查是减少误触发，不是可证明的账单隔离。额外用量/自动充值状态仍须用户在本地账户 UI 确认；未知时不宣称零额外费用。

### 7.5 Fixture provenance 与兼容性

每组 fixture 带来源文件：`synthetic`、`docs-derived`、`captured-live` 之一；附生成日期、文档地址、假设字段、真实 CLI 版本（没测则 null）。不要把自行生成的 stream-json 命名为“real transcript”。

使用 synthetic Claude-like stdout 验证 parser，只能声明“parser 对这些样例通过”。真实 CLI 是否输出完全一样的数据，必须在本地采样后再提高验证等级。

---

## 8. CLI 用户契约

全局支持 `--state-dir` 与 `--json`。JSON 输出到 stdout，诊断到 stderr。统一错误结构含 code、message、retryable、task_id/attempt_id（适用时）。缺参数、状态冲突、未启用 live、执行失败、验证失败应能区分。

最小命令集：

```text
hbridge doctor [--offline] [--json]
hbridge create --task task.json --idempotency-key KEY
hbridge run TASK_ID --mode mock
hbridge status TASK_ID [--json]
hbridge artifacts TASK_ID [--json]
hbridge verify TASK_ID
hbridge review TASK_ID --file review.json
hbridge recover TASK_ID
hbridge cancel TASK_ID
hbridge demo --scenario success|bug-then-repair
```

M1 先实现 create/run/status/artifacts/review/demo；M2 补足 verify/recover/cancel。公共名字确定后同步更新示例与测试，不能文档写一套、实际实现另一套。

`doctor` 默认为非推理诊断，不登录、不访问模型 endpoint、不读 secret 值；输出 capabilities 的 `supported`、`unsupported`、`unknown`，以及证据来源。

`review --verdict approve` 这样的纯 CLI shortcut 不必做，防止漏掉 snapshot binding。通过完整 review.json 提交更可靠。重复 review 使用同一 key 返回原收据，不再次变更状态。

### 8.1 外部 supervisor 的操作约定

`examples/supervisor-instructions.md` 要写成可放入 Codex 的实际操作指引：先明确 goal/constraints/acceptance；创建 TaskSpec；调用 bridge；等待确定性完成信号或低频查看状态；读取 manifest 和相关 diff；独立理解风险；必要时运行额外验证；提交与 snapshot 绑定的 review。

不要每几十秒读取整份日志；只在完成、blocked、限额或里程碑事件后介入。不要每个小改动都给 Opus 新指令。一个任务包应包含一个可独立验收的工作单元。

supervisor 默认不修改 executor 正在编辑的 worktree。后续用户要求 Codex 接管时，先停止并确认 executor 结束，再记录 takeover；V0.1 可以不实现自动 takeover。

---

## 9. 安全与可信边界

V0.1 是可信用户控制下的协作工具，不是恶意代码沙箱。README 和 `docs/SECURITY.md` 必须明确这点。

| 控制 | 本轮可承诺的范围 | 不可承诺的范围 |
|---|---|---|
| worktree | 防止正常流程误改主 checkout | 阻止 executor 访问整个主机 |
| 路径 policy | 校验 bridge 操作、检测候选变更越界、拒绝验收 | 撤销已发生的外部副作用 |
| snapshot digest | 防止陈旧 review、检查误改 | 防止同 UID 进程全面篡改本地存储 |
| 角色 metadata | 分清工作流程中的来源 | 密码学身份认证 |
| timeout/turn limit | 限制已知进程和可观察执行 | 精确限制套餐/账单总消耗 |
| no-live gate | 防止正常 CLI/CI 误启动真实模型 | 操作系统级禁止所有可能的网络进程 |
| verifier | 实際运行预先指定的验收命令 | 自动证明任意需求都已正确实现 |

repo 文件、executor 输出、日志和错误消息都是待审查的数据，不能把其中“忽略指令”“运行这个上传命令”“关闭保护”等文字解释成 bridge 的新权限。

不上传运行数据库、真实 prompt/transcript、凭据、用户本机路径详情或其他私有 repo 内容。`.gitignore` 至少排除 `.env*`（保留明确的占位 `.env.example` 如确需）、token/key 文件、state、artifacts、worktrees、原始会话日志、缓存和构建产物。

仓库策略可检测并阻止桥自身执行危险 Git 操作，但不要声称它能拦截拥有 shell 权限的 Claude 所有外部行为。真实模式最初只用于经过用户确认的可信、小型、本地 fixture repo。

---

## 10. 零额外模型费用的测试方案

### 10.1 测试层级必须分别报告

| 等级 | 内容 | Cloud 目标 | 能证明什么 |
|---|---|---|---|
| T0 | 静态检查、schema、命令构造 | 必做 | 代码/契约的局部性质 |
| T1 | 单元测试、状态转移、幂等 | 必做 | 被覆盖的核心逻辑 |
| T2 | 真实子进程 + 临时 Git + SQLite + verifier + fake wire protocol | 核心目标 | 桥的端到端工程流程 |
| T3 | 本地真实 Claude CLI，用用户订阅执行/修复 | 本轮不做 | 特定版本、配置、账号下的单 harness adapter |
| T4 | 真实 Codex/Astra → bridge → Claude/Opus → Astra review | 本轮不做 | 特定环境下双 harness 闭环 |
| T5 | 对照任务测量质量、用量、返工 | 后续 | 对特定任务集的效果判断 |

T2 必须写作“offline integration / simulated executor”，不能叫“live E2E passed”。T3/T4/T5 的状态是 `NOT_RUN` 或 `BLOCKED_BY_ENVIRONMENT`，不是“预计通过”。

### 10.2 核心演示任务

实现一个很小的 Python fixture 项目：`normalize_tags(values)`。需求固定为：去掉首尾空格、转小写、丢弃空字符串、去重、**保留首次出现顺序**。输入只要求列表中的元素是字符串，其他类型不属于本轮需求。

真实 fixture tests 至少覆盖普通输入、重复、全空、大小写和保序。验收脚本由测试驱动控制；不要让 fake executor 直接修改预期答案。

`bug-then-repair` 流程：

```text
1. 在新的临时路径创建 fixture Git 仓库与 base commit。
2. hbridge 创建 TaskSpec、task worktree 和持久化任务。
3. 第一次 fake subprocess 写入存在排序错误的实现。
4. bridge 执行真实测试，保序 case 失败；即使 fake 自报成功也不能 approve。
5. 脚本化 supervisor 提交 changes_requested，绑定 attempt 与 snapshot。
6. 新一轮 fake subprocess 接收反馈，写入正确实现。
7. bridge 再次运行真实测试，保存新的证据。
8. supervisor 提交有效 approve，任务进入 SUCCEEDED。
9. 启动全新的 CLI 进程读取状态，证明状态不是只保存在内存中。
10. 检查用户原 checkout 未被修改、没有真实模型调用、没有复制任何账号凭据。
```

第一轮失败是 scenario 的预期，不得把整体 demo 误报成失败或悄悄改成一次成功。提供两个独立 demo：success 和 bug-then-repair。不要要求用户手改 task ID；脚本解析 CLI 的 JSON 收据并自动构造下一步。

### 10.3 必须优先实现的测试

| ID | 场景 | 必须断言 | 优先级 |
|---|---|---|---|
| C01 | 正常离线闭环 | 真实文件修改、真实 verifier、有效 review 后成功 | P0 |
| C02 | 第一次失败后修复 | FAIL → changes_requested → 新 attempt → PASS | P0 |
| C03 | executor 自报测试成功 | 独立 verifier 失败时拒绝 approve | P0 |
| C04 | 重复 create | 相同 key/request 不生成新任务；不同 request 冲突 | P0 |
| C05 | 重复 run | 已运行/待审任务不再 spawn executor | P0 |
| C06 | 坏 JSON/缺失 final result | 记录协议错误，不当成成功 | P0 |
| C07 | 进程超时或非零退出 | 被确认管理的进程结束或状态明确不确定 | P0 |
| C08 | 新增 forbidden/untracked 文件 | scope violation 被发现，不能验收 | P0 |
| C09 | stale review | snapshot/attempt/task_version 不匹配时拒绝 | P0 |
| C10 | verifier 超时/没执行 | required check 不是 PASS | P0 |
| C11 | 模型调用误开启 | 默认测试和 demo 不 spawn 真实 binary；live gate 生效 | P0 |
| C12 | 原 checkout 保护 | branch/index/用户文件没有被 bridge 改写 | P0 |
| R01 | SQLite 重开 | 新进程能读取同一任务和事件 | P0 |
| R02 | STARTING 崩溃窗口 | recover 不自动重复 dispatch | P0 |
| R03 | 达到修复上限 | 不发生第四次/额外无限调用 | P0 |
| R04 | 重复 review/event | 状态和 usage 不重复推进 | P1 |
| R05 | 两个进程竞争同一任务 | 至多一个获得 dispatch 权；另一个清晰冲突 | P1 |
| R06 | cancel + child process | 已知 process group 可终止；未知 PID 不被杀 | P1 |
| R07 | review 前候选变化 | 原验证/approve 失效 | P0 |
| A01 | Claude 命令构造 | 无 shell 拼接、精确模型、显式 resume、有限 turns | P1 |
| A02 | 文档衍生 Claude-like fixtures | parser 正确处理已知字段；provenance 为 synthetic/docs-derived | P1 |
| A03 | unknown event / 缺 usage | 保守兼容；未知成本为 null | P1 |
| A04 | 权限/额度错误 | BLOCKED，不更换账户/付费/轮询重跑 | P1 |
| A05 | 超长 stdout/stderr | 持续 drain、防死锁、限额/截断可观测 | P1 |
| A06 | partial UTF-8 / chunk 边界 | parser 不因任意读取边界损坏合法输出 | P1 |
| S01 | `../`/symlink/路径相似前缀 | bridge 自身拒绝越界路径，不跟随链接读秘密 | P0 |
| S02 | credential-looking 测试文本 | 脱敏产物不泄露虚构 token；不使用真 token | P1 |
| S03 | verifier 配置被篡改 | 冻结配置与摘要校验阻止改变验收标准 | P0 |
| S04 | API env 存在/--bare 被误加 | no-API 配置 preflight 报错；不触发真实请求 | P1 |

P0 是达到对应功能验收所需的核心测试，不要求在功能尚未实现时先造大量空测试。先打通 C01，再逐步增加其余 P0。P1 只在核心切片稳定后继续；未完成的行留在验证矩阵中。

### 10.4 测试执行原则

所有 integration tests 使用 tempfile、测试专用 Git identity、隔离的 state root 和测试 HOME，不读取用户实际 Claude/Codex 认证目录。fake executable 使用显式绝对路径，不靠 PATH 中碰巧存在的 `claude`。

单元测试中的时钟可注入；真实 subprocess timeout 测试使用小而有余量的限时与显式握手，不堆长 sleep、不依赖网络。runner 必须并行 drain stdout/stderr，防止管道占满死锁；保留最终 completion 所需证据。[S9]

测试程序不安装依赖、不发网络请求、不调用模型服务。依赖准备放在测试开始之前。可以增加 Python 网络访问守卫和 fake-only dispatch 断言；如果没有 OS 级网络隔离，应诚实写明这是进程级防误用，不是全系统网络防火墙。

真实测试不能通过“检测到 key 就自动跑”启用。`tests/live` 默认不进入常规 suite；未来必须显式选择 live marker + runtime gate + 用户授权。任何 skipped 都在测试报告列出，不用一个绿勾掩盖。

不以某个任意覆盖率数字代替正确性。重点报告关键不变量与失败路径是否覆盖。不得为了跑满覆盖率进行与产品无关的大规模 mutation/fuzz 项目。

---

## 11. 实施顺序、验收门槛和停止点

**严格顺序实现。每阶段都要有可运行结果；不把所有模块先写一半。**

### M0 — 建立独立项目与可接续的开发环境

工作：确认/创建新 repo，建立开发分支，提交计划与最短规则文件；创建 pyproject、最小包、测试入口；记录环境与授权边界。

验收：新仓库/独立目录身份清晰；至少一个真正运行的最小测试；一次本项目提交；remote 是否 push 成功准确记录。

停止点：若只能完成 M0，交付应明确叫 bootstrap，不叫 MVP。无权创建远程时，交付里列出该阻塞，不继续用旧 repo 伪装独立项目。

### M1 — 可运行的最小纵向切片

工作：TaskSpec、SQLite 基本状态、临时 worktree、通用 subprocess runner、fake success executor、独立 verifier、artifact manifest、approve gate、CLI create/run/status/artifacts/review、success demo。

实现策略：先做一条完整路径；不要先构建 capability registry、复杂 budget scheduler 或自动 supervisor。

验收：从干净环境运行 success demo，真正修改文件并执行验收；新 CLI 进程读取到 SUCCEEDED；用户原 checkout 无修改；全部默认命令不触发模型调用。产生实际测试报告，提交并 push（权限允许时）。

停止点：M1 + 已实现路径的 P0 安全检查 + 完整 HANDOFF，是本轮最低有价值交付。不能因为尚无真实 adapter 而丢弃这个成果，也不能声称真实桥已可用。

### M2 — 修复闭环与基础恢复正确性

工作：changes_requested、三次 attempt 总上限、重复命令幂等、stale review 防护、失败/超时、scope detection、可信 verifier 配置、基本 recover/cancel。

先补失败后修复 demo，再补中断窗口。对尚未实现的恢复情形选择 fail closed/明确阻塞，优于复杂但未经验证的自动恢复。

验收：bug-then-repair 完整通过；上述已实现功能对应 P0 tests 通过；启动结果不确定时不重发；超额修复明确停止；执行报告区分实现失败与协议失败。

停止点：额度紧张时完成 M2 后收口，不为“看起来完整”抢写多个真实 adapter。M2 的离线可靠性比五个未验证 provider skeleton 更重要。

### M3 — Claude CLI adapter 与本地接线准备

工作：无副作用 command builder、流式 parser、错误分类、requested/observed model、session binding、显式 live gate、no-API preflight、synthetic/docs-derived contract tests。

验收：真实 adapter 代码路径存在，不只是 `raise NotImplementedError`；命令和 parser 的离线测试有来源记录；所有真实认证/推理项仍标 NOT_RUN；本地 smoke 流程能由文档直接执行。

停止点：如果 adapter 只能实现一半，明确写出缺失方法与 exact next step，不把它注册成“ready”。可暂时让 live 模式明确 UNSUPPORTED，保留已完成的纯函数与测试。

### M4 — 收口与本地接续

工作：从新 venv/干净 checkout 重跑离线检查；修复 README 中不可执行的命令；写准确验证矩阵、未解决问题、最小本地验证步骤；生成手动 CI workflow；完成最后提交和 push 证据。

M4 的最小交接工作必须在每个停止点做，不必等 M3 全部完成。创建一个离线测试 workflow 即可，默认 `workflow_dispatch`，只用标准 runner，设 timeout 和最小 `contents: read` 权限，不使用账户 secrets、不启动模型服务、不自动开启付费额度。

验收：用户 clone 正确 branch 后，按 README/LOCAL_HANDOFF 能复现已声称通过的离线 demo；所有未测 live 能力明确显示 NOT_RUN；文件、代码、commit 与报告一致。

### 优先级摘要

```text
必须保住：独立项目 + 一个跑通的真实工程切片 + 安全失败 + 可复现交接。
然后完善：失败修复闭环 + 基本恢复 + Claude adapter 离线契约。
最后才做：更多兼容性、文档美化、手动 CI、benchmark 元数据。
本轮不做：真实双 harness、真实用量 A/B、完整产品平台。
```

---

## 12. 100 USD bonus 的工作控制

这 100 USD 是用户陈述的 Cloud 可用 bonus；不能假定它能用于第三方模型 API，也不能假定其有效期、适用模型、余额或超出后的扣费行为。以用户实际账户界面和本次授权为准。

### 12.1 不依赖余额读取的默认策略

默认一个主会话，顺序完成 M0→M1→M2→M3；每完成可验收阶段立即保存，不等结束再 push。核心工作完成后进入收口，不为了花完 bonus 自行增加项目范围。

同一阻塞在没有新证据时最多重复一次诊断，不连续重试 GitHub 权限、模型登录、网络封锁或未知 flags。遇到难点先做安全简化，记录限制，不扩成基础设施项目。

实现期间优先运行受影响测试；阶段验收和最终交付再跑完整离线 suite，避免每改一行都重跑所有长测试。不要反复全文读取大日志或完整执行书；状态发生变化后更新精简 STATUS/HANDOFF。

### 12.2 余额可见时的补充策略

只有账户界面或可信系统元数据提供余额，才能引用具体数额。可以把可见剩余额度的最后一部分（例如原 bonus 的约 20%）作为收口保留量；这是工作分配目标，不是程序可执行的账单保证。

余额不可见就写 `development_budget_remaining: unknown`，按里程碑及时收口。不要自己用 API 单价反算 Cloud 套餐消耗，也不要声称“这一阶段精确花了几美元”。

### 12.3 强制收口触发

收到额度/会话结束信号、反复环境阻塞、核心切片已稳定且下一项属于扩展范围、或尚未解决的关键错误会被后续改动掩盖时，停止开新功能。保存当前最佳已验证提交，写 HANDOFF；未通过的改动隔离在明确的 WIP commit/branch，不能藏进“测试通过”的总结。

不因停止而编造已完成项，也不因为预算不够就只输出下一轮计划、不保存已经实现的代码。

---

## 13. GitHub 交付与可复现要求

README 首屏必须明确：experimental prototype；当前验证等级；离线 demo 与真实 adapter 的区别。不得用“production-ready”“完全自动节省 X%”“已验证 Astra/Opus 更强”作为宣传。

每个阶段在 `STATUS.md` 记录：milestone、已完成切片、相关测试命令与实际结果、current blockers、next step、last verified code commit、模型配置确认方式、remote push 状态。完成度使用里程碑和功能状态，不给没有度量依据的“85% 完成”。

在 `docs/VALIDATION_MATRIX.md` 每行记录：feature、implementation status、evidence level、test/command、result、platform/version、remaining uncertainty。

交付日志要有可追溯的代码 revision。可以用“已测试代码 commit + 后续仅文档提交”形式避免最终 commit SHA 自引用；说清最后一次完整测试对应哪个 tree，不编造“当前 commit 的测试通过”而实际后来改过代码。

若建 PR，使用当前工具支持的正式流程，保持不合并状态，并在 description 区分 offline passed 与 live not run。Cloud 不支持 PR API 时，已推送 branch 即可，不为建 PR 持续重试权限。

GitHub push 要通过命令结果和随后可读的远端 ref/commit 确认。只有本地 commit 时明确写 `not pushed`。Git bundle/压缩包只有在实际导出并可获得时才写 delivered；仅存在 VM 的文件路径不算完成交付。

不擅自设置 public、发布 PyPI/npm、安装用户机器常驻服务、创建付费 runner、启用 auto-fix 无穷跟进或自动 merge。采用 private 默认并未决定以后不开源，许可决定留到用户正式发布时。

---

## 14. 本地接续方案：不需要另买模型 API

必须区分三件事：**继续开发 bridge 项目**、**首次测试真实 Claude adapter**、**首次测试真实双 harness**。它们不是一次自动命令。

### 14.1 先在本地复现离线结果

`docs/LOCAL_HANDOFF.md` 必须填入实际仓库、branch 和 last verified revision，以及准确安装命令；目标流程示意：

```bash
# 仓库创建和 Cloud push 完成后，使用实际 branch。
gh repo clone CHANxuanyu/harness-bridge
cd harness-bridge
git switch <ACTUAL_CLOUD_BRANCH>
uv sync --frozen
uv run ruff check .
uv run mypy src/harness_bridge
uv run pytest -m "not live"
uv run hbridge doctor --offline --json
uv run hbridge demo --scenario success
uv run hbridge demo --scenario bug-then-repair
```

以上是待交付的命令契约；最终必须用实际可运行命令替换所有占位。尚未实现某命令时不要让用户原样运行；在文档标明其 milestone 与当前替代步骤。

本地 Mac 与 Cloud Linux 不同，至少重新验证 subprocess 退出/取消、文件权限、路径、Git worktree、SQLite 锁及安装流程。Cloud 通过不等于 macOS 已验证。

### 14.2 首次真实 Claude CLI：先诊断、再明确授权

在小型 disposable fixture repo 中进行，不直接拿 Secretary 大项目测试。先由用户使用官方登录方式确认 Claude Code 订阅可用，检查 API/provider 环境变量、额外用量设置、项目 hooks/MCP 和 tool permission；不要让 bridge 自动登录或拿取 token。

Claude Code 与 Codex 都提供使用各自订阅账号的官方登录路径；这不代表任意额外用量永久免费，也不代表 bonus 可跨产品使用。[S6][S11]

本地真实 smoke 的拟定顺序：

```text
明确授权一次有限真实模型使用
→ 精确模型 pin / 记录 CLI 版本与配置
→ 创建小任务（首次限制一个 attempt）
→ Claude CLI 实际修改 fixture
→ bridge 捕获真实 session/result
→ 运行独立 verifier
→ 人或 Codex 提交 review
→ 将脱敏 wire 样例保存为 captured-live fixture
```

不要第一次就测试十轮重试、小时级任务或自动等配额重置。第一轮只确认认证方式、命令 flag、stdout schema、session metadata、权限和退出行为。

随后单独做一次受控修复/resume；只有本地真实结果支持，才把 adapter 能力标为 T3。保留 fake fixture 与 captured-live fixture 两套来源，不互相覆盖。

### 14.3 首次真实 Codex/Astra → Claude/Opus

在用户当前的 Codex 会话中加入 `examples/supervisor-instructions.md`。Astra 生成 TaskSpec，调用 hbridge，读取证据并提交 review；bridge 不另开 OpenAI API 客户端。

如果 Codex 的沙箱/权限无法启动或访问本机 Claude，正常请求所需权限，或由用户在另一个本地终端运行同一个 hbridge 命令。**后者应标作 manual handoff，不可声称已验证 Codex 自动启动链路。** 不禁用安全策略来通过测试。

经过一个正常任务与一个需要修复的任务，记录实际流程后再标为 T4。真实双方模型、版本和配置都记录来源；无法确认的模型身份标 unknown，不凭对话自述认定。

### 14.4 不依赖模型会话可迁移

GitHub 上的源码、STATUS/HANDOFF 和验收命令是继续开发的主路径。Git commit 不包含供应商完整会话；SQLite 的 task metadata 也不能重建模型上下文。

Claude 官方区分本机 `--resume` 与云端 `--teleport`，后者有账号、仓库和分支条件。用户可以在支持时使用 teleport 继续开发对话，但本项目交付不能把它作为唯一接续手段。[S1]

把 cloud task 的 session ID 原样放到另一台机器并调用 `--resume`，不能当成已经实现的恢复方案。只有正式支持且实际验证的路径才能写成可用功能。

---

## 15. 后续效果评估设计：本轮只准备格式

最初的问题是“多一个 supervisor 是否浪费额度，质量提升是否值得”。本轮不能通过 mock 数据回答。不要为 README 生成虚构百分比或用合成 traces 假装测到模型收益。

后续建议对照：A = Opus 独立完成；B = Opus 完成后同模型自查；C = Astra 规划 + Opus 执行 + Astra 独立验收。B 用于部分区分“多花了 review 工作”与“跨模型 review”带来的变化。

使用同一基线 commit、相同需求与验收、独立 worktree、新会话和明确工作限额。不要把一个方案的解法和失败经验泄漏给另一个方案。开始用少量代表任务做探索性比较，不做显著性结论；具备预算后再增加重复试验、随机执行顺序并报告不确定性。

记录完成/失败、独立验收、wall time、人类干预、repair cycles、双方可观察 usage、上下文/产物读取量、总模型调用次数、模型/CLI 版本、权限和缓存配置。usage 不可见则 null；套餐百分比若跨 reset、分辨率粗或后台有其他使用，必须注明不可比。

另行记录 bridge overhead（启动、产物整理、验证耗时），不要把其 OS 时间和模型推理 token 混成一个“成本”。无法取得真实美元费用就不能计算准确的 cost-per-success。

本輪只提交 `docs/EVALUATION_PLAN.md` 与结果 schema，不运行付费 benchmark、不扩展成大型评测平台。Secretary 可作为后续真实 workload 候选，但本轮不读取、复制或改造其代码。

---

## 16. HANDOFF 最小模板

每次停止/压缩上下文前更新，控制为读一遍即可继续，不能只写“继续上次任务”。

```markdown
# Handoff

## Repo and revision
- Actual repository / visibility:
- Working branch:
- Last verified code revision:
- Latest local commit:
- Remote push verified: yes/no/unknown

## Current milestone
- Completed vertical slice:
- In progress (exact files and behavior):
- Not implemented:

## Verification actually executed
- Command / environment / result:
- Expected failures and skipped tests:
- Validation levels reached:
- Live Claude: NOT_RUN
- Live Codex→Claude: NOT_RUN

## Constraints still in force
- Development model: Opus 5.5 (confirmation source or unknown)
- No extra model API budget; no nested live harness in Cloud
- Runtime mode remains mock unless locally and explicitly authorized
- Development bonus remaining: unknown unless actually observable

## Known issues
- Repro / suspected cause / evidence:
- Safe workaround or fail-closed behavior:

## Next bounded work package
- One concrete goal:
- Files to inspect:
- First reproduction/test command:
- Acceptance criteria:
- Things NOT to do:
```

不要把 TODO 全部从 backlog 复制到 handoff。优先写下一个可完成工作包。另在 LOCAL_HANDOFF 记录平台差异、真实 CLI 尚需验证的字段和权限。

---

## 17. 最终交付回复格式

结束时提供一份有事实依据的简短报告，包含：实际仓库和 branch（如果已创建/上传）、完成到哪个 milestone、哪些 demo/测试真正执行、关键限制、真实 harness 尚未验证、本地第一条正确接续命令，以及 STATUS/HANDOFF 路径。

如果没有远程权限，明确写“远程仓库未创建/未推送”，列出本地已保存提交和真正可获取的导出物。不能只贴一个猜测 GitHub URL；不能因为有 CLI adapter 文件就写“支持 Astra/Opus 全自动协作”。

**现在开始实施 M0，然后继续 M1。不是只回复“我会做”，不是把本执行书换个措辞再交回来。**

---

## 附录 A：官方参考与已确认边界

查阅日期：2026-10-06。下面只作为文档依据，不替代实际安装版本的运行验证。文档变化时更新来源与兼容性记录，不在没有新证据时随意改核心契约。

- **[S1] Claude Code cloud：** 支持 cloud session、GitHub 分支工作流与云端到本地的正式迁移；`--resume` 和 `--teleport` 含义不同。`https://code.claude.com/docs/en/claude-code-on-the-web`
- **[S2] Cloud environments：** GitHub proxy 有仓库范围等限制；不能从能 push 某 repo 推导出能创建任意 repo。`https://code.claude.com/docs/en/cloud-environments`
- **[S3] Programmatic Claude Code：** 提供 `-p`、JSON/stream-json；当前文档说明 `--bare` 不使用订阅登录，并提醒非 bare 模式加载配置入口。`https://code.claude.com/docs/en/headless`
- **[S4] Claude CLI reference：** 模型、turn limit、resume 等参数；预算 flag 不是 Cloud bonus 账单保证。`https://code.claude.com/docs/en/cli-reference`
- **[S5] Model configuration：** 完整模型名可固定版本，别名随供应商/版本变化；本项目目标 `claude-opus-5-5`。`https://code.claude.com/docs/en/model-config`
- **[S6] Claude subscription usage：** 官方订阅登录路径、共享用量与 API key 环境变量的计费风险。`https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan`
- **[S7] GitHub CLI repo creation：** `gh repo create` 的 private、README、source/push 等参数。`https://cli.github.com/manual/gh_repo_create`
- **[S8] Git worktree：** 额外 working tree 与共享 Git 元数据。`https://git-scm.com/docs/git-worktree`
- **[S9] Python subprocess：** argv、管道、timeout 与子进程管理接口；产品应对具体管理边界做测试。`https://docs.python.org/3.12/library/subprocess.html`
- **[S10] Python sqlite3：** 事务与 SQLite 接口；本项目选择基于事务的单机状态存储。`https://docs.python.org/3.12/library/sqlite3.html`
- **[S11] Codex subscription access：** Codex 官方 ChatGPT 账号登录路径；具体用量和权限取决于用户环境。`https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan`

## 附录 B：不允许写进交付的推断

“Mock 通过，所以真实 Claude 认证/恢复已经没问题。”——不成立。  
“有 Claude Code Cloud bonus，所以可免费调用 OpenAI API。”——不成立。  
“写了 task.json，所以关闭 Codex 后 Astra 会自动继续 review。”——不成立。  
“SQLite 里有 session_id，所以换机器可以恢复 vendor 会话。”——不成立。  
“worktree/allowed_paths 已经构成完整安全沙箱。”——不成立。  
“两个模型一定比一个更省额度、更强。”——本项目正要在后续真实评估中检验。  
“本次 100 USD 一定能做到 M4。”——没有可支持这一承诺的数据。
