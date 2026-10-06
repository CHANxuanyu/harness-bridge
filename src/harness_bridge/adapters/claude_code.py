"""Claude Code CLI adapter (``claude -p --output-format stream-json``).

Status: offline contract tests plus bounded local live initial-run and controlled repair/resume
evidence (docs/VALIDATION_MATRIX.md). Historical smoke results do not certify a different local
installation, turn-limit enforcement, or live interruption/timeout behaviour. Each live run still
requires the local preflight and explicit authorization (docs/LOCAL_HANDOFF.md).

Design rules:
* ``build_invocation`` is pure: no process, no network, no file access.
* The task text goes to stdin, never into argv. No shell.
* Exact model pin (``--model claude-opus-5-5``), bounded turns, explicit ``--resume <id>`` only
  for a session id previously observed for this task/worktree. ``--continue`` is never used.
* Never ``--bare`` (it ignores subscription OAuth), never ``--dangerously-skip-permissions`` or
  ``bypassPermissions``, never unrestricted Bash auto-approval.
* Stream parsing keeps metadata only (types, ids, model, usage, final result text); assistant
  content and thinking blocks are not stored.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from harness_bridge.adapters.base import (
    ExecutorResult,
    InvocationContext,
    InvocationSpec,
    ParsedEvent,
    TaskPacket,
    classify_process_level,
    protocol_summary,
)
from harness_bridge.errors import BridgeError
from harness_bridge.models import mock_usage
from harness_bridge.policy import redact_text
from harness_bridge.runner import ProcessOutcome
from harness_bridge.state import AttemptOutcome

FORBIDDEN_FLAGS = (
    "--bare",
    "--dangerously-skip-permissions",
    "--allow-dangerously-skip-permissions",
    "--continue",
    "-c",
    "--fork-session",
    "--no-session-persistence",
)
FORBIDDEN_VALUES = ("bypassPermissions",)

# Official documentation evidence for the flags this adapter uses. The CLI reference states:
# "`claude --help` does not list every flag, so a flag's absence from `--help` does not mean it
# is unavailable." Documentation is a declaration, not proof for a given installation; local
# confirmation (or the CLI rejecting a flag at run time) is separate evidence.
CLI_REFERENCE_URL = "https://code.claude.com/docs/en/cli-reference"
CLI_REFERENCE_CHECKED = "2026-10-06"
DOCUMENTED_FLAGS = frozenset(
    {
        "-p",
        "--print",
        "--output-format",
        "--verbose",
        "--model",
        "--max-turns",
        "--permission-mode",
        "--allowedTools",
        "--allowed-tools",
        "--strict-mcp-config",
        "--resume",
        "-r",
    }
)
_REJECTED_ARGUMENT = (
    re.compile(r"(?i)unknown option:?\s*['\"`]?(-{1,2}[A-Za-z][\w-]*)"),
    re.compile(r"(?i)unrecognized (?:option|argument)s?:?\s*['\"`]?(-{1,2}[A-Za-z][\w-]*)"),
    re.compile(r"(?i)invalid option:?\s*['\"`]?(-{1,2}[A-Za-z][\w-]*)"),
)

# Text patterns that *suggest* a provider-side problem. Matching them only yields a heuristic
# classification; reset times are never inferred from text.
_PROVIDER_PATTERNS = (
    ("rate_limit", re.compile(r"(?i)\brate[ _-]?limit|\b429\b|too many requests")),
    ("usage_limit", re.compile(r"(?i)usage limit|quota|limit (?:reached|exceeded)")),
    ("overloaded", re.compile(r"(?i)overloaded|\b529\b")),
    (
        "auth",
        re.compile(r"(?i)invalid api key|please run /login|not logged in|unauthori[sz]ed|\b401\b"),
    ),
    ("resume", re.compile(r"(?i)no conversation found|session .* not found")),
)


@dataclass(frozen=True)
class ClaudeSettings:
    requested_model: str | None
    max_turns: int
    permission_mode: str
    allowed_tools: tuple[str, ...]
    strict_mcp_config: bool


class ClaudeCodeAdapter:
    kind = "claude-code"

    def __init__(self, settings: ClaudeSettings) -> None:
        self.settings = settings
        self._resume_requested: str | None = None

    def describe_capabilities(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "modes": ["live (gated)", "mock with --stub-binary (contract tests)"],
            "evidence": "offline contract tests and captured-live-redacted samples; bounded "
            "initial and repair/resume run records in docs/VALIDATION_MATRIX.md, "
            "not a certification of the current local configuration",
            "flags_used": self.flags_used(resume=True),
        }

    def flags_used(self, *, resume: bool) -> list[str]:
        flags = ["-p", "--output-format", "--verbose", "--max-turns", "--permission-mode"]
        if self.settings.requested_model:
            flags.append("--model")
        if self.settings.allowed_tools:
            flags.append("--allowedTools")
        if self.settings.strict_mcp_config:
            flags.append("--strict-mcp-config")
        if resume:
            flags.append("--resume")
        return flags

    # -- launch ---------------------------------------------------------------------------------

    def build_invocation(self, packet: TaskPacket, ctx: InvocationContext) -> InvocationSpec:
        if not ctx.executor_binary or not os.path.isabs(ctx.executor_binary):
            raise BridgeError("PREFLIGHT_FAILED", "claude executable path must be absolute")
        s = self.settings
        argv = [ctx.executor_binary, "-p", "--output-format", "stream-json", "--verbose"]
        if s.requested_model:
            argv += ["--model", s.requested_model]
        argv += ["--max-turns", str(s.max_turns), "--permission-mode", s.permission_mode]
        if s.allowed_tools:
            for tool in s.allowed_tools:
                if "," in tool:
                    raise BridgeError(
                        "INVALID_INPUT", f"allowed tool {tool!r} must not contain a comma"
                    )
            argv += ["--allowedTools", ",".join(s.allowed_tools)]
        if s.strict_mcp_config:
            argv.append("--strict-mcp-config")
        notes = []
        self._resume_requested = ctx.resume_session_id
        if ctx.resume_session_id:
            argv += ["--resume", ctx.resume_session_id]
            notes.append("resuming a session id previously observed for this task/worktree")
        elif packet.attempt_kind == "repair":
            notes.append("no verified session to resume; this repair starts a new session")
        check_forbidden(argv)
        env = dict(ctx.base_env)
        return InvocationSpec(
            argv=argv,
            cwd=ctx.worktree,
            stdin=packet.render_prompt().encode("utf-8"),
            env=env,
            requested_model=s.requested_model,
            resume_session_id=ctx.resume_session_id,
            notes=notes,
        )

    # -- stream parsing -------------------------------------------------------------------------

    def parse_event(self, raw_line: bytes) -> ParsedEvent:
        if not raw_line.strip():
            return ParsedEvent("progress", raw_type="blank")
        try:
            obj = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ParsedEvent("malformed", data={"bytes": len(raw_line)})
        if not isinstance(obj, dict):
            return ParsedEvent("malformed", data={"json_type": type(obj).__name__})
        t = obj.get("type")
        sid = _s(obj.get("session_id"))
        if t == "system":
            sub = _s(obj.get("subtype"))
            if sub == "init":
                return ParsedEvent(
                    "session",
                    raw_type="system:init",
                    session_id=sid,
                    model=_s(obj.get("model")),
                    data={
                        "permission_mode": _s(obj.get("permissionMode")),
                        "api_key_source": _s(obj.get("apiKeySource")),
                        "tools_count": len(obj["tools"])
                        if isinstance(obj.get("tools"), list)
                        else None,
                        "mcp_servers_count": len(obj["mcp_servers"])
                        if isinstance(obj.get("mcp_servers"), list)
                        else None,
                        "cli_version": _s(obj.get("claude_code_version")),
                    },
                )
            return ParsedEvent("progress", raw_type=f"system:{sub}", session_id=sid)
        if t in ("assistant", "user"):
            raw_msg = obj.get("message")
            model = _s(raw_msg.get("model")) if isinstance(raw_msg, dict) else None
            return ParsedEvent("message", raw_type=t, session_id=sid, model=model)
        if t == "stream_event":
            return ParsedEvent("progress", raw_type=t, session_id=sid)
        if t == "result":
            usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else None
            denials = obj.get("permission_denials")
            model_usage = obj.get("modelUsage") if isinstance(obj.get("modelUsage"), dict) else None
            return ParsedEvent(
                "result",
                raw_type=f"result:{_s(obj.get('subtype'))}",
                session_id=sid,
                data={
                    "subtype": _s(obj.get("subtype")),
                    "is_error": obj.get("is_error")
                    if isinstance(obj.get("is_error"), bool)
                    else None,
                    "result": _s(obj.get("result"), 4000),
                    "num_turns": obj.get("num_turns")
                    if isinstance(obj.get("num_turns"), int)
                    else None,
                    "duration_ms": obj.get("duration_ms")
                    if isinstance(obj.get("duration_ms"), int | float)
                    else None,
                    "total_cost_usd": obj.get("total_cost_usd")
                    if isinstance(obj.get("total_cost_usd"), int | float)
                    else None,
                    "usage": _usage(usage),
                    "permission_denials": len(denials) if isinstance(denials, list) else None,
                    "permission_denied_tools": sorted(
                        {_s(d.get("tool_name")) or "?" for d in denials if isinstance(d, dict)}
                    )[:20]
                    if isinstance(denials, list)
                    else [],
                    "model_usage_models": sorted(model_usage)[:10] if model_usage else [],
                },
            )
        return ParsedEvent("unknown", raw_type=_s(t) or "<missing>", session_id=sid)

    # -- classification -------------------------------------------------------------------------

    def classify_completion(
        self, process: ProcessOutcome, events: Sequence[ParsedEvent]
    ) -> ExecutorResult:
        init = next((e for e in events if e.kind == "session"), None)
        results = [e for e in events if e.kind == "result"]
        final = results[-1].data if results else None
        proto = protocol_summary(events, process)
        observed = (init.model if init else None) or (
            final["model_usage_models"][0]
            if final and len(final.get("model_usage_models") or []) == 1
            else None
        )
        session_id = (init.session_id if init else None) or (
            results[-1].session_id if results else None
        )
        usage = self._usage(final)
        reported: dict[str, Any] = {
            "status": final.get("subtype") if final else None,
            "is_error": final.get("is_error") if final else None,
            "summary": redact_text(final["result"])[0] if final and final.get("result") else None,
            "num_turns": final.get("num_turns") if final else None,
            "permission_denials": final.get("permission_denials") if final else None,
            "permission_denied_tools": final.get("permission_denied_tools") if final else [],
            "tests_reported": None,
            "model_pin": _model_pin(self.settings.requested_model, observed),
            "api_key_source": init.data.get("api_key_source") if init else None,
        }
        common: dict[str, Any] = {
            "session_id": session_id,
            "observed_model": observed,
            "usage": usage,
            "protocol": proto,
            "executor_reported": reported,
        }
        base = classify_process_level(process)
        if base is not None:
            base.session_id, base.observed_model = session_id, observed
            base.usage, base.protocol, base.executor_reported = usage, proto, reported
            return base

        stderr_text = process.stderr.render().decode("utf-8", "replace")[-4000:]
        if (
            init
            and results
            and results[-1].session_id
            and init.session_id != results[-1].session_id
        ):
            return ExecutorResult(
                AttemptOutcome.PROTOCOL_ERROR,
                "session id changed between init and result",
                **common,
            )
        rejected = (
            _rejected_argument(stderr_text)
            if init is None and not results and process.returncode not in (0, None)
            else None
        )
        if rejected is not None:
            return ExecutorResult(
                AttemptOutcome.BLOCKED,
                f"the claude CLI rejected a command-line argument ({rejected})",
                blocked={
                    "category": "cli_rejected_argument",
                    "classification": "cli_stderr",
                    "flag": rejected,
                    "reset_at": None,
                    "evidence": redact_text(stderr_text[-600:])[0],
                    "next_step": "stopped. The bridge never removes a limit flag and retries; "
                    "decide locally (e.g. update the CLI) before any further attempt",
                },
                **common,
            )
        resume_id = self._resume_requested
        if resume_id is not None and (init is None or init.session_id != resume_id):
            hint = _provider_hint(stderr_text + " " + ((final or {}).get("result") or ""))
            return ExecutorResult(
                AttemptOutcome.BLOCKED,
                "requested resume was not confirmed by the executor output",
                blocked={
                    "category": "resume_failed",
                    "classification": "structured" if init else "missing_init_event",
                    "requested_session_id": resume_id,
                    "observed_session_id": init.session_id if init else None,
                    "text_hint": hint,
                    "next_step": "decide locally whether to start a new session "
                    "(recover --resolve retry) — never silently downgraded",
                },
                **common,
            )
        if final is None:
            hint = _provider_hint(stderr_text)
            if hint:
                return ExecutorResult(
                    AttemptOutcome.BLOCKED,
                    f"no final result; stderr suggests a provider problem ({hint})",
                    blocked={
                        "category": "provider_error",
                        "classification": "heuristic",
                        "hint": hint,
                        "reset_at": None,
                        "evidence": redact_text(stderr_text[-600:])[0],
                    },
                    **common,
                )
            if process.returncode == 0:
                return ExecutorResult(
                    AttemptOutcome.PROTOCOL_ERROR, "exited 0 without a final result event", **common
                )
            return ExecutorResult(
                AttemptOutcome.CRASHED,
                f"exit {process.returncode} / signal {process.exit_signal} without a result",
                **common,
            )
        if len(results) > 1:
            return ExecutorResult(
                AttemptOutcome.PROTOCOL_ERROR, "more than one result event", **common
            )
        subtype, is_error = final.get("subtype"), final.get("is_error")
        if final.get("permission_denials") and (is_error or subtype != "success"):
            return ExecutorResult(
                AttemptOutcome.BLOCKED,
                "executor stopped after permission denials",
                blocked={
                    "category": "permission_denied",
                    "classification": "structured",
                    "tools": final.get("permission_denied_tools"),
                    "reset_at": None,
                },
                **common,
            )
        if subtype == "success" and is_error is False:
            if process.returncode != 0:
                return ExecutorResult(
                    AttemptOutcome.PROTOCOL_ERROR,
                    f"success result but exit code {process.returncode}",
                    **common,
                )
            return ExecutorResult(AttemptOutcome.SUCCEEDED, "result: success", **common)
        if subtype == "error_max_budget_usd":
            return ExecutorResult(
                AttemptOutcome.BLOCKED,
                "executor stopped at its --max-budget-usd limit",
                blocked={
                    "category": "budget_limit",
                    "classification": "structured",
                    "reset_at": None,
                },
                **common,
            )
        if subtype == "error_max_turns":
            return ExecutorResult(AttemptOutcome.FAILED, "reached the max-turns limit", **common)
        if is_error:
            hint = _provider_hint((final.get("result") or "") + " " + stderr_text)
            if hint:
                return ExecutorResult(
                    AttemptOutcome.BLOCKED,
                    f"error result suggests a provider problem ({hint})",
                    blocked={
                        "category": "provider_error",
                        "classification": "heuristic",
                        "hint": hint,
                        "reset_at": None,
                    },
                    **common,
                )
            return ExecutorResult(
                AttemptOutcome.FAILED, f"error result (subtype {subtype})", **common
            )
        return ExecutorResult(
            AttemptOutcome.PROTOCOL_ERROR,
            f"unrecognized terminal result (subtype {subtype!r}, is_error {is_error!r})",
            **common,
        )

    def _usage(self, final: dict[str, Any] | None) -> dict[str, Any]:
        out = mock_usage()
        out["mode"] = "executor_reported"
        out["model_calls_made_by_test"] = None
        u = (final or {}).get("usage") or {}
        out.update(
            {
                "input_tokens_reported": u.get("input_tokens"),
                "output_tokens_reported": u.get("output_tokens"),
                "cache_read_tokens_reported": u.get("cache_read_input_tokens"),
                "cache_creation_tokens_reported": u.get("cache_creation_input_tokens"),
                "cost_estimate_usd_reported": (final or {}).get("total_cost_usd"),
                "source": "executor result event"
                if final and final.get("usage")
                else ("not_observed"),
                "aggregation": "as reported for this invocation; whether resumed history is "
                "included is unverified",
                "cost_note": "API-equivalent estimate reported by the CLI, not a bill and not "
                "subscription usage",
            }
        )
        return out


def _s(value: Any, limit: int = 256) -> str | None:
    return value[:limit] if isinstance(value, str) else None


def _usage(u: dict[str, Any] | None) -> dict[str, Any] | None:
    if not u:
        return None
    keys = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    return {k: u[k] for k in keys if isinstance(u.get(k), int)}


def _model_pin(requested: str | None, observed: str | None) -> str:
    if requested is None:
        return "not_requested"
    if observed is None:
        return "unknown"
    return "satisfied" if observed == requested else "mismatch"


def _provider_hint(text: str) -> str | None:
    for name, pattern in _PROVIDER_PATTERNS:
        if pattern.search(text):
            return name
    return None


def check_forbidden(argv: Sequence[str]) -> None:
    for item in argv[1:]:
        if item in FORBIDDEN_FLAGS or item in FORBIDDEN_VALUES:
            raise BridgeError("PREFLIGHT_FAILED", f"refusing forbidden executor argument {item!r}")


# --- live preflight (non-inference) --------------------------------------------------------------


def help_flags(binary: str, env: dict[str, str]) -> tuple[set[str], str | None]:
    """Flags listed by ``claude --help`` plus ``claude --version`` text. Never runs inference."""
    try:
        help_out = subprocess.run(
            [binary, "--help"], capture_output=True, timeout=30, env=env, check=False
        )
        version = subprocess.run(
            [binary, "--version"], capture_output=True, timeout=30, env=env, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BridgeError("PREFLIGHT_FAILED", f"cannot run {binary} --help: {exc}") from None
    text = help_out.stdout.decode("utf-8", "replace")
    flags = set(re.findall(r"(?<![\w-])(--[a-zA-Z][\w-]*|-[a-zA-Z])\b", text))
    ver = version.stdout.decode("utf-8", "replace").strip().splitlines()
    return flags, (ver[0][:200] if ver else None)


def _rejected_argument(stderr_text: str) -> str | None:
    for pattern in _REJECTED_ARGUMENT:
        m = pattern.search(stderr_text)
        if m:
            return m.group(1)
    return None


def flag_evidence(
    used: Sequence[str], *, listed_flags: set[str] | None, confirmed: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Per-flag evidence from three separate sources; never infers "supported" from docs alone.

    status:
      listed_in_local_help                  this CLI's --help lists it (parse support indicated)
      confirmed_locally_by_user             user recorded a local check in config.toml
      documented_pending_local_confirmation documented officially, not in local --help: unknown
      undocumented_and_unlisted             neither source: unknown
    Runtime behaviour is per attempt (a CLI rejection blocks that attempt); it is not stored here.
    """
    out: dict[str, dict[str, Any]] = {}
    for flag in used:
        documented = flag in DOCUMENTED_FLAGS
        listed = None if listed_flags is None else flag in listed_flags
        is_confirmed = flag in confirmed
        if is_confirmed:
            status = "confirmed_locally_by_user"
        elif listed:
            status = "listed_in_local_help"
        elif documented:
            status = "documented_pending_local_confirmation"
        else:
            status = "undocumented_and_unlisted"
        out[flag] = {
            "official_docs": {
                "declared": documented,
                "source": CLI_REFERENCE_URL if documented else None,
                "checked": CLI_REFERENCE_CHECKED,
            },
            "local_help": "not_checked"
            if listed is None
            else ("listed" if listed else "not_listed"),
            "local_confirmation": "user_confirmed_in_config" if is_confirmed else "none",
            "status": status,
            "usable_for_live": status in ("listed_in_local_help", "confirmed_locally_by_user"),
        }
    return out


