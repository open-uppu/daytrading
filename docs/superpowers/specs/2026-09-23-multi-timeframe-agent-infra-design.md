# Multi-Timeframe Agent Infrastructure — Design Spec

Date: 2026-09-23

## Problem

The user wants specialist agents to trade the same symbol across multiple
timeframes concurrently and permanently — e.g. a Gold-M5 instance and a
Gold-M15 instance both live at once, each a separate persistent agent
(confirmed: "1 agent ต่อ 1 symbol ต่อ 1 timeframe แบบถาวร"). Target
timeframe set: M5, M15, M30, H1, H4, D1 (confirmed). Target symbols: all 9
currently in `SPECIALIST_REGISTRY`/`GATED_SPECIALISTS` (confirmed).

Today `SquadManager` runs exactly one `self.timeframe` for every enabled
specialist in a single process (`agents/squad_manager.py:74`). Running a
second process for a second timeframe is possible at the CLI level, but two
processes trading the **same symbol** currently corrupt each other:

1. **`journal_dir` is never threaded from the CLI.** `main.py::cmd_run`
   constructs `SquadManager(...)` without a `journal_dir` argument, so every
   process falls back to the same default (`journal/{symbol}/`). Two
   processes trading `XAUUSD` at different timeframes would read/write the
   same `daily_trade_state.json`.
2. **Order/position ownership is untracked.** All specialists share one MT5
   magic number (`InpMagicNumber = 888999`, set once at EA `OnInit`, never
   per-order) and one command queue. `agents/base_agent.py:463` filters
   positions by `symbol` only — an M5 instance and an M15 instance trading
   `XAUUSD` would each see, and try to manage (trailing stop, breakeven,
   `max_open_positions` count), **the other instance's positions** as if
   they were its own.
3. **Closed-trade reconciliation is destructive and shared.**
   `MT5BridgeBroker.consume_recently_closed(symbol=...)` calls
   `GET /api/mt5/recently_closed?symbol=...`, which **pops and clears** the
   matching entries from one shared server-side list
   (`mt5/bridge_server.py:298`). Whichever process polls first "steals" the
   record; every other same-symbol instance never sees that trade, so its
   `session_tracker.closed_pnl_today` silently under-counts and its
   mistake-journal never logs the trade.

None of this is visible with a single instance per symbol (today's
production setup) — it only breaks the moment a second timeframe-instance
starts trading the same symbol, which is exactly what this feature requires.

## Goal (Phase 1 of 2)

Build the **infrastructure** that lets N independent, permanent
timeframe-instances of the same symbol run concurrently without corrupting
each other's state, PnL accounting, or position management. This is
mechanism only — it does not decide which symbol/timeframe combinations are
actually profitable or should be enabled live.

**Explicitly out of scope for this spec** (Phase 2, separate spec):
- Backtesting any of the 54 symbol×timeframe combinations that don't
  already have a validated M15 strategy (per `AGENTS.md` leaderboard) or
  validated M5 logic (`strategy_m5_scalper`, gold/btc/eth only).
- Relaxing `SPECIALIST_REGISTRY`'s `forced_timeframe = "M15"` pin for
  xag/gbp/eur/xpt/ukoil/xng — those stay M15-only until Phase 2 backtests
  clear another timeframe for them.
