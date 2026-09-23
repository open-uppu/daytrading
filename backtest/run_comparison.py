"""
Comprehensive Strategy Comparison Runner for Gold (XAUUSD).
Backtests all 5 strategies over real historical M15 data, ranks performance,
and renders an equity curve comparison chart.
"""

from typing import Dict, Any, List
from pathlib import Path
import logging
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config import config
from backtest.data_loader import load_historical_data
from backtest.engine import BacktestEngine
from backtest.strategies import (
    strategy_ema_pullback,
    strategy_sr_breakout,
    strategy_bb_reversion,
    strategy_mtf_momentum,
    strategy_agentic_confluence,
    strategy_optimal_hybrid
)

console = Console()
logger = logging.getLogger("strategy_comparison")


def run_all_strategies(
    df: pd.DataFrame = None,
    initial_balance: float = 10000.0,
    save_chart: bool = True,
    timeframe: str = "M15"
) -> List[Dict[str, Any]]:
    """
    Runs backtests for all strategies and returns sorted results list.
    """
    if df is None:
        df = load_historical_data(timeframe=timeframe)

    engine = BacktestEngine(
        initial_balance=initial_balance,
        risk_per_trade_pct=0.015,  # 1.5% risk per trade so 1:2 RR hits 3% daily target!
        daily_target_pct=0.03,
        daily_max_loss_pct=0.02,
        spread=0.25
    )

    strategies = [
        ("Strategy A: EMA Pullback Rejection", strategy_ema_pullback, "#FFD600"),
        ("Strategy B: S/R Breakout & Retest", strategy_sr_breakout, "#00E5FF"),
        ("Strategy C: Bollinger Bands Reversion", strategy_bb_reversion, "#FF5252"),
        ("Strategy D: MTF Momentum Cross", strategy_mtf_momentum, "#E040FB"),
        ("Strategy E: Agentic Multimodal Confluence", strategy_agentic_confluence, "#7C4DFF"),
        ("Strategy F: Optimal Hybrid (MTF+PA+Rules)", strategy_optimal_hybrid, "#00E676")
    ]

    results = []
    console.print(f"\n[bold gold1]=== Running Gold (XAUUSD) 5-Strategy Backtest ({len(df)} M15 Bars) ===[/bold gold1]\n")

    for name, fn, color in strategies:
        console.print(f"[cyan]Evaluating: [bold]{name}[/bold]...[/cyan]")
        metrics = engine.run(df=df, signal_fn=fn, strategy_name=name)
        metrics["plot_color"] = color
        results.append(metrics)
        console.print(f"  -> Return: [bold green]{metrics['total_return_pct']:+.2f}%[/bold green] | Win Rate: {metrics['win_rate_pct']:.1f}% | Profit Factor: {metrics['profit_factor']:.2f} | Max DD: {metrics['max_drawdown_pct']:.2f}% | Hit 3% Target: {metrics['days_hit_3pct_target']} days ({metrics['daily_target_achievement_pct']}%)")

    # Sort results by Total Return % descending
    results.sort(key=lambda x: x['total_return_pct'], reverse=True)

    # 1. Print Summary Table
    table = Table(
        title="Gold (XAUUSD) Strategy Backtest Leaderboard (Ranked by Return)",
        header_style="bold magenta",
        show_header=True
    )
    table.add_column("Rank", justify="center", style="bold")
    table.add_column("Strategy Name", style="bold white")
    table.add_column("Net Profit ($)", justify="right")
    table.add_column("Return (%)", justify="right")
    table.add_column("Win Rate (%)", justify="right")
    table.add_column("Profit Factor", justify="right")
    table.add_column("Max DD (%)", justify="right")
    table.add_column("Trades", justify="center")
    table.add_column("3% Target Days", justify="right")
    table.add_column("Sharpe", justify="right")

    for rank, res in enumerate(results, start=1):
        color_ret = "green" if res['net_profit'] >= 0 else "red"
        is_winner = (rank == 1)
        rank_str = f"[bold gold1]🥇 #{rank}[/bold gold1]" if is_winner else f"#{rank}"
        
        table.add_row(
            rank_str,
            f"[{color_ret}]{res['strategy_name']}[/{color_ret}]",
            f"[{color_ret}]${res['net_profit']:+,.2f}[/{color_ret}]",
            f"[{color_ret}]{res['total_return_pct']:+.2f}%[/{color_ret}]",
            f"{res['win_rate_pct']:.1f}%",
            f"{res['profit_factor']:.2f}",
            f"{res['max_drawdown_pct']:.2f}%",
            str(res['total_trades']),
            f"{res['days_hit_3pct_target']} ({res['daily_target_achievement_pct']}%)",
            f"{res['sharpe_ratio']:.2f}"
        )

    console.print("\n")
    console.print(table)

    winner = results[0]
    console.print(Panel(
        f"[bold gold1]🏆 WINNING STRATEGY:[/bold gold1] [bold green]{winner['strategy_name']}[/bold green]\n\n"
        f"• [bold]Net Profit:[/bold] ${winner['net_profit']:+,.2f} ([bold green]{winner['total_return_pct']:+.2f}%[/bold green])\n"
        f"• [bold]Win Rate:[/bold] {winner['win_rate_pct']:.1f}%\n"
        f"• [bold]Profit Factor:[/bold] {winner['profit_factor']:.2f}\n"
        f"• [bold]Max Drawdown:[/bold] {winner['max_drawdown_pct']:.2f}%\n"
        f"• [bold]3% Daily Target Hit Rate:[/bold] {winner['days_hit_3pct_target']} trading days ({winner['daily_target_achievement_pct']}% of all session days!)\n"
        f"• [bold]Sharpe Ratio:[/bold] {winner['sharpe_ratio']:.2f}",
        title="Best Performing Method",
        border_style="gold1"
    ))

    # 2. Render Comparative Equity Curve Chart
    if save_chart:
        chart_path = config.artifacts_dir / "backtest_comparison.png"
        fig, (ax_eq, ax_dd) = plt.subplots(
            2, 1, figsize=(14, 8),
            gridspec_kw={'height_ratios': [3, 1]},
            facecolor='#121417'
        )
        ax_eq.set_facecolor('#121417')
        ax_dd.set_facecolor('#121417')

        for res in results:
            eq = res['equity_curve']
            color = res.get('plot_color', '#FFFFFF')
            linewidth = 2.4 if res == winner else 1.2
            alpha = 1.0 if res == winner else 0.65
            label = f"{res['strategy_name']} ({res['total_return_pct']:+.1f}%)"
            ax_eq.plot(eq, label=label, color=color, linewidth=linewidth, alpha=alpha)

        ax_eq.axhline(initial_balance, color='#78909C', linestyle='--', linewidth=0.8, alpha=0.6)
        ax_eq.set_title(
            f"Gold (XAUUSD) Strategy Comparison | Initial: ${initial_balance:,.0f} | 60-Day M15 Data",
            color='#ECEFF1', fontsize=12, pad=10, weight='bold'
        )
        ax_eq.set_ylabel("Account Equity ($)", color='#90A4AE', fontsize=10)
        ax_eq.tick_params(colors='#90A4AE', labelsize=9)
        ax_eq.grid(True, color='#263238', linestyle=':', alpha=0.5)
        ax_eq.legend(loc='upper left', facecolor='#1A232A', edgecolor='#37474F', labelcolor='#CFD8DC', fontsize=9)

        # Plot Winner Drawdown in lower panel
        win_eq = winner['equity_curve']
        peak = np.maximum.accumulate(win_eq)
        dd = (peak - win_eq) / peak * 100.0
        ax_dd.fill_between(range(len(dd)), 0, dd, color='#FF5252', alpha=0.3)
        ax_dd.plot(dd, color='#FF5252', linewidth=1.0, label=f"Max DD: {winner['max_drawdown_pct']:.1f}%")
        ax_dd.set_ylabel("Drawdown %", color='#90A4AE', fontsize=9)
        ax_dd.set_xlabel("Time (M15 Bars)", color='#90A4AE', fontsize=9)
        ax_dd.tick_params(colors='#90A4AE', labelsize=8)
        ax_dd.grid(True, color='#263238', linestyle=':', alpha=0.5)
        ax_dd.legend(loc='upper right', facecolor='#1A232A', edgecolor='#37474F', labelcolor='#CFD8DC', fontsize=8)

        plt.tight_layout()
        fig.savefig(chart_path, dpi=120, facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close(fig)
        console.print(f"\n[bold cyan]Saved Comparative Equity Curve Chart to:[/bold cyan] [green]{chart_path}[/green]\n")

    return results


if __name__ == "__main__":
    run_all_strategies()
