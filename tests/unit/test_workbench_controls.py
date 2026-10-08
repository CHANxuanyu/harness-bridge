"""Model / effort / mode catalogs and choices, native forms and attachment helpers (units)."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_bridge.workbench import controls
from harness_bridge.workbench.conversation import codex_permission_response, elicitation_form
from harness_bridge.workbench.harness import (
    CLAUDE,
    CODEX,
    claude_setting_flags,
    codex_setting_flags,
)
from harness_bridge.workbench.service import _fuzzy, _image_mime, _safe_name

CLAUDE_INIT = {
    "models": [
        {
            "value": "default",
            "resolvedModel": "claude-x-opus",
            "displayName": "Default",
            "description": "d",
            "supportsEffort": True,
            "supportedEffortLevels": ["low", "high", "max"],
            "supportsAutoMode": True,
        },
        {"value": "sonnet", "resolvedModel": "claude-x-sonnet", "displayName": "Sonnet"},
        {"value": "zdr", "displayName": "ZDR", "description": "blocked", "disabled": True},
        {"displayName": "no value"},
    ],
    "commands": [{"name": "compact", "description": "c" * 400}],
}


def claude_cat() -> dict:
    return controls.claude_catalog(CLAUDE_INIT, cli_version="2.1.291")


def test_claude_catalog_comes_only_from_the_initialize_response() -> None:
    cat = claude_cat()
    assert [m["id"] for m in cat["models"]] == ["default", "sonnet", "zdr"]
    default, sonnet, zdr = cat["models"]
    assert default["efforts"] == ["low", "high", "max"] and default["auto_mode"]
    assert sonnet["efforts"] == [] and not sonnet["auto_mode"]
    assert zdr["disabled"]
    assert len(cat["commands"][0]["description"]) == 200
    assert "bypassPermissions" not in [m["id"] for m in cat["modes"]]


def test_codex_catalog_hides_hidden_models_and_applies_org_requirements() -> None:
    cat = controls.codex_catalog(
        [
            {
                "id": "a",
                "displayName": "A",
                "isDefault": True,
                "hidden": False,
                "supportedReasoningEfforts": [{"reasoningEffort": "ultra", "description": "u"}],
                "defaultReasoningEffort": "ultra",
                "inputModalities": ["text"],
            },
            {"id": "h", "hidden": True},
        ],
        {"allowedApprovalPolicies": ["on-request"], "allowedSandboxModes": ["read-only"]},
        cli_version="0.162",
    )
    assert [m["id"] for m in cat["models"]] == ["a"] and cat["default_model"] == "a"
    assert cat["models"][0]["efforts"] == ["ultra"] and not cat["models"][0]["images"]
    assert cat["models"][0]["effort_descriptions"] == {"ultra": "u"}
    modes = {m["id"]: m for m in cat["modes"]}
    assert modes["read-only"]["available"]
    assert not modes["workspace"]["available"] and "组织策略" in modes["workspace"]["reason"]


def test_choices_are_validated_against_the_catalog() -> None:
    cat = claude_cat()
    empty = controls.blank_settings()
    with pytest.raises(controls.ChoiceError, match="模型目录"):
        controls.validate_choice(None, empty, {"model": "default"}, harness=CLAUDE)
    with pytest.raises(controls.ChoiceError, match="不在当前"):
        controls.validate_choice(cat, empty, {"model": "gpt"}, harness=CLAUDE)
    with pytest.raises(controls.ChoiceError, match="当前不可选"):
        controls.validate_choice(cat, empty, {"model": "zdr"}, harness=CLAUDE)
    chosen, notes = controls.validate_choice(
        cat, empty, {"model": "default", "effort": "max", "mode": "auto"}, harness=CLAUDE
    )
    assert chosen == {"model": "default", "effort": "max", "mode": "auto"} and notes == []
    current = {**empty, "chosen": chosen}
    # Switching to a model without effort levels or auto mode drops both, with notices.
    chosen, notes = controls.validate_choice(cat, current, {"model": "sonnet"}, harness=CLAUDE)
    assert chosen == {"model": "sonnet"} and len(notes) == 2
    with pytest.raises(controls.ChoiceError, match="不支持调整思考强度"):
        controls.validate_choice(
            cat, {**empty, "chosen": chosen}, {"effort": "low"}, harness=CLAUDE
        )
    with pytest.raises(controls.ChoiceError, match="不支持自动模式"):
        controls.validate_choice(cat, {**empty, "chosen": chosen}, {"mode": "auto"}, harness=CLAUDE)
    with pytest.raises(controls.ChoiceError, match="不提供"):
        controls.validate_choice(cat, empty, {"mode": "bypassPermissions"}, harness=CLAUDE)
    # None returns a field to the harness's own default.
    chosen, _ = controls.validate_choice(
        cat, {**empty, "chosen": {"model": "sonnet"}}, {"model": None}, harness=CLAUDE
    )
    assert chosen == {}
    with pytest.raises(controls.ChoiceError):
        controls.validate_choice(cat, empty, {"colour": "x"}, harness=CLAUDE)


def test_codex_model_change_does_not_keep_an_effort_the_new_model_lacks() -> None:
    cat = controls.codex_catalog(
        [
            {
                "id": "big",
                "supportedReasoningEfforts": [{"reasoningEffort": "high", "description": ""}],
                "defaultReasoningEffort": "high",
            },
            {
                "id": "mini",
                "supportedReasoningEfforts": [
                    {"reasoningEffort": "low", "description": ""},
                    {"reasoningEffort": "medium", "description": ""},
                ],
                "defaultReasoningEffort": "low",
            },
        ],
        None,
        cli_version=None,
    )
    current = {**controls.blank_settings(), "actual": {"model": "big", "effort": "high"}}
    chosen, notes = controls.validate_choice(cat, current, {"model": "mini"}, harness=CODEX)
    assert chosen == {"model": "mini", "effort": "low"} and "默认强度" in notes[0]
    current = {**controls.blank_settings(), "actual": {"model": "big", "effort": "low"}}
    chosen, notes = controls.validate_choice(cat, current, {"model": "mini"}, harness=CODEX)
    assert chosen == {"model": "mini"} and notes == []


def test_host_reports_are_matched_without_guessing() -> None:
    cat = claude_cat()
    assert controls.model_matches(cat, "default", "claude-x-opus")
    assert controls.model_matches(cat, "sonnet", "claude-x-sonnet[1m]")
    assert controls.model_matches(cat, "sonnet", "sonnet")
    assert not controls.model_matches(cat, "sonnet", "claude-x-opus")
    assert not controls.model_matches(cat, "sonnet", None)
    assert controls.codex_mode_of("on-request", {"type": "readOnly"}) == "read-only"
    assert controls.codex_mode_of("on-request", "workspace-write") == "workspace"
    assert controls.codex_mode_of("never", {"type": "dangerFullAccess"}) is None
    assert "完全访问" in controls.describe_codex_mode("never", {"type": "dangerFullAccess"})
    assert "approval=untrusted" in controls.describe_codex_mode("untrusted", {"type": "readOnly"})


def test_terminal_flags_carry_only_explicit_choices_and_never_skip_approval() -> None:
    assert claude_setting_flags({}) == []
    assert claude_setting_flags({"model": "sonnet", "effort": "high", "mode": "plan"}) == [
        "--model",
        "sonnet",
        "--effort",
        "high",
        "--permission-mode",
        "plan",
    ]
    assert claude_setting_flags({"mode": "bypassPermissions"}) == []
    assert codex_setting_flags({"model": "a", "effort": "low", "mode": "read-only"}) == [
        "-m",
        "a",
        "-c",
        'model_reasoning_effort="low"',
        "-a",
        "on-request",
        "-s",
        "read-only",
    ]
    assert codex_setting_flags({"mode": "full"}) == []


def test_mcp_forms_supported_shapes_and_typed_answers() -> None:
    params = {
        "mode": "form",
        "message": "m",
        "requestedSchema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer"},
                "f": {"type": "number"},
                "b": {"type": "boolean"},
                "c": {"type": "string", "oneOf": [{"const": "x", "title": "X"}]},
            },
            "required": ["n"],
        },
    }
    form = elicitation_form(params)
    assert form is not None and [f["name"] for f in form["fields"]] == ["n", "f", "b", "c"]
    assert form["fields"][3]["choices"] == [{"value": "x", "label": "X"}]
    response = codex_permission_response(
        "mcpServer/elicitation/request", "accept", params, {"n": "2", "f": "1.5", "b": "true"}
    )
    assert response == {"action": "accept", "content": {"n": 2, "f": 1.5, "b": True}}
    with pytest.raises(ValueError, match="整数"):
        codex_permission_response("mcpServer/elicitation/request", "accept", params, {"n": "2.5"})
    assert codex_permission_response("mcpServer/elicitation/request", "cancel", params) == {
        "action": "cancel"
    }
    arrays = {**params, "requestedSchema": {"properties": {"t": {"type": "array"}}}}
    assert elicitation_form(arrays) is None
    assert elicitation_form({"mode": "url", "url": "javascript:alert(1)"}) is None
    url = elicitation_form({"mode": "url", "url": "https://example.com/x"})
    assert url == {"mode": "url", "url": "https://example.com/x", "fields": []}
    assert elicitation_form({"mode": "openai/form"}) is None


def test_question_answers_map_to_codex_ids() -> None:
    params = {"questions": [{"id": "a", "question": "?"}, {"id": "b", "question": "?"}]}
    out = codex_permission_response(
        "item/tool/requestUserInput", "answer", params, {"a": ["x", "y"], "b": ""}
    )
    assert out == {"answers": {"a": {"answers": ["x", "y"]}, "b": {"answers": []}}}
    assert codex_permission_response("item/tool/requestUserInput", "deny", params) == {
        "answers": {}
    }


def test_attachment_and_file_search_helpers() -> None:
    assert _image_mime(b"\x89PNG\r\n\x1a\n...") == "image/png"
    assert _image_mime(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
    assert _image_mime(b"GIF89a") == "image/gif"
    assert _image_mime(b"<svg>") is None
    assert _safe_name("../../etc/passwd") == "passwd"
    assert _safe_name(".env") == "_.env"
    assert _safe_name("") == "附件"
    assert _fuzzy("", "x") == 0
    assert _fuzzy("led", "src/ledger.py") == 0
    assert _fuzzy("src", "src/ledger.py") == 50
    assert _fuzzy("slp", "src/ledger.py") is not None and _fuzzy("zz", "src/ledger.py") is None
    assert CODEX != CLAUDE


def test_history_shows_attachments_as_chips_and_the_model_of_each_reply(tmp_path: Path) -> None:
    import json as _json

    from harness_bridge.workbench.conversation import _user_inputs, claude_transcript_items

    att = "/s/workbench/attachments/ses_x/att_1/billing.log"
    lines = [
        {
            "type": "user",
            "uuid": "u1",
            "message": {
                "content": [
                    {"type": "text", "text": f'看看这个\n\n附件：@"{att}"'},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png"}},
                ]
            },
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "message": {"model": "claude-x", "content": [{"type": "text", "text": "好的"}]},
        },
        {"type": "user", "uuid": "u2", "message": {"content": 'not ours\n\n附件：@"/etc/hosts"'}},
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(_json.dumps(x, ensure_ascii=False) for x in lines))
    out = claude_transcript_items(path)
    first, _reply, end, second = out
    assert first["text"] == "看看这个"
    assert [(a["kind"], a["name"]) for a in first["attachments"]] == [
        ("image", "图片"),
        ("file", "billing.log"),
    ]
    assert end == {**end, "type": "turn_end", "model": "claude-x"}
    # A mention RepoBridge did not add stays as the user wrote it.
    assert second["text"].endswith('@"/etc/hosts"') and second["attachments"] == []
    text, chips = _user_inputs(
        [
            {"type": "text", "text": f"读一下\n\n附件文件（请读取）：\n- {att}"},
            {"type": "localImage", "path": "/a/b.png"},
        ]
    )
    assert text == "读一下" and [c["name"] for c in chips] == ["b.png", "billing.log"]
