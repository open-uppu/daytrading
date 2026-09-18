"""
Unit tests for technical indicators calculation.
"""

import pytest
import numpy as np
import pandas as pd
from core.indicators import (
    compute_ema,
    compute_atr,
    compute_rsi,
    detect_support_resistance,
    analyze_candlestick_patterns,
    compute_all_indicators
)


def create_sample_ohlcv(n: int = 100) -> pd.DataFrame:
    """Generates synthetic trending XAUUSD OHLCV data."""
    np.random.seed(42)
    base_price = 2600.0
    drift = 0.5  # slight upward drift
    
    closes = [base_price]
    for _ in range(n - 1):
        change = np.random.normal(drift, 3.0)
        closes.append(closes[-1] + change)
        
    closes = np.array(closes)
    highs = closes + np.abs(np.random.normal(1.5, 1.0, n))
    lows = closes - np.abs(np.random.normal(1.5, 1.0, n))
    opens = closes + np.random.normal(0, 1.0, n)
    volume = np.random.randint(100, 2000, n)
    
    return pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volume
    })


def test_indicators_computation():
    df = create_sample_ohlcv(80)
    enriched = compute_all_indicators(df)
    
    assert 'ema_20' in enriched.columns
    assert 'ema_50' in enriched.columns
    assert 'ema_200' in enriched.columns
    assert 'atr_14' in enriched.columns
    assert 'rsi_14' in enriched.columns
    
    # ATR should be positive
    assert (enriched['atr_14'] > 0).all()
    # RSI should be bounded between 0 and 100
    assert (enriched['rsi_14'] >= 0).all() and (enriched['rsi_14'] <= 100).all()


def test_support_resistance_detection():
    df = create_sample_ohlcv(100)
    sr = detect_support_resistance(df)
    
    assert "support" in sr
    assert "resistance" in sr
    assert isinstance(sr["support"], list)
    assert isinstance(sr["resistance"], list)


def test_candlestick_patterns():
    # Construct a strong bullish pin bar: small body near top, long lower wick
    row_pin = pd.Series({
        'open': 2650.0,
        'high': 2652.0,
        'low': 2635.0,  # 15 point lower drop
        'close': 2651.0
    })
    pattern = analyze_candlestick_patterns(row_pin)
    assert pattern["bullish_pin"] is True
    assert pattern["is_bullish"] is True
    assert pattern["lower_wick_ratio"] >= 0.60
