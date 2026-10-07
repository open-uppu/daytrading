#!/usr/bin/env python3
"""Health check for the daytrad docker stack (bridge + squad).

Run standalone:
    python3 scripts/check_stack_health.py

Exit codes: 0 = OK, 1 = DEGRADED, 2 = DOWN.
Prints a short human/Markdown report on stdout (used verbatim by cron).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

PROJECT = "/Users/up-mac/wokrspace/mind/trader/daytrad"
BRIDGE_URL = "http://127.0.0.1:8000"
BRIDGE_CONTAINER = "agentic_mt5_bridge"
SQUAD_CONTAINER = "agentic_squad_agent"
SYMBOLS = ("XAUUSD", "BTCUSD", "ETHUSD")
TIMEFRAME = "M15"
BAR_MAX_AGE_SEC = 300  # M15 bars should arrive well under one bar period
SYNC_MAX_AGE_SEC = 300  # EA telemetry heartbeat freshness
ERROR_PATTERNS = re.compile(
    r"(Traceback \(most recent call last\)|\bCRITICAL\b|\bERROR\b"
    r"|ConnectionError|Max retries|circuit breaker|TARGET_REACHED|LOSS_CUTOFF)",
    re.IGNORECASE,
)
# MT5 retcode 10027 = TRADE_RETCODE_CLIENT_DISABLES_AT: the terminal's
# AutoTrading button is off.  Not a code bug -- it needs a human at the
# terminal, so it gets its own actionable message.
AUTOTRADING_OFF = re.compile(r"10027|CLIENT_DISABLES_AT|auto-?trading disabled", re.IGNORECASE)

problems: list[str] = []
warnings: list[str] = []
lines: list[str] = []


def sh(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return 1, f"{type(exc).__name__}: {exc}"


def get_json(path: str) -> tuple[dict | None, str | None]:
    try:
        with urllib.request.urlopen(f"{BRIDGE_URL}{path}", timeout=8) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def container_state(name: str) -> str:
    rc, out = sh(["docker", "inspect", "-f",
                  "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}|{{.State.StartedAt}}",
                  name])
    if rc != 0:
        return "missing"
    return out.strip()


def main() -> int:
    now = time.time()

    # --- 1. containers -------------------------------------------------
    for label, name in (("bridge", BRIDGE_CONTAINER), ("squad", SQUAD_CONTAINER)):
        state = container_state(name)
        if state == "missing":
            problems.append(f"{label} container `{name}` not found")
            lines.append(f"- {label}: MISSING")
            continue
        status, health, started = (state.split("|") + ["", ""])[:3]
        lines.append(f"- {label}: {status} (health={health})")
        if status != "running":
            problems.append(f"{label} container status={status}")
        if health not in ("healthy", "n/a"):
            problems.append(f"{label} health={health}")
        # Restart loop detection: StartedAt within 90s while also unhealthy is a
        # real signal; a healthy just-restarted container is only a warning.
        try:
            started_ts = time.mktime(time.strptime(started[:19], "%Y-%m-%dT%H:%M:%S"))
            if now - started_ts < 90 and health != "healthy":
                warnings.append(f"{label} restarted {int(now - started_ts)}s ago")
        except Exception:  # noqa: BLE001
            pass

    # --- 2. bridge HTTP -------------------------------------------------
    status_json, err = get_json("/api/mt5/status")
    if err or status_json is None:
        problems.append(f"bridge /api/mt5/status unreachable: {err}")
        lines.append(f"- bridge HTTP: UNREACHABLE ({err})")
    else:
        st = status_json
        connected = bool(st.get("connected"))
        lines.append(f"- bridge HTTP: ONLINE, MT5 connected={connected}")
        if not connected:
            problems.append("bridge reports MT5 not connected (EA not pushing telemetry)")

        last_sync = st.get("last_sync")
        if last_sync:
            try:
                from datetime import datetime, timezone
                ts = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - ts).total_seconds()
                lines.append(f"- EA heartbeat: {int(age)}s ago "
                             f"(equity={st.get('equity')}, "
                             f"acct={st.get('account_number')})")
                if age > SYNC_MAX_AGE_SEC:
                    problems.append(f"EA heartbeat stale ({int(age)}s)")
            except Exception:  # noqa: BLE001
                warnings.append(f"unparsable last_sync={last_sync!r}")
        else:
            problems.append("bridge has no last_sync (no telemetry received)")

        md = st.get("market_data") or {}
        stale = []
        missing = []
        for sym in SYMBOLS:
            entry = md.get(f"{sym}:{TIMEFRAME}")
            if not entry:
                missing.append(sym)
                continue
            if entry.get("bars", 0) < 100:
                problems.append(f"{sym} only {entry.get('bars')} bars cached")
            if not entry.get("fresh") or entry.get("age_sec", 0) > BAR_MAX_AGE_SEC:
                stale.append(f"{sym}({entry.get('age_sec')}s)")
        if missing:
            problems.append(f"no cached bars for {', '.join(missing)}")
        if stale:
            problems.append(f"stale bars: {', '.join(stale)}")
        lines.append(f"- bars cached: {len(md)} keys"
                     + (f", stale={','.join(stale)}" if stale else ", all fresh"))

    # --- 3. squad behaviour --------------------------------------------
    rc, logs = sh(["docker", "logs", "--since", "10m", SQUAD_CONTAINER], timeout=30)
    if rc == 0 and logs:
        errs = [ln.strip() for ln in logs.splitlines() if ERROR_PATTERNS.search(ln)]
        retcode_10027 = bool(AUTOTRADING_OFF.search(logs))
        if errs:
            sev = "DEGRADED" if retcode_10027 else "ERROR"
            problems.append(
                f"squad logged {len(errs)} {sev} line(s)"
                + (" — MT5 retcode 10027 (AutoTrading disabled in the terminal EA)"
                   if retcode_10027 else "")
            )
            lines.append("- squad errors (last 10m):")
            lines.extend(f"    {e[:200]}" for e in errs[:3])
        else:
            lines.append("- squad logs (last 10m): no errors")

        # The squad also polls /account several times per loop iteration, so a
        # low count is normal while it is simply scanning; only a zero count
        # proves the loop stopped.
        polls = len(re.findall(r"GET http://bridge:8000/api/mt5/account", logs))
        lines.append(f"- squad→bridge poll loop: {polls} account calls in last 10m")
        if polls == 0:
            problems.append("squad not polling the bridge (no account calls in 10m)")

    # --- 4. live account / open positions -------------------------------
    acct, err = get_json("/api/mt5/account")
    if err or acct is None:
        problems.append(f"bridge /api/mt5/account unreachable: {err}")
    else:
        positions = acct.get("open_positions") or []
        balance = acct.get("balance") or 0.0
        equity = acct.get("equity") or 0.0
        lines.append(f"- account: balance={balance} equity={equity} "
                     f"open_positions={len(positions)}")
        if balance:
            dd_pct = (balance - equity) / balance * 100.0
            if dd_pct >= 3.0:
                problems.append(f"floating drawdown {dd_pct:.2f}% (>= 3% of balance)")
            elif dd_pct >= 2.0:
                warnings.append(f"floating drawdown {dd_pct:.2f}%")
        for pos in positions:
            if not pos.get("sl"):
                warnings.append(f"position #{pos.get('ticket')} has no stop-loss")

    # --- report ---------------------------------------------------------
    worst = 2 if any("MISSING" in p or "unreachable" in p or "not found" in p
                     or "not connected" in p or "status=" in p for p in problems) else 0
    head = "DOWN" if worst == 2 else ("DEGRADED" if problems else "OK")

    print(f"daytrad stack: {head}")
    print(f"checked {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n".join(lines))
    if problems:
        print("\nPROBLEMS:")
        print("\n".join(f"  * {p}" for p in problems))
    if warnings:
        print("\nWARNINGS:")
        print("\n".join(f"  - {w}" for w in warnings))
    if not problems and not warnings:
        print("\nno issues")

    return worst or (0 if not problems else 1)


if __name__ == "__main__":
    sys.exit(main())
