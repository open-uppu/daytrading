"""
Unit tests for strategy enhancements:
1. Dynamic Trailing Break-Even in BaseSpecialistAgent._manage_active_position
2. Multi-Timeframe Macro Trend Filter in BaseSpecialistAgent.step
3. SquadManager Duo Preset (--agent=duo)
"""

import pytest
from pathlib import Path
import tempfile
import pandas as pd

from config import config
from agents.gold_agent import GoldSpecialistAgent
from agents.squad_manager import SquadManager
from mt4.paper_broker import PaperTradingBroker


def test_dynamic_trailing_breakeven():
    """Validates that profit >= +0.8R automatically modifies SL to Entry + Buffer."""
    broker = PaperTradingBroker(initial_balance=10000.0)
    with tempfile.TemporaryDirectory() as tmp:
        agent = GoldSpecialistAgent(
            broker=broker,
            broker_mode="paper",
            initial_balance=10000.0,
            journal_dir=Path(tmp) / "xauusd"
        )
        
        # Open a test BUY position
        open_res = broker.open_order(
            symbol="XAUUSD",
            order_type="BUY",
            lots=0.10,
            sl=2600.0,
            tp=2660.0
        )
        ticket = open_res["ticket"]
        pos = broker.open_positions[ticket]
        open_p = pos["open_price"]
        
        # Set realistic SL below entry (sl_dist = $2.00)
        pos["sl"] = open_p - 2.0
        # Set market price above trailing trigger (+0.8R = +$1.60)
        pos["bid"] = open_p + 2.50
        pos["ask"] = open_p + 2.75
        
        agent._manage_active_position(pos)
        
        # Check that SL was moved to Entry + Spread Buffer
        updated_pos = broker.open_positions[ticket]
        assert ticket in agent.trailed_tickets
        assert updated_pos["sl"] > open_p  # SL is now above entry in profit territory!


def test_mtf_macro_trend_filter():
    """Validates that M5 cannot BUY when price is below M15 HTF EMA 200."""
    broker = PaperTradingBroker(initial_balance=10000.0)
    with tempfile.TemporaryDirectory() as tmp:
        agent = GoldSpecialistAgent(
            broker=broker,
            broker_mode="paper",
            initial_balance=10000.0,
            timeframe="M5",
            journal_dir=Path(tmp) / "xauusd"
        )
        
        # Mock signal to BUY
        agent.evaluate_strategy_signal = lambda _df: {
            "action": "BUY",
            "sl": 2490.0,
            "tp": 2520.0,
            "reason": "mock-buy"
        }
        
        n = 60
        mock_m5 = pd.DataFrame({
            "timestamp": pd.date_range("2026-08-01 10:00", periods=n, freq="5min"),
            "open": [2500.0] * n,
            "high": [2505.0] * n,
            "low": [2495.0] * n,
            "close": [2500.0] * n,
            "volume": [100] * n
        })
        
        # HTF M15 DataFrame where price is 2700 (so EMA 200 is 2700, far above 2500)
        mock_htf = pd.DataFrame({
            "timestamp": pd.date_range("2026-08-01 10:00", periods=n, freq="15min"),
            "open": [2700.0] * n,
            "high": [2705.0] * n,
            "low": [2695.0] * n,
            "close": [2700.0] * n,
            "volume": [100] * n
        })
        
        def mock_get_market_data(symbol, timeframe="M5", bars=60):
            if timeframe == "M15":
                return mock_htf.copy()
            return mock_m5.copy()
            
        agent.broker.get_market_data = mock_get_market_data
        
        result = agent.step()
        # Should be vetoed by MTF macro filter
        assert result["status"] == "VETOED_BY_MTF_MACRO"


def test_squad_manager_duo_preset():
    """Validates that --agent=duo enables Gold and BTC, omitting ETH."""
    squad = SquadManager(
        broker_mode="paper",
        initial_balance=10000.0,
        agents_to_enable=["duo"]
    )
    assert "gold" in squad.specialists
    assert "btc" in squad.specialists
    assert "eth" not in squad.specialists
    assert len(squad.specialists) == 2
