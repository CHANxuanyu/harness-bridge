"""Local diagnostics, opt-in product events and operation correlation for RepoBridge.

Everything stays on this machine. Diagnostics (fault records) are on by default; product events
are off by default. Records carry only whitelisted metadata (enums, counts, durations, stable error
codes and keyed local aliases) — never prompts, conversation/tool text, attachment content, paths,
URLs, headers, environment values, native session IDs or raw exception text.
See docs/OBSERVABILITY_EVENTS.md.
"""

from harness_bridge.observability.recorder import Observability, current_op
from harness_bridge.observability.schema import EVENTS, SCHEMA_VERSION

__all__ = ["EVENTS", "SCHEMA_VERSION", "Observability", "current_op"]
