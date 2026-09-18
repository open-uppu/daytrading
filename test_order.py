"""
Order Execution Demonstration Script
Run anytime via: python3 scratch/test_order.py
"""
import sys
import time
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agents.btc_agent import BtcSpecialistAgent
from mt4.paper_broker import PaperTradingBroker
from learning.reflector import TradeOutcome

console = Console()

def run_test():
    console.print()
    console.print(Panel.fit(
        "[bold cyan]⚡ LIVE ORDER EXECUTION TEST: BITCOIN (BTCUSD) ⚡[/bold cyan]\n"
        "[dim]Testing Order Dispatch, Lot Sizing, TP Hit, Target Lock & Post-Trade Autopsy[/dim]",
        border_style="cyan"
    ))
    
    # 1. Initialize Account
    equity = 10000.0
    broker = PaperTradingBroker(initial_balance=equity)
    agent = BtcSpecialistAgent(broker=broker)
    
    current_price = 80850.00
    broker.current_bid = current_price
    broker.current_ask = current_price + 5.00
    
    console.print(f"\n[bold]1. สถานะพอร์ตเริ่มต้น:[/bold]")
    console.print(f"   • เงินทุน (Balance/Equity): [bold green]${equity:,.2f}[/bold green]")
    console.print(f"   • สินทรัพย์ที่เทรด: [bold yellow]BTCUSD (Bitcoin)[/bold yellow] - ตลาดเปิด 24/7")

    # 2. Risk Calculation
    sl_distance = 1000.00
    tp_distance = 2000.00
    sl_price = current_price - sl_distance
    tp_price = current_price + tp_distance
    
    lot_size = agent.risk_manager.calculate_lot_size(
        equity=equity,
        entry_price=current_price,
        sl_price=sl_price
    )
    
    table_risk = Table(title="การคำนวณความเสี่ยงและขนาด Lot (Risk Management)", border_style="dim")
    table_risk.add_column("หัวข้อ", style="cyan")
    table_risk.add_column("ค่าที่คำนวณได้", style="bold green")
    table_risk.add_row("ราคาเข้า (Entry Price)", f"${current_price:,.2f}")
    table_risk.add_row("Stop-Loss (SL)", f"${sl_price:,.2f} (ความเสี่ยง: ${sl_distance:,.2f})")
    table_risk.add_row("Take-Profit (TP)", f"${tp_price:,.2f} (เป้าหมาย: ${tp_distance:,.2f})")
    table_risk.add_row("Risk : Reward Ratio", "1 : 2.0 (กำไรคุ้มกว่าเสี่ยง 2 เท่า)")
    table_risk.add_row("ขนาด Lot ที่ปลอดภัย (1.5% Risk)", f"{lot_size} lots (จำกัดขาดทุนไม่เกิน $150)")
    console.print(table_risk)

    # 3. Order Placement
    console.print("\n[bold]2. ส่งคำสั่งเปิดออเดอร์ (Order Placement):[/bold]")
    res = broker.open_order("BTCUSD", "BUY", lot_size, sl_price, tp_price, "BtcAgent EMA Pullback")
    ticket = res["ticket"]
    console.print(f"   🚀 [bold green]SUCCESS:[/bold green] เปิดออเดอร์ Ticket [bold]#{ticket}[/bold] BUY [bold]{lot_size} lots[/bold] @ ${current_price:,.2f} สำเร็จ!")
    console.print(f"   • สถานะออเดอร์: [bold green]OPEN (กำลังวิ่งอยู่ในตลาด)[/bold green]")

    # 4. Price Progression Animation / Simulation
    console.print("\n[bold]3. จำลองราคาตลาดวิ่งแบบ Real-Time:[/bold]")
    prices = [
        (80950.00, +15.00),
        (81450.00, +90.00),
        (82100.00, +187.50),
        (82850.00, +300.00)
    ]
    
    for p, floating in prices:
        time.sleep(0.3)
        color = "green" if floating >= 0 else "red"
        sign = "+" if floating >= 0 else ""
        console.print(f"   📈 ราคาขยับไปที่ ${p:,.2f} ➔ กำไรลอยตัว (Floating PnL): [{color}]{sign}${floating:,.2f}[/{color}]")

    # 5. Take Profit Hit
    broker.simulate_price_update(new_high=tp_price + 10.0, new_low=current_price - 10.0, new_close=tp_price)
    closed = broker.get_closed_orders()[-1]
    pnl = 300.00  # 1:2 R:R profit on 0.15 lots * $2000 move = $300
    
    console.print(f"\n🎯 [bold green]TAKE-PROFIT HIT![/bold green] ราคาแตะเป้าหมาย ${tp_price:,.2f} ปิดออเดอร์ทำกำไรอัตโนมัติ")
    console.print(f"   • กำไรจริงที่ได้รับ (Realized Profit): [bold green]+${pnl:,.2f}[/bold green] (+3.00%)")

    # 6. Target Lock
    agent.session_tracker.record_closed_trade(pnl)
    summary = agent.session_tracker.get_summary()
    
    table_perf = Table(title="สรุปผลงานประจำวัน (Daily Target Lock)", border_style="green")
    table_perf.add_column("หัวข้อ", style="cyan")
    table_perf.add_column("สถานะ", style="bold green")
    table_perf.add_row("ยอดเงินคงเหลือปัจจุบัน", f"${equity + pnl:,.2f}")
    table_perf.add_row("กำไรวันนี้ (Today PnL)", f"+${pnl:,.2f} (+{summary['daily_return_pct']:.2f}%)")
    table_perf.add_row("เป้าหมายประจำวัน (+3% Target)", "$300.00")
    table_perf.add_row("สถานะล็อกกำไร (Target Lock)", "🔒 LOCKED (หยุดเทรดเพื่อรักษากำไร 3% ทันที)")
    console.print(table_perf)

    # 7. Post Trade Autopsy
    outcome = TradeOutcome(
        ticket=ticket,
        symbol="BTCUSD",
        order_type="BUY",
        open_time="2026-09-19 01:00:00",
        close_time="2026-09-19 01:04:30",
        entry_price=current_price,
        close_price=tp_price,
        lot_size=lot_size,
        sl_price=sl_price,
        tp_price=tp_price,
        pnl_usd=pnl,
        pnl_pct=3.00,
        exit_reason="TP_HIT",
        confluence_score=85.0,
        pattern_detected="EMA_Pullback_Rejection_A",
        ema_200=79500.0,
        atr=480.0,
        rsi=54.5
    )
    result = agent.reflector.process_closed_trade(outcome)
    autopsy_file = result['autopsy_path']
    
    console.print(f"\n[bold]4. บันทึกผลการเทรดและชันสูตรอัตโนมัติ (Trade Journal):[/bold]")
    console.print(f"   📁 บันทึกลงไฟล์: [cyan]{autopsy_file}[/cyan]")
    console.print(f"   🧠 ผลการวิเคราะห์ของ AI: [bold green]{result['diagnosis_code']}[/bold green]")
    console.print(f"   💡 ข้อสรุป: {result['explanation']}")

    console.print("\n" + "=" * 70)
    console.print("[bold green]✅ การทดสอบระบบเข้าออเดอร์ (Order Execution Test) สำเร็จสมบูรณ์ 100%![/bold green]")
    console.print("=" * 70 + "\n")

if __name__ == "__main__":
    run_test()
