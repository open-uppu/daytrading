import pytest
from backtest.run_m5_backtest import run_single_asset_m5_backtest

def test_single_asset_m5_backtest_runs():
    res = run_single_asset_m5_backtest(symbol="XAUUSD", initial_balance=10000.0, max_bars=300)
    assert "total_trades" in res
    assert "win_rate_pct" in res
    assert "avg_minutes_between_trades" in res
    assert res["total_trades"] > 0
    # Cadence should be close to 10-25 minutes in active periods
    assert res["avg_minutes_between_trades"] > 0
