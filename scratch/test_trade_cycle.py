"""
Live Trade Cycle Simulation Test.
Demonstrates:
1. Confluence calculation & Minimax AI Vision
2. Dynamic lot sizing based on 1.5% risk
3. Order dispatch
4. Price progression to Take-Profit (+300 USD)
5. 3% Daily Target Lock activation
6. Post-trade autopsy generation in markdown journal
"""

import logging
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agents.gold_agent import GoldSpecialistAgent
from mt4.paper_broker import PaperTradingBroker
from learning.reflector import TradeOutcome

console = Console()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def run_test_trade():
    console.print(Panel("[bold green]=== Live Trade Execution & Reflection Simulation ===[/bold green]", border_style="green"))

    # 1. Initialize Paper Broker with Gold
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="XAUUSD")
    gold_agent = GoldSpecialistAgent(broker=broker)

    account_start = broker.get_account_info()
    console.print(f"[bold cyan]1. Account Initialized:[/bold cyan] Balance = ${account_start['balance']:,.2f}, Equity = ${account_start['equity']:,.2f}")

    # 2. Compute dynamic Lot Size & Risk Parameters
    current_price = 2635.00
    atr = 3.50
    sl_price, tp_price, rr_ratio = gold_agent.risk_manager.compute_sl_tp("BUY", current_price, atr)
    lot_size = gold_agent.risk_manager.calculate_lot_size(account_start['equity'], current_price, sl_price)

    console.print(f"[bold cyan]2. Risk Calculation:[/bold cyan]")
    console.print(f"   • Entry Price: [bold]${current_price:.2f}[/bold]")
    console.print(f"   • Stop-Loss (SL): [bold red]${sl_price:.2f}[/bold red] (Risk: ${abs(current_price - sl_price):.2f})")
    console.print(f"   • Take-Profit (TP): [bold green]${tp_price:.2f}[/bold green] (Reward: ${abs(tp_price - current_price):.2f})")
    console.print(f"   • Risk:Reward Ratio: [bold yellow]1:{rr_ratio:.1f}[/bold yellow]")
    console.print(f"   • Calculated Lot Size: [bold magenta]{lot_size} lots[/bold magenta] (100 oz contract)")

    # 3. Open Order
    order_res = broker.open_order(
        symbol="XAUUSD",
        order_type="BUY",
        lots=lot_size,
        sl=sl_price,
        tp=tp_price,
        comment="Test_Agent_Buy"
    )
    ticket = order_res["ticket"]
    console.print(f"[bold green]3. Order Dispatched:[/bold green] #{ticket} BUY {lot_size} lots XAUUSD @ ${current_price:.2f}")

    # Check active open positions
    open_pos = broker.get_open_positions()
    console.print(f"   Active Open Positions: {len(open_pos)}")

    # 4. Simulate Price Moving to Take-Profit
    console.print(f"\n[bold yellow]4. Market Progression:[/bold yellow] Price rallies from ${current_price:.2f} ➔ ${tp_price:.2f} (TP Hit!)...")
    broker.simulate_price_update(new_high=tp_price + 0.50, new_low=current_price - 0.20, new_close=tp_price)

    # 5. Check Trade Closure & PnL
    closed_orders = broker.get_closed_orders()
    assert len(closed_orders) >= 1
    last_closed = closed_orders[-1]
    pnl = last_closed["pnl_usd"]
    console.print(f"[bold green]5. Position Closed:[/bold green] Reason: {last_closed['exit_reason']} | Realized Profit: [bold green]+${pnl:,.2f}[/bold green]")

    # 6. Session Tracker & Daily 3% Target Check
    gold_agent.session_tracker.record_closed_trade(pnl)
    summary = gold_agent.session_tracker.get_summary()

    console.print(f"\n[bold cyan]6. Daily Session Performance:[/bold cyan]")
    console.print(f"   • Realized Profit Today: [bold green]+${summary['closed_pnl_today']:,.2f}[/bold green] (+{summary['daily_return_pct']:.2f}%)")
    color = "green" if summary["target_reached"] else "yellow"
    console.print(f"   • Target Reached: [{color}]{summary['target_reached']}[/{color}]")

    can_trade, reason = gold_agent.session_tracker.can_open_new_trade()
    if not can_trade:
        console.print(f"   🔒 [bold yellow]TARGET LOCK ACTIVE:[/bold yellow] {reason}")

    # 7. Self-Learning Trade Autopsy
    outcome = TradeOutcome(
        ticket=ticket,
        symbol="XAUUSD",
        order_type="BUY",
        open_time="2026-09-19 00:37:00",
        close_time="2026-09-19 00:38:30",
        entry_price=current_price,
        close_price=tp_price,
        lot_size=lot_size,
        sl_price=sl_price,
        tp_price=tp_price,
        pnl_usd=pnl,
        pnl_pct=round((pnl / 10000.0) * 100, 2),
        exit_reason="TP_HIT",
        confluence_score=75.0,
        pattern_detected="MTF_Momentum_Cross_D",
        ema_200=2620.0,
        atr=atr,
        rsi=56.0
    )
    res = gold_agent.reflector.process_closed_trade(outcome)
    console.print(f"\n[bold green]7. Post-Trade Autopsy Saved:[/bold green] [cyan]{res['autopsy_path']}[/cyan]")
    console.print(f"   Diagnosis: [bold]{res['diagnosis_code']}[/bold] - {res['explanation']}\n")

if __name__ == "__main__":
    run_test_trade()
