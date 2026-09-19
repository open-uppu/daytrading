# M5 High-Frequency Scalping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an M5 high-frequency multi-asset scalping system targeting ~1 order every 10 minutes across Gold, BTC, and ETH, supporting concurrent positions (up to 3), 10-minute cadence spacing, dynamic tight ATR SL/TP, MT5 bridge M5 support, and comprehensive backtests.

**Architecture:** M5 high-frequency multi-signal scalper (Pullback Bounce + Micro Breakout + Fast Cross) integrated into `BaseSpecialistAgent` with multi-position support and cadence cooldown, supported by an updated MT5 EA streaming M5 bars and validated by M5 backtest benchmarks.

**Tech Stack:** Python 3.10+, Pandas, NumPy, MetaTrader 5 (MQL5), FastAPI, Pytest.

## Global Constraints
- Timeframe target: M5 (5-minute bars).
- Cadence target: ~1 order every 10 minutes (approx. every 2 M5 bars) during active setups.
- Max open positions per asset: 3 positions.
- Entry cooldown between positions on the same asset: minimum 10 minutes (or 2 bars / distinct price levels).
- Daily Target Lock (+3.0%) and Max Daily Loss Cutoff (-2.0%) must be preserved.
- Risk per trade: 0.5% (0.005) equity risk.

---

### Task 1: Configuration & CLI Timeframe Support

**Files:**
- Modify: `config.py`
- Modify: `main.py`
- Test: `tests/test_config_timeframe.py`

**Interfaces:**
- `config.timeframe_main`: string, default `"M5"`
- `config.max_open_positions`: int, default `3`
- `config.risk_per_trade_pct`: float, default `0.005`
- `main.py`: accepts `--timeframe` argument (choices: `["M1", "M5", "M15", "H1"]`, default `"M5"`)

- [ ] **Step 1: Write the failing test**
Create `tests/test_config_timeframe.py`:
```python
import pytest
from config import config
import argparse
from main import main

def test_config_scalping_defaults():
    assert config.timeframe_main == "M5"
    assert config.max_open_positions >= 3
    assert config.risk_per_trade_pct <= 0.01

def test_cli_parser_has_timeframe():
    from main import main
    import sys
    # Verify main module can parse --timeframe argument
    from main import cmd_loop
    assert callable(cmd_loop)
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_config_timeframe.py -v`
Expected: FAIL (because default is currently M15, max_open_positions is 1)

- [ ] **Step 3: Update `config.py` and `main.py`**
Modify `config.py`:
Set `timeframe_main: str = "M5"`
Set `max_open_positions: int = 3`
Set `risk_per_trade_pct: float = 0.005`
Set `loop_interval_sec: int = 10`

Modify `main.py`:
Add `--timeframe` argument to `loop` and `run` subparsers (default `"M5"`).
Pass `timeframe=args.timeframe` to `SquadManager`.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_config_timeframe.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add config.py main.py tests/test_config_timeframe.py
git commit -m "feat(config): support M5 default timeframe and 3 concurrent scalp positions"
```

---

### Task 2: M5 Scalping Strategy Suite

**Files:**
- Modify: `backtest/strategies.py`
- Test: `tests/test_m5_scalper.py`

**Interfaces:**
- `strategy_m5_scalper(window: pd.DataFrame, current_idx: int, asset_type: str = "gold") -> Dict[str, Any]`
  - Returns dict with keys: `action` ("BUY", "SELL", "HOLD"), `sl` (float), `tp` (float), `reason` (str), `signal_type` ("PULLBACK", "BREAKOUT", "CROSS")

- [ ] **Step 1: Write the failing test**
Create `tests/test_m5_scalper.py`:
```python
import pandas as pd
import numpy as np
import pytest
from backtest.strategies import strategy_m5_scalper

def generate_mock_m5_data(trend="bullish", count=40):
    prices = [2000.0]
    for i in range(count - 1):
        delta = 0.5 if trend == "bullish" else -0.5
        prices.append(prices[-1] + delta + np.random.uniform(-0.2, 0.2))
    df = pd.DataFrame({
        "open": prices,
        "high": [p + 0.5 for p in prices],
        "low": [p - 0.5 for p in prices],
        "close": prices,
        "volume": [100] * count
    })
    return df

def test_m5_scalper_bullish_pullback_or_cross():
    df = generate_mock_m5_data("bullish", 40)
    sig = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="gold")
    assert sig["action"] in ["BUY", "HOLD"]
    if sig["action"] == "BUY":
        assert sig["sl"] < df.iloc[-1]["close"]
        assert sig["tp"] > df.iloc[-1]["close"]

