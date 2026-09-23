# Multi-Timeframe Agent Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let independent, permanent per-timeframe instances of the same specialist agent (e.g. Gold-M5 and Gold-M15) trade concurrently on the same MT5 account without corrupting each other's position management, PnL accounting, or journal state.

**Architecture:** Every timeframe-instance gets two independent, deterministic identifiers — a `journal_dir` (already partially wired) and an MT5 `magic` number (new). The magic number is threaded end-to-end: Python assigns it per order, the EA stamps it on the resulting MT5 position/deal, and every read path (open positions, closed-order history) filters by it so one instance only ever sees and manages its own trades.

**Tech Stack:** Python (FastAPI bridge server, existing agent/broker classes), MQL5 (`AgenticMT5Bridge.mq5`), pytest.

## Global Constraints

- The live M5 instance's magic number **must stay 888999** — this is the value already in use by real open positions on the account right now (`mt5/AgenticMT5Bridge.mq5:18`, `InpMagicNumber = 888999`). Nothing in this plan may change what magic the M5 instance uses.
- The live M5 instance's `journal_dir` **must stay `journal/{symbol}/`** (unchanged path) — no flag change should be required to keep today's production M5 squad running exactly as it does now.
- Every Python broker class (`PaperTradingBroker`, `MT5BridgeBroker`, `MT4BridgeBroker`) must accept the same `magic` keyword on `open_order`/`close_order`/`modify_order` — `agents/base_agent.py` calls all three polymorphically through `BaseBroker`, so a signature gap on any one of them is a `TypeError` at runtime, not a design choice.
- `PaperTradingBroker.open_order`'s `magic` parameter defaults to `888999`, not `None` — 19 existing test call sites across 8 test files call `broker.open_order(...)` directly without a `magic` argument and then rely on an agent (which defaults `self.magic` to `888999`) to see that position. If the broker default were `None`, every one of those tests would break on a silent `None != 888999` mismatch.
- Run `pytest tests/ -q` after every task and keep it green before moving to the next task.
- Out of scope (do not implement): relaxing `SPECIALIST_REGISTRY`'s `forced_timeframe="M15"` pin for xag/gbp/eur/xpt/ukoil/xng; any backtest validation of new symbol/timeframe combinations; any change to how `close_order`/`modify_order` commands are keyed (ticket already uniquely identifies a position — magic there is only used by the EA to enforce ownership, not to look the position up); a cross-instance shared position cap.

---

## File Structure

| File | Responsibility in this plan |
|---|---|
| `mt4/broker_interface.py` | `BaseBroker` ABC — add `magic` param to `open_order`/`close_order`/`modify_order` |
| `mt4/paper_broker.py` | `PaperTradingBroker` — store/filter `magic` in-memory |
| `mt4/bridge_server.py` | `MT4BridgeBroker` — signature compatibility only (Python side; no MQL4 change) |
| `mt5/bridge_server.py` | `MT5BridgeBroker` + FastAPI bridge — thread `magic` into queued commands and fix the destructive shared `recently_closed` pop |
| `mt5/AgenticMT5Bridge.mq5` | EA — apply per-command magic on order open/close/modify; stop filtering telemetry to a single hardcoded magic |
| `agents/base_agent.py` | `BaseSpecialistAgent` — `magic` identity, position filtering, pass `magic` on every broker call |
| `agents/squad_manager.py` | Deterministic `TIMEFRAME_MAGIC` table; thread `magic` + `journal_dir` into each specialist |
| `main.py` | `cmd_loop` — auto-derive `journal_dir` from timeframe, thread it to `SquadManager`, expand `--timeframe` choices |

---

## Task 1: `PaperTradingBroker` + `BaseBroker` interface — magic support

**Files:**
- Modify: `mt4/broker_interface.py:24-34` (`open_order`), `:37-39` (`close_order`), `:41-43` (`modify_order`)
- Modify: `mt4/paper_broker.py:87-118` (`open_order`), `:120-153` (`close_order`), `:161-169` (`modify_order`), `:183-187` (`consume_recently_closed`)
- Test: `tests/test_paper_broker.py`

