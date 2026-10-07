# 首发路线：Astra Advisor + Opus / GLM Flash Executors

_2026-10-07。用户明确选择的产品主路径；P8 实施契约，尚不是已通过的整条路线。_

## 固定角色

| 角色 | 宿主与模型 | 工作 |
|---|---|---|
| Advisor | Codex · Astra | 检查 repo、拆任务、判断难度与依赖、派发、审查、决定返修/升级、整合和最终验收 |
| 复杂任务 Executor | Claude Code · Opus 5.5 | 不确定性高、跨模块、架构变更、疑难故障等任务 |
| 简单任务 Executor | ZCode · GLM 5.3 Flash | 接口已定、范围明确、可独立验收的局部实现和机械性修改 |

用户始终与同一个 Codex Astra 会话合作。该会话就是 Advisor；Bridge 不另开一个规划 agent，
不直接调用模型 API。已有 Codex Executor 与 ZCode Advisor 功能保留为其他路线，不占据本路线的主位置。
本轮确认产品分工，不变更当前宿主会话的模型设置，也不续发已消耗的真实执行额度。

模型标识与证据必须分开：Codex 工具目录列出 `gpt-6-astra`；此前真实 Claude 记录观察到
`claude-opus-5-5`；本机 ZCode 0.16.9 静态目录使用 `GLM-5.3-Flash`。
ZCode 的账号可用模型、实际 provider/套餐路径和会话所选模型仍须通过原生元数据核对。
仅有显示名称不够；不能用通用 `opus`、默认模型、GLM 非 Flash 或 FlashX 静默代替用户的选择。
Advisor 的实际模型由 Codex 宿主决定，Bridge 的角色标签不证明当前会话已在使用 Astra。

## 任务如何分配

难度由 Advisor 依据 repo 和任务判断，不由 Bridge 增加一次“模型路由”推理，也不按改动行数机械分级。

| 判据 | 默认交给 |
|---|---|
| 已有明确接口/模式，改动局限，依赖固定，可写出直接验收方法 | GLM 5.3 Flash |
| 根因未知、需要方案取舍、涉及多个模块/兼容契约/并发，或局部改动有较大影响 | Opus 5.5 |
| 信息不足以拆分或验收 | Astra 先调查、澄清或拆小，再派发 |

例子：已定字段的参数接线、既有模式下的文档同步、明确回归案例的补充可以给 Flash；
设计序列化兼容契约、定位取消进程残留、修改恢复状态机可以给 Opus。测试任务也可能很复杂，
不能仅因为是“补测试”就默认给 Flash。以上是用户偏好的工作分工，不是模型质量/成本对比结论。

每个子任务冻结执行 harness、精确模型选择、选择理由、可改范围、依赖基线、检查方法和预算。
路由说明可以先放在现有任务上下文中；新增机器可校验字段必须另行实现兼容与测试，不能往当前严格 schema
随意加键。并发只用于独立、范围不冲突的就绪任务；有依赖则等待已批准快照。

## 反馈、返修与升级

1. Bridge 在任务自己的 worktree/cwd 中启动 Executor；用户无需新建项目或选择文件夹。
2. Executor 的完成自述只作为输入。Astra 读取实际 diff 与独立检查证据后决定是否批准。
3. 需要返修且预算允许时，恢复相同 harness 的原生会话和原工作区，计入同一目标的尝试/返修限额。
4. Flash 任务暴露复杂性或检查失败后，Astra 判断继续定向返修、缩小范围或升级给 Opus；不自动无限重试。
5. 跨 harness 升级是显式的新任务/会话。确认旧执行退出，审查并固定可转交的工作快照，传递失败证据和剩余工作；
   不把 GLM 的 session ID 交给 Claude，不修改原任务冻结模型，也不让两个执行者写同一目录。
6. 升级继续受总目标预算和已授权执行端约束；只有确实超出授权时才追加询问。
7. Astra 审查整合版本，整体检查通过后交付明确分支/提交；两个子任务通过不代替总目标验收。

**当前升级边界：**冻结计划前可以重新分配；正确批准的子任务后，可以新增依赖它的 Opus 子任务。
但“失败、未批准的 Flash 子任务 → Opus 接管其部分成果”仍缺少任务替代与快照交接契约。
现有引擎要求每个目标子任务都批准才能整合，不能删掉失败子任务、虚假批准或新建目标重置预算。
这是 P8 必须补齐的能力；当前模板会如实报告，不把规划当作已支持的自动升级。

Opus/Flash 不承担最终验收权，也不自行跨 harness 再委派。推送/合并继续遵循用户对当前项目的授权。
本项目源码推送已获批准；这不把远程发布或新模型调用变成默认动作。

