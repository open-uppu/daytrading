"""
Agentic Multi-Asset (Gold, Bitcoin, Ethereum) Day Trading System - Main Entry Point.
Orchestrates Specialist Agents (GoldSpecialistAgent, BtcSpecialistAgent, EthSpecialistAgent)
and the SquadManager with Portfolio 3% Daily Profit Protection.
"""

import sys
import argparse
import logging
import time
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from pathlib import Path

from config import config
from agents.squad_manager import SquadManager
from agents.gold_agent import GoldSpecialistAgent
from agents.btc_agent import BtcSpecialistAgent
from agents.eth_agent import EthSpecialistAgent
from mt4.paper_broker import PaperTradingBroker
from core.chart_generator import generate_candlestick_chart
from core.vision_analyzer import VisionAnalyzer
from core.confluence import ConfluenceEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
console = Console()


def cmd_analyze(args):
    """Performs a single-pass multimodal market analysis for a given asset."""
    symbol = "XAUUSD" if args.symbol.upper() in ["GOLD", "XAUUSD"] else args.symbol.upper()
    console.print(f"\n[bold gold1]=== {symbol} Multimodal Market Analysis ===[/bold gold1]\n")
    
    broker = PaperTradingBroker()
    df = broker.get_market_data(symbol=symbol, timeframe="M15", bars=60)
    
    console.print(f"[cyan]1. Generating M15 Candlestick Chart with Indicators...[/cyan]")
    chart_path = generate_candlestick_chart(df, timeframe="M15", symbol=symbol)
    console.print(f"   Saved to: [green]{chart_path}[/green]")
    
    console.print(f"[cyan]2. Running Multimodal Chart Vision Analysis...[/cyan]")
    vision = VisionAnalyzer()
    vision_result = vision.analyze_chart(chart_path, df, timeframe="M15")
    
    console.print(f"[cyan]3. Calculating Unified Confluence Score...[/cyan]")
    confluence = ConfluenceEngine()
    decision = confluence.evaluate(df, vision_result)
    
    # Render Result Table
    table = Table(title=f"{symbol} Market Confluence Assessment", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="dim", width=25)
    table.add_column("Value", style="bold")
    
    table.add_row("Current Price", f"${decision['current_price']:.2f}")
    table.add_row("RSI (14)", f"{decision['rsi']:.1f}")
    table.add_row("ATR (14)", f"${decision['atr']:.2f}")
    table.add_row("Vision Engine", str(vision_result.get('engine')))
    table.add_row("Pattern Detected", str(vision_result.get('pattern_detected')))
    table.add_row("Vision Score", f"{vision_result.get('vision_score'):+d}")
    table.add_row("Quantitative Score", f"{decision['quant_score']:+d}")
    table.add_row("Final Confluence Score", f"{decision['confluence_score']:+.1f}")
    
    action_color = "green" if decision['action'] == "BUY" else "red" if decision['action'] == "SELL" else "yellow"
    table.add_row("Trading Decision", f"[{action_color}]{decision['action']}[/{action_color}]")
    table.add_row("Reasoning", decision['reason'])
    
    console.print(table)
    
    if vision_result.get("observations"):
        console.print("\n[bold]Visual Observations:[/bold]")
        for obs in vision_result["observations"]:
            console.print(f" • {obs}")
    print("")


def cmd_loop(args):
    """Runs the autonomous trading loop with the Multi-Asset Specialist Squad or single agent."""
    agents_map = {
        "all": ["gold", "btc", "eth"],
        "gold": ["gold"],
        "btc": ["btc"],
        "eth": ["eth"]
    }
    selected_agents = agents_map.get(args.agent.lower(), ["gold", "btc", "eth"])
    
    console.print(Panel(
        f"[bold cyan]Agentic Multi-Asset Specialist Squad[/bold cyan]\n"
        f"Active Specialists: [bold yellow]{', '.join([a.upper() for a in selected_agents])}[/bold yellow]\n"
        f"Daily Profit Target: [bold green]+3.0%[/bold green] (Lock on achievement) | Loss Cutoff: [bold red]-2.0%[/bold red]\n"
        f"Broker Mode: [bold]{args.mode}[/bold] | Interval: [bold]{args.interval}s[/bold]",
        expand=False
    ))
    
    # In Docker, the bridge/EA can come up after the squad container.  Live
    # mode may therefore wait for a valid terminal heartbeat and fresh bars,
    # but it must never fill that gap with historical CSV data.
    while True:
        try:
            squad = SquadManager(
                broker_mode=args.mode,
                initial_balance=args.balance,
                agents_to_enable=selected_agents,
                timeframe=getattr(args, "timeframe", config.timeframe_main)
            )
            break
        except RuntimeError as exc:
            if args.mode == "mt5" and args.wait_for_live_data:
                console.print(
                    f"[yellow]Live preflight not ready: {exc}[/yellow]\n"
                    f"[dim]Waiting {args.interval}s for fresh MT5 telemetry and bars...[/dim]"
                )
                time.sleep(args.interval)
                continue
            raise
    
    squad.run_loop(max_iterations=args.max_iter, interval_sec=args.interval)