**Interfaces:**
- Produces: `PaperTradingBroker.open_order(..., magic: int = 888999)` stores `"magic"` on the position dict. `PaperTradingBroker.consume_recently_closed(symbol=None, magic=None)` — when `magic` is given, only pops entries matching both `symbol` (if given) and `magic`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_paper_broker.py`:

```python
def test_paper_broker_filters_recently_closed_by_magic():
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="XAUUSD")

    entry = broker.current_price
    res_a = broker.open_order(symbol="XAUUSD", order_type="BUY", lots=0.1,
                               sl=entry - 5.0, tp=entry + 10.0, magic=888999)
    res_b = broker.open_order(symbol="XAUUSD", order_type="BUY", lots=0.1,
                               sl=entry - 5.0, tp=entry + 10.0, magic=888915)

    # Close both by pushing price through both take-profits.
    broker.simulate_price_update(new_high=entry + 11.0, new_low=entry, new_close=entry + 10.5)
    assert len(broker.get_open_positions()) == 0

    only_a = broker.consume_recently_closed(symbol="XAUUSD", magic=888999)
    assert [o["ticket"] for o in only_a] == [res_a["ticket"]]

    only_b = broker.consume_recently_closed(symbol="XAUUSD", magic=888915)
    assert [o["ticket"] for o in only_b] == [res_b["ticket"]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_paper_broker.py::test_paper_broker_filters_recently_closed_by_magic -v`
Expected: FAIL with `TypeError: open_order() got an unexpected keyword argument 'magic'`

- [ ] **Step 3: Write minimal implementation**

In `mt4/broker_interface.py`, update the three abstract methods:

```python
    @abstractmethod
    def open_order(
        self,
        symbol: str,
        order_type: str,
        lots: float,
        sl: float,
        tp: float,
        comment: str = "",
        magic: Optional[int] = None
    ) -> Dict[str, Any]:
        """Submits a BUY or SELL market order."""
        pass

    @abstractmethod
    def close_order(self, ticket: int, magic: Optional[int] = None) -> Dict[str, Any]:
        """Closes an open position by ticket."""
        pass

    @abstractmethod
    def modify_order(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None,
                      magic: Optional[int] = None) -> Dict[str, Any]:
        """Modifies SL and/or TP for an open position."""
        pass
```

In `mt4/paper_broker.py`, update `open_order` (add the param, default `888999` — see Global Constraints — and store it on the position dict):

```python
    def open_order(
        self,
        symbol: str,
        order_type: str,
        lots: float,
        sl: float,
        tp: float,
        comment: str = "",
        magic: int = 888999
    ) -> Dict[str, Any]:
        """Executes a market order with simulated spread."""
        bid = self.current_price - (self.spread / 2)
        ask = self.current_price + (self.spread / 2)

        fill_price = ask if order_type == "BUY" else bid
        ticket = self.next_ticket
        self.next_ticket += 1

        position = {
            "ticket": ticket,
            "symbol": symbol,
            "type": order_type,
            "lots": lots,
            "open_price": round(fill_price, 2),
            "open_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "comment": comment,
            "magic": magic,
            "unrealized_pnl": 0.0
        }

        self.open_positions[ticket] = position
        logger.info(f"[PAPER] Opened #{ticket} {order_type} {lots} lots at {fill_price:.2f} (SL: {sl:.2f}, TP: {tp:.2f})")
        return {"status": "SUCCESS", "ticket": ticket, "fill_price": fill_price}
```

Update `close_order` to accept (and ignore — ticket already uniquely identifies the position in-memory) `magic`, and carry the position's own stored `"magic"` into the closed record:

```python
    def close_order(self, ticket: int, exit_reason: str = "MANUAL_CLOSE", magic: Optional[int] = None) -> Dict[str, Any]:
        """Closes an open order and updates realized account balance."""
        if ticket not in self.open_positions:
            return {"status": "ERROR", "message": f"Position #{ticket} not found"}

        pos = self.open_positions.pop(ticket)
        bid = self.current_price - (self.spread / 2)
        ask = self.current_price + (self.spread / 2)
        close_price = bid if pos["type"] == "BUY" else ask

        if pos["type"] == "BUY":
            pnl_usd = (close_price - pos["open_price"]) * pos["lots"] * self.contract_size
        else:
            pnl_usd = (pos["open_price"] - close_price) * pos["lots"] * self.contract_size

        pnl_usd = round(pnl_usd, 2)
        pnl_pct = round((pnl_usd / self.balance) * 100.0, 2)
        self.balance += pnl_usd
        self._update_equity()

        closed_record = {
            "ticket": ticket,
            "symbol": pos["symbol"],
            "type": pos["type"],
            "lots": pos["lots"],
            "open_price": pos["open_price"],
            "close_price": round(close_price, 2),
            "open_time": pos["open_time"],
            "close_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sl": pos["sl"],
            "tp": pos["tp"],
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "exit_reason": exit_reason,
            "comment": pos["comment"],
            "magic": pos.get("magic", 888999)
        }

        self.closed_orders.append(closed_record)
        self.recently_closed_orders.append(closed_record)
        logger.info(f"[PAPER] Closed #{ticket} at {close_price:.2f} | Reason: {exit_reason} | PnL: ${pnl_usd:+.2f}")
        return {"status": "SUCCESS", "closed_order": closed_record}
```

Update `modify_order` to accept (and ignore) `magic`:

```python
    def modify_order(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None,
                      magic: Optional[int] = None) -> Dict[str, Any]:
        """Updates SL/TP of an active position."""
        if ticket not in self.open_positions:
            return {"status": "ERROR", "message": "Position not found"}
        if sl is not None:
            self.open_positions[ticket]["sl"] = round(sl, 2)
        if tp is not None:
            self.open_positions[ticket]["tp"] = round(tp, 2)
        return {"status": "SUCCESS", "position": self.open_positions[ticket]}
```

Update `consume_recently_closed` to also filter by `magic` when given:

```python
    def consume_recently_closed(self, symbol: Optional[str] = None, magic: Optional[int] = None) -> List[Dict[str, Any]]:
        """Pops and returns closed orders that haven't been reflected upon yet
        (only `symbol`'s / `magic`'s when given)."""
        recent = [
            o for o in self.recently_closed_orders
            if (not symbol or o.get("symbol") == symbol)
            and (magic is None or o.get("magic") == magic)
        ]
        self.recently_closed_orders[:] = [o for o in self.recently_closed_orders if o not in recent]
        return recent
```

Also find `simulate_price_update`'s call into `close_order` (it triggers automatic SL/TP fills) and make sure it forwards the position's own `magic` so the closed record is correctly tagged even on an automatic TP/SL exit:

```bash
grep -n "close_order(ticket" mt4/paper_broker.py
```

Update that call site to pass `magic=pos.get("magic", 888999)` alongside its existing arguments (read the surrounding ~10 lines first — the exact call already has `exit_reason=` as a kwarg; add `magic=` the same way).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_paper_broker.py -v`
Expected: All PASS, including the new test and the pre-existing `test_paper_broker_order_lifecycle`.

- [ ] **Step 5: Run the full suite to confirm no regressions from the interface change**

Run: `pytest tests/ -q`
Expected: All PASS (this touches `BaseBroker`, which every broker/agent test depends on).

- [ ] **Step 6: Commit**

```bash
git add mt4/broker_interface.py mt4/paper_broker.py tests/test_paper_broker.py
git commit -m "feat(broker): add magic-number support to BaseBroker and PaperTradingBroker

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: `MT4BridgeBroker` — signature compatibility

**Files:**
- Modify: `mt4/bridge_server.py` (`MT4BridgeBroker.open_order`, `close_order`, `modify_order` — find exact lines with `grep -n "def open_order\|def close_order\|def modify_order" mt4/bridge_server.py`)
- Test: `tests/test_paper_broker.py` (existing `test_mt4_bridge_api` covers this file; extend it)

**Interfaces:**
- Produces: `MT4BridgeBroker.open_order(..., magic: Optional[int] = None)` includes `"magic": magic` in the queued command dict only when `magic is not None` (omitting the key preserves today's exact wire shape when unused). `close_order`/`modify_order` accept `magic: Optional[int] = None` and forward it the same way. No MT4 EA (`.mq4`) changes — MT4 mode has no automated test coverage of live execution and is out of scope for this plan's EA work.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_paper_broker.py`:

```python
def test_mt4_bridge_open_order_accepts_magic_kwarg():
    broker = MT4BridgeBroker(in_process=True)
    # Must not raise TypeError -- agents/base_agent.py always passes magic=.
    response = broker.open_order(
        symbol="XAUUSD", order_type="BUY", lots=0.01,
        sl=1990.0, tp=2015.0, magic=888915, await_confirm=False
    )
    assert response["status"] == "QUEUED"
```

Check `MT4BridgeBroker.__init__` supports `in_process=True` first:

```bash
grep -n "def __init__" -A 15 mt4/bridge_server.py | head -20
```

If it doesn't support `in_process`, use whatever construction pattern the existing `test_mt4_bridge_api` test in the same file already uses instead (read that test first — it's right above where you're adding this one).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_paper_broker.py::test_mt4_bridge_open_order_accepts_magic_kwarg -v`
Expected: FAIL with `TypeError: open_order() got an unexpected keyword argument 'magic'`

- [ ] **Step 3: Write minimal implementation**

In `mt4/bridge_server.py`, update `MT4BridgeBroker.open_order` (keep every existing param, add `magic` last, and only add the key to the command dict when provided):

```python
    def open_order(
        self,
        symbol: str,
        order_type: str,
        lots: float,
        sl: float,
        tp: float,
        comment: str = "",
        await_confirm: bool = True,
        confirm_timeout: float = 10.0,
        magic: Optional[int] = None
    ) -> Dict[str, Any]:
        """Queues an open command for the MT4 EA and waits for confirmation."""
        cmd_id = f"cmd_{self.cmd_counter}_{int(pd.Timestamp.now().timestamp())}"
        self.cmd_counter += 1

        command = {
            "id": cmd_id,
            "action": "ORDER_OPEN",
            "symbol": symbol,
            "type": order_type,
            "volume": lots,
            "sl": sl,
            "tp": tp,
            "comment": comment
        }
        if magic is not None:
            command["magic"] = magic
        # ... rest of the method unchanged from here (queue + await confirmation)
```

Read the rest of the method (`grep -n "def open_order" -A 40 mt4/bridge_server.py`) and keep everything after the command dict construction exactly as it is today — only the signature and the `if magic is not None` block are new.

Apply the same pattern (`magic: Optional[int] = None` param, `if magic is not None: command["magic"] = magic`) to `close_order` and `modify_order` in the same file — find them with `grep -n "def close_order\|def modify_order" mt4/bridge_server.py` and read each one fully before editing, since the exact surrounding code must be preserved.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_paper_broker.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add mt4/bridge_server.py tests/test_paper_broker.py
git commit -m "feat(broker): accept magic kwarg on MT4BridgeBroker for interface parity

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: `MT5BridgeBroker` + `mt5/bridge_server.py` — magic threading and the recently-closed fix

**Files:**
- Modify: `mt5/bridge_server.py:292-305` (`get_recently_closed`, `_pop_recently_closed`), `:513-560` (`open_order`), `:558-585` (`close_order`), `:587-615` (`modify_order`), `:644-656` (`get_open_positions`, `consume_recently_closed`)
- Test: `tests/test_mt5_bridge.py`

**Interfaces:**
- Produces: `GET /api/mt5/recently_closed?symbol=X&magic=Y` pops only entries matching both when `magic` is given. `MT5BridgeBroker.open_order(..., magic: Optional[int] = None)`, `.close_order(ticket, magic=None, ...)`, `.modify_order(ticket, ..., magic=None)`, `.consume_recently_closed(symbol=None, magic=None)` all thread `magic` through to the wire, included in the command/query only when not `None`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mt5_bridge.py`:

```python
def test_pop_recently_closed_scopes_by_magic_not_just_symbol():
    """Regression guard: two same-symbol timeframe-instances must not steal
    each other's closed-trade records out of the shared queue."""
    bridge_server._mt5_state["recently_closed"] = [
        {"ticket": 1, "symbol": "XAUUSD", "magic": 888999, "pnl_usd": 12.5},
        {"ticket": 2, "symbol": "XAUUSD", "magic": 888915, "pnl_usd": -3.0},
    ]

    only_m5 = bridge_server._pop_recently_closed("XAUUSD", 888999)
    assert [o["ticket"] for o in only_m5] == [1]

    # The M15 instance's record must still be in the queue -- not stolen.
    remaining = bridge_server._mt5_state["recently_closed"]
    assert [o["ticket"] for o in remaining] == [2]

    only_m15 = bridge_server._pop_recently_closed("XAUUSD", 888915)
    assert [o["ticket"] for o in only_m15] == [2]
    assert bridge_server._mt5_state["recently_closed"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mt5_bridge.py::test_pop_recently_closed_scopes_by_magic_not_just_symbol -v`
Expected: FAIL with `TypeError: _pop_recently_closed() takes 1 positional argument but 2 were given`

- [ ] **Step 3: Write minimal implementation**

In `mt5/bridge_server.py`, update `_pop_recently_closed` and its endpoint:

```python
@app.get("/api/mt5/recently_closed")
async def get_recently_closed(symbol: Optional[str] = None, magic: Optional[int] = None):
    """Returns and clears recently closed orders (only `symbol`'s / `magic`'s when given)."""
    return {"recently_closed": _pop_recently_closed(symbol, magic)}


def _pop_recently_closed(symbol: Optional[str], magic: Optional[int] = None) -> List[Dict[str, Any]]:
    queue = _mt5_state["recently_closed"]
    taken = [
        o for o in queue
        if (not symbol or str(o.get("symbol", "")).upper() == symbol.upper())
        and (magic is None or o.get("magic") == magic)
    ]
    kept = [o for o in queue if o not in taken]
    queue[:] = kept
    return taken
```

Update `MT5BridgeBroker.open_order` — add `magic` param, include in command only when given:

```python
    def open_order(
        self,
        symbol: str,
        order_type: str,
        lots: float,
        sl: float,
        tp: float,
        comment: str = "",
        await_confirm: bool = True,
        confirm_timeout: float = 10.0,
        magic: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Queues an MQL5 trade order for the MT5 EA to execute.

        Raises RuntimeError if the command could not be delivered to the bridge.
        When await_confirm is True, blocks until the EA reports back (or timeout)
        so callers get a real fill status instead of a bare "QUEUED".
        """
        cmd_id = self._next_cmd_id("mt5")

        command = {
            "id": cmd_id,
            "action": "ORDER_OPEN",
            "symbol": symbol,
            "type": order_type,
            "volume": lots,
            "sl": sl,
            "tp": tp,
            "comment": comment or f"AgenticMT5_{order_type}"
        }
        if magic is not None:
            command["magic"] = magic

        response = self._queue_command(command)
        # ... rest of the method (logging + await_confirm handling) unchanged
```

Update `close_order` and `modify_order` the same way — add `magic: Optional[int] = None`, add `if magic is not None: command["magic"] = magic` right after building the `command` dict, leave everything else (confirmation waiting, error handling) untouched:

```python
    def close_order(
        self,
        ticket: int,
        await_confirm: bool = True,
        confirm_timeout: float = 10.0,
        magic: Optional[int] = None
    ) -> Dict[str, Any]:
        """Queues a position close command for MT5 and waits for EA confirmation."""
        cmd_id = self._next_cmd_id("close")

        command = {
            "id": cmd_id,
            "action": "ORDER_CLOSE",
            "ticket": ticket
        }
        if magic is not None:
            command["magic"] = magic

        response = self._queue_command(command)
        # ... rest unchanged
```

```python
    def modify_order(
        self,
        ticket: int,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        await_confirm: bool = True,
        confirm_timeout: float = 10.0,
        magic: Optional[int] = None
    ) -> Dict[str, Any]:
        """Queues an order modification for MT5 and waits for EA confirmation."""
        cmd_id = self._next_cmd_id("modify")

        command = {
            "id": cmd_id,
            "action": "ORDER_MODIFY",
            "ticket": ticket,
            "sl": sl,
            "tp": tp
        }
        if magic is not None:
            command["magic"] = magic

        response = self._queue_command(command)
        # ... rest unchanged
```

Update `consume_recently_closed` to thread `magic` through the HTTP call and the in-process fallback:

```python
    def consume_recently_closed(self, symbol: Optional[str] = None, magic: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.in_process:
            try:
                params = {}
                if symbol:
                    params["symbol"] = symbol
                if magic is not None:
                    params["magic"] = magic
                resp = httpx.get(
                    f"{self.base_url}/api/mt5/recently_closed",
                    params=params or None,
                    timeout=3.0,
                )
                if resp.status_code == 200:
                    return resp.json().get("recently_closed", [])
            except Exception as e:
                logger.warning(f"[MT5-RECENT] Bridge unreachable ({type(e).__name__}: {e}); using in-process state.")

        return _pop_recently_closed(symbol, magic)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mt5_bridge.py -v`
Expected: All PASS.

- [ ] **Step 5: Add a second test — magic omitted keeps today's pop-everything-for-symbol behavior**

Add to `tests/test_mt5_bridge.py`:

```python
def test_pop_recently_closed_without_magic_still_pops_whole_symbol():
    """Backward compatibility: a caller that never opts into per-instance
    magic (e.g. the current production M5 path before it's updated) must
    keep seeing every closed record for its symbol, exactly like today."""
    bridge_server._mt5_state["recently_closed"] = [
        {"ticket": 1, "symbol": "XAUUSD", "magic": 888999},
        {"ticket": 2, "symbol": "XAUUSD", "magic": 888915},
        {"ticket": 3, "symbol": "BTCUSD", "magic": 888999},
    ]
    taken = bridge_server._pop_recently_closed("XAUUSD")
    assert sorted(o["ticket"] for o in taken) == [1, 2]
    assert [o["ticket"] for o in bridge_server._mt5_state["recently_closed"]] == [3]
```

Run: `pytest tests/test_mt5_bridge.py -v`
Expected: All PASS (this one should pass immediately given Step 3's implementation — it documents the intentional fallback behavior).

- [ ] **Step 6: Run the full suite**

Run: `pytest tests/ -q`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add mt5/bridge_server.py tests/test_mt5_bridge.py
git commit -m "fix(mt5-bridge): scope recently_closed pop by magic, not just symbol

Two same-symbol timeframe-instances previously raced for the same shared
recently_closed queue -- whichever polled first silently stole the other's
closed-trade record. magic is now an optional second filter key.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: `mt5/AgenticMT5Bridge.mq5` — per-command magic and managed-magic telemetry

This task requires MetaEditor (no Python test harness can compile or execute MQL5). Follow the project's established convention for `.mq5` changes: edit, recompile in MetaEditor, verify 0 errors/0 warnings, reattach.

**Files:**
- Modify: `mt5/AgenticMT5Bridge.mq5`

**Interfaces:**
- Produces: EA applies `SetExpertMagicNumber` per `ORDER_OPEN` command (falling back to `InpMagicNumber` when a command omits `magic`); `ORDER_CLOSE`/`ORDER_MODIFY` check ownership against the command's declared magic instead of the single hardcoded `InpMagicNumber`; open-position and closed-deal telemetry report every magic this EA suite manages (not just `InpMagicNumber`), so new timeframe-instances' positions become visible to the bridge at all.

- [ ] **Step 1: Add the managed-magic table and helper**

Near the top of `mt5/AgenticMT5Bridge.mq5`, right after the existing `g_squadSymbols[]` array (find it with `grep -n "g_squadSymbols\[\]" mt5/AgenticMT5Bridge.mq5`), add:

```mql5
// One entry per timeframe-instance this EA suite can manage. Must mirror
// agents/squad_manager.py's TIMEFRAME_MAGIC table exactly -- an EA build
// that drifts from the Python table will silently stop reporting positions
// for whichever timeframe's magic went missing from both lists.
ulong g_managedMagics[] = {888999, 888901, 888915, 888930, 888960, 889140, 890340};

bool IsManagedMagic(const long magic)
{
   for(int i = 0; i < ArraySize(g_managedMagics); i++)
      if((long)g_managedMagics[i] == magic)
         return true;
   return false;
}
```

- [ ] **Step 2: Apply per-command magic on `ORDER_OPEN`**

In `ExecuteCommand`, find the `ORDER_OPEN` branch (`grep -n "ORDER_OPEN" mt5/AgenticMT5Bridge.mq5`). Right after the existing `double tp = ExtractDouble(json, "\"tp\":", 0.0);` line and before the validation checks, add:

```mql5
      ulong cmdMagic = (ulong)ExtractDouble(json, "\"magic\":", (double)InpMagicNumber);
```

Then, immediately before the `bool success = false;` block that calls `g_trade.Buy(...)` / `g_trade.Sell(...)`, add:

```mql5
      g_trade.SetExpertMagicNumber(cmdMagic);
```

So the execution block reads:

```mql5
      g_trade.SetExpertMagicNumber(cmdMagic);
      bool success = false;
      if(isBuy)
      {
         success = g_trade.Buy(volume, cmdSymbol, 0, sl, tp, "AgenticMT5");
      }
      else
      {
         success = g_trade.Sell(volume, cmdSymbol, 0, sl, tp, "AgenticMT5");
      }
```

- [ ] **Step 3: Check ownership against the command's own magic on `ORDER_CLOSE` and `ORDER_MODIFY`**

Find the `ORDER_CLOSE` branch:

```mql5
   else if(StringFind(json, "ORDER_CLOSE") >= 0)
   {
      string cmdId = ExtractString(json, "\"id\":\"", "\"");
      ulong ticket = (ulong)ExtractDouble(json, "\"ticket\":", 0.0);
```

Add a magic extraction line right after the `ticket` line, and change the ownership check from `InpMagicNumber` to `cmdMagic`:

```mql5
   else if(StringFind(json, "ORDER_CLOSE") >= 0)
   {
      string cmdId = ExtractString(json, "\"id\":\"", "\"");
      ulong ticket = (ulong)ExtractDouble(json, "\"ticket\":", 0.0);
      ulong cmdMagic = (ulong)ExtractDouble(json, "\"magic\":", (double)InpMagicNumber);
      bool success = false;
      if(ticket > 0 && g_pos.SelectByTicket(ticket) && g_pos.Magic() == cmdMagic)
      {
         success = g_trade.PositionClose(ticket);
      }
      else
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "Position not found or not owned by this EA");
         return;
      }
      if(success)
         ConfirmExecution(cmdId, "SUCCESS", ticket, "Position closed in MT5");
      else
         ConfirmExecution(cmdId, "FAILED", ticket, "Close retcode: " + IntegerToString(g_trade.ResultRetcode()), g_trade.ResultRetcode());
   }
```

Apply the identical pattern to `ORDER_MODIFY`:

```mql5
   else if(StringFind(json, "ORDER_MODIFY") >= 0)
   {
      string cmdId = ExtractString(json, "\"id\":\"", "\"");
      ulong ticket = (ulong)ExtractDouble(json, "\"ticket\":", 0.0);
      double sl = ExtractDouble(json, "\"sl\":", 0.0);
      double tp = ExtractDouble(json, "\"tp\":", 0.0);
      ulong cmdMagic = (ulong)ExtractDouble(json, "\"magic\":", (double)InpMagicNumber);
      if(ticket <= 0 || !g_pos.SelectByTicket(ticket) || g_pos.Magic() != cmdMagic)
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "Position not found or not owned by this EA");
         return;
      }
      if(g_trade.PositionModify(ticket, sl, tp))
         ConfirmExecution(cmdId, "SUCCESS", ticket, "Position modified in MT5");
      else
         ConfirmExecution(cmdId, "FAILED", ticket, "Modify retcode: " + IntegerToString(g_trade.ResultRetcode()), g_trade.ResultRetcode());
   }
```

- [ ] **Step 4: Widen telemetry from `== InpMagicNumber` to `IsManagedMagic(...)`, and include `magic` in both payloads**

This is the fix for the bigger, previously-hidden gap: `SendTelemetry()` currently reports *only* positions/deals whose magic equals `InpMagicNumber` (888999) — a brand-new timeframe-instance's positions would otherwise never reach the bridge at all, regardless of the fixes in Steps 2-3.

In `SendTelemetry()`, find the open-positions loop:

```mql5
         if(g_pos.Magic() == InpMagicNumber)
         {
            if(!first) json += ",";
            first = false;
            string typeStr = (g_pos.PositionType() == POSITION_TYPE_BUY) ? "BUY" : "SELL";
            json += "{";
            json += "\"ticket\":" + IntegerToString(ticket) + ",";
            json += "\"symbol\":\"" + g_pos.Symbol() + "\",";
            json += "\"type\":\"" + typeStr + "\",";
            json += "\"lots\":" + DoubleToString(g_pos.Volume(), 2) + ",";
            json += "\"open_price\":" + DoubleToString(g_pos.PriceOpen(), 2) + ",";
            json += "\"sl\":" + DoubleToString(g_pos.StopLoss(), 2) + ",";
            json += "\"tp\":" + DoubleToString(g_pos.TakeProfit(), 2) + ",";
            json += "\"profit\":" + DoubleToString(g_pos.Profit(), 2) + ",";
            json += "\"bid\":" + DoubleToString(SymbolInfoDouble(g_pos.Symbol(), SYMBOL_BID), 2) + ",";
            json += "\"ask\":" + DoubleToString(SymbolInfoDouble(g_pos.Symbol(), SYMBOL_ASK), 2);
            json += "}";
         }
```

Replace with:

```mql5
         if(IsManagedMagic(g_pos.Magic()))
         {
            if(!first) json += ",";
            first = false;
            string typeStr = (g_pos.PositionType() == POSITION_TYPE_BUY) ? "BUY" : "SELL";
            json += "{";
            json += "\"ticket\":" + IntegerToString(ticket) + ",";
            json += "\"symbol\":\"" + g_pos.Symbol() + "\",";
            json += "\"type\":\"" + typeStr + "\",";
            json += "\"lots\":" + DoubleToString(g_pos.Volume(), 2) + ",";
            json += "\"open_price\":" + DoubleToString(g_pos.PriceOpen(), 2) + ",";
            json += "\"sl\":" + DoubleToString(g_pos.StopLoss(), 2) + ",";
            json += "\"tp\":" + DoubleToString(g_pos.TakeProfit(), 2) + ",";
            json += "\"profit\":" + DoubleToString(g_pos.Profit(), 2) + ",";
            json += "\"magic\":" + IntegerToString(g_pos.Magic()) + ",";
            json += "\"bid\":" + DoubleToString(SymbolInfoDouble(g_pos.Symbol(), SYMBOL_BID), 2) + ",";
            json += "\"ask\":" + DoubleToString(SymbolInfoDouble(g_pos.Symbol(), SYMBOL_ASK), 2);
            json += "}";
         }
```

Find the closed-deals loop:

```mql5
         if(entryType == DEAL_ENTRY_OUT && magic == (long)InpMagicNumber) // Deal closed
```

Replace with:

```mql5
         if(entryType == DEAL_ENTRY_OUT && IsManagedMagic(magic)) // Deal closed
```

And add `"magic"` to that record's JSON — find:

```mql5
            json += "\"lots\":" + DoubleToString(dealLots, 2) + ",";
            json += "\"pnl_usd\":" + DoubleToString(dealProfit, 2);
            json += "}";
```

Replace with:

```mql5
            json += "\"lots\":" + DoubleToString(dealLots, 2) + ",";
            json += "\"pnl_usd\":" + DoubleToString(dealProfit, 2) + ",";
            json += "\"magic\":" + IntegerToString(magic);
            json += "}";
```

- [ ] **Step 5: Compile and verify**

Open `mt5/AgenticMT5Bridge.mq5` in MetaEditor. Compile (Ctrl+F7 or the toolbar Compile button). Confirm the output panel shows **0 errors, 0 warnings**. Confirm the `.ex5` file's modified timestamp changed (per this project's known history, a silent no-op compile has happened before — check the file's mtime, don't trust the log alone):

```bash
ls -la "$(mdfind -name AgenticMT5Bridge.ex5 2>/dev/null | head -1)" 2>/dev/null || echo "locate the .ex5 under MetaTrader 5's MQL5/Experts folder manually if mdfind finds nothing"
```

Do not reattach to the live chart yet — that happens in Task 8's rollout sequence, together with the Python deploy, per the Global Constraints migration-safety requirement.

- [ ] **Step 6: Commit**

```bash
git add mt5/AgenticMT5Bridge.mq5
git commit -m "feat(ea): per-command magic ownership + managed-magic telemetry

ORDER_OPEN now applies the magic the caller requests (falling back to
InpMagicNumber when omitted); ORDER_CLOSE/ORDER_MODIFY check ownership
against that same declared magic. Telemetry (open positions + closed
deals) now reports every magic this EA suite manages, not just
InpMagicNumber -- previously a new timeframe-instance's positions would
open successfully but never be reported back to the bridge at all.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: `agents/base_agent.py` — per-instance `magic` identity

**Files:**
- Modify: `agents/base_agent.py:38-63` (`__init__` signature + body), `:463` (`symbol_positions` filter), `:158-190` (`_reconcile_closed_trades`), `:801-808` (`open_order` call), `:310`, `:325` (`modify_order` calls), `:422` (`close_order` call)
- Test: `tests/test_agents.py`

**Interfaces:**
- Consumes: `PaperTradingBroker`/`MT5BridgeBroker`/`MT4BridgeBroker` all accept `magic` on `open_order`/`close_order`/`modify_order` (Tasks 1-3).
- Produces: `BaseSpecialistAgent.__init__(..., magic: Optional[int] = None)` — stored as `self.magic`, defaulting to `888999`. Every broker call the agent makes passes `magic=self.magic`. `symbol_positions` only includes positions matching both `self.symbol` and `self.magic`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agents.py` (check the top of the file for existing imports of `GoldSpecialistAgent`/`PaperTradingBroker` and reuse them — do not re-import):

```python
def test_symbol_positions_filtered_by_own_magic(tmp_path):
    """Two timeframe-instances of the same symbol share one broker/account in
    live MT5 mode. An instance must only see and manage its own positions --
    not another instance's, even though both trade the same symbol."""
    broker = PaperTradingBroker(initial_balance=10000.0)
    agent_m5 = GoldSpecialistAgent(broker=broker, timeframe="M5",
                                    journal_dir=tmp_path / "m5", magic=888999)
    agent_m15 = GoldSpecialistAgent(broker=broker, timeframe="M15",
                                     journal_dir=tmp_path / "m15", magic=888915)

    entry = broker.current_price
    res_m5 = broker.open_order(symbol="XAUUSD", order_type="BUY", lots=0.1,
                                sl=entry - 5.0, tp=entry + 50.0, magic=888999)
    res_m15 = broker.open_order(symbol="XAUUSD", order_type="BUY", lots=0.1,
                                 sl=entry - 5.0, tp=entry + 50.0, magic=888915)

    result_m5 = agent_m5.step(allow_new_entry=False)
    result_m15 = agent_m15.step(allow_new_entry=False)

    assert result_m5["position"]["ticket"] == res_m5["ticket"]
    assert result_m15["position"]["ticket"] == res_m15["ticket"]
```

(`step()`'s exact response shape for a single tracked position — check `agents/base_agent.py` around the `MAX_OPEN_POSITIONS`/monitoring return block, e.g. `"position": symbol_positions[0] if symbol_positions else None`, already used by the existing `NEWS_BLACKOUT_ACTIVE` return — reuse whatever key name that same convention already returns for the "monitoring, not opening" path so this assertion matches real output; run the test first and read the actual failure/output to confirm before assuming the key name.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agents.py::test_symbol_positions_filtered_by_own_magic -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'magic'`

- [ ] **Step 3: Write minimal implementation**

In `agents/base_agent.py`, add `magic` to `__init__`:

```python
    def __init__(
        self,
        symbol: str,
        asset_name: str,
        timeframe: str = "M5",
        contract_size: float = 100.0,
        min_lot: float = 0.01,
        max_lot: float = 10.0,
        min_sl_dist: float = 2.0,
        broker: Optional[BaseBroker] = None,
        broker_mode: str = "paper",
        initial_balance: Optional[float] = None,
        journal_dir: Optional[Path] = None,
        strategy_type: str = "trend",
        max_open_positions: Optional[int] = None,
        min_entry_interval_sec: Optional[int] = None,
        magic: Optional[int] = None
    ):
        self.symbol = symbol
        self.asset_name = asset_name
        self.timeframe = timeframe
        self.contract_size = contract_size
        self.min_lot = min_lot
        self.max_lot = max_lot
        self.min_sl_dist = min_sl_dist
        self.strategy_type = strategy_type
        self.max_open_positions = max_open_positions or config.max_open_positions
        self.min_entry_interval_sec = min_entry_interval_sec if min_entry_interval_sec is not None else getattr(config, "min_entry_interval_sec", 300)
        self.last_entry_time: Optional[datetime] = None
        # Identifies which MT5 positions belong to this specific
        # symbol+timeframe instance (see agents/squad_manager.py's
        # TIMEFRAME_MAGIC table). Defaults to the historical single global
        # magic (888999) so any direct/manual construction -- including
        # every existing test -- keeps today's single-instance behavior
        # unless it explicitly opts into a different one.
        self.magic = magic if magic is not None else 888999
```

Update the `symbol_positions` filter (`agents/base_agent.py:463`):

```python
        all_open = self.broker.get_open_positions()
        symbol_positions = [
            p for p in all_open
            if p.get("symbol") == self.symbol and p.get("magic") == self.magic
        ]
```

Update `_reconcile_closed_trades` (`agents/base_agent.py:158-168`) to pass `magic`:

```python
    def _reconcile_closed_trades(self) -> None:
        """Checks for newly closed trades, logs autopsies, and updates learned rules."""
        if hasattr(self.broker, "consume_recently_closed"):
            closed_trades = self.broker.consume_recently_closed(symbol=self.symbol, magic=self.magic)
        elif hasattr(self.broker, "get_closed_orders"):
            closed_trades = self.broker.get_closed_orders()
        elif hasattr(self.broker, "get_trade_history"):
            closed_trades = self.broker.get_trade_history(symbol=self.symbol, count=10)
        else:
            closed_trades = []
```

Update the `open_order` call site (`agents/base_agent.py:801-808`):

```python
            order_res = self.broker.open_order(
                symbol=self.symbol,
                order_type=action,
                lots=lot_size,
                sl=sl_candidate,
                tp=tp_candidate,
                comment=f"{self.symbol}_{self.strategy_name[:8]}",
                magic=self.magic
            )
```

Update the two `modify_order` call sites (`agents/base_agent.py:310`, `:325`) — read each one first (`grep -n "modify_order(ticket=ticket" agents/base_agent.py`) since they're inside a trailing-stop/breakeven block with surrounding logic; add `magic=self.magic` as a new keyword argument to both, keeping every existing argument:

```python
self.broker.modify_order(ticket=ticket, sl=new_sl, tp=tp, magic=self.magic)
```

Update the `close_order` call site (`agents/base_agent.py:422`):

```python
self.broker.close_order(ticket, magic=self.magic)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agents.py::test_symbol_positions_filtered_by_own_magic -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -q`
Expected: All PASS. If anything using `agent.step()` and a directly-opened `broker.open_order(...)` fails, check that test's `open_order` call — if it doesn't pass `magic=`, confirm it's relying on `PaperTradingBroker`'s `888999` default (Task 1) matching the agent's own `888999` default (Step 3 above); if a test constructs the agent with an explicit non-default `magic`, its direct `open_order` calls need updating to match.

- [ ] **Step 6: Commit**

```bash
git add agents/base_agent.py tests/test_agents.py
git commit -m "feat(agent): scope position management to the agent's own magic number

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: `agents/squad_manager.py` — deterministic per-timeframe magic table

**Files:**
- Modify: `agents/squad_manager.py:33` area (module-level constants, near `SPECIALIST_REGISTRY`), `:154-164` (specialist construction loop)
- Test: `tests/test_agents.py`

**Interfaces:**
- Consumes: `BaseSpecialistAgent.__init__(..., magic=...)` (Task 5).
- Produces: `agents.squad_manager.TIMEFRAME_MAGIC: Dict[str, int]` and `agents.squad_manager.magic_for_timeframe(timeframe: str) -> int` (raises `ValueError` for an unmapped timeframe — fail closed rather than silently reusing 888999, which would collide with the live M5 instance).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agents.py`:

```python
def test_squad_manager_assigns_per_timeframe_magic_and_journal_dir(tmp_path):
    """Every timeframe-instance must get its own MT5 magic number and journal
    directory so concurrent same-symbol instances never share state or
    silently steal each other's positions. M5 must keep the exact magic the
    live account's open positions already use."""
    from agents.squad_manager import TIMEFRAME_MAGIC
    broker = PaperTradingBroker(initial_balance=10000.0)

    squad_m5 = SquadManager(broker=broker, initial_balance=10000.0,
                             agents_to_enable=["gold"], timeframe="M5",
                             journal_dir=tmp_path / "m5")
    assert squad_m5.specialists["gold"].magic == 888999
    assert squad_m5.specialists["gold"].journal_dir == tmp_path / "m5" / "xauusd"

    squad_m15 = SquadManager(broker=broker, initial_balance=10000.0,
                              agents_to_enable=["gold"], timeframe="M15",
                              journal_dir=tmp_path / "m15")
    assert squad_m15.specialists["gold"].magic == TIMEFRAME_MAGIC["M15"]
    assert squad_m15.specialists["gold"].magic != 888999
    assert squad_m15.specialists["gold"].journal_dir == tmp_path / "m15" / "xauusd"


def test_squad_manager_uses_forced_timeframes_own_magic_not_squads(tmp_path):
    """xag/gbp/eur/xpt are forced to M15 regardless of the squad's own
    timeframe (see SPECIALIST_REGISTRY) -- their magic must follow their
    actual (forced) timeframe, not whatever the squad was started with."""
    from agents.squad_manager import TIMEFRAME_MAGIC
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(broker=broker, initial_balance=10000.0,
                          agents_to_enable=["all"], timeframe="M5",
                          journal_dir=tmp_path)
    assert squad.specialists["gold"].magic == 888999
    assert squad.specialists["xag"].magic == TIMEFRAME_MAGIC["M15"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agents.py::test_squad_manager_assigns_per_timeframe_magic_and_journal_dir -v`
Expected: FAIL with `ImportError: cannot import name 'TIMEFRAME_MAGIC' from 'agents.squad_manager'`

- [ ] **Step 3: Write minimal implementation**

In `agents/squad_manager.py`, add near the top (after the `SPECIALIST_REGISTRY`/`GATED_SPECIALISTS` definitions, since this table documents the same set of timeframes those registries' `forced_timeframe` values draw from):

```python
# Deterministic MT5 magic number per timeframe: 888900 + minutes(timeframe).
# M5 is the one exception -- it must stay 888999 to match the magic already
# in use by real open positions on the live account (see
# mt5/AgenticMT5Bridge.mq5's InpMagicNumber default). This table must be
# kept in sync with mt5/AgenticMT5Bridge.mq5's g_managedMagics[] array --
# an entry missing from either side means that timeframe's positions won't
# be reported back to the Python bridge at all.
TIMEFRAME_MAGIC: Dict[str, int] = {
    "M1": 888901,
    "M5": 888999,
    "M15": 888915,
    "M30": 888930,
    "H1": 888960,
    "H4": 889140,
    "D1": 890340,
}


def magic_for_timeframe(timeframe: str) -> int:
    try:
        return TIMEFRAME_MAGIC[timeframe.upper()]
    except KeyError:
        raise ValueError(
            f"No magic number mapping for timeframe {timeframe!r}. "
            f"Add one to TIMEFRAME_MAGIC before running this timeframe live -- "
            f"never fall back to another timeframe's magic, that would make "
            f"two instances silently share (and corrupt) each other's positions."
        )
```

Update the specialist construction loop (`agents/squad_manager.py:154-164`):

```python
        for key in resolved:
            if key not in all_specialists:
                continue
            agent_cls, journal_subdir, forced_timeframe = all_specialists[key]
            effective_timeframe = forced_timeframe or self.timeframe
            self.specialists[key] = agent_cls(
                broker=self.broker,
                broker_mode=self.broker_mode,
                initial_balance=self.initial_balance,
                timeframe=effective_timeframe,
                journal_dir=(journal_dir / journal_subdir) if journal_dir else None,
                magic=magic_for_timeframe(effective_timeframe)
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agents.py::test_squad_manager_assigns_per_timeframe_magic_and_journal_dir tests/test_agents.py::test_squad_manager_uses_forced_timeframes_own_magic_not_squads -v`
Expected: Both PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -q`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/squad_manager.py tests/test_agents.py
git commit -m "feat(squad): deterministic per-timeframe magic number table

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: `main.py` — journal_dir auto-derivation and expanded `--timeframe` choices

**Files:**
- Modify: `main.py:83-125` (`cmd_loop`), `:259-268` (`loop_parser` argument definitions)
- Test: `tests/test_agents.py` or a new `tests/test_main_cli.py` (check `ls tests/test_main*.py` first — reuse if one already exists, else create)

**Interfaces:**
- Consumes: `SquadManager(..., journal_dir: Optional[Path])` (already exists — Task 6 didn't change this signature).
- Produces: `main.py::_default_journal_dir(timeframe: str) -> Path` — a small, independently-testable pure function. `M5` (case-insensitive) → `config.project_root / "journal"`; any other timeframe → `config.project_root / f"journal_{timeframe.lower()}"`.

- [ ] **Step 1: Write the failing test**

Check first whether a CLI test file exists:

```bash
ls tests/test_main*.py 2>/dev/null || echo "none yet"
```

If none exists, create `tests/test_main_cli.py`:

```python
"""
Unit tests for main.py's CLI helper functions.
"""

from pathlib import Path
from config import config
from main import _default_journal_dir


def test_default_journal_dir_m5_keeps_todays_production_path():
    """The live M5 squad's journal path must not move -- no flag change
    should be required to keep it running exactly as it does today."""
    assert _default_journal_dir("M5") == config.project_root / "journal"
    assert _default_journal_dir("m5") == config.project_root / "journal"


def test_default_journal_dir_other_timeframes_get_a_distinct_path():
    assert _default_journal_dir("M15") == config.project_root / "journal_m15"
    assert _default_journal_dir("H4") == config.project_root / "journal_h4"
```

If `tests/test_main*.py` already exists, add these two test functions to it instead (matching that file's existing import style) rather than creating a second file.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_cli.py -v`
Expected: FAIL with `ImportError: cannot import name '_default_journal_dir' from 'main'`

- [ ] **Step 3: Write minimal implementation**

In `main.py`, add near the top of the file (after imports, before `cmd_analyze`):

```python
def _default_journal_dir(timeframe: str) -> Path:
    """The M5 production squad's journal path must never move -- it's
    journal/ today and stays journal/ regardless of this feature. Every
    other timeframe gets its own journal_<tf>/ so concurrent same-symbol
    instances never share daily_trade_state.json."""
    if timeframe.upper() == "M5":
        return config.project_root / "journal"
    return config.project_root / f"journal_{timeframe.lower()}"
```

Check `main.py`'s existing imports for `Path` (`grep -n "^from pathlib\|^import pathlib" main.py`) — add `from pathlib import Path` near the top if it's missing.

Update `cmd_loop` (`main.py:83-125`) to thread `journal_dir` through, and add a `--journal-dir` override:

```python
def cmd_loop(args):
    """Runs the autonomous trading loop with the Multi-Asset Specialist Squad or single agent."""
    agents_map = {
        "all": ["all"],  # SquadManager expands this to every SPECIALIST_REGISTRY key (gold/btc/eth + the 4 confirmed new markets, not ukoil/xng)
        "duo": ["gold", "btc"],
        "legacy3": ["gold", "btc", "eth"],  # fallback while the EA hasn't been recompiled to stream the new symbols' bars yet
        "gold": ["gold"], "btc": ["btc"], "eth": ["eth"],
        "xag": ["xag"], "gbp": ["gbp"], "eur": ["eur"], "xpt": ["xpt"],
        "ukoil": ["ukoil"], "xng": ["xng"],
    }
    selected_agents = agents_map.get(args.agent.lower(), ["all"])
    effective_timeframe = getattr(args, "timeframe", config.timeframe_main)
    journal_dir = Path(args.journal_dir) if getattr(args, "journal_dir", None) else _default_journal_dir(effective_timeframe)

    console.print(Panel(
        f"[bold cyan]Agentic Multi-Asset Specialist Squad[/bold cyan]\n"
        f"Active Specialists: [bold yellow]{', '.join([a.upper() for a in selected_agents])}[/bold yellow]\n"
        f"Timeframe: [bold]{effective_timeframe}[/bold] | Journal: [bold]{journal_dir}[/bold]\n"
        f"Daily Profit Target: [bold green]+3.0%[/bold green] (Lock on achievement) | Loss Cutoff: [bold red]-2.0%[/bold red]\n"
        f"Broker Mode: [bold]{args.mode}[/bold] | Interval: [bold]{args.interval}s[/bold]",
        expand=False
    ))

    while True:
        try:
            squad = SquadManager(
                broker_mode=args.mode,
                initial_balance=args.balance,
                agents_to_enable=selected_agents,
                timeframe=effective_timeframe,
                journal_dir=journal_dir
            )
            break
        except RuntimeError as exc:
            if args.mode == "mt5" and args.wait_for_live_data:
                console.print(
                    f"[yellow]Live preflight not ready: {exc}[/yellow]\n"
                    f"[dim]Waiting {args.interval}s for fresh MT5 telemetry and bars...[/dim]"
                )
                time.sleep(args.interval)
                continue
            raise

    squad.run_loop(max_iterations=args.max_iter, interval_sec=args.interval)
```

Update the `loop_parser` argument definitions (`main.py:259-268`):

```python
        loop_parser.add_argument("--timeframe", default=config.timeframe_main,
                                  choices=["M1", "M5", "M15", "M30", "H1", "H4", "D1"],
                                  help="Execution timeframe (e.g. M5 for high frequency)")
        loop_parser.add_argument("--journal-dir", default=None,
                                  help="Override the journal directory (default: journal/ for M5, journal_<tf>/ otherwise)")
```

Add the `--journal-dir` line right after the existing `--timeframe` line, keeping every other existing argument in that block untouched.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -q`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main_cli.py
git commit -m "feat(cli): auto-derive journal_dir per timeframe, expand --timeframe choices

M5 keeps its existing journal/ path unchanged. M15/M30/H1/H4/D1 each get
journal_<tf>/ so concurrent same-symbol timeframe-instances never share
daily_trade_state.json. --journal-dir remains available as an override.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 8: Rollout — recompile, redeploy, verify, then bring up a second instance on demo

This task is operational, not code. Do not skip or reorder steps — the live account has real open positions right now under magic 888999.

- [ ] **Step 1: Run the full test suite one more time on the final state of the branch**

Run: `pytest tests/ -q`
Expected: All PASS.

- [ ] **Step 2: Rebuild the Docker container**

The project's usual convention is that Python-only changes need just a container *restart* (bind-mounted, no rebuild) — but this round touches enough surface, and was explicitly requested, that a full rebuild is warranted here:

```bash
docker compose build
docker compose up -d
```

(If the project uses a different compose invocation or service name, check `docker-compose.yml` / `compose.yaml` in the repo root first — `cat docker-compose.yml 2>/dev/null || cat compose.yaml 2>/dev/null`.)

- [ ] **Step 3: Recompile the EA in MetaEditor**

Open `mt5/AgenticMT5Bridge.mq5` in MetaEditor (Task 4 already made the edits). Compile. Confirm 0 errors, 0 warnings, and confirm the `.ex5`'s modified timestamp actually changed.

- [ ] **Step 4: Reattach the EA to the existing M5 chart**

In the MT5 terminal, remove and re-drag the recompiled EA onto the chart currently running the live M5 squad. Set/confirm `InpMagicNumber = 888999` on the Inputs tab (this must not change from what it already is).

- [ ] **Step 5: Verify the M5 instance still sees its existing live position(s) before anything else happens**

With the recompiled EA now attached and the rebuilt Python container running (paused/not yet placing new orders if possible — check the squad's current run state first), confirm the account's real open position(s) are still visible:

```bash
curl -s http://127.0.0.1:8000/api/mt5/account | python3 -m json.tool
```

Compare the `open_positions` list against what MT5's own Terminal → Trade tab shows for that account, open position by open position (ticket, symbol, lots, SL, TP). Do not proceed to Step 6 until every real open position is accounted for in both places.

- [ ] **Step 6: Attach the EA to 4 additional charts for M30/H1/H4/D1 bar coverage**

Per the spec's "Operational step" section — the EA already streams bars for whatever `InpTimeframe` it's given, for every squad symbol, regardless of which symbol's chart it's attached to. Attach the same recompiled EA to 4 more charts (any symbol), setting `InpTimeframe` to `PERIOD_M30`, `PERIOD_H1`, `PERIOD_H4`, and `PERIOD_D1` respectively — one chart per timeframe. (M5 is already covered by the Step 4 chart; M15 is already covered for free, since every instance streams it regardless of its own `InpTimeframe`.)

- [ ] **Step 7: Bring up a second instance on the demo account only — prove no cross-contamination**

Do not point a second instance at the real ~10,000 THB account yet. On the demo account, start a second process for Gold at M15 (gold/btc/eth are the only specialists with `forced_timeframe=None`, so this is the cleanest proving ground):

```bash
python3 main.py run --agent=gold --mode=mt5 --timeframe=M15 --balance=500
```

While that's running alongside the existing M5 process (both against the demo account), let each open, manage, and close at least one full trade cycle. Confirm via the journal files that:
- `journal/xauusd/daily_trade_state.json` (M5) and `journal_m15/xauusd/daily_trade_state.json` (M15) each only record their own trades' PnL — check `trades_count_today` and `closed_pnl_today` in each file independently.
- Neither instance's log output shows it managing (trailing-stop/breakeven messages for) a ticket that belongs to the other instance.

- [ ] **Step 8: Only after Step 7 passes cleanly — decide on real-capital rollout separately**

This plan's scope ends at a demo-verified, working multi-timeframe infrastructure. Whether and when to run a second timeframe-instance against the real ~10,000 THB account is a separate decision for the user to make explicitly — do not do it as part of finishing this plan.

---

## Self-Review Notes

- **Spec coverage:** Every section of `docs/superpowers/specs/2026-09-23-multi-timeframe-agent-infra-design.md` (A-F) maps to a task above. One correction made during planning that the spec got wrong: the spec claimed "close/modify-by-ticket commands do not need a magic field" — reading `mt5/AgenticMT5Bridge.mq5` closely (Task 4) showed `ORDER_CLOSE`/`ORDER_MODIFY` already enforce `g_pos.Magic() == InpMagicNumber` as an ownership guard, so they need the same per-command magic Task 4 Step 3 adds, or a new timeframe-instance could never close/modify its own positions. The spec also didn't anticipate that `SendTelemetry()` already filters both open-position and closed-deal reporting down to `InpMagicNumber` — without Task 4 Step 4's `IsManagedMagic()` change, a new instance's positions would open successfully but stay permanently invisible to the bridge. Both are incorporated into Task 4 above; the spec document itself is not being edited retroactively, since the plan is the authoritative next artifact.
- **Placeholder scan:** No TBD/TODO markers; every step has complete, runnable code.
- **Type consistency:** `magic: Optional[int]` used consistently across `BaseBroker`, `PaperTradingBroker`, `MT4BridgeBroker`, `MT5BridgeBroker`, and `BaseSpecialistAgent`. `TIMEFRAME_MAGIC` / `magic_for_timeframe` names match between Task 6's implementation and Task 6's own test imports.
