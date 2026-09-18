"""
TIGHT REPRO: why order dispatch silently fails.

Run inside the squad container:
    docker exec agentic_squad_agent python3 scratch/repro_order_dispatch.py
"""

import sys
import traceback

import mt5.bridge_server as bs
from mt5.bridge_server import MT5BridgeBroker

print("=" * 72)
print("STEP 1: is `httpx` bound in mt5.bridge_server's module namespace?")
print("=" * 72)
print(f"  hasattr(bs, 'httpx')  = {hasattr(bs, 'httpx')}")
try:
    import httpx  # noqa: F401
    print("  import httpx standalone = OK (package installed)")
except Exception as e:
    print(f"  import httpx standalone = FAILED: {e}")

print()
print("=" * 72)
print("STEP 2: call the exact line every broker method relies on")
print("=" * 72)
try:
    bs.httpx.get("http://bridge:8000/api/mt5/status", timeout=3.0)
    print("  bs.httpx.get(...) = OK")
except Exception as e:
    print(f"  bs.httpx.get(...) RAISES -> {type(e).__name__}: {e}")

print()
print("=" * 72)
print("STEP 3: what does open_order() RETURN for the caller?")
print("=" * 72)
broker = MT5BridgeBroker()
before = len(bs._pending_commands)
res = broker.open_order("XAUUSD", "BUY", 0.01, 2600.0, 2650.0, "REPRO")
after = len(bs._pending_commands)

print(f"  open_order() returned : {res}")
print(f"  local _pending_commands: {before} -> {after}  (delta +{after - before})")
print()
print("  ^ The caller sees status=QUEUED and believes the order was dispatched.")
print("    But it was appended to THIS process's in-memory list, which the MT5")
print("    EA in the *bridge* container can never read.")

print()
print("=" * 72)
print("STEP 4: can this process reach the bridge over REST at all?")
print("=" * 72)
try:
    import httpx as real_httpx
    r = real_httpx.get("http://bridge:8000/api/mt5/status", timeout=3.0)
    print(f"  real httpx get status={r.status_code} body={r.text[:120]}")
    print("  -> Bridge is reachable. Fixing the import is sufficient.")
except Exception as e:
    print(f"  RAISED: {type(e).__name__}: {e}")

print()
print("=" * 72)
print("STEP 5: silently-swallowed exceptions (bare except Exception: pass)")
print("=" * 72)
import inspect
src = inspect.getsource(bs.MT5BridgeBroker.open_order)
print(src)
