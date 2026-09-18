"""
Unit tests for Backtest Engine, Data Loader, and Strategies.
"""

import pytest
import pandas as pd
from backtest.data_loader import generate_fallback_gold_data
from backtest.engine import BacktestEngine
from backtest.strategies import strategy_mtf_momentum, strategy_ema_pullback


def test_fallback_data_generator():
    df = generate_fallback_gold_data(bars=100)
    assert len(df) == 100
    assert 'close' in df.columns
    assert 'timestamp' in df.columns
    assert (df['high'] >= df['low']).all()


def test_backtest_engine_execution():
    df = generate_fallback_gold_data(bars=200)
    engine = BacktestEngine(
        initial_balance=10000.0,
        risk_per_trade_pct=0.01,
        daily_target_pct=0.03,
        daily_max_loss_pct=0.02,
        spread=0.25
    )
    
    metrics = engine.run(df, strategy_mtf_momentum, strategy_name="TestMTF")
    
    assert "total_trades" in metrics
    assert "total_return_pct" in metrics
    assert "win_rate_pct" in metrics
    assert "profit_factor" in metrics
    assert "equity_curve" in metrics
    assert len(metrics["equity_curve"]) > 100
