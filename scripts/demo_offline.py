"""Run both offline demos and print a compact report. Exit status 0 only if both pass.

Usage: uv run python scripts/demo_offline.py [--keep]
No model is invoked; the executor is the bundled fake subprocess.
"""

from __future__ import annotations

import argparse
import json
import sys

from harness_bridge.demo import DEMO_SCENARIOS, run_demo


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep the demo directories")
    args = parser.parse_args()
    ok = True
    for scenario in DEMO_SCENARIOS:
        report = run_demo(scenario, cleanup=not args.keep)
        ok &= bool(report.get("demo_passed"))
        print(
            json.dumps(
                {
                    "scenario": scenario,
                    "demo_passed": report.get("demo_passed"),
                    "final_state": report.get("final_state"),
                    "timeline": report.get("timeline"),
                    "checks": report.get("checks"),
                    "workdir": report.get("workdir"),
                    "error": report.get("error"),
                },
                indent=2,
            )
        )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
