"""
Unit tests for Machine Learning Meta-Labeling and Quant Confidence Filter.
"""

import pytest
import pandas as pd
import numpy as np

from core.ml_filter import MLQuantFilter
from backtest.run_ml_backtest import prepare_precomputed_df, extract_fast_signals, FastQuantMLEngine


def test_ml_quant_feature_extraction():
    # Synthetic DataFrame
    n = 60
    closes = [2000.0 + (i * 0.5) for i in range(n)]
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-08-01 10:00", periods=n, freq="5min"),
        "open": closes,
        "high": [c + 1.0 for c in closes],
        "low": [c - 1.0 for c in closes],
        "close": closes,
        "volume": [100] * n
    })

    flt = MLQuantFilter(confidence_threshold=0.75)
    vector = flt.extract_features(df, "BUY")
    assert vector is not None
    assert vector.shape == (1, 11)
    # Check action_code is 1.0 for BUY
    assert vector[0, -1] == 1.0

    vector_sell = flt.extract_features(df, "SELL")
    assert vector_sell[0, -1] == 0.0


def test_ml_quant_heuristic_confidence():
    n = 60
    closes = [2000.0 + (i * 0.5) for i in range(n)]
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-08-01 10:00", periods=n, freq="5min"),
        "open": closes,
        "high": [c + 1.0 for c in closes],
        "low": [c - 1.0 for c in closes],
        "close": closes,
        "volume": [100] * n
    })

    flt = MLQuantFilter(confidence_threshold=0.70)
    conf = flt.predict_confidence(df, "BUY", "xauusd")
    assert 0.10 <= conf <= 0.95

    passed, c_val, details = flt.evaluate_proposal({"action": "BUY"}, df, "xauusd")
    assert "ml_confidence" in details
    assert "passed" in details


def test_fast_quant_ml_engine():
    engine = FastQuantMLEngine(initial_balance=10000.0)
    res = engine.run_benchmark_for_asset("XAUUSD")
    assert len(res) == 4
    for r in res:
        assert "win_rate_pct" in r
        assert "profit_factor" in r
        assert "total_trades" in r
