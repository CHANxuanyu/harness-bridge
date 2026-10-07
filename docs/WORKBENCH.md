# RepoBridge 工作台：使用、实现与验收

_2026-10-07，作者 Xuanyu CHAN。产品范围见 [PROJECT_PLAN.md](PROJECT_PLAN.md) v2.0；本文描述已实现的 W1–W3
代码、运行方式、证据等级和尚未完成的真实验收。_

## 运行

```bash
uv sync --extra desktop        # 安装可选的原生窗口依赖 pywebview（只需一次）
uv run hbridge app             # 打开 RepoBridge 原生窗口（也可用 `uv run repobridge`）
uv run hbridge app --browser   # 不用 pywebview，在默认浏览器中打开同一界面
```

- 请从 Finder 打开的终端或普通终端启动，不要在另一个 agent 会话（例如 Claude Code 的终端）里启动：
  App 检测到 `CLAUDECODE` 或云 agent 环境变量时会拒绝启动原生会话。
- 状态目录默认为 `~/.local/state/harness-bridge`（可用 `--state-dir` 或 `HBRIDGE_STATE_DIR` 指定），
  工作台数据在其中的 `workbench.sqlite3` 与 `workbench/`，与旧任务库分开。
- CLI 自动发现：`claude` 依次查 PATH、`~/.local/bin`、Homebrew 等；`codex` 还会查找 ChatGPT/Codex 桌面
  App 自带的 CLI。可用 `--claude-binary` / `--codex-binary` 指定绝对路径。
- 关闭窗口会先确认；关闭等同于关闭终端：会话进程结束，原生会话由各家 CLI 保存，可在 App 中“恢复”。

## 使用

1. **添加项目**：选择本地目录（Git 仓库请选顶层）。App 不修改目录内容。
2. **新建会话**：在项目下点 “＋ Claude Code” 或 “＋ Codex”。App 在自有终端里启动原生交互式 CLI，
   你像平常一样对话、批准权限、使用斜杠命令。Shift+Enter 发送 Ctrl+J（两个 CLI 都把它当作换行）。
3. **右侧面板**：
   - 活动：Claude Code 的请求/工具/权限/停止事件（只记录的 hooks）；Codex 的每轮完成与终端通知
     （含审批请求）。等待权限时会话显示“等待权限”，在终端中回答。
   - 文件变更：工作目录的 Git 状态和单文件 diff（只读）。
   - 会话：harness、原生会话 ID 与绑定方式、恢复状态、运行记录（退出码/信号/失败原因、未传递的环境变量）、交接链。
4. **停止 / 恢复**：停止向进程组发送 SIGHUP（必要时升级），确认退出后记录。已有对话的会话可“恢复”：
   Claude 用 `--resume <id>`，Codex 用 `codex resume <id>`；也可在普通终端中运行同样的原生命令。
5. **交接**：在会话栏点“交接…”，选择目标 harness，填写进度，编辑 App 生成的说明后创建。
   原会话需先停止（同一工作目录只允许一个写入会话）。新会话在同一项目启动；勾选时说明会作为第一条消息
   发送（这是一次由你确认的模型调用）。新会话不继承原会话的原生上下文；原会话保留，可之后恢复。

## 实现结构

```text
src/harness_bridge/workbench/
  harness.py    CLI 发现、--version 探测、原生 argv、会话环境（去除 API/provider 变量）、嵌套/云环境拒绝
  relay.py      只记录的旁路：Claude hook stdin / Codex notify 参数 → 每次运行的 events.jsonl；永不输出、永远 exit 0
  pty_host.py   PTY 进程：受控终端、读写、resize、SIGHUP→TERM→KILL、进程组退出确认、输出缓冲/日志、OSC 9 解析
  store.py      workbench.sqlite3：projects / sessions / runs / events / handoffs；单写入名额在 BEGIN IMMEDIATE 中判定
  service.py    Workbench：项目、会话、运行、旁路事件、权限提示、Git 变更、交接、重启后的 reconcile、订阅推送
  changes.py    只读 git status / diff（沿用 workspace.git 的安全参数）
  handoff.py    交接说明草稿（只用 App 观察到的事实 + 用户填写的进度）
  server.py     127.0.0.1 HTTP + SSE；令牌 cookie、Host/Origin/自定义头/JSON 校验、CSP
  app.py        `hbridge app` / `repobridge`：pywebview 窗口或浏览器
  static/       index.html、app.css、app.js（无构建步骤）、vendor/xterm（MIT，未修改）
```

关键约定：

- **会话 = 一个原生会话名额。** 第一次运行为新建；之后只能原生恢复。尚未观察到任何对话轮次时允许“重新启动”
  （Claude 会换一个新的预分配 ID），已有对话则必须恢复或另建会话。
