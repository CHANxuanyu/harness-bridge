"""Per-session model, reasoning-effort and permission-mode controls.

Options come only from the harness itself:

* Claude Code: the ``initialize`` control response (``models`` with ``supportedEffortLevels``),
  changed with the ``set_model`` / ``apply_flag_settings`` (``effortLevel``) /
  ``set_permission_mode`` control requests and confirmed with ``get_settings`` (``applied``) and
  the echoed mode.
* Codex: ``model/list`` (``supportedReasoningEfforts``), ``configRequirements/read`` (allowed
  approval policies and sandbox modes), applied as ``thread/start`` / ``thread/resume`` /
  ``turn/start`` parameters and confirmed with ``thread/read`` (model, effort) and the
  ``thread/resume`` result (approval policy, sandbox).

A choice is only *confirmed* when the harness reports it back. A rejected choice is recorded as
failed with the harness's reason and the previous value stays in force; nothing is silently
replaced by another model, effort or mode.

Two modes are deliberately not offered (they remove all approval): Claude Code
``bypassPermissions`` and Codex full access (``never`` + ``danger-full-access``). When the
harness's own configuration already runs a session that way, the selector shows it as the
current mode, read-only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from harness_bridge.workbench.harness import CLAUDE, CODEX

FIELDS = ("model", "effort", "mode")
STATES = ("default", "selected", "applying", "confirmed", "failed")

EFFORT_LABELS = {
    "none": "关闭",
    "minimal": "最低",
    "low": "低",
    "medium": "中",
    "high": "高",
    "xhigh": "很高",
    "max": "最高",
    "ultra": "极高",
}

CLAUDE_MODES: list[dict[str, Any]] = [
    {
        "id": "default",
        "label": "需要时询问",
        "description": "编辑文件、运行命令等操作前先问你（Claude Code 的默认模式）",
    },
    {
        "id": "acceptEdits",
        "label": "自动接受编辑",
        "description": "文件编辑直接执行；其他需要确认的操作仍会询问",
    },
    {
        "id": "plan",
        "label": "计划模式",
        "description": "只读分析并给出计划，不修改文件；你批准计划后才执行",
    },
    {
        "id": "auto",
        "label": "自动模式",
        "description": "由 Claude Code 的安全审查决定是否放行；仅部分模型支持",
        "needs": "auto_mode",
    },
    {
        "id": "dontAsk",
        "label": "不询问",
        "description": "未预先允许的操作一律拒绝，不弹出确认",
    },
]
CLAUDE_NOT_OFFERED = {"bypassPermissions": "跳过所有权限检查"}

CODEX_MODES: list[dict[str, Any]] = [
    {
        "id": "read-only",
        "label": "只读",
        "description": "可以读取文件、回答问题；修改文件或运行越界命令需要审批",
        "approval": "on-request",
        "sandbox_mode": "read-only",
        "sandbox": {"type": "readOnly"},
    },
    {
        "id": "workspace",
        "label": "工作区可写",
        "description": "可以在项目内修改文件、运行命令；越出工作区或联网需要审批",
        "approval": "on-request",
        "sandbox_mode": "workspace-write",
        "sandbox": {"type": "workspaceWrite"},
    },
]
CODEX_MODE_BY_ID = {m["id"]: m for m in CODEX_MODES}


def effort_label(level: str | None) -> str:
    if not level:
        return "默认"
    return EFFORT_LABELS.get(level, level)


# --- catalogs ----------------------------------------------------------------------------------


def claude_catalog(init: Mapping[str, Any], *, cli_version: str | None) -> dict[str, Any]:
    """Normalise Claude Code's ``initialize`` response (only what the selectors need)."""
    models = []
    for raw in init.get("models") or []:
        if not isinstance(raw, dict) or not isinstance(raw.get("value"), str):
            continue
        levels = raw.get("supportedEffortLevels") if raw.get("supportsEffort") else None
        models.append(
            {
                "id": raw["value"],
                "label": str(raw.get("displayName") or raw["value"]),
                "description": str(raw.get("description") or ""),
                "resolved": raw.get("resolvedModel"),
                "efforts": [str(x) for x in levels] if isinstance(levels, list) else [],
                "effort_descriptions": {},
                "default_effort": None,
                "auto_mode": bool(raw.get("supportsAutoMode")),
                "images": True,
                "disabled": bool(raw.get("disabled")),
            }
        )
    commands = []
    for raw in init.get("commands") or []:
        if isinstance(raw, dict) and isinstance(raw.get("name"), str):
            commands.append(
                {
                    "name": raw["name"],
                    "description": str(raw.get("description") or "")[:200],
                    "hint": str(raw.get("argumentHint") or "")[:80],
                }
            )
    return {
        "harness": CLAUDE,
        "source": "initialize",
        "cli_version": cli_version,
        "models": models,
        "default_model": "default" if any(m["id"] == "default" for m in models) else None,
        "modes": [dict(m) for m in CLAUDE_MODES],
        "default_mode": "default",
        "commands": commands[:200],
        "requirements": None,
        "error": None,
    }


