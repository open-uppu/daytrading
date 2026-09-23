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
    compute_all_indicators,
    compute_vwap,
    detect_liquidity_sweep,
    detect_rsi_divergence,
    detect_order_block_retest
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


def test_compute_vwap_matches_hand_calculation():
    # 3 bars, period=3: typical price = (h+l+c)/3, VWAP = sum(tp*vol)/sum(vol)
    df = pd.DataFrame({
        "high":   [10.0, 12.0, 14.0],
        "low":    [8.0, 10.0, 12.0],
        "close":  [9.0, 11.0, 13.0],
        "volume": [100, 200, 300],
    })
    vwap = compute_vwap(df, period=3)
    typical = [(10 + 8 + 9) / 3, (12 + 10 + 11) / 3, (14 + 12 + 13) / 3]
    expected = sum(t * v for t, v in zip(typical, [100, 200, 300])) / 600
    assert vwap.iloc[-1] == pytest.approx(expected)
    assert pd.isna(vwap.iloc[0])  # not enough bars yet for a full window


def test_compute_vwap_handles_zero_volume_window():
    df = pd.DataFrame({
        "high": [10.0, 10.0], "low": [9.0, 9.0], "close": [9.5, 9.5], "volume": [0, 0],
    })
    vwap = compute_vwap(df, period=2)
    assert pd.isna(vwap.iloc[-1])  # zero total volume must not raise or divide by zero


def test_detect_liquidity_sweep_bullish_stop_hunt_and_reclaim():
    # 10 quiet bars holding low=100, then a sweep bar: wicks to 95 but closes at 101 (reclaim)
    quiet = pd.DataFrame({"high": [102.0] * 10, "low": [100.0] * 10, "close": [101.0] * 10})
    sweep_bar = pd.DataFrame({"high": [101.5], "low": [95.0], "close": [101.0]})
    df = pd.concat([quiet, sweep_bar], ignore_index=True)
    result = detect_liquidity_sweep(df, lookback=10)
    assert result["bullish_sweep"] is True
    assert result["bearish_sweep"] is False


def test_detect_liquidity_sweep_no_sweep_when_low_holds():
    quiet = pd.DataFrame({"high": [102.0] * 10, "low": [100.0] * 10, "close": [101.0] * 10})
    normal_bar = pd.DataFrame({"high": [101.5], "low": [100.2], "close": [101.0]})
    df = pd.concat([quiet, normal_bar], ignore_index=True)
    result = detect_liquidity_sweep(df, lookback=10)
    assert result["bullish_sweep"] is False
    assert result["bearish_sweep"] is False


def test_detect_liquidity_sweep_handles_short_window():
    df = pd.DataFrame({"high": [102.0, 101.0], "low": [100.0, 99.0], "close": [101.0, 100.5]})
    result = detect_liquidity_sweep(df, lookback=10)
    assert result == {"bullish_sweep": False, "bearish_sweep": False}


def test_detect_rsi_divergence_bullish_lower_low_higher_rsi():
    df = pd.DataFrame({
        "low": [100.0] * 5 + [95.0] + [100.0] * 4 + [93.0],   # prior swing low=95, current low=93 (lower low)
        "high": [105.0] * 11,
        "rsi_14": [50.0] * 5 + [25.0] + [50.0] * 4 + [30.0],   # prior RSI at that low=25, current RSI=30 (higher)
    })
    result = detect_rsi_divergence(df, lookback=10)
    assert result["bullish_divergence"] is True
    assert result["bearish_divergence"] is False


def test_detect_rsi_divergence_none_when_rsi_confirms_the_new_low():
    df = pd.DataFrame({
        "low": [100.0] * 5 + [95.0] + [100.0] * 4 + [93.0],
        "high": [105.0] * 11,
        "rsi_14": [50.0] * 5 + [25.0] + [50.0] * 4 + [20.0],   # RSI also makes a lower low -- no divergence
    })
    result = detect_rsi_divergence(df, lookback=10)
    assert result["bullish_divergence"] is False


def test_detect_order_block_retest_bullish():
    # bar 5: strong bearish candle (open 110 close 100); bar 6: big bullish impulse closing far above.
    # atr_14 held at 2.0 throughout so a >3.0 move clears the 1.5x threshold. Current close retests bar 5's range.
    rows = []
    for _ in range(6):
        rows.append({"open": 100.0, "close": 100.0, "high": 101.0, "low": 99.0, "atr_14": 2.0})
    rows.append({"open": 110.0, "close": 100.0, "high": 111.0, "low": 99.0, "atr_14": 2.0})   # bearish OB candle
    rows.append({"open": 100.0, "close": 120.0, "high": 121.0, "low": 100.0, "atr_14": 2.0})  # impulse up (+20 > 1.5*2)
    for _ in range(3):
        rows.append({"open": 120.0, "close": 120.0, "high": 121.0, "low": 119.0, "atr_14": 2.0})
    rows.append({"open": 105.0, "close": 105.0, "high": 106.0, "low": 104.0, "atr_14": 2.0})  # retest inside [99,111]
    df = pd.DataFrame(rows)
    result = detect_order_block_retest(df, lookback=10)
    assert result["bullish_ob_retest"] is True


def test_detect_order_block_retest_handles_short_window():
    df = pd.DataFrame({"open": [1.0, 2.0], "close": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0], "atr_14": [0.1, 0.1]})
    result = detect_order_block_retest(df, lookback=10)
    assert result == {"bullish_ob_retest": False, "bearish_ob_retest": False}
