"""Internal detached worker entrypoint; requires an already authorized durable reservation."""

from __future__ import annotations

import argparse
from pathlib import Path

from harness_bridge.cli import _install_signal_handlers
from harness_bridge.service import Bridge, StopFlag


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    flag = StopFlag()
    _install_signal_handlers(flag)
    bridge = Bridge(args.state_dir, stop_flag=flag)
    try:
        return 0 if bridge.jobs.execute(args.job_id) else 1
    finally:
        bridge.close()


if __name__ == "__main__":
    raise SystemExit(main())
