import pandas as pd
import numpy as np
import pytest
from backtest.strategies import strategy_m5_scalper

def generate_mock_m5_data(trend="bullish", count=50):
    prices = [2000.0]
    for i in range(count - 1):
        delta = 0.5 if trend == "bullish" else -0.5
        prices.append(prices[-1] + delta + np.random.uniform(-0.1, 0.1))
    
    df = pd.DataFrame({
        "open": prices,
        "high": [p + 0.8 for p in prices],
        "low": [p - 0.8 for p in prices],
        "close": prices,
        "volume": [100] * count
    })
    return df

def test_m5_scalper_bullish_pullback_or_cross():
    df = generate_mock_m5_data("bullish", 50)
    sig = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="gold")
    assert sig["action"] in ["BUY", "HOLD"]
    if sig["action"] == "BUY":
        assert sig["sl"] < df.iloc[-1]["close"]
        assert sig["tp"] > df.iloc[-1]["close"]
        assert "reason" in sig

def test_m5_scalper_bearish():
    df = generate_mock_m5_data("bearish", 50)
    sig = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="gold")
    assert sig["action"] in ["SELL", "HOLD"]
    if sig["action"] == "SELL":
        assert sig["sl"] > df.iloc[-1]["close"]
        assert sig["tp"] < df.iloc[-1]["close"]
        assert "reason" in sig

def test_m5_scalper_handles_short_window():
    df = generate_mock_m5_data("bullish", 10)
    sig = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="gold")
    assert sig["action"] == "HOLD"
