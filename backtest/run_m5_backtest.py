"""
High-Frequency M5 Backtest Engine & Comparative Benchmark.
Specifically validates the ~10-minute entry cadence goal, concurrent position handling (up to 3),
and tight ATR scalping performance across Gold, BTC, and ETH.
"""

from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
import pandas as pd
import numpy as np
import logging
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config import config
from backtest.data_loader import load_historical_data
from backtest.strategies import strategy_m5_scalper
from backtest.metrics import calculate_performance_metrics

logger = logging.getLogger("m5_backtest")
console = Console()


class M5BacktestEngine:
    """
    Simulates high-frequency M5 scalping with:
    - Multiple concurrent positions (up to max_open_positions, default 3)
    - 10-minute cadence cooldown (cooldown_bars, default 2 bars)
    - Dynamic tight ATR SL/TP
    - Portfolio daily target lock (+3%) and max loss cutoff (-2%)
    """

    def __init__(
        self,
        initial_balance: float = 10000.0,
        risk_per_trade_pct: float = 0.005,  # 0.5% per scalp trade
        daily_target_pct: float = 0.03,
        daily_max_loss_pct: float = 0.02,
        spread: float = 0.25,
        contract_size: float = 100.0,
        max_open_positions: int = 3,
        cooldown_bars: int = 2,  # 2 bars of M5 = 10 minutes
        min_sl_dist: float = 0.80
    ):
        self.initial_balance = initial_balance
        self.risk_per_trade_pct = risk_per_trade_pct
        self.daily_target_pct = daily_target_pct
        self.daily_max_loss_pct = daily_max_loss_pct
        self.spread = spread
        self.contract_size = contract_size
        self.max_open_positions = max_open_positions
        self.cooldown_bars = cooldown_bars
        self.min_sl_dist = min_sl_dist

    def run(
        self,
        df: pd.DataFrame,
        signal_fn: Callable[[pd.DataFrame, int], Dict[str, Any]],
        strategy_name: str = "M5_Scalper",
        warmup_bars: int = 40
    ) -> Dict[str, Any]:
        balance = self.initial_balance
        equity = self.initial_balance
        equity_curve: List[float] = [self.initial_balance]

        trades: List[Dict[str, Any]] = []
        open_positions: List[Dict[str, Any]] = []

        daily_pnls: Dict[str, float] = {}
        current_day_str = ""
        daily_closed_pnl = 0.0
        daily_locked = False

        n_bars = len(df)
        ticket_counter = 1
        last_entry_bar_idx = -999
        entry_intervals: List[int] = []  # in minutes

        for i in range(warmup_bars, n_bars):
            row = df.iloc[i]
            timestamp = row['timestamp']
            day_str = str(timestamp).split(' ')[0] if ' ' in str(timestamp) else str(timestamp)[:10]

            if day_str != current_day_str:
                if current_day_str:
                    daily_pnls[current_day_str] = round(daily_closed_pnl, 2)
                current_day_str = day_str
                daily_closed_pnl = 0.0
                daily_locked = False

            high = float(row['high'])
            low = float(row['low'])
            close_p = float(row['close'])

            # 1. Manage Active Positions (Check SL & TP hits)
            remaining_positions: List[Dict[str, Any]] = []
            for pos in open_positions:
                pos_type = pos['type']
                entry_p = pos['entry_price']
                sl_p = pos['sl']
                tp_p = pos['tp']
                lots = pos['lots']

                exit_price = None
                exit_reason = None

                if pos_type == "BUY":
                    if high >= tp_p:
                        exit_price = tp_p
                        exit_reason = "TP_HIT"
                    elif low <= sl_p:
                        exit_price = sl_p
                        exit_reason = "SL_HIT"
                else:  # SELL
                    if low <= tp_p:
                        exit_price = tp_p
                        exit_reason = "TP_HIT"
                    elif high >= sl_p:
                        exit_price = sl_p
                        exit_reason = "SL_HIT"

                if exit_price is not None:
                    if pos_type == "BUY":
                        pnl = (exit_price - entry_p - self.spread) * lots * self.contract_size
                    else:
                        pnl = (entry_p - exit_price - self.spread) * lots * self.contract_size

                    balance += pnl
                    daily_closed_pnl += pnl
                    pos['exit_price'] = exit_price
                    pos['exit_time'] = timestamp
                    pos['exit_reason'] = exit_reason
                    pos['pnl_usd'] = round(pnl, 2)
                    pos['balance_after'] = round(balance, 2)
                    trades.append(pos)
                else:
                    remaining_positions.append(pos)

            open_positions = remaining_positions

            # 2. Daily Risk Limits Check (+3% Lock or -2% Cutoff)
            daily_target_usd = balance * self.daily_target_pct
            daily_max_loss_usd = balance * self.daily_max_loss_pct

            if daily_closed_pnl >= daily_target_usd:
                daily_locked = True
            elif daily_closed_pnl <= -daily_max_loss_usd:
                daily_locked = True

            # 3. Check Signal & Cadence Cooldown for New Entries
            can_enter_slot = len(open_positions) < self.max_open_positions
            can_enter_cooldown = (i - last_entry_bar_idx) >= self.cooldown_bars

            if not daily_locked and can_enter_slot and can_enter_cooldown:
                window = df.iloc[:i + 1]
                signal = signal_fn(window, i)
                action = signal.get("action", "HOLD")

                if action in ["BUY", "SELL"]:
                    sl_candidate = signal.get("sl")
                    tp_candidate = signal.get("tp")

                    sl_dist = abs(close_p - sl_candidate) if sl_candidate else self.min_sl_dist
                    sl_dist = max(sl_dist, self.min_sl_dist)

                    # Dynamic Scalp Lot Sizing based on 0.5% risk
                    risk_usd = balance * self.risk_per_trade_pct
                    raw_lot = risk_usd / (sl_dist * self.contract_size)
                    lot = max(0.01, min(round(raw_lot, 2), 5.0))

                    if sl_candidate is None:
                        sl_candidate = close_p - sl_dist if action == "BUY" else close_p + sl_dist
                    if tp_candidate is None:
                        tp_dist = sl_dist * 1.5
                        tp_candidate = close_p + tp_dist if action == "BUY" else close_p - tp_dist

                    new_pos = {
                        "ticket": ticket_counter,
                        "type": action,
                        "entry_price": close_p,
                        "lots": lot,
                        "sl": sl_candidate,
                        "tp": tp_candidate,
                        "entry_time": timestamp,
                        "entry_bar": i,
                        "strategy": strategy_name,
                        "reason": signal.get("reason", "M5 Scalp")
                    }
                    ticket_counter += 1
                    open_positions.append(new_pos)

                    if last_entry_bar_idx > 0:
                        mins = (i - last_entry_bar_idx) * 5
                        entry_intervals.append(mins)
                    last_entry_bar_idx = i

            # Track floating equity
            floating_pnl = 0.0
            for pos in open_positions:
                if pos['type'] == "BUY":
                    floating_pnl += (close_p - pos['entry_price'] - self.spread) * pos['lots'] * self.contract_size
                else:
                    floating_pnl += (pos['entry_price'] - close_p - self.spread) * pos['lots'] * self.contract_size

            equity = balance + floating_pnl
            equity_curve.append(round(equity, 2))

        # Close remaining open positions at final close
        final_row = df.iloc[-1]
        final_close = float(final_row['close'])
        for pos in open_positions:
            if pos['type'] == "BUY":
                pnl = (final_close - pos['entry_price'] - self.spread) * pos['lots'] * self.contract_size
            else:
                pnl = (pos['entry_price'] - final_close - self.spread) * pos['lots'] * self.contract_size
            balance += pnl
            pos['exit_price'] = final_close
            pos['exit_time'] = final_row['timestamp']
            pos['exit_reason'] = "SESSION_END"
            pos['pnl_usd'] = round(pnl, 2)
            pos['balance_after'] = round(balance, 2)
            trades.append(pos)

        # Performance Metrics
        metrics = calculate_performance_metrics(
            initial_balance=self.initial_balance,
            equity_curve=equity_curve,
            trades=trades,
            daily_pnls=daily_pnls,
            target_daily_pct=self.daily_target_pct
        )
        metrics["strategy_name"] = strategy_name
        metrics["trades"] = trades

        avg_interval = float(np.mean(entry_intervals)) if entry_intervals else 10.0
        metrics["avg_minutes_between_trades"] = round(avg_interval, 1)
        metrics["total_bars"] = n_bars
        total_days = max(len(daily_pnls), 1)
        metrics["trades_per_day"] = round(len(trades) / total_days, 1)

        return metrics


