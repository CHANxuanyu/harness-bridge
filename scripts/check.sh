#!/usr/bin/env bash
# Offline checks: lint, type check, tests (live tests excluded). No network, no model calls.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src/harness_bridge
uv run --frozen pytest -m "not live" "$@"
