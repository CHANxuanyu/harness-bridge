import harness_bridge
from harness_bridge.errors import BridgeError, known_codes


def test_package_version_and_schema() -> None:
    assert harness_bridge.__version__.startswith("0.1.")
    assert harness_bridge.SCHEMA_VERSION == "1.0"


def test_error_structure_is_uniform() -> None:
    err = BridgeError("STATE_CONFLICT", "task is not READY", task_id="t1")
    payload = err.to_dict()
    assert payload == {
        "code": "STATE_CONFLICT",
        "message": "task is not READY",
        "retryable": True,
        "task_id": "t1",
    }
    assert err.exit_status == 3
    assert "LIVE_GATE_CLOSED" in known_codes()
