# Multi-Timeframe Backtest Coverage — Design Spec

Date: 2026-09-23

## Problem

`docs/superpowers/specs/2026-09-23-multi-timeframe-agent-infra-design.md` built the
infrastructure to run permanent, concurrent per-symbol-per-timeframe live
instances (M5, M15, M30, H1, H4, D1 — six timeframes across all 9
`SPECIALIST_REGISTRY`/`GATED_SPECIALISTS` symbols), but explicitly deferred
deciding **which** of those combinations are actually profitable enough to
run live:

> "This is mechanism only — it does not decide which symbol/timeframe
> combinations are actually profitable or should be enabled live."
> "Whether and when to run a second timeframe-instance against the real
> ~10,000 THB account is a separate decision for the user to make
> explicitly."

Today `python3 main.py backtest --timeframe` only accepts `M5` or `M15`
(`main.py`'s `bt_parser`). `backtest/data_loader.py::load_historical_data`
only has explicit branches for `M15`, `H1`, and `M5` — `H1` already fetches
correctly but is unreachable from the CLI; anything else (`M30`, `D1`)
silently falls through to the `M15` `else` branch and backtests the wrong
bar data without any error. `backtest/run_cross_market_comparison.py`'s
`evaluate_market_strategies()` hardcodes `timeframe="M15"` in its
`load_historical_data(...)` call, so even `H1` can't be reached through the
existing cross-market leaderboard path either.

Confirmed with the user (2026-09-23):
- Target timeframe set for this backtest expansion: **M30, H1, D1** (H4
  removed — Yahoo Finance has no native 4-hour interval; resampling from H1
  was considered and rejected, H4 is out of scope entirely, not deferred).
- Target symbols: all 9 (`gold, btc, eth, xag, gbp, eur, xpt, ukoil, xng`) —
  one generic implementation, not a phased subset.
- No automated pass/fail gate. The user is not yet confident in a numeric
  threshold (return%, win rate, profit factor, max DD) — this spec produces
  the same leaderboard-style report the M15/M5 paths already produce, and
  the decision to bring any specific combo live stays a manual, human step,
  exactly like it is today for M15.

## Goal

Make `M30`, `H1`, and `D1` backtestable for all 9 symbols through the
existing CLI and reporting shape, with zero behavior change to the existing
`M5`/`M15` paths.

**Explicitly out of scope:**
- `H4` (no native Yahoo interval; removed as a target entirely per user
  decision, not merely deferred).
- Any automated go/no-go threshold or gate on the results — output is a
  report only.
- Relaxing `SPECIALIST_REGISTRY`'s `forced_timeframe="M15"` pin for
  xag/gbp/eur/xpt/ukoil/xng, or deciding to bring any new combo live. That
  remains a separate, explicit decision per the infra spec's own scope
  boundary.
- Tuning `ASSET_SPECS`' per-symbol `min_sl_dist` floors for the new
  timeframes. Every strategy's SL/TP is ATR-derived and self-scales with
  the bar's own volatility; the fixed-dollar floor exists only as a lower
  bound and is already effectively inert on higher timeframes where ATR
  dominates it. If a specific combo's backtest results look distorted by
  this, that's a targeted follow-up on that combo, not a blanket change
  made speculatively now.
- A dedicated M30/H1/D1-specific strategy runner (paralleling
  `backtest/run_m5_backtest.py`). That file exists because the M5 scalper
  needed genuinely different mechanics (cadence cooldown, up to 3 stacked
  positions). M30/H1/D1 run the same multi-strategy evaluation M15
  already does — no new mechanics, so no new module.

## Architecture

### `backtest/data_loader.py::load_historical_data`

Add two explicit branches alongside the existing `M15`/`H1`/`M5` ones (found
via `grep -n "timeframe.upper() ==" backtest/data_loader.py`):

- `M30` → `fetch_yahoo_candle_data(yahoo_sym, interval="30m", range_str="60d", ...)`
- `D1` → `fetch_yahoo_candle_data(yahoo_sym, interval="1d", range_str="730d", ...)`

`H1` already has a correct branch (`interval="1h", range_str="730d"`) — no
change needed there, it's just never been reachable from the CLI.

The `else` branch (silent fallback to `M15`'s fetch) stays as the catch-all
for any future/unrecognized timeframe string, but every timeframe this spec
targets now gets its own explicit branch, so none of them can silently hit
it.

### `backtest/run_cross_market_comparison.py`

- `evaluate_market_strategies(symbol: str, initial_balance: float = 10000.0)`
  gains `timeframe: str = "M15"` and forwards it into its
  `load_historical_data(symbol=symbol, timeframe=timeframe)` call instead of
  the hardcoded string.
- `run_cross_market_study(initial_balance: float = 10000.0)` gains the same
  `timeframe: str = "M15"` param and forwards it to each
  `evaluate_market_strategies(...)` call it makes across the 9 symbols.

Default stays `"M15"` on both — every existing caller (including any
existing test) that doesn't pass `timeframe` keeps today's exact behavior.

### `main.py`

`bt_parser`'s `--timeframe` argument: `choices=["M5", "M15"]` becomes
`choices=["M5", "M15", "M30", "H1", "D1"]`. `cmd_backtest`'s existing
dispatch (`if tf == "M5": ... else: ... run_cross_market_study(...) /
evaluate_market_strategies(...)`) already forwards `tf` nowhere today for
the non-M5 path — that call site (`main.py`'s `cmd_backtest`, the
`run_cross_market_study(initial_balance=args.balance)` and
`evaluate_market_strategies(symbol=symbol, initial_balance=args.balance)`
calls) needs `timeframe=tf` added as an argument, now that the functions
accept it.

No change to the `M5` branch, the `M5_TUNED_SYMBOLS` gate, or anything
`--ml` related.

### Output / reporting

Unchanged shape. `--market=all --timeframe=M30` prints the same
cross-market leaderboard panel `--market=all --timeframe=M15` prints today
(winner strategy per symbol, Return%, Win Rate, Profit Factor, Max DD, Days
Hit 3% Target). `--market=<symbol> --timeframe=D1` prints the same
single-market winner panel. No new output format, no persistence beyond
whatever the existing path already writes (if anything).

## Testing

- Extend whatever test file already covers `load_historical_data`
  (`grep -rn "load_historical_data" tests/`) with cases asserting `M30` →
  `interval="30m"` and `D1` → `interval="1d"` are the values passed to
  `fetch_yahoo_candle_data` (mock/monkeypatch that call, matching however
  the existing `M15`/`H1`/`M5` cases in that file are already tested — reuse
  the same mocking pattern rather than inventing a new one).
- A test asserting `evaluate_market_strategies(symbol=..., timeframe="M30")`
  calls `load_historical_data` with `timeframe="M30"` (not the old hardcoded
  `"M15"`), and that omitting `timeframe` still defaults to `"M15"`.
- Run `pytest tests/ -q` after each change; must stay green throughout —
  this is a pure additive/parameterization change, no existing test should
  need to change.

## Self-Review Notes

- **Placeholder scan:** none.
- **Internal consistency:** `H1` is called out explicitly as "already
  correct, just unreachable" rather than lumped in with the two genuinely
  new branches — this matters for the implementation plan, since `H1`
  needs zero `data_loader.py` changes, only the CLI `choices` and the two
  function signatures.
- **Scope check:** single cohesive change across 3 files, no
  decomposition needed.
- **Ambiguity check:** "pass criteria" is deliberately left unresolved per
  the user's own "ยังไม่มั่นใจ" (not confident yet) — this spec does not
  invent a threshold on the user's behalf; the Goal section states plainly
  that output is a report, not a gate.
