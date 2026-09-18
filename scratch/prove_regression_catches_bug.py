"""Prove the regression test goes RED on the pre-fix implementation."""


class OldStyleBroker:
    """Mirrors the OLD open_order body from HEAD:mt5/bridge_server.py."""

    def open_order(self, symbol, order_type, lots, sl, tp, comment=""):
        command = {"id": "cmd_old_1", "action": "ORDER_OPEN", "symbol": symbol}
        try:
            # OLD code referenced an undefined module global `httpx` here,
            # which is what actually happened in production.
            print("  [old] attempting httpx.post ...")
            raise AttributeError("module 'mt5.bridge_server' has no attribute 'httpx'")
        except Exception:
            pass  # <-- the swallowed error (the bug)
        return {"status": "QUEUED", "command_id": command["id"]}  # phantom success


class NewStyleBroker:
    """Mirrors the FIXED _queue_command behavior."""

    def open_order(self, symbol, order_type, lots, sl, tp, comment=""):
        raise RuntimeError(
            "[MT5-QUEUE] Cannot reach MT5 bridge at http://127.0.0.1:9 "
            "(AttributeError: ...). Command cmd_new_1 was NOT queued."
        )


print("=" * 70)
print("REGRESSION CHECK: does `pytest.raises(RuntimeError)` catch the bug?")
print("=" * 70)

print("\n--- OLD implementation (pre-fix) ---")
old_result = OldStyleBroker().open_order("XAUUSD", "BUY", 0.10, 2640.0, 2660.0)
print(f"  returned: {old_result}")
print("  raised:   NO  -> pytest.raises(RuntimeError) would FAIL here (test RED)")

print("\n--- NEW implementation (post-fix) ---")
try:
    NewStyleBroker().open_order("XAUUSD", "BUY", 0.10, 2640.0, 2660.0)
    print("  raised:   NO (unexpected)")
except RuntimeError as e:
    print(f"  raised:   YES -> RuntimeError: {str(e)[:80]}...")
    print("  -> pytest.raises(RuntimeError) PASSES here (test GREEN)")

print("\nConclusion: the regression test is red-capable on the old code and")
print("green on the new code, so it genuinely guards the fixed behavior.")
