"""Manual cross-harness handoff notes.

A handoff starts a *new* native session in the same project. The new agent receives this note and
the current code; it does not inherit the previous session's native context, and the note says so.
The note is built only from what the App observed plus the user's own progress text.
"""

from __future__ import annotations

from typing import Any

from harness_bridge.workbench.harness import LABELS

MAX_PROMPTS = 5
MAX_ACTIVITY = 15
MAX_FILES = 40

_STATUS = {
    "starting": "启动中",
    "running": "运行中",
    "exited": "已正常退出",
    "failed": "失败",
    "stopped": "已由用户停止",
    "interrupted": "已中断（App 退出）",
}


def run_summary(run: dict[str, Any] | None) -> str:
    if run is None:
        return "尚未运行"
    text = _STATUS.get(run["status"], str(run["status"]))
    if run.get("exit_code") is not None:
        text += f"，退出码 {run['exit_code']}"
    if run.get("exit_signal") is not None:
        text += f"，信号 {run['exit_signal']}"
    return text


def _activity_line(event: dict[str, Any]) -> str | None:
    p = event["payload"]
    name = p.get("event")
    if p.get("source") == "claude-hook" and name in ("PreToolUse", "PostToolUseFailure"):
        line = f"{p.get('tool_name') or '工具'}: {p.get('summary') or ''}".strip()
        return line + ("（失败）" if name == "PostToolUseFailure" else "")
    if p.get("source") == "codex-notify" and p.get("message"):
        return f"Codex 一轮完成：{p['message']}"
    return None


def draft(
    *,
    project: dict[str, Any],
    session: dict[str, Any],
    target_harness: str,
    last_run: dict[str, Any] | None,
    events: list[dict[str, Any]],
    git_status: dict[str, Any],
    diffstat: str,
    progress: str = "",
) -> str:
    prompts = [
        e["payload"]["prompt"]
        for e in events
        if e["kind"] == "activity" and e["payload"].get("prompt")
    ][-MAX_PROMPTS:]
    activity = [line for line in map(_activity_line, events) if line][-MAX_ACTIVITY:]
    source = LABELS.get(session["harness"], session["harness"])
    target = LABELS.get(target_harness, target_harness)
    out = [
        "# 会话交接说明（RepoBridge）",
        "",
        f"你正在接手同一项目中另一个 coding agent 会话（{source}）的工作，当前使用 {target}。",
        "这是一次人工交接：你没有上一会话的原生上下文，只有这份说明和当前代码。",
        "请先阅读相关代码并用 `git status` / `git diff` 核实进度；说明与代码不一致时以代码为准，",
        "并告诉用户。开始动手前，用一两句话说明你核实到的进度和打算的下一步。",
        "",
        "## 项目",
        f"- 名称：{project['name']}",
        f"- 工作目录：{session['workdir']}",
    ]
    if git_status.get("git"):
        head = (git_status.get("head") or "（无提交）")[:12]
        out.append(f"- 分支：{git_status.get('branch') or '（detached）'} · HEAD：{head}")
    out += [
        "",
        "## 上一会话",
        f"- Harness：{source}",
        f"- 标题：{session['title']}",
        f"- 原生会话 ID：{session.get('native_session_id') or '未知'}"
        "（仍由原 CLI 保存；本会话不会继承其上下文）",
        f"- 最后状态：{run_summary(last_run)}",
        "",
        "## 进度与下一步（用户填写）",
        progress.strip() or "（用户未填写）",
        "",
        "## 上一会话最近的用户请求（App 观察到的）",
    ]
    out += [f"{i}. {p}" for i, p in enumerate(prompts, 1)] or ["（未观察到）"]
    out += ["", "## 上一会话最近的执行活动（App 观察到的）"]
    out += [f"- {line}" for line in activity] or ["（未观察到）"]
    out += ["", "## 当前未提交的变更"]
    files = git_status.get("files") or []
    if not git_status.get("git"):
        out.append("（工作目录不是 Git 仓库）")
    elif not files:
        out.append("（没有未提交的变更）")
    else:
        out += [f"- {f['kind']}: {f['path']}" for f in files[:MAX_FILES]]
        if len(files) > MAX_FILES:
            out.append(f"- …另有 {len(files) - MAX_FILES} 个文件")
        if diffstat:
            out += ["", "```", diffstat, "```"]
    return "\n".join(out).rstrip() + "\n"