- **原生 ID 只用观察到的事实。** Claude：`--session-id` 预分配，SessionStart hook 报告相同 ID 即“已确认”，
  `/clear` 等导致 ID 变化时以最新为准并记录事件。Codex：首轮完成的 notify 带 thread-id 前显示“未知”。
- **单写入**：同一真实工作目录（realpath）同一时刻只有一个 starting/running 的运行；第二个请求返回占用会话。
  App 重启后，仍记为运行中但进程（pid + 启动时间）已不存在的运行标为“已中断”并释放名额；
  进程仍在的保持占用，可在 App 中终止。
- **旁路粒度不同**：Codex TUI 没有逐工具的外部事件，界面如实说明，不补造。
- **环境**：会话环境继承用户环境，去掉 `config.API_PROVIDER_ENV` / `CODEX_PROVIDER_ENV` 中的变量与外层终端身份变量，
  设置 `TERM=xterm-256color`；被去掉的变量只记录名称。App 不读取任何登录文件或令牌。
- **Codex 覆盖项**：`--no-daemon`（会话不挂到共享后台服务，保持在 App 进程组内）、`-c notify=[...]`、`tui.notifications=true`、`tui.notification_method="osc9"`、
  `tui.notification_condition="always"` 只对本次进程生效；会覆盖你在 config.toml 中自己的 `notify`（本次进程内）。
- **Claude hooks**：`--settings <运行目录>/claude-settings.json` 中为 SessionStart、UserPromptSubmit、Pre/PostToolUse、
  PostToolUseFailure、PermissionRequest、Notification、Stop、SessionEnd 注册同一个只记录的命令；与你自己的设置合并，
  不改变权限决定。

## 证据（2026-10-07）

| 等级 | 内容 | 结果 |
|---|---|---|
| T1 | `tests/unit/test_workbench_units.py`：argv/禁用参数、TOML 覆盖项、环境去除、嵌套拒绝、二进制解析、relay 无输出且永不失败、OSC 9 分片、JSONL 增量、ANSI 尾部、跨实例单写入、交接说明 | 通过 |
| T2-W | `tests/integration/test_workbench.py`：真实 PTY/子进程/Git/SQLite + **stub CLI**；生命周期、受控终端 resize、Codex thread-id、单写入、嵌套拒绝、缺失 CLI、失败原因、`/clear` 重新绑定、Claude 权限与 Codex OSC 9、跨 harness 交接、崩溃后 reconcile 与遗留进程、路径校验 | 通过 |
| T2-W | `tests/integration/test_workbench_server.py`：令牌 cookie、Host/Origin/CSRF/Content-Type、静态资源、SSE 输出与活动、HTTP 交接草稿 | 通过 |
| UI-offline | 内置浏览器中以 stub CLI 操作：添加项目、新建 Claude 会话、终端输入、权限提示与清除、文件变更与 diff、停止后交接到 Codex、交接链与会话详情 | 通过 |
| 窗口 | pywebview 6.2.1 原生窗口以 stub CLI 启动：1440×900 窗口在屏幕上，WebKit 进程与本地服务建立连接；SIGTERM 后进程退出 | 通过（未截图：当前 shell 无屏幕录制权限） |
| 发现 | 真实 `claude --version` = 2.1.291，ChatGPT.app 内置 `codex --version` = 0.162.0-alpha.2；只运行 `--version` | 通过 |
| T3-W / T4-W | 在 App 中启动真实 Claude Code / Codex 会话、恢复、交接 | **未执行**：开发会话本身运行在 Claude Code 内，按规则不能从这里启动真实 harness；需由你在本机执行或另行授权 |

## 真实验收步骤（W4，由你在本机执行）

在普通终端（不是 agent 会话）中：

```bash
cd <harness-bridge 仓库>
uv sync --extra desktop
uv run hbridge app
```

1. 顶栏显示 Claude Code 2.1.291 与 Codex 0.162.0-alpha.2；若出现“未传递 API 变量”，确认这是你期望的。
2. 添加一个小的测试仓库，新建 Claude Code 会话：终端出现原生欢迎界面；“会话”页的原生 ID 绑定变为“已由 CLI 确认”。
3. 发一条消息、让它改一个文件：活动页出现请求/工具事件，“文件变更”出现该文件；遇到权限提示时会话显示“等待权限”。
4. 点“停止”后点“恢复”：原生 CLI 回到同一会话历史。
5. 再次停止，点“交接…”到 Codex：新 Codex 会话在同项目启动并读取说明；首轮结束后显示 thread-id。
6. 关闭窗口再打开：会话列表、交接链与最后输出仍在；可恢复。

任何一步失败，请把“会话”页的运行记录（退出码、失败原因、最后输出）发给我；这些不包含令牌。
