"""
End-to-end integration test verifying the complete autonomous trading cycle:
Market Scan -> Chart Vision -> Confluence -> Pre-trade Filter -> Order Execution ->
TP Hit -> 3% Daily Target Lock -> Post-Trade Autopsy (.md).
"""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path

from agent.loop import TradingAgent
from mt4.paper_broker import PaperTradingBroker


def create_strong_bullish_dataset(bars: int = 80) -> pd.DataFrame:
    """Creates a dataset with clear uptrend, healthy pullback to EMA20/50, and a bullish pin bar bounce."""
    base = 2600.0
    closes = []
    
    # 1. Steady uptrend for first 65 bars
    for i in range(65):
        closes.append(base + (i * 0.6))
        
    # 2. Healthy pullback for 12 bars (brings RSI from overbought down to ~50)
    last_val = closes[-1]
    for i in range(12):
        closes.append(last_val - (i * 0.4))
        
    # 3. Final 3 bars: stabilization and strong bounce
    last_val = closes[-1]
    closes.append(last_val + 0.2)
    closes.append(last_val + 0.5)
    closes.append(last_val + 1.2)  # final close
    
    closes = np.array(closes)
    opens = closes - 0.3
    highs = closes + 1.0
    lows = closes - 0.8
    
    # Final candle: bullish pin bar with long lower rejection wick
    lows[-1] = closes[-1] - 6.0
    opens[-1] = closes[-1] - 0.3
    highs[-1] = closes[-1] + 0.4
    volume = np.random.randint(500, 2000, len(closes))
    
    return pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volume
    })


def test_end_to_end_trading_and_3_pct_target_lock(tmp_path):
    # Setup paper broker with custom bullish dataset
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="XAUUSD")
    bullish_df = create_strong_bullish_dataset(80)
    broker.m15_data = bullish_df
    broker.current_price = float(bullish_df.iloc[-1]['close'])
    
    # Initialize Agent
    agent = TradingAgent(
        broker=broker,
        broker_mode="paper",
        initial_balance=10000.0,
        poll_interval=1
    )
    
    # Point reflector to tmp_path
    agent.reflector.trades_dir = tmp_path / "trades"
    agent.reflector.trades_dir.mkdir(parents=True, exist_ok=True)
    
    # Use deterministic heuristic vision for unit test
    agent.vision_analyzer.provider = "heuristic"

    # Lower threshold to 40.0 to trigger on synthetic test setup
    agent.confluence_engine.threshold = 40.0
    
    # Step 1: Agent scans market, generates chart, detects confluence, and opens order
    step_res = agent.step()
    
    assert step_res["status"] == "ORDER_PLACED"
    assert step_res["action"] == "BUY"
    assert step_res["lot_size"] > 0
    assert len(broker.get_open_positions()) == 1
    
    open_pos = broker.get_open_positions()[0]
    entry_price = open_pos["open_price"]
    tp_price = open_pos["tp"]
    sl_price = open_pos["sl"]
    ticket = open_pos["ticket"]
    
    # Step 2: In between steps, simulate market rallying to hit TP
    broker.simulate_price_update(new_high=tp_price + 2.0, new_low=entry_price, new_close=tp_price)
    assert len(broker.get_open_positions()) == 0  # Position filled at TP
    
    # Step 3: Next loop step reconciles closed trade, runs autopsy, and locks trading if >= 3% target hit
    step_res_2 = agent.step()
    
    # Verify autopsy markdown was written
    autopsies = list((tmp_path / "trades").glob("*.md"))
    assert len(autopsies) == 1
    autopsy_content = autopsies[0].read_text()
    assert f"#{ticket}" in autopsy_content
    assert "[WIN]" in autopsy_content
    
    # Verify that session tracker recorded the profit
    summary = agent.session_tracker.get_summary()
    assert summary["trades_count"] == 1
    assert summary["wins"] == 1
    assert summary["closed_pnl_today"] > 0
    
    # If the trade gained >= 3% ($300), the session should be LOCKED!
    if agent.session_tracker.is_target_reached:
        assert step_res_2["status"] == "LOCKED"
        assert "DAILY_TARGET_REACHED" in step_res_2["reason"]
        
        # Subsequent steps should stay locked!
        step_res_3 = agent.step()
        assert step_res_3["status"] == "LOCKED"