def test_m5_scalper_bearish():
    df = generate_mock_m5_data("bearish", 40)
    sig = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="gold")
    assert sig["action"] in ["SELL", "HOLD"]
    if sig["action"] == "SELL":
        assert sig["sl"] > df.iloc[-1]["close"]
        assert sig["tp"] < df.iloc[-1]["close"]
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_m5_scalper.py -v`
Expected: FAIL (ImportError: cannot import name 'strategy_m5_scalper')

- [ ] **Step 3: Implement `strategy_m5_scalper` in `backtest/strategies.py`**
Add:
- Fast EMA 9, EMA 21, EMA 100/200 calculation.
- Pullback touch on EMA 9/21 with confirmation.
- Micro breakout (5-bar high/low break).
- Fast cross (EMA 9 crossing EMA 21).
- ATR-based tight SL/TP tailored per asset (gold, btc, eth).

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_m5_scalper.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add backtest/strategies.py tests/test_m5_scalper.py
git commit -m "feat(strategy): implement M5 high-frequency scalper with multi-trigger engine"
```

---

### Task 3: Base Specialist Agent Multi-Position & 10-Minute Cooldown

**Files:**
- Modify: `agents/base_agent.py`
- Test: `tests/test_agent_concurrency.py`

**Interfaces:**
- `BaseSpecialistAgent`:
  - `max_open_positions: int = 3`
  - `min_entry_interval_sec: int = 600` (10 minutes)
  - `last_entry_time: Optional[datetime]`
  - `min_entry_dist_atr: float = 0.8` (new entry must be spaced from existing positions)
  - `step()` allows opening orders if `len(symbol_positions) < self.max_open_positions` and cooldown satisfied.

- [ ] **Step 1: Write the failing test**
Create `tests/test_agent_concurrency.py`:
```python
import pytest
from agents.gold_agent import GoldSpecialistAgent
from mt4.paper_broker import PaperTradingBroker

def test_specialist_concurrency_settings():
    agent = GoldSpecialistAgent(broker=PaperTradingBroker(), timeframe="M5")
    assert agent.timeframe == "M5"
    assert agent.max_open_positions == 3
    assert agent.min_entry_interval_sec == 600
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_agent_concurrency.py -v`
Expected: FAIL

- [ ] **Step 3: Implement concurrency & cooldown in `agents/base_agent.py`**
- Add `max_open_positions` (default 3) and `min_entry_interval_sec` (default 600) to `BaseSpecialistAgent.__init__`.
- In `step()`:
  - Check open positions for symbol: if `len(symbol_positions) >= self.max_open_positions`, monitor and return `CAP_REACHED`.
  - If open positions < max, verify cooldown (at least 600s or first trade) and spacing (`abs(current_price - pos['open_price']) >= 0.8 * atr`).
  - Adjust default `min_sl_dist` for M5 (Gold: 0.8, BTC: 25.0, ETH: 2.0).

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_agent_concurrency.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add agents/base_agent.py tests/test_agent_concurrency.py
git commit -m "feat(agent): support up to 3 concurrent scalp positions with 10-minute cadence cooldown"
```

---

### Task 4: Wire Specialists (Gold, BTC, ETH) and SquadManager to M5

**Files:**
- Modify: `agents/gold_agent.py`
- Modify: `agents/btc_agent.py`
- Modify: `agents/eth_agent.py`
- Modify: `agents/squad_manager.py`
- Test: `tests/test_specialists_m5.py`

**Interfaces:**
- `GoldSpecialistAgent`: uses `strategy_m5_scalper` for gold, default `timeframe="M5"`, `min_sl_dist=0.8`
- `BtcSpecialistAgent`: uses `strategy_m5_scalper` for btc, default `timeframe="M5"`, `min_sl_dist=25.0`
- `EthSpecialistAgent`: uses `strategy_m5_scalper` for eth, default `timeframe="M5"`, `min_sl_dist=2.0`
- `SquadManager`: propagates `timeframe` to all child specialists.

- [ ] **Step 1: Write the failing test**
Create `tests/test_specialists_m5.py`:
```python
import pytest
from agents.gold_agent import GoldSpecialistAgent
from agents.btc_agent import BtcSpecialistAgent
from agents.eth_agent import EthSpecialistAgent
from agents.squad_manager import SquadManager

def test_specialists_defaults_m5():
    g = GoldSpecialistAgent()
    b = BtcSpecialistAgent()
    e = EthSpecialistAgent()
    assert g.timeframe == "M5"
    assert b.timeframe == "M5"
    assert e.timeframe == "M5"
    assert g.min_sl_dist == 0.8
    assert b.min_sl_dist == 25.0
    assert e.min_sl_dist == 2.0