## 当前差距与 P8 顺序

P7 已验收 Codex Advisor → Claude Code/Codex Executors 的记录范围，源码 `113b0a7` 已推送。
这个结果保留，不改写成 Astra → Opus + Flash 的验收。首发主路径尚未闭环。

| 项目 | 当前状态与下一步 |
|---|---|
| P8.0 路线与接口发现 | 本文固定分工；已运行本机无推理 help 并只读检查 ZCode 安装包 |
| P8.1 原生契约与启动前检查 | 已检查账号界面与隔离原生空会话；确认初始化回调，保留权限返回不匹配和空会话恢复失败；有效隔离、认证执行与桌面仍待核对 |
| P8.2 ZCode adapter | 离线 profile revision2 支持 Start Plan、绑定初始化回调、原会话返修、预算/取消/独立验收；真实入口保持关闭 |
| P8.3 Advisor 路由与交接 | 源码插件 alpha.7 已有难度记录和严格目标/子任务模板；未批准任务的跨 harness 替代尚待实现，已安装 alpha.6 不变 |
| P8.4 目标路线真实验收 | 准备具体任务、模型/权限/预算和停止条件后，按新有界授权运行 Astra → Opus + Flash；验证双方原历史与桌面入口 |

P8 的通过标准：同一个 Astra Advisor 会话派发一个困难子任务给 Opus 5.5、一个简单子任务给
GLM 5.3 Flash；两者执行模型和账号来源可核对、工作区正确、结果回到 Advisor；至少一个有界原会话返修；
整体独立检查与精确交付通过；原生会话可在桌面定位。另以离线证据覆盖错误模型、未知退出、重复派发、
过期 Advisor、预算拒绝、权限拒绝和显式升级。声明/实测/未支持必须分别报告。

## ZCode 0.16.9 的零推理发现

P8.0 只运行 `zcode --help` / `app-server --help`，并检查已安装 bundle 的协议符号与内置模型目录。
随后 P8.1 在隔离 HOME/数据目录中启动原生 stdio 服务器，只查询 `runtime/capabilities`，收到
`independentPlanState: true` 后关闭连接并确认退出。没有创建原生会话、发送 prompt、读取凭据或改全局配置。
探针前两次的缺失配置和 socket 路径过长失败保留；成功查询不把会话执行和权限行为变成已验证。
见 [脱敏探针记录](ZCODE_PROTOCOL_PROBE.json)、[适配器契约](ZCODE_EXECUTOR.md)和[验收记录](VALIDATION_MATRIX.md)。

- CLI help 提供 `--cwd`、`--resume`、`--surface`、`--mode`、`--json` 和 `app-server`。
- **`--prompt` 的默认权限模式是 `yolo`。** 适配必须显式选择并验证受限模式，不能采用默认放权。
- 顶层 help 未提供单次 `--model` 参数；安装包存在 `session/create` 的初始 model 字段以及
  `session/setModel`、`session/setMode`、`session/read`、`session/events`、`session/send`、`session/stop` 等方法名。
  原生协议是优先调查路径；符号存在不代表参数契约、限制和安全行为已经验证。
- 内置规范名是 `GLM-5.3-Flash`。账号模型可用性、provider ID 与只用既有套餐的来源检查仍待 P8.1。
- 预算继承“按 harness 能力区分”的用户决定：内部轮数硬上限若不可验证，就明确不支持，采用执行次数、
  强制墙钟超时和取消；不得从输出或日志猜测内部调用次数。
- 不因单次 CLI 能输出文字就宣告适配完成。会话绑定、失败处理、取消、返修、独立检查与桌面历史都属于交付范围。

本机 bundle SHA-256：`fad4c35c4c36ec210d8a06d3fa0e77de23c8545e2eb6ff90aea1eb38d1e6275f`。
私有探针记录在接管会话的 `work/p8-routing-discovery/`；不把整份厂商 bundle 或用户配置放进 public repo。
后续协议探针记录在 `work/p8-protocol-probe/`。离线模拟输出与原生探针分别标注来源。
空会话与界面核对记录在 `work/p8-native-contract/`，公开结论见
[ZCode 原生接入检查](ZCODE_NATIVE_PREFLIGHT.md)。Start Plan 与 Coding Plan 必须分开选择；
界面可用性不证明 Bridge 子进程已绑定同一账号或额度来源。
官方资料确认账号连接可使用 GLM-5.3-Flash 和既有 Coding Plan，具体账号授权仍以原生结果为准：
[ZCode 模型与套餐](https://zcode.z.ai/cn/docs/configuration)。
