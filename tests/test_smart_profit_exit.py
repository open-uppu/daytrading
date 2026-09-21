"""
Unit tests for Smart Profit Exit Engine.
Verifies that Specialist Agents actively close profitable orders before hitting TP/SL
under four conditions: Opposite Signal, Wick Rejection, Bollinger Band Touch, and Stagnation Timeout.
Also strictly verifies that Smart Exit NEVER fires when a position is in loss.
"""

from datetime import datetime, timedelta
import pandas as pd
import pytest

from config import config
from agents.btc_agent import BtcSpecialistAgent
from mt4.paper_broker import PaperTradingBroker


@pytest.fixture(autouse=True)
def force_smart_exit_on(monkeypatch):
    """Smart Exit ships disabled (A/B experiment); these tests exercise the engine itself."""
    monkeypatch.setattr(config, "smart_exit_enabled", True)


def create_mock_bars(n: int = 30, base_price: float = 80000.0, trend: str = "flat") -> pd.DataFrame:
    """Helper to construct synthetic OHLCV bars with predictable indicator behavior."""
    prices = []
    curr = base_price
    for i in range(n):
        if trend == "bullish":
            curr += 15.0
        elif trend == "bearish":
            curr -= 15.0
        prices.append(curr)

    highs = [p + 10.0 for p in prices]
    lows = [p - 10.0 for p in prices]
    opens = [p - 2.0 for p in prices]
    closes = prices

    return pd.DataFrame({
        "timestamp": pd.date_range("2026-08-01 10:00", periods=n, freq="5min"),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1000] * n
    })


def test_smart_exit_triggers_on_opposite_signal_when_in_profit(tmp_path):
    """Validates that a profitable BUY order is closed when an opposite bearish signal appears."""
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="BTCUSD")
    broker.current_price = 80000.0
    res = broker.open_order(
        symbol="BTCUSD",
        order_type="BUY",
        lots=0.10,
        sl=79500.0,
        tp=81000.0
    )
    ticket = res["ticket"]
    # Price moves up into profit
    broker.current_price = 80100.0
    pos = broker.get_open_positions()[0]
    assert pos["unrealized_pnl"] > 0

    agent = BtcSpecialistAgent(broker=broker, timeframe="M5", journal_dir=tmp_path)

    # Rally then pullback: EMA 9 crosses below EMA 21 on the last bar (close 80,065 still > entry).
    # Wicks kept tight so only the EMA-cross rule can fire.
    closes = [79800.0 + i * 25 for i in range(26)] + [80425.0 - 40 * j for j in range(1, 10)]
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-08-01 10:00", periods=len(closes), freq="5min"),
        "open": [c + 2 for c in closes],
        "high": [c + 3 for c in closes],
        "low": [c - 1 for c in closes],
        "close": closes,
        "volume": [1000] * len(closes),
    })
    broker.current_price = closes[-1]

    closed = agent._manage_active_position(pos, df_main=df)
    assert closed is True
    # Verify position is closed in broker
    assert len(broker.get_open_positions()) == 0
    assert len(broker.get_closed_orders()) == 1


def test_smart_exit_never_closes_when_in_loss(tmp_path):
    """Validates that Smart Exit NEVER executes if the position is in drawdown."""
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="BTCUSD")
    # Open BUY at 80,000, current price drops to 79,800 (in loss -$20)
    broker.current_price = 79800.0
    res = broker.open_order(
        symbol="BTCUSD",
        order_type="BUY",
        lots=0.10,
        sl=79500.0,
        tp=81000.0
    )
    ticket = res["ticket"]
    pos = broker.get_open_positions()[0]
    assert pos["unrealized_pnl"] < 0  # In loss

    agent = BtcSpecialistAgent(broker=broker, timeframe="M5", journal_dir=tmp_path)

    # Even with a strong bearish opposite signal:
    df = create_mock_bars(30, base_price=79800.0, trend="bearish")

    closed = agent._manage_active_position(pos, df_main=df)
    # MUST NOT CLOSE: Smart profit exit only closes when in profit!
    assert closed is False
    assert len(broker.get_open_positions()) == 1


def test_smart_exit_wick_rejection(tmp_path):
    """Validates that a profitable BUY order is closed when the latest candle has a long upper rejection wick."""
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="BTCUSD")
    broker.current_price = 80000.0
    res = broker.open_order(
        symbol="BTCUSD",
        order_type="BUY",
        lots=0.10,
        sl=79500.0,
        tp=81000.0
    )
    # Price moves up into profit
    broker.current_price = 80150.0
    pos = broker.get_open_positions()[0]
    assert pos["unrealized_pnl"] > 0

    agent = BtcSpecialistAgent(broker=broker, timeframe="M5", journal_dir=tmp_path)

    # Construct bars with strong upper rejection wick on last bar
    df = create_mock_bars(30, base_price=80100.0, trend="bullish")
    # High spiked to 80,320 but closed at 80,130 (Upper wick = 190 / 210 = 90%)
    df.loc[df.index[-1], "open"] = 80120.0
    df.loc[df.index[-1], "high"] = 80320.0
    df.loc[df.index[-1], "low"] = 80110.0
    df.loc[df.index[-1], "close"] = 80130.0

    closed = agent._manage_active_position(pos, df_main=df)
    assert closed is True
    assert len(broker.get_open_positions()) == 0


def test_smart_exit_bollinger_band_touch(tmp_path):
    """Validates that a profitable BUY order is closed when price touches the Upper Bollinger Band."""
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="BTCUSD")
    broker.current_price = 80000.0
    res = broker.open_order(
        symbol="BTCUSD",
        order_type="BUY",
        lots=0.10,
        sl=79500.0,
        tp=81000.0
    )
    # Price moves up into profit
    broker.current_price = 80500.0
    pos = broker.get_open_positions()[0]
    assert pos["unrealized_pnl"] > 0

    agent = BtcSpecialistAgent(broker=broker, timeframe="M5", journal_dir=tmp_path)

    df = create_mock_bars(30, base_price=80000.0, trend="bullish")
    # Make last price surge well above Upper BB
    df.loc[df.index[-1], "close"] = 80500.0

    closed = agent._manage_active_position(pos, df_main=df)
    assert closed is True
    assert len(broker.get_open_positions()) == 0


def test_smart_exit_stagnation_timeout(tmp_path):
    """Validates that a position held > 20 mins in profit with stalled momentum is closed."""
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="BTCUSD")
    broker.current_price = 80000.0
    res = broker.open_order(
        symbol="BTCUSD",
        order_type="BUY",
        lots=0.10,
        sl=79500.0,
        tp=81000.0
    )
    ticket = res["ticket"]
    # Price moves up into profit
    broker.current_price = 80100.0
    pos = broker.get_open_positions()[0]
    assert pos["unrealized_pnl"] > 0

    agent = BtcSpecialistAgent(broker=broker, timeframe="M5", journal_dir=tmp_path)
    # Simulate order opened 25 minutes ago
    agent.position_open_times[ticket] = datetime.now() - timedelta(minutes=25)

    df = create_mock_bars(30, base_price=80100.0, trend="flat")
    # Ensure no new high between last two bars
    df.loc[df.index[-1], "high"] = 80110.0
    df.loc[df.index[-2], "high"] = 80115.0

    closed = agent._manage_active_position(pos, df_main=df)
    assert closed is True
    assert len(broker.get_open_positions()) == 0
