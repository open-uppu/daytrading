"""
Performance Metrics and Statistics for Trading Strategy Backtests.
"""

from typing import Dict, Any, List
import numpy as np
import pandas as pd


def calculate_performance_metrics(
    initial_balance: float,
    equity_curve: List[float],
    trades: List[Dict[str, Any]],
    daily_pnls: Dict[str, float],
    target_daily_pct: float = 0.03
) -> Dict[str, Any]:
    """
    Computes professional quantitative performance statistics for backtests.
    """
    final_equity = equity_curve[-1] if equity_curve else initial_balance
    net_profit = final_equity - initial_balance
    total_return_pct = (net_profit / initial_balance) * 100.0 if initial_balance > 0 else 0.0

    total_trades = len(trades)
    if total_trades == 0:
        return {
            "initial_balance": initial_balance,
            "final_equity": round(final_equity, 2),
            "net_profit": 0.0,
            "total_return_pct": 0.0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "break_evens": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "total_trading_days": len(daily_pnls),
            "days_hit_3pct_target": 0,
            "daily_target_achievement_pct": 0.0,
            "sharpe_ratio": 0.0
        }

    wins = [t for t in trades if t['pnl_usd'] > 0]
    losses = [t for t in trades if t['pnl_usd'] < 0]
    break_evens = [t for t in trades if t['pnl_usd'] == 0]

    win_count = len(wins)
    loss_count = len(losses)
    win_rate_pct = (win_count / total_trades) * 100.0

    gross_profit = sum(t['pnl_usd'] for t in wins)
    gross_loss = abs(sum(t['pnl_usd'] for t in losses))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 99.0

    avg_win = round(gross_profit / win_count, 2) if win_count > 0 else 0.0
    avg_loss = round(gross_loss / loss_count, 2) if loss_count > 0 else 0.0

    # Max Drawdown Calculation
    peak = initial_balance
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = peak - val
        dd_pct = (dd / peak) * 100.0 if peak > 0 else 0.0
        if dd > max_dd_usd:
            max_dd_usd = dd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    # Daily Target (3%) Achievement Rate
    target_usd = initial_balance * target_daily_pct
    total_days = len(daily_pnls)
    days_hit_target = sum(1 for pnl in daily_pnls.values() if pnl >= target_usd)
    daily_target_achievement_pct = round((days_hit_target / total_days) * 100.0, 1) if total_days > 0 else 0.0

    # Sharpe Ratio (daily returns based)
    daily_returns = [pnl / initial_balance for pnl in daily_pnls.values()]
    if len(daily_returns) > 1 and np.std(daily_returns) > 0:
        daily_std = np.std(daily_returns)
        daily_mean = np.mean(daily_returns)
        sharpe = round((daily_mean / daily_std) * np.sqrt(252), 2)
    else:
        sharpe = 0.0

    return {
        "initial_balance": initial_balance,
        "final_equity": round(final_equity, 2),
        "net_profit": round(net_profit, 2),
        "total_return_pct": round(total_return_pct, 2),
        "total_trades": total_trades,
        "wins": win_count,
        "losses": loss_count,
        "break_evens": len(break_evens),
        "win_rate_pct": round(win_rate_pct, 1),
        "profit_factor": profit_factor,
        "max_drawdown_usd": round(max_dd_usd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "total_trading_days": total_days,
        "days_hit_3pct_target": days_hit_target,
        "daily_target_achievement_pct": daily_target_achievement_pct,
        "sharpe_ratio": sharpe
    }
