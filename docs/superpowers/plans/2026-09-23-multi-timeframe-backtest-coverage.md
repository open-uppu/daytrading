# Multi-Timeframe Backtest Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `M30`, `H1`, and `D1` backtestable for all 9 squad symbols through the existing `python3 main.py backtest` CLI and leaderboard report, with zero behavior change to the existing `M5`/`M15` paths.

**Architecture:** Thread an explicit `timeframe` parameter through the three backtest entry points that currently hardcode `"M15"` (`run_comparison.run_all_strategies`, `run_cross_market_comparison.evaluate_market_strategies`, `run_cross_market_comparison.run_cross_market_study`), add the two missing Yahoo-interval branches (`M30`, `D1`) to `data_loader.load_historical_data`, and widen `main.py`'s `--timeframe` CLI choices. No new module — every timeframe reuses the same multi-strategy evaluator M15 already runs today.

**Tech Stack:** Python, pandas, pytest, monkeypatch-based mocking (no live network calls in tests).

## Global Constraints

- H4 is explicitly out of scope — do not add it anywhere in this plan (no native Yahoo interval; user decided to drop it entirely, not defer it).
- `run_cross_market_study`'s hardcoded `markets = ["XAUUSD", "BTCUSD", "ETHUSD"]` list (`backtest/run_cross_market_comparison.py:88`) stays exactly as-is. Full 9-symbol coverage for the new timeframes comes from the single-market CLI path (`--market=<any of the 9>`), which already resolves every symbol via `MARKET_ALIASES`. Expanding `--market=all` to 9 symbols would also change today's M15 `--market=all` output and is a separate decision, not part of this plan.
- No automated pass/fail gate on results. Every task's output stays the existing report-only leaderboard/panel shape — do not add scoring, thresholds, or a go/no-go decision anywhere.
- Zero behavior change when `timeframe` is omitted or `M15`/`M5` is passed — every new parameter defaults to `"M15"` (or, for `main.py`'s CLI flag, keeps its existing default of `"M5"`), matching today's exact behavior for any caller that doesn't opt in.
- Run `pytest tests/ -q` after every task and keep it green before moving to the next task.
- Do not touch `ASSET_SPECS` (`backtest/data_loader.py:36-134`), `backtest/strategies.py`, or anything under `backtest/run_m5_backtest.py` — none of them need to change for this plan's scope.

---

## File Structure

| File | Responsibility in this plan |
|---|---|
| `backtest/data_loader.py` | `load_historical_data` — add `M30`/`D1` Yahoo-interval branches (`H1` already exists and is correct, just previously unreachable from the CLI) |
| `backtest/run_cross_market_comparison.py` | `evaluate_market_strategies` + `run_cross_market_study` — accept and forward a `timeframe` param instead of hardcoding `"M15"` |
| `backtest/run_comparison.py` | `run_all_strategies` (the gold-specific CLI path) — same `timeframe` threading; missed by the original design spec, found during planning (see Self-Review Notes) |
| `main.py` | `cmd_backtest` — forward `timeframe=tf` into all three call sites above; `bt_parser` — widen `--timeframe` choices |

---

## Task 1: `data_loader.load_historical_data` — add M30/D1 branches

**Files:**
- Modify: `backtest/data_loader.py:200-208` (the `if/elif/else` inside `load_historical_data`)
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `load_historical_data(symbol=..., timeframe="M30")` calls `fetch_yahoo_candle_data(yahoo_sym, interval="30m", range_str="60d", price_precision=price_precision)`; `timeframe="D1"` calls it with `interval="1d", range_str="730d"`. `timeframe="H1"` behavior is unchanged (already correct). No change to `M15`/`M5`/the `else` fallback.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_backtest.py` (reuse this file's existing imports — `fetch_yahoo_candle_data` is already imported at the top):

```python
def test_load_historical_data_m30_and_d1_use_correct_yahoo_intervals(monkeypatch, tmp_path):
    """M30/D1 must hit their own Yahoo interval, not silently fall through
    to the M15 branch's interval="15m" (which is what happens today for
    any timeframe string the if/elif chain doesn't recognize)."""
    import backtest.data_loader as data_loader

    monkeypatch.setattr(data_loader, "DATA_DIR", tmp_path)

    calls = []

    def fake_fetch(yahoo_symbol, interval="15m", range_str="60d", price_precision=2):
        calls.append({"interval": interval, "range_str": range_str})
        return pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=5, freq="D"),
            "open": [1.0] * 5, "high": [1.0] * 5, "low": [1.0] * 5,
            "close": [1.0] * 5, "volume": [100] * 5
        })

    monkeypatch.setattr(data_loader, "fetch_yahoo_candle_data", fake_fetch)

    data_loader.load_historical_data(symbol="XAUUSD", timeframe="M30")
    data_loader.load_historical_data(symbol="XAUUSD", timeframe="D1")

    assert calls[0] == {"interval": "30m", "range_str": "60d"}
    assert calls[1] == {"interval": "1d", "range_str": "730d"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backtest.py::test_load_historical_data_m30_and_d1_use_correct_yahoo_intervals -v`
Expected: FAIL — `calls[0]` is `{"interval": "15m", "range_str": "60d"}` (the `else` branch), not `{"interval": "30m", ...}`.

- [ ] **Step 3: Write minimal implementation**

In `backtest/data_loader.py`, replace the `try:` block's `if/elif/else` chain (currently lines 200-208):

```python
        if timeframe.upper() == "M15":
            df = fetch_yahoo_candle_data(yahoo_sym, interval="15m", range_str="60d", price_precision=price_precision)
        elif timeframe.upper() == "H1":
            df = fetch_yahoo_candle_data(yahoo_sym, interval="1h", range_str="730d", price_precision=price_precision)
        elif timeframe.upper() == "M5":
            df = fetch_yahoo_candle_data(yahoo_sym, interval="5m", range_str="60d", price_precision=price_precision)
        elif timeframe.upper() == "M30":
            df = fetch_yahoo_candle_data(yahoo_sym, interval="30m", range_str="60d", price_precision=price_precision)
        elif timeframe.upper() == "D1":
            df = fetch_yahoo_candle_data(yahoo_sym, interval="1d", range_str="730d", price_precision=price_precision)
        else:
            df = fetch_yahoo_candle_data(yahoo_sym, interval="15m", range_str="60d", price_precision=price_precision)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backtest.py::test_load_historical_data_m30_and_d1_use_correct_yahoo_intervals -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -q`
Expected: All PASS (this touches a shared data-loading path — confirm nothing that relies on the `M15`/`H1`/`M5` branches regressed).

- [ ] **Step 6: Commit**

```bash
git add backtest/data_loader.py tests/test_backtest.py
git commit -m "feat(backtest): add M30/D1 Yahoo interval branches to load_historical_data

H1 already had a correct branch but was unreachable from the CLI.
M30/D1 previously fell through to the M15 branch's interval=\"15m\"
silently -- any backtest requested at those timeframes was actually
running on 15-minute bars with no error.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: `run_cross_market_comparison.py` — thread `timeframe` through

**Files:**
- Modify: `backtest/run_cross_market_comparison.py:33-41` (`evaluate_market_strategies` signature + `load_historical_data` call), `:64` (the bar-count log line), `:84-92` (`run_cross_market_study` signature + its `evaluate_market_strategies` calls)
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `load_historical_data(symbol, timeframe)` (Task 1 — no signature change there, just newly correct for `M30`/`D1`).
- Produces: `evaluate_market_strategies(symbol: str, initial_balance: float = 10000.0, timeframe: str = "M15")`; `run_cross_market_study(initial_balance: float = 10000.0, timeframe: str = "M15")`. Both default to `"M15"` — any existing caller that doesn't pass `timeframe` keeps today's exact behavior.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_backtest.py`:

```python
def test_evaluate_market_strategies_forwards_timeframe(monkeypatch):
    """evaluate_market_strategies must pass its own timeframe argument into
    load_historical_data instead of the hardcoded "M15" it used before this
    change -- otherwise --timeframe=M30 silently backtests M15 bars."""
    import backtest.run_cross_market_comparison as cross_market

    captured = {}

    def fake_load(symbol, timeframe="M15", **kwargs):
        captured["timeframe"] = timeframe
        return generate_fallback_gold_data(bars=100)

    monkeypatch.setattr(cross_market, "load_historical_data", fake_load)

    cross_market.evaluate_market_strategies(symbol="XAUUSD", timeframe="M30")
    assert captured["timeframe"] == "M30"

    # Default stays M15 when the caller doesn't opt in.
    cross_market.evaluate_market_strategies(symbol="XAUUSD")
    assert captured["timeframe"] == "M15"
```

Check `tests/test_backtest.py`'s top import line (`from backtest.data_loader import generate_fallback_gold_data, ...`) already brings in `generate_fallback_gold_data` — reuse it, don't re-import.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backtest.py::test_evaluate_market_strategies_forwards_timeframe -v`
Expected: FAIL with `TypeError: evaluate_market_strategies() got an unexpected keyword argument 'timeframe'`

- [ ] **Step 3: Write minimal implementation**

In `backtest/run_cross_market_comparison.py`, update `evaluate_market_strategies`:

```python
def evaluate_market_strategies(
    symbol: str,
    initial_balance: float = 10000.0,
    timeframe: str = "M15"
) -> Dict[str, Any]:
    """
    Evaluates all strategies on a specific market and returns ranked results and winner.
    """
    spec = ASSET_SPECS.get(symbol, ASSET_SPECS["XAUUSD"])
    df = load_historical_data(symbol=symbol, timeframe=timeframe)
```

Update the bar-count log line right after (currently `f"... | {len(df)} M15 Bars ===[/bold gold1]")`) to report the actual timeframe instead of a hardcoded label:

```python
    console.print(f"\n[bold gold1]=== Testing Market: {symbol} ({spec['name']}) | {len(df)} {timeframe} Bars ===[/bold gold1]")
```

Update `run_cross_market_study`:

```python
def run_cross_market_study(initial_balance: float = 10000.0, timeframe: str = "M15") -> Dict[str, Any]:
    """
    Runs full comparative study across Gold (XAUUSD), Bitcoin (BTCUSD), and Ethereum (ETHUSD).
    """
    markets = ["XAUUSD", "BTCUSD", "ETHUSD"]
    study_results = {}

    for m in markets:
        study_results[m] = evaluate_market_strategies(m, initial_balance=initial_balance, timeframe=timeframe)
```

Leave everything else in both functions (the leaderboard table rendering, sort/winner logic) untouched.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backtest.py::test_evaluate_market_strategies_forwards_timeframe -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -q`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add backtest/run_cross_market_comparison.py tests/test_backtest.py
git commit -m "feat(backtest): thread timeframe through evaluate_market_strategies/run_cross_market_study

Both hardcoded timeframe=\"M15\" in their load_historical_data call.
Default stays M15 -- no behavior change for existing callers.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: `run_comparison.py` — thread `timeframe` through the gold-specific path

**Files:**
- Modify: `backtest/run_comparison.py:35-44` (`run_all_strategies` signature + its `load_historical_data` call)
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `load_historical_data(symbol, timeframe)` (Task 1).
- Produces: `run_all_strategies(df=None, initial_balance=10000.0, save_chart=True, timeframe="M15")`. When `df` is explicitly passed, `timeframe` is unused (matches existing behavior — the hardcoded call only ever ran when `df is None`).

**Why this task exists:** `main.py`'s `cmd_backtest` special-cases `market in ["gold", "xauusd"]` to call `run_all_strategies` instead of `evaluate_market_strategies` (`main.py:277-280`). This path was missed by the original design spec — it has its own independent `load_historical_data(timeframe="M15")` hardcode (`backtest/run_comparison.py:44`), completely separate from `run_cross_market_comparison.py`. Without this task, `python3 main.py backtest --market=gold --timeframe=M30` would silently keep running M15 bars while every other symbol correctly switched to M30.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_backtest.py`:

```python
def test_run_all_strategies_forwards_timeframe_when_df_omitted(monkeypatch):
    """The gold-only CLI path (main.py's `--market=gold` special case) has
    its own independent load_historical_data call, separate from
    evaluate_market_strategies -- it must honor --timeframe too."""
    from backtest.run_comparison import run_all_strategies
    import backtest.run_comparison as run_comparison

    captured = {}

    def fake_load(timeframe="M15", **kwargs):
        captured["timeframe"] = timeframe
        return generate_fallback_gold_data(bars=100)

    monkeypatch.setattr(run_comparison, "load_historical_data", fake_load)

    run_all_strategies(initial_balance=10000.0, save_chart=False, timeframe="M30")
    assert captured["timeframe"] == "M30"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backtest.py::test_run_all_strategies_forwards_timeframe_when_df_omitted -v`
Expected: FAIL with `TypeError: run_all_strategies() got an unexpected keyword argument 'timeframe'`

- [ ] **Step 3: Write minimal implementation**

In `backtest/run_comparison.py`, update `run_all_strategies`:

```python
def run_all_strategies(
    df: pd.DataFrame = None,
    initial_balance: float = 10000.0,
    save_chart: bool = True,
    timeframe: str = "M15"
) -> List[Dict[str, Any]]:
    """
    Runs backtests for all strategies and returns sorted results list.
    """
    if df is None:
        df = load_historical_data(timeframe=timeframe)
```

Leave the rest of the function (engine construction, strategy loop, chart saving) untouched.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backtest.py::test_run_all_strategies_forwards_timeframe_when_df_omitted -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -q`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add backtest/run_comparison.py tests/test_backtest.py
git commit -m "feat(backtest): thread timeframe through run_all_strategies (gold CLI path)

main.py's --market=gold special case calls this instead of
evaluate_market_strategies and had its own independent M15 hardcode --
missed by the original spec, found while wiring the CLI in this plan.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: `main.py` — widen `--timeframe` choices and forward `tf` to all three call sites

**Files:**
- Modify: `main.py:277-296` (`cmd_backtest`'s `market == "all"` / `market in ["gold", "xauusd"]` / `else` branches), `main.py:375` (`bt_parser`'s `--timeframe` argument)
- Test: `tests/test_main_cli.py`

**Interfaces:**
- Consumes: `run_cross_market_study(initial_balance, timeframe)`, `run_all_strategies(initial_balance, save_chart, timeframe)`, `evaluate_market_strategies(symbol, initial_balance, timeframe)` (Tasks 2-3).
- Produces: `python3 main.py backtest --market=<any> --timeframe=<M5|M15|M30|H1|D1>` reaches the correct branch with the requested timeframe forwarded. The `M5` branch (`main.py:250-271`) and its `M5_TUNED_SYMBOLS` gate are untouched.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main_cli.py`:

```python
def test_backtest_parser_accepts_new_timeframe_choices():
    from main import build_parser
    parser = build_parser()
    for tf in ["M30", "H1", "D1"]:
        args = parser.parse_args(["backtest", "--market", "gold", "--timeframe", tf])
        assert args.timeframe == tf


def test_cmd_backtest_forwards_timeframe_to_all_three_non_m5_paths(monkeypatch):
    """market=all -> run_cross_market_study, market=gold -> run_all_strategies,
    any other market -> evaluate_market_strategies. All three must receive
    the CLI's --timeframe, not silently default to M15."""
    import main
    from main import build_parser, cmd_backtest

    captured = {}

    def fake_study(initial_balance, timeframe="M15"):
        captured["study_tf"] = timeframe

    def fake_all_strategies(initial_balance, save_chart=True, timeframe="M15"):
        captured["gold_tf"] = timeframe
        return []

    def fake_evaluate(symbol, initial_balance, timeframe="M15"):
        captured["single_tf"] = timeframe
        return {"winner": {
            "strategy_name": "x", "total_return_pct": 0.0, "win_rate_pct": 0.0,
            "profit_factor": 0.0, "max_drawdown_pct": 0.0, "days_hit_3pct_target": 0
        }}

    monkeypatch.setattr("backtest.run_cross_market_comparison.run_cross_market_study", fake_study)
    monkeypatch.setattr("backtest.run_comparison.run_all_strategies", fake_all_strategies)
    monkeypatch.setattr("backtest.run_cross_market_comparison.evaluate_market_strategies", fake_evaluate)

    parser = build_parser()

    cmd_backtest(parser.parse_args(["backtest", "--market", "all", "--timeframe", "M30"]))
    assert captured["study_tf"] == "M30"

    cmd_backtest(parser.parse_args(["backtest", "--market", "gold", "--timeframe", "H1"]))
    assert captured["gold_tf"] == "H1"

    cmd_backtest(parser.parse_args(["backtest", "--market", "xag", "--timeframe", "D1"]))
    assert captured["single_tf"] == "D1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_cli.py -v`
Expected: `test_backtest_parser_accepts_new_timeframe_choices` FAILS with `SystemExit: 2` (argparse rejects `M30`/`H1`/`D1` — not in `choices`). `test_cmd_backtest_forwards_timeframe_to_all_three_non_m5_paths` also FAILS (same reason, parsing fails before `cmd_backtest` is even called).

- [ ] **Step 3: Write minimal implementation**

In `main.py`, update the `bt_parser` timeframe line:

```python
    bt_parser.add_argument("--timeframe", default="M5", choices=["M5", "M15", "M30", "H1", "D1"], help="Timeframe for backtesting (default M5)")
```

Update `cmd_backtest`'s three non-M5 branches (currently `main.py:273-296`) to forward `tf`:

```python
    if market == "all":
        from backtest.run_cross_market_comparison import run_cross_market_study
        console.print("[bold cyan]Starting Full Cross-Market Research Study (Gold, BTC, ETH)...[/bold cyan]")
        run_cross_market_study(initial_balance=args.balance, timeframe=tf)
    elif market in ["gold", "xauusd"]:
        from backtest.run_comparison import run_all_strategies
        console.print("[bold gold1]Running Gold (XAUUSD) Strategy Comparison...[/bold gold1]")
        run_all_strategies(initial_balance=args.balance, save_chart=True, timeframe=tf)
    else:
        from backtest.run_cross_market_comparison import evaluate_market_strategies
        symbol = MARKET_ALIASES.get(market, market.upper())
        console.print(f"[bold cyan]Running {symbol} Strategy Comparison...[/bold cyan]")
        res = evaluate_market_strategies(symbol=symbol, initial_balance=args.balance, timeframe=tf)
        win = res["winner"]
        console.print(Panel(
            f"[bold green]Winner for {symbol}: {win['strategy_name']}[/bold green]\n"
            f"Total Return: [bold]{win['total_return_pct']:+.2f}%[/bold]\n"
            f"Win Rate: [bold]{win['win_rate_pct']:.1f}%[/bold]\n"
            f"Profit Factor: [bold]{win['profit_factor']:.2f}[/bold]\n"
            f"Max Drawdown: [bold]{win['max_drawdown_pct']:.2f}%[/bold]\n"
            f"Days Hit 3% Target: [bold]{win['days_hit_3pct_target']} days[/bold]",
            title=f"Optimal Strategy for {symbol}",
            border_style="green"
        ))
```

Leave everything above `if market == "all":` (the `--ml` early return, the `M5` branch and its `M5_TUNED_SYMBOLS` gate) exactly as it is today.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_cli.py -v`
Expected: All PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -q`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main_cli.py
git commit -m "feat(cli): widen backtest --timeframe to M30/H1/D1, forward tf to all 3 non-M5 paths

market=all -> run_cross_market_study, market=gold -> run_all_strategies,
every other market -> evaluate_market_strategies now all receive the
requested timeframe instead of implicitly running M15. H4 intentionally
not added (no native Yahoo interval).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** All three spec sections (`data_loader.py`, `run_cross_market_comparison.py`, `main.py`) map to Tasks 1, 2, and 4. **One gap found during planning, not in the original spec:** `backtest/run_comparison.py::run_all_strategies` — `main.py`'s `market in ["gold", "xauusd"]` branch calls this function, not `evaluate_market_strategies`, and it has its own completely independent `load_historical_data(timeframe="M15")` hardcode. Without Task 3, `--market=gold --timeframe=M30` would parse successfully (Task 4) but silently keep backtesting M15 bars for gold specifically, while every other symbol correctly switched timeframes — a worse bug than an error, since it fails silently. Added as Task 3; the spec document itself is not being edited retroactively, per this project's established convention (see `docs/superpowers/plans/2026-09-23-multi-timeframe-agent-infra.md`'s own Self-Review Notes for the same precedent).
- **Also corrected during planning:** the spec's Architecture section implied `run_cross_market_study` iterates "across the 9 symbols" — it doesn't; it's hardcoded to `["XAUUSD", "BTCUSD", "ETHUSD"]` and stays that way (see Global Constraints). Full 9-symbol coverage comes from the single-market path, which already resolves all 9 via `MARKET_ALIASES`.
- **Placeholder scan:** none — every step has complete, runnable code.
- **Type consistency:** `timeframe: str = "M15"` used consistently across `load_historical_data` (already existed), `evaluate_market_strategies`, `run_cross_market_study`, and `run_all_strategies`. `main.py`'s local variable is `tf` (already existed, `tf = getattr(args, "timeframe", "M5").upper()` at `main.py:239`) — Task 4 forwards that same variable, doesn't introduce a new name.