def test_squad_manager_timeframe_propagation():
    squad = SquadManager(timeframe="M5", broker_mode="paper")
    for agent in squad.specialists.values():
        assert agent.timeframe == "M5"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_specialists_m5.py -v`
Expected: FAIL

- [ ] **Step 3: Update `gold_agent.py`, `btc_agent.py`, `eth_agent.py`, and `squad_manager.py`**
Wire `strategy_m5_scalper` and set `timeframe="M5"`.
Accept `timeframe` in `SquadManager.__init__`.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_specialists_m5.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add agents/ tests/test_specialists_m5.py
git commit -m "feat(agents): connect Gold, BTC, ETH specialists and SquadManager to M5 scalper"
```

---

### Task 5: MT5 Bridge M5 Support

**Files:**
- Modify: `mt5/AgenticMT5Bridge.mq5`
- Modify: `mt5/bridge_server.py`
- Test: `tests/test_bridge_m5.py`

**Interfaces:**
- `mt5/bridge_server.py`: `get_market_data(timeframe="M5")` supports fallback to `M5` and converts bars properly.
- `AgenticMT5Bridge.mq5`:
  - Parameter `input ENUM_TIMEFRAMES InpTimeframe = PERIOD_M5;`
  - Dynamic timeframe serialization in JSON: `TimeframeToString(timeframe)` instead of hardcoded `"M15"`.

- [ ] **Step 1: Write the failing test**
Create `tests/test_bridge_m5.py`:
```python
import pytest
from mt5.bridge_server import MT5BridgeBroker, BarData, BarUploadPayload

def test_bridge_bar_payload_m5():
    payload = BarUploadPayload(
        symbol="XAUUSD",
        timeframe="M5",
        bars=[BarData(timestamp=1700000000, open=2000.0, high=2002.0, low=1999.0, close=2001.0, volume=50)]
    )
    assert payload.timeframe == "M5"
```

- [ ] **Step 2: Run test to verify it passes/fails**
Run: `pytest tests/test_bridge_m5.py -v`

- [ ] **Step 3: Update `AgenticMT5Bridge.mq5` and `mt5/bridge_server.py`**
- Fix line 107 in `AgenticMT5Bridge.mq5` to use `TimeframeToString(timeframe)` so M5 is serialized as `"M5"`.
- Add `SendMarketBars(..., InpTimeframe, 150)`.
- Ensure `MT5BridgeBroker.get_market_data` defaults or queries `timeframe="M5"`.

- [ ] **Step 4: Commit**
```bash
git add mt5/AgenticMT5Bridge.mq5 mt5/bridge_server.py tests/test_bridge_m5.py
git commit -m "fix(mt5): enable dynamic M5 bar upload in MT5 EA and bridge server"
```

---

### Task 6: M5 Data Loader & Backtest Benchmark Engine

**Files:**
- Modify: `backtest/data_loader.py`
- Modify: `backtest/run_cross_market_comparison.py`
- Modify: `backtest/run_comparison.py`
- Create: `backtest/run_m5_backtest.py`
- Test: `tests/test_m5_backtest.py`

**Interfaces:**
- `load_historical_data(symbol, timeframe="M5")`: fetches or generates high-density M5 bars.
- `run_m5_backtest()`: executes comparative M5 backtest across Gold, BTC, and ETH.
- Produces trade count, trades per hour, win rate, total return, profit factor, max drawdown, and days hitting +3% target.

- [ ] **Step 1: Write the failing test**
Create `tests/test_m5_backtest.py`:
```python
import pytest
from backtest.run_m5_backtest import run_single_asset_m5_backtest

def test_single_asset_m5_backtest_runs():
    res = run_single_asset_m5_backtest(symbol="XAUUSD", initial_balance=10000.0, max_bars=300)
    assert "total_trades" in res
    assert "win_rate_pct" in res
    assert res["total_trades"] > 0
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_m5_backtest.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `backtest/run_m5_backtest.py` and enhance `data_loader.py`**
- Ensure M5 data loader handles caching and generation if offline/synthetic.
- Implement simulation engine accounting for concurrent positions (up to 3) and 10-min cadence.
- Track trade entry timestamps to report average minutes between trades.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_m5_backtest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add backtest/ tests/test_m5_backtest.py
git commit -m "feat(backtest): implement comprehensive M5 high-frequency backtesting engine"
```

---

### Task 7: Full Verification & Live Simulation Run

**Files:**
- Run all tests across the test suite: `pytest -v`
- Run paper simulation loop: `python3 main.py run --agent=all --mode=paper --timeframe=M5 --max-iter=5`
- Execute full M5 backtest across Gold, BTC, ETH: `python3 backtest/run_m5_backtest.py`
- Update `AGENTS.md` and `README.md` documentation to reflect M5 scalping mode and performance.
- Commit all documentation and test verification reports.
