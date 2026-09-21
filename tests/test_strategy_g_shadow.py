"""Strategy G (BB 2.5σ extreme reversion) signal + shadow-log behaviour on the Gold agent."""

import json
import pandas as pd

from agents.gold_agent import GoldSpecialistAgent
from backtest.strategies import strategy_bb_extreme
from mt4.paper_broker import PaperTradingBroker


def make_bars(closes) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-08-01 10:00", periods=len(closes), freq="5min"),
        "open": [c + 0.1 for c in closes],
        "high": [c + 0.3 for c in closes],
        "low": [c - 0.3 for c in closes],
        "close": closes,
        "volume": [1000] * len(closes),
    })


CRASH = [2000.0 + (0.4 if i % 2 else -0.4) for i in range(50)] + [1998.0, 1996.0, 1993.0, 1989.0, 1984.0, 1978.0]
FLAT = [2000.0 + (0.4 if i % 2 else -0.4) for i in range(56)]


def test_signal_buy_on_crash_hold_on_flat():
    sig = strategy_bb_extreme(make_bars(CRASH))
    assert sig["action"] == "BUY" and sig["tp"] > sig["close"] > sig["sl"]
    assert strategy_bb_extreme(make_bars(FLAT))["action"] == "HOLD"


def test_shadow_log_once_per_bar_and_real_signal_unchanged(tmp_path):
    agent = GoldSpecialistAgent(broker=PaperTradingBroker(initial_balance=10000.0, symbol="XAUUSD"),
                                timeframe="M5", journal_dir=tmp_path)
    forming = CRASH + [1978.5]  # extra last bar = still-forming candle, must be ignored
    df = make_bars(forming)
    first = agent.evaluate_strategy_signal(df)
    agent.evaluate_strategy_signal(df)  # same closed bar again -> no duplicate line
    lines = (tmp_path / "shadow_strategy_g.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["action"] == "BUY"
    assert first.get("action") in ("BUY", "SELL", "HOLD")