def run_single_asset_m5_backtest(
    symbol: str = "XAUUSD",
    initial_balance: float = 10000.0,
    max_bars: Optional[int] = None
) -> Dict[str, Any]:
    """Runs high-frequency M5 scalping backtest for a single asset."""
    sym = symbol.upper()
    df = load_historical_data(symbol=sym, timeframe="M5")
    if max_bars and len(df) > max_bars:
        df = df.iloc[:max_bars].copy()

    asset_type = "gold" if "XAU" in sym else ("btc" if "BTC" in sym else "eth")
    contract_size = 100.0 if "XAU" in sym else 1.0
    spread = 0.20 if "XAU" in sym else (15.0 if "BTC" in sym else 1.0)
    min_sl = 1.0 if "XAU" in sym else (25.0 if "BTC" in sym else 2.0)

    engine = M5BacktestEngine(
        initial_balance=initial_balance,
        risk_per_trade_pct=0.005,
        daily_target_pct=0.03,
        daily_max_loss_pct=0.02,
        spread=spread,
        contract_size=contract_size,
        max_open_positions=3,
        cooldown_bars=2,
        min_sl_dist=min_sl
    )

    def signal_wrapper(window: pd.DataFrame, idx: int) -> Dict[str, Any]:
        return strategy_m5_scalper(window, idx, asset_type=asset_type)

    metrics = engine.run(
        df=df,
        signal_fn=signal_wrapper,
        strategy_name=f"M5_Scalper_{sym}"
    )
    metrics["symbol"] = sym
    return metrics


