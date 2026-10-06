# 本地继续开发时的启动指令

使用前提：已经取得 Cloud 的真实代码与交接文件，位于它实际推送的仓库/分支。下面的指令用于继续开发项目，**不自动授权真实模型调用或额外付费**。

---

继续 Harness Bridge 项目。先读取 AGENTS.md、CLAUDE.md、STATUS.md、HANDOFF.md、docs/LOCAL_HANDOFF.md 和 docs/VALIDATION_MATRIX.md；只在需要时回查 docs/CLOUD_EXECUTION_PLAN.md。

先核对当前仓库、branch、last verified commit、dirty state 和本地工具版本，不覆盖我的未提交修改。不要重新从零设计，也不要因没有 Cloud 对话记录就认为无法继续。

先用本地临时状态目录与 fixture repo，复现 Cloud 实际声称通过的离线检查、success demo 和 bug-then-repair demo。若某项根本尚未实现，如实区分，不把文档中的拟定命令当成已存在功能。macOS 的进程管理、路径、worktree 和 SQLite 行为需要本地重新验证。

根据 HANDOFF 里的下一个有限工作包继续实现。优先修复真实复现的问题，然后补齐 Claude CLI adapter 的纯函数/协议测试。开发仍使用我当前选择的模型；Claude executor 的目标模型保持 Opus 5.5，不主动改成其他模型。

默认不运行真实 Claude/Codex 推理、不申请 API key、不启用额外付费、不读取或搬运 OAuth 凭据。先完成 non-inference doctor 与 live preflight，明确报告安装版本、模型配置、认证方式是否可确认、所需权限，以及真实测试预计会使用哪个已有订阅。

只有我明确授权本轮真实模型使用后，才在小型 disposable fixture repo 中做一个受限 Claude smoke test；先验证真实单 harness，再验证受控 resume，最后测试当前 Codex/Astra 通过 bridge 下发和 review。每提高一层验证等级，都必须有真实记录。由用户另一个终端执行的路径标作 manual handoff，不当成已经证明 Codex 自动启动。

不要默认加 --bare；先核对当前官方文档与本地版本的订阅认证兼容性。不要用 --dangerously-skip-permissions、禁用嵌套保护或无限制 shell 来让 demo 过关。API/provider 配置或额外用量状态不明时，暂停真实 dispatch，不改动我的全局登录配置。

每完成一个工作包，更新状态与交接、运行相关测试并提交。是否 push 以我当前这次本地会话的授权为准；Cloud 阶段的上传授权不被扩展为所有未来远程操作。