- Deploying any new symbol/timeframe combination against real capital.
- A shared, cross-instance position-count/exposure cap (see "Considered and
  rejected" below).

## Architecture

### Per-instance identity: `journal_dir` + `magic`

Every timeframe-instance of a specialist is identified by two independent,
deterministic values — no coordination file or registry needed:

| Timeframe | `journal_dir` | `magic` |
|---|---|---|
| M5 (today's production default) | `journal/{symbol}/` (unchanged) | **888999** (unchanged — the live default in `AgenticMT5Bridge.mq5:18`) |
| M15 | `journal_m15/{symbol}/` | 888915 |
| M30 | `journal_m30/{symbol}/` | 888930 |
| H1  | `journal_h1/{symbol}/`  | 888960 |
| H4  | `journal_h4/{symbol}/`  | 889140 |
| D1  | `journal_d1/{symbol}/`  | 890340 |

`magic = 888900 + minutes(timeframe)` (M5=5, M15=15, M30=30, H1=60, H4=240,
D1=1440). Deterministic from the timeframe string alone; no new file, no
runtime allocation, no collision risk between timeframes.

**The M5/888999 pairing must not change.** The live account has real open
positions right now under magic 888999. If the M5 instance's magic filter
ever stopped matching 888999, the agent would stop seeing its own open
positions — no trailing stop, no breakeven, no exit management, on a live
position. Every other timeframe is a brand-new instance with zero existing
positions, so no migration concern there.

### EA changes (`mt5/AgenticMT5Bridge.mq5`) — requires recompile

1. **Per-command magic.** The command dict already carries an unused
   `comment` field (`mt5/bridge_server.py:517`) that the EA has never read.
   Add a `magic` field the same way: when a queued command includes
   `"magic": <int>`, the EA calls `g_trade.SetExpertMagicNumber(magic)`
   before executing that specific command; when absent, it falls back to
   `InpMagicNumber` (888999) — preserving today's behavior for any caller
   that doesn't send one.
2. **Magic in position telemetry.** `SendTelemetry()`'s open-positions
   payload gains a `"magic"` field per position
   (`PositionGetInteger(POSITION_MAGIC)`).
3. **Magic in closed-order telemetry.** The closed-order records gain a
   `"magic"` field (`HistoryDealGetInteger(DEAL_MAGIC)` at the time the
   close is detected and pushed).
4. **No change to bar streaming.** `InpTimeframe` is already a per-instance
   EA input (`mt5/AgenticMT5Bridge.mq5:22`) and every instance already
   streams M15 bars regardless of its own timeframe
   (`OnTimer()`, lines 95–99). Covering all 6 target timeframes needs zero
   MQL5 changes — see "Operational step" below.

Both telemetry payload fields are additive on an already-untyped
`Dict[str, Any]` wire shape (`TelemetryPayload.open_positions: List[Dict[str, Any]]`,
`queue_command_endpoint(command: Dict[str, Any])`) — no Pydantic schema
changes needed on the Python side.

### `mt5/bridge_server.py` changes

1. `GET /api/mt5/recently_closed` gains an optional `magic` query param.
   `_pop_recently_closed(symbol, magic)` pops only entries matching
   **both** `symbol` and `magic` when `magic` is given (falls back to
   symbol-only pop when omitted, for backward compatibility). This is the
   fix for the "whoever polls first steals the record" bug — each
   instance's poll only removes its own entries, leaving other magics'
   entries in the queue for their own owners.
2. `MT5BridgeBroker.consume_recently_closed(symbol=..., magic=...)` — thread
   the new param through to the query string.
3. `MT5BridgeBroker.open_order(..., magic: Optional[int] = None)` — include
   `"magic": magic` in the command dict when provided.

### `agents/base_agent.py` changes

1. `BaseSpecialistAgent.__init__` gains `magic: Optional[int] = None`
   (defaults to 888999 — today's implicit global value — when not given, so
   any direct instantiation outside `SquadManager` keeps working).
2. `symbol_positions` filtering (`agents/base_agent.py:463`) becomes
   `p.get("symbol") == self.symbol and p.get("magic") == self.magic`. This
   is the fix that stops one timeframe-instance from managing (trailing
   stop, breakeven, counting toward `max_open_positions`) another
   instance's positions.
3. `_reconcile_closed_trades()` calls
   `self.broker.consume_recently_closed(symbol=self.symbol, magic=self.magic)`.
4. Every `self.broker.open_order(...)` call site passes `magic=self.magic`.

### `agents/squad_manager.py` changes

`SquadManager.__init__` already accepts `journal_dir` and threads it to each
specialist (`journal_dir / journal_subdir`) — this part already works, it's
just never called with a real path from the CLI today. Add a `magic` lookup
(the deterministic table above, keyed by `self.timeframe`) and pass
`magic=...` alongside `journal_dir=...` when constructing each specialist.

### `main.py` changes

1. `cmd_run` currently builds `SquadManager(...)` without `journal_dir` —
   thread it through. Auto-derive the default from timeframe so the
   existing M5 production invocation needs **no flag change** to keep its
   current path: `journal_dir = config.project_root / "journal"` when
   `timeframe == "M5"`, else `config.project_root / f"journal_{timeframe.lower()}"`.
   An explicit `--journal-dir` override remains available for tests/manual
   runs.
2. `--timeframe` choices (`main.py:267`) expand from
   `["M1", "M5", "M15", "H1"]` to `["M1", "M5", "M15", "M30", "H1", "H4", "D1"]`.

### Operational step (no code): bar coverage for M30/H1/H4/D1

The already-compiled EA already streams bars for whatever `InpTimeframe`
it's given, for every squad symbol, every poll cycle
(`g_squadSymbols` loop in `OnTimer()`). Getting bars for all 6 target
timeframes into the bridge means attaching the (recompiled, per this spec)
EA to 4 additional charts — one each with `InpTimeframe` = M30, H1, H4, D1
(M5 and M15 are already covered: M5 by the existing production chart, M15
for free since every instance always streams it regardless of its own
`InpTimeframe`). Each additional chart can be any symbol's chart — the EA
loops over all 9 squad symbols internally regardless of which chart it's
attached to.

This is a manual MT5 terminal step for the user to perform once the
recompiled EA is deployed, not part of the code change.

## Considered and rejected

**A shared, cross-instance concurrent-position cap per symbol.** E.g.
capping total open `XAUUSD` positions at 3 *across all 6 timeframe
instances combined*, instead of 3 *per instance*. Rejected for Phase 1:
`max_open_positions` (`agents/base_agent.py:538`) already reads real
account state (`self.broker.get_open_positions()`), which is shared across
all processes — once positions are correctly filtered by `magic` (this
spec), each instance's own cap is already enforced against reality, and
building a second, cross-instance cap needs new coordination state this
spec doesn't otherwise require. If real-money testing in Phase 2 shows
6-instance stacking is a genuine exposure problem, that's a targeted follow
up then, not a speculative addition now.

**Routing commands to a specific EA chart instance instead of a shared
queue.** Rejected — the shared FIFO queue
(`_pending_commands.pop(0)`, `mt5/bridge_server.py:204`) already works
correctly once each *command* carries the magic it needs; which physical
chart happens to execute it doesn't matter, since `SetExpertMagicNumber` is
now set per-command, not per-EA-instance. Routing by chart would need a new
per-instance queue/polling scheme for no behavioral gain.

## Migration / rollout safety (real capital — read before deploying)

1. Deploy the recompiled EA and the updated Python code **together**. The
   command-magic fallback (`InpMagicNumber` when a command omits `magic`)
   and the position/closed-order magic default (888999) mean the M5
   instance's behavior is unchanged if wired correctly — but this must be
   verified, not assumed.
2. Immediately after restart, confirm the M5 instance still sees its
   existing open position(s): compare `get_open_positions()` output against
   what MT5's own Terminal → Trade tab shows, before letting the loop place
   any new order.
3. Bring up new timeframe-instances (M15 first, since gold/btc/eth already
   support `forced_timeframe=None`) on the **demo account only** first —
   confirm two instances of the same symbol run a full cycle (open, manage,
   close) without cross-touching each other's positions or double/zero
   counting PnL — before ever pointing a second instance at the real
   ~10,000 THB account.

## Testing

- `tests/test_squad_manager.py` (or wherever `SquadManager` construction is
  covered today): two specialists for the same symbol, different
  timeframes/magics/journal_dirs, constructed side by side — assert
  distinct `journal_dir` and `magic` per the table above, including the
  M5→888999 pin.
- `tests/test_agents.py`: `symbol_positions` filtering — given a fake broker
  returning positions with mixed `magic` values for the same symbol, assert
  a specialist only counts/manages the ones matching its own `magic`.
- `tests/test_mt5_bridge.py`: `_pop_recently_closed(symbol, magic)` — given
  queued closed-order entries for two different magics on the same symbol,
  assert polling with `magic=A` only removes A's entries and leaves B's
  entries in the queue for a later poll.
- A small addition confirming `main.py`'s journal-dir auto-derivation: M5
  timeframe → `journal/`, any other timeframe → `journal_{tf}/`.

Per project convention (`[[feedback_rebuild_after_code_fix]]`): Python
changes are exercised via `pytest tests/ -q` and a container restart
(bind-mounted, no rebuild needed for logic changes — this session's docker
rebuild request is a one-off, not a standing requirement). The `.mq5` change
requires a MetaEditor recompile and reattaching the EA to its chart(s), plus
the new M30/H1/H4/D1 chart attachments described above.

## Out of Scope

- Everything under "Goal" above marked out of scope for Phase 1.
- A UI/dashboard view spanning multiple timeframe-instances of the same
  symbol (each instance's own journal/rich-console output is unchanged).
- Close/modify-by-ticket commands do not need a `magic` field — a ticket
  number already uniquely identifies a position; `magic` is only needed for
  attribution on `ORDER_OPEN` and for filtering broad queries
  (`get_open_positions`, `recently_closed`).
