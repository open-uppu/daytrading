"""
Agentic Gold (XAUUSD) Day Trading System - Main Entry Point.
"""

import sys
import argparse
import logging
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from pathlib import Path

from config import config
from agent.loop import TradingAgent
from mt4.paper_broker import PaperTradingBroker
from core.chart_generator import generate_candlestick_chart
from core.vision_analyzer import VisionAnalyzer
from core.confluence import ConfluenceEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
console = Console()


def cmd_analyze(args):
    """Performs a single-pass multimodal market analysis."""
    console.print("\n[bold gold1]=== Gold (XAUUSD) Multimodal Market Analysis ===[/bold gold1]\n")
    
    broker = PaperTradingBroker()
    df = broker.get_market_data(symbol="XAUUSD", timeframe="M15", bars=60)
    
    console.print(f"[cyan]1. Generating M15 Candlestick Chart with Indicators...[/cyan]")
    chart_path = generate_candlestick_chart(df, timeframe="M15", symbol="XAUUSD")
    console.print(f"   Saved to: [green]{chart_path}[/green]")
    
    console.print(f"[cyan]2. Running Multimodal Chart Vision Analysis...[/cyan]")
    vision = VisionAnalyzer()
    vision_result = vision.analyze_chart(chart_path, df, timeframe="M15")
    
    console.print(f"[cyan]3. Calculating Unified Confluence Score...[/cyan]")
    confluence = ConfluenceEngine()
    decision = confluence.evaluate(df, vision_result)
    
    # Render Result Table
    table = Table(title="Market Confluence Assessment", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="dim", width=25)
    table.add_column("Value", style="bold")
    
    table.add_row("Current Gold Price", f"${decision['current_price']:.2f}")
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
    """Runs the continuous autonomous trading loop."""
    console.print(Panel(
        f"[bold gold1]Starting Agentic Gold Day Trading Loop[/bold gold1]\n"
        f"Symbol: [bold]XAUUSD[/bold] | Daily Target: [bold green]3.0%[/bold green] (Min $300 on $10k)\n"
        f"Broker Mode: [bold cyan]{args.mode}[/bold cyan] | Poll Interval: [bold]{args.interval}s[/bold]",
        expand=False
    ))
    
    agent = TradingAgent(
        broker_mode=args.mode,
        poll_interval=args.interval
    )
    
    agent.run_loop(max_iterations=args.max_iter)


def cmd_journal(args):
    """Displays learned rules, mistake stats, and journal overview."""
    console.print("\n[bold gold1]=== Agentic Self-Learning Journal & Rulebook ===[/bold gold1]\n")
    
    rules_file = config.learned_rules_file
    if rules_file.exists():
        console.print(Panel(rules_file.read_text(), title="Active Learned Rules (journal/learned_rules.md)", border_style="green"))
    else:
        console.print("[yellow]No learned_rules.md found yet.[/yellow]")
        
    mistakes_file = config.mistakes_db_file
    if mistakes_file.exists():
        console.print(Panel(mistakes_file.read_text(), title="Mistakes Database (journal/mistakes_database.md)", border_style="cyan"))


def cmd_backtest(args):
    """Runs the 5-strategy backtest leaderboard across real Gold historical data."""
    from backtest.run_comparison import run_all_strategies
    run_all_strategies(initial_balance=args.balance, save_chart=True)


def cmd_bridge(args):
    """Runs the MT4 FastAPI bridge server."""
    import uvicorn
    console.print(f"[bold green]Starting MT4 Bridge Server on {config.mt4_host}:{config.mt4_port}...[/bold green]")
    uvicorn.run("mt4.bridge_server:app", host=config.mt4_host, port=config.mt4_port, reload=False)


def main():
    parser = argparse.ArgumentParser(description="Agentic Gold (XAUUSD) Day Trading System")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Loop command
    loop_parser = subparsers.add_parser("loop", help="Run autonomous trading loop")
    loop_parser.add_argument("--mode", default="paper", choices=["paper", "mt4"], help="Broker execution mode")
    loop_parser.add_argument("--interval", type=int, default=5, help="Loop interval in seconds")
    loop_parser.add_argument("--max-iter", type=int, default=None, help="Stop after N iterations (for testing)")
    
    # Analyze command
    subparsers.add_parser("analyze", help="Perform single-pass multimodal analysis")
    
    # Journal command
    subparsers.add_parser("journal", help="View learned rules and mistakes database")

    # Backtest command
    bt_parser = subparsers.add_parser("backtest", help="Run multi-strategy backtest on real historical Gold data")
    bt_parser.add_argument("--balance", type=float, default=10000.0, help="Initial capital in USD")
    
    # Bridge command
    subparsers.add_parser("bridge", help="Run MT4 FastAPI Bridge Server")
    
    args = parser.parse_args()
    
    if args.command == "loop":
        cmd_loop(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "journal":
        cmd_journal(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "bridge":
        cmd_bridge(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