def cmd_journal(args):
    """Displays learned rules and mistake logs for specified asset or all assets."""
    assets = ["xauusd", "btcusd", "ethusd"] if args.asset.lower() == "all" else [args.asset.lower()]
    
    console.print("\n[bold gold1]=== Specialist Agent Learned Rulebooks & Autopsy Databases ===[/bold gold1]\n")
    
    for asset in assets:
        asset_dir = config.project_root / "journal" / asset
        rules_file = asset_dir / "learned_rules.md"
        mistakes_file = asset_dir / "mistakes_database.md"
        
        console.print(f"\n[bold cyan]------------------ {asset.upper()} Specialist Journal ------------------[/bold cyan]")
        if rules_file.exists():
            console.print(Panel(rules_file.read_text(), title=f"{asset.upper()} Learned Rules ({rules_file.name})", border_style="green"))
        else:
            console.print(f"[yellow]No learned rules found for {asset.upper()}[/yellow]")
            
        if mistakes_file.exists():
            console.print(Panel(mistakes_file.read_text(), title=f"{asset.upper()} Mistakes Log ({mistakes_file.name})", border_style="cyan"))


def cmd_backtest(args):
    """Runs backtesting across single asset or full cross-market multi-asset comparison."""
    market = args.market.lower()
    tf = getattr(args, "timeframe", "M5").upper()
    
    if tf == "M5":
        from backtest.run_m5_backtest import run_m5_squad_backtest, run_single_asset_m5_backtest
        if market == "all":
            run_m5_squad_backtest(initial_balance=args.balance)
            return
        else:
            sym = "XAUUSD" if market in ["gold", "xauusd"] else ("BTCUSD" if market in ["btc", "btcusd"] else "ETHUSD")
            res = run_single_asset_m5_backtest(symbol=sym, initial_balance=args.balance)
            color_ret = "green" if res['total_return_pct'] >= 0 else "red"
            console.print(Panel(
                f"[bold {color_ret}]M5 High-Frequency Scalper for {sym}[/bold {color_ret}]\n"
                f"Total Return: [bold]{res['total_return_pct']:+.2f}%[/bold]\n"
                f"Win Rate: [bold]{res['win_rate_pct']:.1f}%[/bold]\n"
                f"Profit Factor: [bold]{res['profit_factor']:.2f}[/bold]\n"
                f"Total Trades: [bold]{res['total_trades']}[/bold] (~{res['trades_per_day']} trades/day)\n"
                f"Cadence (Entry Spacing): [bold yellow]{res['avg_minutes_between_trades']} minutes/trade[/bold yellow]\n"
                f"Days Hit 3% Target: [bold]{res['days_hit_3pct_target']} days[/bold]\n"
                f"Max Drawdown: [bold]{res['max_drawdown_pct']:.2f}%[/bold]",
                title=f"M5 Scalper Performance: {sym}",
                border_style=color_ret
            ))
            return

    if market == "all":
        from backtest.run_cross_market_comparison import run_cross_market_study
        console.print("[bold cyan]Starting Full Cross-Market Research Study (Gold, BTC, ETH)...[/bold cyan]")
        run_cross_market_study(initial_balance=args.balance)
    elif market in ["gold", "xauusd"]:
        from backtest.run_comparison import run_all_strategies
        console.print("[bold gold1]Running Gold (XAUUSD) Strategy Comparison...[/bold gold1]")
        run_all_strategies(initial_balance=args.balance, save_chart=True)
    else:
        from backtest.run_cross_market_comparison import evaluate_market_strategies
        symbol = "BTCUSD" if market in ["btc", "btcusd"] else "ETHUSD"
        console.print(f"[bold cyan]Running {symbol} Strategy Comparison...[/bold cyan]")
        res = evaluate_market_strategies(symbol=symbol, initial_balance=args.balance)
        win = res["winner"]
        console.print(Panel(
            f"[bold green]Winner for {symbol}: {win['strategy_name']}[/bold green]\n"
            f"Total Return: [bold]{win['total_return_pct']:+.2f}%[/bold]\n"
            f"Win Rate: [bold]{win['win_rate_pct']:.1f}%[/bold]\n"
            f"Profit Factor: [bold]{win['profit_factor']:.2f}[/bold]\n"
            f"Max Drawdown: [bold]{win['max_drawdown_pct']:.2f}%[/bold]\n"
            f"Days Hit 3% Target: [bold]{win['days_hit_3pct_target']} days[/bold]",
            title=f"Optimal Strategy for {symbol}",
            border_style="green"
        ))


