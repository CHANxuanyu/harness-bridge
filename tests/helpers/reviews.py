from __future__ import annotations

from typing import Any


def review_for(summary: dict[str, Any], verdict: str, key: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        **summary["review_template"],
        "verdict": verdict,
        "idempotency_key": key,
    }
    if verdict != "approve":
        body["findings"] = [
            {"severity": "blocking", "explanation": "fix it", "requested_change": "do better"}
        ]
    body.update(extra)
    return body