def codex_catalog(
    model_list: list[Mapping[str, Any]],
    requirements: Mapping[str, Any] | None,
    *,
    cli_version: str | None,
) -> dict[str, Any]:
    """Normalise Codex ``model/list`` and ``configRequirements/read`` results."""
    models = []
    default = None
    for raw in model_list:
        if not isinstance(raw, dict) or raw.get("hidden") or not isinstance(raw.get("id"), str):
            continue
        options = [o for o in raw.get("supportedReasoningEfforts") or [] if isinstance(o, dict)]
        models.append(
            {
                "id": raw["id"],
                "label": str(raw.get("displayName") or raw["id"]),
                "description": str(raw.get("description") or ""),
                "resolved": raw.get("model"),
                "efforts": [str(o.get("reasoningEffort")) for o in options],
                "effort_descriptions": {
                    str(o.get("reasoningEffort")): str(o.get("description") or "") for o in options
                },
                "default_effort": raw.get("defaultReasoningEffort"),
                "auto_mode": False,
                "images": "image" in (raw.get("inputModalities") or ["text", "image"]),
                "disabled": False,
            }
        )
        if raw.get("isDefault"):
            default = raw["id"]
    req = dict(requirements or {})
    allowed_approval = req.get("allowedApprovalPolicies")
    allowed_sandbox = req.get("allowedSandboxModes")
    modes = []
    for mode in CODEX_MODES:
        reason = None
        if isinstance(allowed_approval, list) and mode["approval"] not in allowed_approval:
            reason = "组织策略不允许这种审批方式"
        if isinstance(allowed_sandbox, list) and mode["sandbox_mode"] not in allowed_sandbox:
            reason = "组织策略不允许这种沙箱"
        modes.append({**mode, "available": reason is None, "reason": reason})
    return {
        "harness": CODEX,
        "source": "model/list",
        "cli_version": cli_version,
        "models": models,
        "default_model": default,
        "modes": modes,
        "default_mode": None,
        "commands": [],
        "requirements": {
            "allowed_approval": allowed_approval,
            "allowed_sandbox": allowed_sandbox,
        }
        if requirements
        else None,
        "error": None,
    }


def find_model(catalog: Mapping[str, Any] | None, model: str | None) -> dict[str, Any] | None:
    if not catalog or not model:
        return None
    for entry in catalog.get("models") or []:
        if model in (entry["id"], entry.get("resolved")):
            return dict(entry)
    return None


def mode_options(catalog: Mapping[str, Any] | None, model: str | None) -> list[dict[str, Any]]:
    """Modes with availability for the given (chosen or current) model."""
    if not catalog:
        return []
    entry = find_model(catalog, model) if model else None
    out = []
    for mode in catalog.get("modes") or []:
        item = {k: v for k, v in mode.items() if k != "needs"}
        item.setdefault("available", True)
        item.setdefault("reason", None)
        if mode.get("needs") == "auto_mode" and entry is not None and not entry["auto_mode"]:
            item["available"] = False
            item["reason"] = "当前模型不支持自动模式"
        elif mode.get("needs") == "auto_mode" and entry is None:
            supported = any(m["auto_mode"] for m in catalog.get("models") or [])
            if not supported:
                item["available"] = False
                item["reason"] = "这个账号的模型目录中没有支持自动模式的模型"
        out.append(item)
    return out


# --- choices -----------------------------------------------------------------------------------


def blank_settings() -> dict[str, Any]:
    return {"chosen": {}, "fields": {}, "actual": {}, "notices": []}


