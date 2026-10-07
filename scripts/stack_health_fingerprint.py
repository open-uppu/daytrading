#!/usr/bin/env python3
"""Deterministic health fingerprint for the daytrad stack.

Used as the `monitor` of the daytrad cron job: its stdout is diffed against the
previous tick, so it must be byte-stable while the stack is in the same state.

Two things that would otherwise wake the agent on EVERY tick and burn tokens:
  * numbers that drift on their own (heartbeat age, bar age, drawdown %,
    error-line counts, restart uptimes)
  * line ordering
So the problem text is normalized: every digit run collapses to `N`. The alert
message the user receives still carries the real numbers, because that is built
from check_stack_health.py's own output, not from this fingerprint.

Always exits 0 -- a non-zero exit is read by the scheduler as "monitor source
failed", which suppresses the agent run instead of reporting the problem.
"""
from __future__ import annotations

import importlib.util
import io
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

HEALTH = Path(__file__).with_name("check_stack_health.py")
DIGITS = re.compile(r"\d+")


def main() -> int:
    spec = importlib.util.spec_from_file_location("_stack_health", HEALTH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    buf = io.StringIO()
    with redirect_stdout(buf):
        spec.loader.exec_module(mod)
        code = mod.main()

    verdict = "OK" if code == 0 else ("DEGRADED" if code == 1 else "DOWN")
    print(f"verdict={verdict}")

    seen = set()
    for line in buf.getvalue().splitlines():
        stripped = line.strip()
        if not stripped.startswith("* "):
            continue
        normalized = DIGITS.sub("N", stripped)
        if normalized in seen:  # collapse duplicates that only differ by numbers
            continue
        seen.add(normalized)
        print(normalized)
    return 0


if __name__ == "__main__":
    sys.exit(main())