def cmd_bridge(args):
    """Runs the MT5 FastAPI bridge server."""
    import uvicorn
    console.print(f"[bold green]Starting MT5 Bridge Server on {config.mt5_host}:{config.mt5_port}...[/bold green]")
    console.print(f"Connected Account: [bold cyan]{config.mt5_login}[/bold cyan] | Server: [bold cyan]{config.mt5_server}[/bold cyan]")
    uvicorn.run("mt5.bridge_server:app", host=config.mt5_host, port=config.mt5_port, reload=False, access_log=False)


def cmd_test_order(args):
    """Executes full order lifecycle test (BUY, SELL, and CLOSE)."""
    import test_order
    if args.mode == "mt5":
        test_order.run_mt5_live_test()
    else:
        test_order.run_paper_test()


def main():
    parser = argparse.ArgumentParser(description="Agentic Multi-Asset (Gold, BTC, ETH) Day Trading System")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Loop / Run command
    for cmd_alias in ["loop", "run"]:
        loop_parser = subparsers.add_parser(cmd_alias, help="Run autonomous trading loop (squad or specialist)")
        loop_parser.add_argument("--agent", default="all", choices=["all", "gold", "btc", "eth"], help="Specialist agent to run")
        loop_parser.add_argument("--mode", default="mt5", choices=["mt5", "paper", "mt4"], help="Broker execution mode")
        loop_parser.add_argument("--balance", type=float, default=10000.0, help="Initial account balance")
        loop_parser.add_argument("--interval", type=int, default=5, help="Loop interval in seconds")
        loop_parser.add_argument("--timeframe", default=config.timeframe_main, choices=["M1", "M5", "M15", "H1"], help="Execution timeframe (e.g. M5 for high frequency)")
        loop_parser.add_argument("--max-iter", type=int, default=None, help="Stop after N iterations (for testing)")
        loop_parser.add_argument(
            "--wait-for-live-data", action="store_true",
            help="In MT5 mode, wait safely for fresh telemetry/bars instead of exiting when EA is not ready"
        )
    
    # Analyze command
    ana_parser = subparsers.add_parser("analyze", help="Perform single-pass multimodal analysis")
    ana_parser.add_argument("--symbol", default="XAUUSD", help="Symbol to analyze (e.g. XAUUSD, BTCUSD, ETHUSD)")
    
    # Journal command
    jnl_parser = subparsers.add_parser("journal", help="View learned rules and mistakes database")
    jnl_parser.add_argument("--asset", default="all", choices=["all", "xauusd", "btcusd", "ethusd", "gold", "btc", "eth"], help="Asset journal to view")

    # Backtest command
    bt_parser = subparsers.add_parser("backtest", help="Run strategy backtests and comparative leaderboards")
    bt_parser.add_argument("--market", default="all", choices=["all", "gold", "btc", "eth", "xauusd", "btcusd", "ethusd"], help="Market to test")
    bt_parser.add_argument("--timeframe", default="M5", choices=["M5", "M15"], help="Timeframe for backtesting (default M5)")
    bt_parser.add_argument("--balance", type=float, default=10000.0, help="Initial capital in USD")
    
    # Bridge command
    subparsers.add_parser("bridge", help="Run MT5 FastAPI Bridge Server (connects with AgenticMT5Bridge.mq5)")

    # Test-order command
    to_parser = subparsers.add_parser("test-order", help="Test BUY, SELL and CLOSE order lifecycle")
    to_parser.add_argument("--mode", default="paper", choices=["paper", "mt5"], help="Execution mode (paper or mt5)")
    
    args = parser.parse_args()
    
    if args.command in ["loop", "run"]:
        cmd_loop(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "journal":
        cmd_journal(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "bridge":
        cmd_bridge(args)
    elif args.command == "test-order":
        cmd_test_order(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