def preflight(
    adapter: ClaudeCodeAdapter,
    argv: Sequence[str],
    *,
    listed_flags: set[str],
    allow_unlisted: Sequence[str],
) -> dict[str, Any]:
    """Hold live dispatch until every flag is listed by local --help or confirmed locally.

    Missing from --help is not treated as "unsupported" (the docs say --help is incomplete); it
    is "unknown, pending local confirmation". There is no global bypass: confirmation is per flag.
    """
    check_forbidden(argv)
    used = [a for a in argv[1:] if a.startswith("-") and not a.startswith("---")]
    evidence = flag_evidence(used, listed_flags=listed_flags, confirmed=allow_unlisted)
    pending = [f for f, e in evidence.items() if not e["usable_for_live"]]
    if pending:
        documented = [f for f in pending if evidence[f]["official_docs"]["declared"]]
        undocumented = [f for f in pending if f not in documented]
        parts = []
        if documented:
            parts.append(
                ", ".join(documented)
                + f": declared in the official CLI reference ({CLI_REFERENCE_URL}, checked "
                f"{CLI_REFERENCE_CHECKED}) but not listed by this installation's --help. --help "
                "does not list every flag, so this is not evidence of absence; status on this "
                "installation: unknown (pending local confirmation)."
            )
        if undocumented:
            parts.append(
                ", ".join(undocumented)
                + ": neither documented nor listed by --help; status unknown."
            )
        raise BridgeError(
            "PREFLIGHT_FAILED",
            "live dispatch held until these flags are confirmed on this machine: "
            + " ".join(parts)
            + " After confirming locally, list each flag in [live] allow_unlisted_flags. If the "
            "CLI then rejects a flag at run time the attempt stops as BLOCKED; the bridge never "
            "drops a limit flag and retries.",
            details={"pending_local_confirmation": pending, "flag_evidence": evidence},
        )
    return {"flags_checked": used, "flag_evidence": evidence}
