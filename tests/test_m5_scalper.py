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


def test_use_vwap_confirmation_toggle_is_accepted_and_defaults_off():
    """New experimental VWAP filter must default False -- must not silently
    change live behavior for anyone not explicitly opting in."""
    df = generate_mock_m5_data("bullish", 50)
    default_call = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc")
    explicit_off = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc",
                                        use_vwap_confirmation=False)
    assert default_call == explicit_off


def test_use_funding_confirmation_toggle_is_accepted_and_defaults_off():
    """New experimental funding-rate crowding filter must default False."""
    df = generate_mock_m5_data("bullish", 50)
    default_call = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc")
    explicit_off = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc",
                                        use_funding_confirmation=False)
    assert default_call == explicit_off


def test_use_rsi_divergence_confirmation_toggle_is_accepted_and_defaults_off():
    df = generate_mock_m5_data("bullish", 50)
    default_call = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc")
    explicit_off = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc",
                                        use_rsi_divergence_confirmation=False)
    assert default_call == explicit_off


def test_use_order_block_confirmation_toggle_is_accepted_and_defaults_off():
    df = generate_mock_m5_data("bullish", 50)
    default_call = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc")
    explicit_off = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc",
                                        use_order_block_confirmation=False)
    assert default_call == explicit_off


def test_use_smc_confirmation_toggle_is_accepted_and_defaults_off():
    """New experimental SMC liquidity-sweep filter must default False."""
    df = generate_mock_m5_data("bullish", 50)
    default_call = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc")
    explicit_off = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc",
                                        use_smc_confirmation=False)
    assert default_call == explicit_off


def test_use_fear_greed_confirmation_toggle_is_accepted_and_defaults_off():
    """New experimental crypto Fear&Greed filter must default False."""
    df = generate_mock_m5_data("bullish", 50)
    default_call = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc")
    explicit_off = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc",
                                        use_fear_greed_confirmation=False)
    assert default_call == explicit_off


def test_use_news_sentiment_confirmation_toggle_is_accepted_and_defaults_off():
    """New experimental Google News headline-tone filter must default False."""
    df = generate_mock_m5_data("bullish", 50)
    default_call = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc")
    explicit_off = strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc",
                                        use_news_sentiment_confirmation=False)
    assert default_call == explicit_off


def test_news_sentiment_score_can_change_a_pullback_signal_on_real_data():
    """news_sentiment_score is a plain scalar param (Google News RSS has no
    history) -- prove it's actually wired into BTC's pullback gate on real
    cached price data, not a silent no-op."""
    from backtest.data_loader import load_historical_data
    df = load_historical_data(symbol="BTCUSD", timeframe="M5")

    found_diff = False
    for idx in range(60, len(df), 20):
        window = df.iloc[:idx + 1]
        off = strategy_m5_scalper(window, current_idx=idx, asset_type="btc",
                                   use_news_sentiment_confirmation=False)
        on = strategy_m5_scalper(window, current_idx=idx, asset_type="btc",
                                  use_news_sentiment_confirmation=True, news_sentiment_score=-100.0)
        if off != on:
            found_diff = True
            break
    assert found_diff, "expected at least one real bar where news_sentiment_score changes BTC's signal"


def test_fear_greed_value_column_can_change_a_pullback_signal_on_real_data():
    """fear_greed_value rides in as a df column (like funding_rate, since it
    has real point-in-time history) -- prove a hand-set extreme value changes
    BTC's pullback gate on real cached price data, not a silent no-op."""
    from backtest.data_loader import load_historical_data
    df = load_historical_data(symbol="BTCUSD", timeframe="M5").copy()
    df["fear_greed_value"] = 90.0  # extreme greed: blocks bullish confirmation

    found_diff = False
    for idx in range(60, len(df), 20):
        window = df.iloc[:idx + 1]
        off = strategy_m5_scalper(window, current_idx=idx, asset_type="btc",
                                   use_fear_greed_confirmation=False)
        on = strategy_m5_scalper(window, current_idx=idx, asset_type="btc",
                                  use_fear_greed_confirmation=True)
        if off != on:
            found_diff = True
            break
    assert found_diff, "expected at least one real bar where fear_greed_value changes BTC's signal"


def test_confirmation_gates_can_change_golds_cross_signal_on_real_data():
    """Gold's cross entry is now gated by the same candlestick/VWAP/SMC
    confirmations as BTC/ETH's pullback entries -- scan real cached history
    for at least one bar where toggling actually flips the outcome, proving
    the gate is wired and reachable (not a silent no-op for this asset)."""
    from backtest.data_loader import load_historical_data
    df = load_historical_data(symbol="XAUUSD", timeframe="M5")

    found_diff = False
    for idx in range(60, len(df), 20):  # sampled for speed
        window = df.iloc[:idx + 1]
        off = strategy_m5_scalper(window, current_idx=idx, asset_type="gold",
                                   use_candlestick_confirmation=True, use_vwap_confirmation=True,
                                   use_smc_confirmation=True)
        on = strategy_m5_scalper(window, current_idx=idx, asset_type="gold",
                                  use_candlestick_confirmation=False, use_vwap_confirmation=False,
                                  use_smc_confirmation=False)
        if off != on:
            found_diff = True
            break
    assert found_diff, "expected at least one real bar where the confirmation gates change Gold's signal"
