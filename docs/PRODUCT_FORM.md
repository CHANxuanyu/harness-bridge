# 产品形态：跨 harness 的 Advisor + Executor

_2026-10-07。本文是产品摘要，统一计划见 [PROJECT_PLAN.md](PROJECT_PLAN.md)。实际完成度以 STATUS 和验证矩阵为准。_

**Advisor 本身就是用户正在使用的一个 coding agent 会话。它领导一个或多个 Executor 会话，
这些执行会话可以运行于其他 harness。Harness Bridge 使这种主 agent / 子 agent 关系可靠工作。**

目标用户已经同时订阅 ZCode/GLM、Claude Code、Codex 等工具，希望在同一个主会话中利用这些工具，
不用自己开多个窗口传递 prompt、挑选目录、复制结果和追踪返修。

## 角色与使用形态

```text
用户 ⇄ Advisor 会话（检查 repo、拆任务、派发、审查、整合）
                 ⇅
       Bridge（任务、工作区、会话绑定、执行与证据）
          ├─ Executor 会话 A + 独立工作区 A
          └─ Executor 会话 B + 独立工作区 B
                 ↓
       整合版本 → 总目标验收 → 本地交付分支
```

| 部分 | 职责 |
|---|---|
| Advisor 会话 | 理解用户目标、检查 repo、决定任务和依赖、选择执行端、审查和协调整合 |
| Executor 会话 | 接收明确任务，在分配的工作区实现、自测、回报并按意见返修 |
| Bridge 内核 | 校验项目、锁定基线、创建工作区、指定 cwd 启动执行、管理限额/生命周期、收集真实证据 |
| Plugin / Skill | 在 Advisor 所在宿主提供派发、查看、等待、审查、返修和交付能力 |

插件是使用入口，独立本地内核承担运行机制。Bridge 不增加一个隐藏的规划模型。
代码中的 `supervisor` 对应产品中的 Advisor；角色按任务确定，不永久绑定某个厂商。

## 一次完整委派

1. 用户向当前 Advisor 描述目标和允许的工具/预算。
2. Advisor 看 repo、决定子任务和验收条件，必要时先固定共享接口或依赖。
3. Bridge 准备每个子任务的工作区和环境，从正确目录启动 Executor；用户无需替它选择文件夹。
4. Executor 运行，Bridge 保存状态、实际修改与独立检查证据，Advisor 在原会话读取并决定是否返修。
5. 子任务结果按明确版本整合，在整合版本上重新验收，生成本地交付分支。

一次子任务可以包含多次尝试；一次尝试是一个进程，返修可恢复已绑定的执行会话。
Advisor 会话结束后，V1 目标是已启动的尝试能完成并留待审查，之后由会话接续。
Bridge 不自动建立新 Advisor，也不自动开始新的子任务或修复。

## 首版工作默认

- 单用户、单机、单 Git repo，先以当前 macOS 环境验收。
- 一个 Advisor 会话；默认并发 1 个 Executor，可在授权内设为 2 个。
- 首发主路径：**Codex Astra Advisor → Claude Code Opus 5.5（难任务）+ ZCode GLM 5.3 Flash（简单任务）**。
  用户已明确此分工；ZCode Executor 尚待 P8 实现/验收，见 [路由契约](ROUTING_PROFILE.md)。
- 已有 ZCode Advisor 与 Codex Executor 保留为其他路线，不替代主路径的 Flash 执行端。
- 每个活动子任务有独立可写 worktree；依赖就绪、基线固定后才创建依赖任务的执行工作区。
- 总目标管理归属、并发和总预算；整合后的检查决定整体成功。
- 默认交付新的本地分支；不由子任务批准自动修改当前分支或触发 push/merge。

这些是工程默认规则；各项当前实现情况见下节，不把计划当作验收证据。完整边界、数据关系、故障处理、P0–P7 实施阶段、
V01–V15 验收项及新增 P8 路线都在 [项目计划书](PROJECT_PLAN.md)与其路由契约中，本摘要不再维护第二套详细路线图。

## Executor 会话与桌面历史

当前版本从指定工作区启动 Claude Code / Codex 原生 CLI 会话，保存其原生会话 ID，返修时恢复该会话。
它不通过模拟点击来操作 Executor 的聊天窗口。原生聊天记录可能按子任务工作目录归档，
Claude/Codex 的已完成会话交接与桌面历史可见性已按 P7 记录范围验收；运行中的实时交互接管不在此结论内。

用户在 Advisor 中查看子任务的 harness、工作区、状态和结果；Bridge 提供会话定位与执行证据。
ZCode Executor 的同会话桌面历史仍待 P8 验证，不能靠额外发送模型消息来制造历史条目。

## 当前做到哪里

P1–P4 本地协调、独立工作区、依赖、受管理后台执行、预算、审查、整合、精确本地交付与保留/清理已经实现。
P5 包含 Claude Code/Codex 两个原生执行端的适配与各自预算契约；P6/P7 的 alpha.6 插件已安装在实际 Codex / ZCode 中，
共享一个本地运行时与任务库，升级/卸载保留数据已经验证。

P7 真实一对二并发、Codex 原会话返修、独立整合验收与精确交付已经通过。生命周期验收发现 Codex
取消后工具子进程残留；修复已通过 732 项离线回归，获授权的原生取消复测和 Claude 轮数停止也已通过。
Claude 的原生交接、原历史/目录/侧栏已实测；用户确认 Codex 原会话页面与侧栏可见，GUI 退出/重开后历史仍在。
Codex/ZCode GUI 生命周期使用模拟 worker 按记录范围通过；其他系统、后台服务整体终止和通用后台存活未作承诺。

当前为 Apache-2.0 的实验性本地候选；已验收源码分支按用户授权推送，未创建 tag、远程 Release 或发布包。
准确证据见 [P7_CLOSEOUT.md](P7_CLOSEOUT.md)和 [P7_RESULT.md](P7_RESULT.md)；
统一范围及后续验收见 [PROJECT_PLAN.md](PROJECT_PLAN.md)。

下一阶段围绕用户的 Astra/Opus/Flash 分工补齐 ZCode Executor。P7 已完成不等于这条新主路径已经验收。