def run_m5_squad_backtest(initial_balance: float = 10000.0) -> List[Dict[str, Any]]:
    """Runs complete M5 high-frequency benchmark across Gold, BTC, and ETH."""
    console.print("\n[bold gold1]===========================================================[/bold gold1]")
    console.print("[bold gold1]   HIGH-FREQUENCY M5 SCALPER BENCHMARK (Goal: 10m Entry)   [/bold gold1]")
    console.print("[bold gold1]===========================================================[/bold gold1]\n")

    symbols = ["XAUUSD", "BTCUSD", "ETHUSD"]
    results = []

    for sym in symbols:
        console.print(f"[cyan]Evaluating M5 High-Frequency Scalper for [bold]{sym}[/bold]...[/cyan]")
        res = run_single_asset_m5_backtest(symbol=sym, initial_balance=initial_balance)
        results.append(res)
        console.print(
            f"  -> Total Trades: [bold]{res['total_trades']}[/bold] "
            f"(~{res['trades_per_day']} trades/day | Cadence: {res['avg_minutes_between_trades']} min/trade)"
        )
        console.print(
            f"  -> Return: [bold green]{res['total_return_pct']:+.2f}%[/bold green] | "
            f"Win Rate: {res['win_rate_pct']:.1f}% | Profit Factor: {res['profit_factor']:.2f} | "
            f"Hit 3% Target: {res['days_hit_3pct_target']} days"
        )

    # Leaderboard Table
    table = Table(
        title="M5 High-Frequency Scalping Squad Leaderboard (~10-min Target Cadence)",
        header_style="bold magenta",
        show_header=True
    )
    table.add_column("Symbol", style="bold white", justify="center")
    table.add_column("Return (%)", justify="right")
    table.add_column("Win Rate (%)", justify="right")
    table.add_column("Profit Factor", justify="right")
    table.add_column("Trades", justify="center")
    table.add_column("Cadence (Avg Min)", justify="center", style="bold yellow")
    table.add_column("Trades / Day", justify="center")
    table.add_column("3% Target Days", justify="right")
    table.add_column("Max DD (%)", justify="right")

    for res in results:
        ret_style = "green" if res['total_return_pct'] >= 0 else "red"
        table.add_row(
            res['symbol'],
            f"[{ret_style}]{res['total_return_pct']:+.2f}%[/{ret_style}]",
            f"{res['win_rate_pct']:.1f}%",
            f"{res['profit_factor']:.2f}",
            str(res['total_trades']),
            f"{res['avg_minutes_between_trades']} min",
            str(res['trades_per_day']),
            f"{res['days_hit_3pct_target']} days",
            f"{res['max_drawdown_pct']:.2f}%"
        )

    console.print(table)
    return results


if __name__ == "__main__":
    run_m5_squad_backtest()
