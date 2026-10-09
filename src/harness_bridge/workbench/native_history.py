"""Project-scoped native discovery and bounded immutable history pages.

No credential files, global transcript traversal, native writes, resumes or model turns.
Codex is queried through its native read-only app-server methods. Claude reads only the
exact project transcript directory after checking its recorded cwd and UUID.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import stat
import threading
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from harness_bridge.errors import BridgeError
from harness_bridge.workbench.conversation import (
    HISTORY_FILE_CAP,
    claude_config_dir,
    claude_transcript_items,
    codex_turn_items,
)
from harness_bridge.workbench.harness import CLAUDE, CODEX
from harness_bridge.workbench.structured import StructuredError, read_codex_data

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness_bridge.workbench.service import Workbench


HISTORY_ERRORS = {
    "native_capability_unsupported": "当前 Codex 不支持所需的原生历史接口。",
    "native_protocol_unsupported": "当前原生历史响应格式尚不受支持。",
    "storage_layout_unsupported": "不支持通过符号链接读取项目历史目录。",
    "harness_unavailable": "找不到可用的 Codex，无法读取原生历史。",
    "native_timeout": "原生历史读取超时，请稍后刷新。",
    "native_process_exited": "读取历史的原生进程提前退出，请重试。",
    "native_transport_error": "原生历史连接中断，请重试。",
    "native_exit_unconfirmed": "历史读取进程的退出尚未确认。",
    "native_writer_busy": "原生会话仍被其他客户端占用。",
    "native_history_missing": "这个会话的本地原生历史文件已不存在。",
    "native_history_invalid": "原生历史元数据无法校验，请核对会话记录。",
    "native_identity_changed": "原生会话 ID 或工作目录与关联记录不一致。",
    "native_read_failed": "读取原生历史失败，请稍后刷新或在原生客户端核对。",
}
UNSUPPORTED = {
    "native_capability_unsupported",
    "native_protocol_unsupported",
    "storage_layout_unsupported",
    "unsupported_source",
}


def history_failure(reason: str) -> BridgeError:
    reason = reason if reason in HISTORY_ERRORS else "native_read_failed"
    return BridgeError(
        "PREFLIGHT_FAILED",
        HISTORY_ERRORS[reason],
        details={"reason": reason, "capability_unsupported": reason in UNSUPPORTED},
    )


class NativeIdentityError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def native_id(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def page_limit(value: Any, default: int = 50) -> int:
    try:
        number = int(value) if value is not None else default
    except (ValueError, TypeError):
        number = 0
    if isinstance(value, bool) or not 1 <= number <= 100:
        raise BridgeError(
            "INVALID_INPUT", "每页数量必须是 1 到 100 的整数。", details={"reason": "invalid_limit"}
        )
    return number


def expired() -> BridgeError:
    return BridgeError(
        "STATE_CONFLICT",
        "历史分页已过期，请从第一页重新加载。",
        details={"reason": "cursor_expired"},
    )


def completeness(reasons: list[str]) -> dict[str, Any]:
    return {"state": "partial" if reasons else "complete", "reasons": list(dict.fromkeys(reasons))}


class Pages:
    """Bounded opaque cursors, scoped to identity/query; no client-provided file paths."""

    def __init__(self) -> None:
        self.entries: OrderedDict[str, tuple[float, str, Any]] = OrderedDict()
        self.lock = threading.RLock()
        self.sizes: dict[str, int] = {}

    def put(self, scope: str, value: Any) -> str:
        token = uuid.uuid4().hex
        size = len(json.dumps(value, ensure_ascii=False).encode())
        if size > 16 << 20:
            raise BridgeError(
                "PREFLIGHT_FAILED",
                "历史快照超过分页大小上限。",
                details={"reason": "history_snapshot_limit"},
            )
        with self.lock:
            self.sizes[token] = size
            self.entries[token] = (time.monotonic(), scope, copy.deepcopy(value))
            while len(self.entries) > 64 or sum(self.sizes.values()) > 32 << 20:
                oldest, _ = self.entries.popitem(last=False)
                self.sizes.pop(oldest, None)
        return token

    def get(self, token: str, scope: str) -> Any:
        with self.lock:
            row = self.entries.get(token)
            if row is None or row[1] != scope or time.monotonic() - row[0] > 600:
                raise expired()
            return copy.deepcopy(row[2])

    def history(
        self, scope: str, result: dict[str, Any], limit: int, before: str | None, since: str | None
    ) -> dict[str, Any]:
        if before and since:
            raise BridgeError(
                "INVALID_INPUT",
                "不能同时请求更早历史和增量刷新。",
                details={"reason": "invalid_cursor_combination"},
            )
        reset = False
        if before:
            result, end = self.get(before, scope + ":before")
            items = result["items"]
        else:
            result = copy.deepcopy(result)
            items = result["items"]
            end = len(items)
        hashes = {i["id"]: digest(i) for i in items}
        since_token = self.put(scope + ":since", hashes)
        if since:
            try:
                old = self.get(since, scope + ":since")
            except BridgeError:
                old, reset = {}, True
            if set(old) - set(hashes):
                reset = True
            if not reset:
                changed = [i for i in items if old.get(i["id"]) != hashes[i["id"]]]
                # Never drop a refresh delta silently; reset to newest page when it is too large.
                if len(changed) <= limit:
                    return {
                        **result,
                        "items": changed,
                        "page": self._page(result, None, since_token, False),
                    }
                reset = True
        start = max(0, end - limit)
        cursor = self.put(scope + ":before", (result, start)) if start else None
        return {
            **result,
            "items": items[start:end],
            "page": self._page(result, cursor, since_token, reset),
        }

    @staticmethod
    def _page(
        result: dict[str, Any], before: str | None, since: str, reset: bool
    ) -> dict[str, Any]:
        reasons = result.get("partial_reasons", [])
        error = result["history"].get("error")
        state = "partial" if reasons or error else "ready"
        if not result["items"]:
            state = "unavailable" if error else ("partial" if reasons else "empty")
        return {
            "state": state,
            "next_before": before,
            "next_since": since,
            "has_more": before is not None,
            "reset": reset,
            "completeness": completeness(reasons),
        }


class NativeHistory:
    def __init__(self, wb: Workbench) -> None:
        self.wb = wb
        self.pages = Pages()
        self.candidates: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.lock = threading.RLock()

    def environment(self, harness: str) -> dict[str, str]:
        env = self.wb._history_env()
        root = (
            claude_config_dir(env)
            if harness == CLAUDE
            else Path(
                env.get("CODEX_HOME") or str(Path(env.get("HOME") or str(Path.home())) / ".codex")
            )
        )
        return {
            "id": "env_" + digest([harness, str(root.resolve())])[:24],
            "kind": "local",
            "label": "Claude Code local" if harness == CLAUDE else "Codex local",
        }

    def scope(self, project_id: str) -> tuple[dict[str, Any], list[str]]:
        project = self.wb._project(project_id)
        if project["archived"]:
            raise BridgeError(
                "STATE_CONFLICT", "项目已归档。", details={"reason": "project_archived"}
            )
        paths = [project["root_path"]]
        paths.extend(
            s["workdir"] for s in self.wb.store.list_sessions(project_id, include_archived=True)
        )
        return project, list(dict.fromkeys(str(Path(p).resolve()) for p in paths))

    def _remember(self, meta: dict[str, Any], project_id: str) -> dict[str, Any]:
        cid = (
            "nat_"
            + digest(
                [project_id, meta["harness"], meta["environment"]["id"], meta["native_session_id"]]
            )[:24]
        )
        meta = {**meta, "candidate_id": cid, "_project_id": project_id}
        with self.lock:
            self.candidates[cid] = meta
            self.candidates.move_to_end(cid)
            while len(self.candidates) > 2000:
                self.candidates.popitem(last=False)
        return self.public(meta)

    def public(self, meta: dict[str, Any]) -> dict[str, Any]:
        result = {k: v for k, v in meta.items() if not k.startswith("_")}
        link = self.wb.store.find_native_link(
            meta["harness"], meta["environment"]["id"], meta["native_session_id"]
        )
        result["already_linked"] = None
        result["occupancy"] = {"state": "unknown", "reason": "External activity is not observable"}
        if link is None:
            existing = [
                s
                for s in self.wb.store.list_sessions(include_archived=True)
                if s["harness"] == meta["harness"]
                and s["native_session_id"] == meta["native_session_id"]
                and s["workdir"] == meta["workdir"]
                and self.wb.store.native_link(s["session_id"]) is None
            ]
            if len(existing) == 1:
                link = {
                    "linked": True,
                    "session_id": existing[0]["session_id"],
                    "archived": existing[0]["archived"],
                }
        if link and link["linked"]:
            sid = link["session_id"]
            result["already_linked"] = {"session_id": sid, "archived": bool(link["archived"])}
            session = self.wb._session(sid)
            if session.get("external_json"):
                result["occupancy"] = {
                    "state": "external",
                    "reason": "External use must be confirmed ended",
                }
            if self.wb._is_active(self.wb.store.list_runs(sid)):
                result["occupancy"] = {"state": "repobridge", "reason": "Session is running here"}
        result["directory_state"] = "available" if Path(meta["workdir"]).is_dir() else "missing"
        if result["directory_state"] == "missing":
            result.update(resumable=False, resume_reason="directory_missing")
        return result

    def candidate(self, cid: str) -> dict[str, Any]:
        with self.lock:
            meta = copy.deepcopy(self.candidates.get(cid))
        if not meta:
            raise BridgeError(
                "NOT_FOUND",
                "候选会话已失效，请刷新列表后重新选择。",
                details={"reason": "candidate_expired"},
            )
        _, paths = self.scope(meta["_project_id"])
        if meta["workdir"] not in paths or meta["environment"] != self.environment(meta["harness"]):
            raise expired()
        return meta

    def discover(
        self,
        project_id: str,
        harness: str,
        *,
        limit: Any = 20,
        q: str = "",
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if harness not in (CLAUDE, CODEX) or len(q) > 200:
            raise BridgeError(
                "INVALID_INPUT", "会话类型或搜索条件无效。", details={"reason": "invalid_filter"}
            )
        size = page_limit(limit, 20)
        project, paths = self.scope(project_id)
        scope = digest([project_id, paths, harness, self.environment(harness), q, size])
        if harness == CLAUDE:
            if cursor:
                records, reasons, offset = self.pages.get(cursor, scope)
            else:
                records, reasons = self._claude_list(paths, project["root_path"], q)
                offset = 0
            rows = records[offset : offset + size]
            more = offset + size < len(records)
            next_cursor = self.pages.put(scope, (records, reasons, offset + size)) if more else None
        else:
            native_cursor = self.pages.get(cursor, scope) if cursor else None
            params: dict[str, Any] = {
                "cwd": paths,
                "limit": size,
                "useStateDbOnly": True,
                "sortKey": "updated_at",
                "sortDirection": "desc",
            }
            if native_cursor:
                params["cursor"] = native_cursor
            if q:
                params["searchTerm"] = q
            result = self.codex(paths[0], "", lambda call: call("thread/list", params, timeout=15))
            rows, reasons = [], ["local_only", "native_index_only"]
            if not isinstance(result.get("data"), list):
                raise history_failure("native_protocol_unsupported")
            for t in result["data"]:
                if (
                    not isinstance(t, dict)
                    or not native_id(t.get("id"))
                    or t.get("cwd") not in paths
                ):
                    reasons.append("invalid_native_metadata")
                    continue
                try:
                    rows.append(self._codex_meta(t, project["root_path"]))
                except (ValueError, TypeError, OverflowError, OSError):
                    reasons.append("invalid_native_metadata")
            nxt = result.get("nextCursor")
            next_cursor = self.pages.put(scope, nxt) if isinstance(nxt, str) and nxt else None
        return {
            "items": [self._remember(m, project_id) for m in rows],
            "next_cursor": next_cursor,
            "completeness": completeness(reasons),
        }

    def _claude_list(
        self, paths: list[str], root: str, query: str
    ) -> tuple[list[dict[str, Any]], list[str]]:
        records, reasons = [], ["local_only"]
        projects = claude_config_dir(self.wb._history_env()).resolve() / "projects"
        if projects.is_symlink():
            raise history_failure("storage_layout_unsupported")
        count = 0
        for workdir in paths:
            directory = projects / re.sub(r"[^a-zA-Z0-9]", "-", workdir)
            if directory.is_symlink():
                reasons.append("symlink_skipped")
                continue
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if not entry.name.endswith(".jsonl") or not native_id(entry.name[:-6]):
                            continue
                        count += 1
                        if count > 2000:
                            reasons.append("scan_limit")
                            break
                        path = Path(entry.path)
                        try:
                            meta = self._claude_meta(path, workdir, root)
                        except (OSError, ValueError, TypeError):
                            reasons.append("invalid_native_metadata")
                            continue
                        if (
                            query.casefold()
                            in (meta["title"] + " " + meta["native_session_id"]).casefold()
                        ):
                            records.append(meta)
            except FileNotFoundError:
                continue
            except OSError:
                reasons.append("directory_unreadable")
        return sorted(
            records, key=lambda m: (m["updated_at"], m["native_session_id"]), reverse=True
        ), reasons

    def _claude_meta(self, path: Path, cwd: str, root: str) -> dict[str, Any]:
        if path.resolve() != path or not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("Not a regular transcript")
        # Bounded project metadata only. No global history.jsonl or credentials.
        title, observed, updated = path.stem, False, ""
        with path.open("rb") as fh:
            for raw in fh.read(256 << 10).splitlines():
                try:
                    record = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("sessionId") and record.get("sessionId") != path.stem:
                    raise NativeIdentityError("Native ID mismatch")
                if record.get("cwd"):
                    if str(Path(record["cwd"]).resolve()) != cwd:
                        raise NativeIdentityError("Native cwd mismatch")
                    observed = record.get("sessionId") == path.stem or observed
                if record.get("customTitle"):
                    title = str(record["customTitle"])[:120]
                if isinstance(record.get("timestamp"), str):
                    updated = record["timestamp"]
        if not observed:
            raise ValueError("No matching native metadata")
        updated = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        return {
            "harness": CLAUDE,
            "native_session_id": path.stem,
            "environment": self.environment(CLAUDE),
            "source": "unknown",
            "title": title,
            "updated_at": updated,
            "workdir": cwd,
            "project_match": "root" if cwd == root else "registered_workdir",
            "resumable": True,
            "resume_reason": None,
            "_path": str(path),
        }

    def _codex_meta(self, t: dict[str, Any], root: str) -> dict[str, Any]:
        source = "cli" if t.get("source") in ("cli", "exec") else "unknown"
        if t.get("source") == "vscode" or isinstance(t.get("source"), dict):
            source = "other"
        # appServer does not establish desktop origin; do not guess from client names.
        resumable = not t.get("ephemeral", False) and not isinstance(t.get("source"), dict)
        return {
            "harness": CODEX,
            "native_session_id": t["id"],
            "environment": self.environment(CODEX),
            "source": source,
            "title": str(t.get("name") or t["id"])[:120],
            "updated_at": datetime.fromtimestamp(t.get("updatedAt", 0), UTC).isoformat(),
            "workdir": t["cwd"],
            "project_match": "root" if t["cwd"] == root else "registered_workdir",
            "resumable": resumable,
            "resume_reason": None if resumable else "unsupported_source",
        }

    def codex(
        self, cwd: str, native: str, operation: Callable[..., dict[str, Any]]
    ) -> dict[str, Any]:
        info = self.wb.harnesses()[CODEX]
        if not info.available or not info.binary:
            raise history_failure("harness_unavailable")
        scratch = self.wb.root / "history" / uuid.uuid4().hex
        scratch.mkdir()
        try:
            # Missing project folder must not prevent reading its indexed history.
            return read_codex_data(
                info.binary,
                self.wb._history_env(),
                cwd if Path(cwd).is_dir() else str(scratch),
                native,
                scratch,
                operation,
            )
        except StructuredError as exc:
            raise history_failure(exc.reason) from None
        except OSError:
            raise history_failure("native_read_failed") from None
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def history(self, meta: dict[str, Any]) -> dict[str, Any]:
        if meta["environment"] != self.environment(meta["harness"]):
            raise BridgeError(
                "STATE_CONFLICT",
                "原生存储位置已变化，请切回关联时的存储环境。",
                details={"reason": "environment_changed"},
            )
        reasons: list[str] = []
        error = None
        reason: str | None = None
        items: list[dict[str, Any]] = []
        source = "claude-transcript" if meta["harness"] == CLAUDE else "codex"
        try:
            if meta["harness"] == CLAUDE:
                path = Path(meta["_path"])
                fresh = self._claude_meta(path, meta["workdir"], meta["workdir"])
                if fresh["native_session_id"] != meta["native_session_id"]:
                    raise NativeIdentityError("Native ID mismatch")
                items = claude_transcript_items(path, diagnostics=reasons)
                if path.stat().st_size > HISTORY_FILE_CAP:
                    reasons.append("native_file_limit")
            else:

                def read(call: Callable[..., dict[str, Any]]) -> dict[str, Any]:
                    thread = call(
                        "thread/read", {"threadId": meta["native_session_id"]}, timeout=15
                    ).get("thread")
                    if (
                        not isinstance(thread, dict)
                        or thread.get("id") != meta["native_session_id"]
                        or thread.get("cwd") != meta["workdir"]
                    ):
                        raise StructuredError(
                            "Native identity or cwd mismatch", reason="native_identity_changed"
                        )
                    turns: list[dict[str, Any]] = []
                    cursor, deadline = None, time.monotonic() + 15
                    for _ in range(20):
                        params = {
                            "threadId": meta["native_session_id"],
                            "itemsView": "full",
                            "sortDirection": "desc",
                            "limit": 100,
                        }
                        if cursor:
                            params["cursor"] = cursor
                        page = call("thread/turns/list", params, timeout=15)
                        if not isinstance(page.get("data"), list):
                            raise StructuredError(
                                "Unsupported native history shape",
                                reason="native_protocol_unsupported",
                            )
                        turns.extend(t for t in page["data"] if isinstance(t, dict))
                        cursor = page.get("nextCursor")
                        if not cursor or time.monotonic() > deadline:
                            break
                    return {"items": codex_turn_items(reversed(turns)), "partial": bool(cursor)}

                result = self.codex(meta["workdir"], meta["native_session_id"], read)
                items = result["items"]
                if result["partial"]:
                    reasons.append("native_page_limit")
        except BridgeError as exc:
            reason = exc.details.get("reason", "native_read_failed")
        except FileNotFoundError:
            reason = "native_history_missing"
        except NativeIdentityError:
            reason = "native_identity_changed"
        except (ValueError, TypeError):
            reason = "native_history_invalid"
        except OSError:
            reason = "native_read_failed"
        if reason:
            error = HISTORY_ERRORS.get(reason, HISTORY_ERRORS["native_read_failed"])
        retained: list[dict[str, Any]] = []
        size = 0
        for item in reversed(items):
            size += len(json.dumps(item, ensure_ascii=False).encode())
            if size > 8 << 20 or len(retained) >= 10000:
                reasons.append("history_snapshot_limit")
                break
            retained.append(item)
        items = list(reversed(retained))
        return {
            "items": [{**i, "history": True} for i in items],
            "history": {
                "source": source,
                "error": error,
                "reason": reason,
                "capability_unsupported": reason in UNSUPPORTED,
            },
            "partial_reasons": reasons,
        }

    def preview(
        self, cid: str, *, limit: Any = 50, before: str | None = None, since: str | None = None
    ) -> dict[str, Any]:
        meta = self.candidate(cid)
        return self.pages.history(
            cid, self.history(meta) if not before else {}, page_limit(limit), before, since
        )
