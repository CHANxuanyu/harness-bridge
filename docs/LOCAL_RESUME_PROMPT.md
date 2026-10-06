# 本地继续开发时的启动指令

使用前提：已经取得 Cloud 的真实代码与交接文件，位于它实际推送的仓库/分支。下面的指令用于继续开发项目，**不自动授权真实模型调用或额外付费**。

---

继续 Harness Bridge 项目。先读取 AGENTS.md、CLAUDE.md、STATUS.md、HANDOFF.md、docs/LOCAL_HANDOFF.md 和 docs/VALIDATION_MATRIX.md；只在需要时回查 docs/CLOUD_EXECUTION_PLAN.md。

先核对当前仓库、branch、last verified commit、dirty state 和本地工具版本，不覆盖我的未提交修改。不要重新从零设计，也不要因没有 Cloud 对话记录就认为无法继续。

复用已完成的 Linux/macOS 离线检查、demos、T3/T4 smoke 和受控 repair/resume 记录，不因接管或换会话重复测试。只针对新增修改、真实失败或未解疑点运行必要检查；未实现项与已验证项如实区分。直接用当前本地工具推进，不让我在多个 agent 之间传递指令。

根据 HANDOFF 里的下一个有限工作包继续实现。优先修复真实复现的问题，然后补齐 Claude CLI adapter 的纯函数/协议测试。开发仍使用我当前选择的模型；Claude executor 的目标模型保持 Opus 5.5，不主动改成其他模型。

默认不运行真实 Claude/Codex 推理、不申请 API key、不启用额外付费、不读取或搬运 OAuth 凭据。先完成 non-inference doctor 与 live preflight，明确报告安装版本、模型配置、认证方式是否可确认、所需权限，以及真实测试预计会使用哪个已有订阅。

只有我明确授权本轮真实模型使用后，才在新的小型 disposable fixture 中执行约定的有限验证。初次执行与受控 repair/resume 已通过（docs/LIVE_REPAIR_RESULT.md），下一项缺口是真实中断/超时，不重复已完成层级。每提高一层验证等级都保留真实记录；当前 Codex 已能直接启动 bridge、审查并批准，无需默认退回用户终端。

不要默认加 --bare；先核对当前官方文档与本地版本的订阅认证兼容性。不要用 --dangerously-skip-permissions、禁用嵌套保护或无限制 shell 来让 demo 过关。API/provider 配置或额外用量状态不明时，暂停真实 dispatch，不改动我的全局登录配置。

每完成一个工作包，更新状态与交接、运行相关测试并提交。是否 push 以我当前这次本地会话的授权为准；Cloud 阶段的上传授权不被扩展为所有未来远程操作。
