"""Unit tests for backtest performance metrics, including the zero-trade edge case."""
from backtest.metrics import calculate_performance_metrics


def test_zero_trades_returns_same_keys_as_the_normal_case():
    zero = calculate_performance_metrics(
        initial_balance=10000.0, equity_curve=[10000.0], trades=[], daily_pnls={}
    )
    normal = calculate_performance_metrics(
        initial_balance=10000.0,
        equity_curve=[10000.0, 10100.0],
        trades=[{"pnl_usd": 100.0}],
        daily_pnls={"2026-09-23": 100.0},
    )
    assert set(zero.keys()) == set(normal.keys())
    assert zero["days_hit_3pct_target"] == 0
    assert zero["total_return_pct"] == 0.0