def normalise(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    out = blank_settings()
    if isinstance(raw, Mapping):
        for key in out:
            value = raw.get(key)
            if isinstance(value, type(out[key])):
                out[key] = value
        for key in ("turn_model",):
            if key in raw:
                out[key] = raw[key]
    return out


class ChoiceError(ValueError):
    pass


def validate_choice(
    catalog: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    changes: Mapping[str, Any],
    *,
    harness: str,
) -> tuple[dict[str, Any], list[str]]:
    """Return the new ``chosen`` mapping and notices; raise ChoiceError on an invalid choice.

    ``None`` for a field means "the harness's own default".
    """
    if not catalog or not catalog.get("models"):
        raise ChoiceError("还没有取得这个 CLI 的模型目录；连接后或刷新目录后再选择")
    chosen = dict(current.get("chosen") or {})
    notices: list[str] = []
    for key, value in changes.items():
        if key not in FIELDS:
            raise ChoiceError(f"未知设置 {key!r}")
        if value is not None and not isinstance(value, str):
            raise ChoiceError(f"{key} 必须是字符串")
    if "model" in changes:
        model = changes["model"]
        if model is None:
            chosen.pop("model", None)
        else:
            entry = find_model(catalog, model)
            if entry is None:
                raise ChoiceError(f"模型 {model} 不在当前 CLI 提供的目录中")
            if entry["disabled"]:
                raise ChoiceError(f"模型 {entry['label']} 当前不可选：{entry['description']}")
            chosen["model"] = entry["id"]
    model_now = chosen.get("model") or (current.get("actual") or {}).get("model")
    entry = find_model(catalog, model_now) if model_now else None
    if "effort" in changes:
        effort = changes["effort"]
        if effort is None:
            chosen.pop("effort", None)
        else:
            if entry is not None and effort not in entry["efforts"]:
                if not entry["efforts"]:
                    raise ChoiceError(f"{entry['label']} 不支持调整思考强度")
                raise ChoiceError(
                    f"{entry['label']} 支持的思考强度是 "
                    + "、".join(effort_label(e) for e in entry["efforts"])
                )
            chosen["effort"] = effort
    elif "model" in changes and chosen.get("effort") and entry is not None:
        # A new model may not offer the effort chosen for the old one: say so, do not guess.
        if chosen["effort"] not in entry["efforts"]:
            old = chosen.pop("effort")
            notices.append(
                f"{entry['label']} 不支持思考强度「{effort_label(old)}」，已改回该模型的默认强度"
            )
    elif "model" in changes and entry is not None and harness == CODEX:
        # Codex keeps the thread's effort across a model change; if the new model does not
        # offer it, ask for the model's own default explicitly instead of sending a bad pair.
        in_force = (current.get("actual") or {}).get("effort")
        default = entry.get("default_effort")
        if in_force and entry["efforts"] and in_force not in entry["efforts"] and default:
            chosen["effort"] = default
            notices.append(
                f"{entry['label']} 不支持当前的思考强度「{effort_label(in_force)}」，"
                f"将改用它的默认强度「{effort_label(default)}」"
            )
    if "mode" in changes:
        mode = changes["mode"]
        if mode is None:
            chosen.pop("mode", None)
        else:
            options = {m["id"]: m for m in mode_options(catalog, model_now)}
            if mode not in options:
                if harness == CLAUDE and mode in CLAUDE_NOT_OFFERED:
                    raise ChoiceError("RepoBridge 不提供跳过所有权限检查的模式")
                raise ChoiceError(f"未知权限模式 {mode!r}")
            if not options[mode]["available"]:
                raise ChoiceError(options[mode]["reason"] or "这个模式当前不可用")
            chosen["mode"] = mode
    elif "model" in changes and chosen.get("mode") == "auto" and entry is not None:
        if not entry["auto_mode"]:
            chosen.pop("mode")
            notices.append(f"{entry['label']} 不支持自动模式，权限模式已改回默认")
    return chosen, notices


# --- confirmation ------------------------------------------------------------------------------


def model_matches(catalog: Mapping[str, Any] | None, chosen: str, actual: str | None) -> bool:
    if not actual:
        return False
    if chosen == actual:
        return True
    entry = find_model(catalog, chosen)
    if entry is None:
        return False
    resolved = entry.get("resolved")
    if resolved and (actual == resolved or _strip_suffix(actual) == _strip_suffix(resolved)):
        return True
    # "default" follows whatever the harness resolves it to.
    return chosen == "default"


def _strip_suffix(model: str) -> str:
    return model.split("[", 1)[0]


def codex_mode_of(approval: Any, sandbox: Any) -> str | None:
    """Map a Codex approval policy + sandbox back to a RepoBridge mode id (None = other)."""
    stype = sandbox.get("type") if isinstance(sandbox, dict) else sandbox
    for mode in CODEX_MODES:
        if approval == mode["approval"] and stype in (
            mode["sandbox"]["type"],
            mode["sandbox_mode"],
        ):
            return str(mode["id"])
    return None


def describe_codex_mode(approval: Any, sandbox: Any) -> str:
    mode = codex_mode_of(approval, sandbox)
    if mode:
        return str(CODEX_MODE_BY_ID[mode]["label"])
    stype = sandbox.get("type") if isinstance(sandbox, dict) else sandbox
    if approval == "never" and stype in ("dangerFullAccess", "danger-full-access"):
        return "完全访问（来自 Codex 配置）"
    approval_text = approval if isinstance(approval, str) else "自定义审批"
    return f"其他：approval={approval_text}，sandbox={stype}"


def claude_mode_label(mode: str | None) -> str:
    for item in CLAUDE_MODES:
        if item["id"] == mode:
            return str(item["label"])
    if mode in CLAUDE_NOT_OFFERED:
        return f"{CLAUDE_NOT_OFFERED[mode]}（来自 Claude Code 设置）"
    return mode or "未知"
