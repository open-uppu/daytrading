"""
Cross-Market Strategy Research & Backtest for Gold (XAUUSD), Bitcoin (BTCUSD), and Ethereum (ETHUSD).
Discovers the optimal trading strategy for each individual financial asset.
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
from backtest.data_loader import load_historical_data, ASSET_SPECS
from backtest.engine import BacktestEngine
from backtest.strategies import (
    strategy_ema_pullback,
    strategy_sr_breakout,
    strategy_bb_reversion,
    strategy_mtf_momentum,
    strategy_agentic_confluence
)

console = Console()
logger = logging.getLogger("cross_market")


def evaluate_market_strategies(
    symbol: str,
    initial_balance: float = 10000.0
) -> Dict[str, Any]:
    """
    Evaluates all strategies on a specific market and returns ranked results and winner.
    """
    spec = ASSET_SPECS.get(symbol, ASSET_SPECS["XAUUSD"])
    df = load_historical_data(symbol=symbol, timeframe="M15")
    
    engine = BacktestEngine(
        initial_balance=initial_balance,
        risk_per_trade_pct=0.015,  # 1.5% risk
        daily_target_pct=0.03,
        daily_max_loss_pct=0.02,
        spread=spec["typical_spread"],
        contract_size=spec["contract_size"],
        min_sl_dist=spec.get("min_sl_dist", 0.5),
        price_precision=spec.get("price_precision", 2),
        breakeven_buffer=spec.get("breakeven_buffer", 0.20)
    )
    
    strategies = [
        ("Strategy A: EMA Pullback Rejection", strategy_ema_pullback, "#FFD600"),
        ("Strategy B: S/R Breakout & Retest", strategy_sr_breakout, "#00E5FF"),
        ("Strategy C: Bollinger Bands Reversion", strategy_bb_reversion, "#FF5252"),
        ("Strategy D: MTF Momentum Cross", strategy_mtf_momentum, "#00E676"),
        ("Strategy E: Agentic Multimodal Confluence", strategy_agentic_confluence, "#7C4DFF")
    ]
    
    market_results = []
    console.print(f"\n[bold gold1]=== Testing Market: {symbol} ({spec['name']}) | {len(df)} M15 Bars ===[/bold gold1]")
    
    for name, fn, color in strategies:
        metrics = engine.run(df=df, signal_fn=fn, strategy_name=name)
        metrics["plot_color"] = color
        metrics["symbol"] = symbol
        market_results.append(metrics)
        console.print(f"  • {name:<36} -> Return: [bold green]{metrics['total_return_pct']:+.2f}%[/bold green] | Win Rate: {metrics['win_rate_pct']:.1f}% | Max DD: {metrics['max_drawdown_pct']:.2f}% | Hit 3% Target: {metrics['days_hit_3pct_target']} days")

    market_results.sort(key=lambda x: x['total_return_pct'], reverse=True)
    winner = market_results[0]
    
    return {
        "symbol": symbol,
        "name": spec["name"],
        "winner": winner,
        "all_results": market_results
    }


def run_cross_market_study(initial_balance: float = 10000.0) -> Dict[str, Any]:
    """
    Runs full comparative study across Gold (XAUUSD), Bitcoin (BTCUSD), and Ethereum (ETHUSD).
    """
    markets = ["XAUUSD", "BTCUSD", "ETHUSD"]
    study_results = {}
    
    for m in markets:
        study_results[m] = evaluate_market_strategies(m, initial_balance=initial_balance)
        
    # Render Master Multi-Asset Leaderboard
    table = Table(
        title="Cross-Market Multi-Asset Strategy Leaderboard (Best per Asset)",
        header_style="bold magenta",
        show_header=True
    )
    table.add_column("Asset", style="bold cyan", width=12)
    table.add_column("Optimal Strategy", style="bold white", width=34)
    table.add_column("Net Profit ($)", justify="right")
    table.add_column("Return (%)", justify="right")
    table.add_column("Win Rate (%)", justify="right")
    table.add_column("Profit Factor", justify="right")
    table.add_column("Max DD (%)", justify="right")
    table.add_column("Trades", justify="center")
    table.add_column("3% Target Days", justify="right")
    table.add_column("Sharpe", justify="right")

    for m in markets:
        win = study_results[m]["winner"]
        ret_color = "green" if win["net_profit"] >= 0 else "red"
        table.add_row(
            f"[bold]{m}[/bold]",
            f"[{ret_color}]{win['strategy_name']}[/{ret_color}]",
            f"[{ret_color}]${win['net_profit']:+,.2f}[/{ret_color}]",
            f"[{ret_color}]{win['total_return_pct']:+.2f}%[/{ret_color}]",
            f"{win['win_rate_pct']:.1f}%",
            f"{win['profit_factor']:.2f}",
            f"{win['max_drawdown_pct']:.2f}%",
            str(win['total_trades']),
            f"{win['days_hit_3pct_target']} ({win['daily_target_achievement_pct']}%)",
            f"{win['sharpe_ratio']:.2f}"
        )

    console.print("\n")
    console.print(table)
    
    # Save Multi-Panel Comparative Equity Chart
    chart_path = config.artifacts_dir / "cross_market_comparison.png"
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), facecolor='#121417')
    
    for idx, m in enumerate(markets):
        ax = axes[idx]
        ax.set_facecolor('#121417')
        market_data = study_results[m]
        winner = market_data["winner"]
        
        for res in market_data["all_results"]:
            eq = res["equity_curve"]
            is_win = (res == winner)
            lw = 2.4 if is_win else 1.0
            alpha = 1.0 if is_win else 0.5
            color = res["plot_color"]
            label = f"{res['strategy_name']} ({res['total_return_pct']:+.1f}%)"
            ax.plot(eq, label=label, color=color, linewidth=lw, alpha=alpha)
            
        ax.axhline(initial_balance, color='#78909C', linestyle='--', linewidth=0.8, alpha=0.5)
        ax.set_title(f"{m} ({market_data['name']}) - Strategy Equity Curves | Winner: {winner['strategy_name']} ({winner['total_return_pct']:+.2f}%)", color='#ECEFF1', fontsize=11, weight='bold')
        ax.set_ylabel("Equity ($)", color='#90A4AE', fontsize=9)
        ax.tick_params(colors='#90A4AE', labelsize=8)
        ax.grid(True, color='#263238', linestyle=':', alpha=0.5)
        ax.legend(loc='upper left', facecolor='#1A232A', edgecolor='#37474F', labelcolor='#CFD8DC', fontsize=8)

    plt.tight_layout()
    fig.savefig(chart_path, dpi=120, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    console.print(f"\n[bold cyan]Saved Cross-Market Comparison Chart to:[/bold cyan] [green]{chart_path}[/green]\n")

    return study_results


if __name__ == "__main__":
    run_cross_market_study()
