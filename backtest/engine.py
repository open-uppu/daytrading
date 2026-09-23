"""
Fast, High-Fidelity Historical Backtesting Engine for Gold (XAUUSD).
Simulates realistic spread, dynamic lot sizing, daily 3% target locking, and trailing stops.
"""

from typing import Dict, Any, List, Optional, Callable
import pandas as pd
import numpy as np
import logging
from config import config
from backtest.metrics import calculate_performance_metrics

logger = logging.getLogger("backtest_engine")


class BacktestEngine:
    """Simulates trading strategy performance on historical candlestick data."""

    def __init__(
        self,
        initial_balance: float = 10000.0,
        risk_per_trade_pct: float = 0.01,
        daily_target_pct: float = 0.03,
        daily_max_loss_pct: float = 0.02,
        spread: float = 0.25,
        contract_size: float = 100.0,
        min_sl_dist: float = 0.5,
        price_precision: int = 2,
        breakeven_buffer: float = 0.20
    ):
        self.initial_balance = initial_balance
        self.risk_per_trade_pct = risk_per_trade_pct
        self.daily_target_pct = daily_target_pct
        self.daily_max_loss_pct = daily_max_loss_pct
        self.spread = spread
        self.contract_size = contract_size
        # Absolute-dollar SL/TP validity floor. Default 0.5 is tuned for Gold's
        # price scale and preserves exact prior behavior for XAUUSD/BTCUSD/ETHUSD.
        # A market whose price scale differs a lot (e.g. forex pairs ~1.0-1.3,
        # natural gas ~2-4) needs a much smaller floor or every signal gets
        # rejected here regardless of strategy.
        self.min_sl_dist = min_sl_dist
        # Default 2 preserves exact prior behavior for Gold/BTC/ETH-scale prices.
        # A forex pair (~1.08, 5 decimals) rounded to 2 loses up to ~0.005 --
        # bigger than the entire SL distance on a tiny pip-scale stop, which
        # desyncs the stored entry_price from the real fill and makes every
        # trade look stopped-out almost immediately.
        self.price_precision = price_precision
        # Absolute-dollar breakeven-stop offset. Default 0.20 is tuned for
        # Gold's price scale and preserves exact prior behavior for
        # XAUUSD/BTCUSD/ETHUSD/XAGUSD/XPTUSD/UKOIL. On a forex pair
        # (~1.0-1.3) this default is ~2000 pips -- the breakeven-move check
        # (line ~104 below) then sets a "stop" the market can never realistically
        # reach on the correct side, so the SL/TP trigger check treats it as an
        # immediate, fabricated fill on the FAVORABLE side (confirmed: EURUSD
        # SELL trades exited exactly at entry-0.20 with pnl == lots*100000*0.20,
        # mislabeled "SL_HIT" while actually a phantom $100,000 win).
        self.breakeven_buffer = breakeven_buffer

    def run(
        self,
        df: pd.DataFrame,
        signal_fn: Callable[[pd.DataFrame, int], Dict[str, Any]],
        strategy_name: str = "Strategy",
        warmup_bars: int = 50
    ) -> Dict[str, Any]:
        """
        Executes backtest over the provided candlestick DataFrame.
        """
        balance = self.initial_balance
        equity = self.initial_balance
        equity_curve: List[float] = [self.initial_balance]
        
        trades: List[Dict[str, Any]] = []
        open_pos: Optional[Dict[str, Any]] = None
        
        daily_pnls: Dict[str, float] = {}
        current_day_str = ""
        daily_closed_pnl = 0.0
        
        n_bars = len(df)
        ticket_counter = 1
        
        for i in range(warmup_bars, n_bars):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]
            
            # Timestamp & Day Rollover
            timestamp = row['timestamp']
            day_str = str(timestamp).split(' ')[0] if ' ' in str(timestamp) else str(timestamp)[:10]
            
            if day_str != current_day_str:
                if current_day_str:
                    daily_pnls[current_day_str] = round(daily_closed_pnl, 2)
                current_day_str = day_str
                daily_closed_pnl = 0.0

            # 1. Manage Open Position (Check SL, TP, Trailing Stop)
            if open_pos is not None:
                high = float(row['high'])
                low = float(row['low'])
                close_p = float(row['close'])
                
                pos_type = open_pos['type']
                entry_p = open_pos['entry_price']
                sl_p = open_pos['sl']
                tp_p = open_pos['tp']
                lots = open_pos['lots']
                
                # Trailing Break-Even Check: If profit reached 1.0R, move SL to entry
                sl_dist = abs(entry_p - open_pos['initial_sl'])
                if pos_type == "BUY" and (high - entry_p) >= sl_dist and sl_p < entry_p:
                    open_pos['sl'] = entry_p + self.breakeven_buffer  # break-even + buffer
                    sl_p = open_pos['sl']
                elif pos_type == "SELL" and (entry_p - low) >= sl_dist and sl_p > entry_p:
                    open_pos['sl'] = entry_p - self.breakeven_buffer
                    sl_p = open_pos['sl']

                # Check SL / TP Triggers
                exit_price = None
                exit_reason = None
                
                if pos_type == "BUY":
                    if high >= tp_p:
                        exit_price = tp_p
                        exit_reason = "TP_HIT"
                    elif low <= sl_p:
                        exit_price = sl_p
                        exit_reason = "SL_HIT"
                elif pos_type == "SELL":
                    if low <= tp_p:
                        exit_price = tp_p
                        exit_reason = "TP_HIT"
                    elif high >= sl_p:
                        exit_price = sl_p
                        exit_reason = "SL_HIT"

                if exit_price is not None:
                    # Calculate Realized PnL
                    if pos_type == "BUY":
                        pnl = (exit_price - entry_p) * lots * self.contract_size
                    else:
                        pnl = (entry_p - exit_price) * lots * self.contract_size
                        
                    pnl = round(pnl, 2)
                    balance += pnl
                    daily_closed_pnl += pnl
                    
                    trades.append({
                        "ticket": open_pos['ticket'],
                        "type": pos_type,
                        "entry_time": open_pos['entry_time'],
                        "exit_time": str(timestamp),
                        "entry_price": entry_p,
                        "exit_price": exit_price,
                        "lots": lots,
                        "pnl_usd": pnl,
                        "exit_reason": exit_reason,
                        "rr_ratio": open_pos['rr_ratio']
                    })
                    open_pos = None

            # 2. Daily Risk & Target Gates
            daily_target_usd = self.initial_balance * self.daily_target_pct
            daily_max_loss_usd = self.initial_balance * self.daily_max_loss_pct
            
            is_target_reached = daily_closed_pnl >= daily_target_usd
            is_max_loss_hit = daily_closed_pnl <= -daily_max_loss_usd
            
            # 3. Look for Entry if Flat and Authorized
            if open_pos is None and not is_target_reached and not is_max_loss_hit:
                # Provide historical slice up to current bar to prevent lookahead bias
                window = df.iloc[:i + 1]
                signal = signal_fn(window, i)
                
                action = signal.get("action", "HOLD")
                if action in ["BUY", "SELL"]:
                    curr_close = float(row['close'])
                    sl = float(signal.get("sl", 0.0))
                    tp = float(signal.get("tp", 0.0))
                    
                    sl_dist = abs(curr_close - sl)
                    tp_dist = abs(curr_close - tp)
                    
                    if sl_dist > self.min_sl_dist and tp_dist > self.min_sl_dist:
                        rr = tp_dist / sl_dist
                        if rr >= 1.4:  # Minimum valid RR
                            # Calculate Lot Size (1% equity risk)
                            risk_usd = balance * self.risk_per_trade_pct
                            lot = risk_usd / (sl_dist * self.contract_size)
                            lot = round(max(0.01, min(5.0, lot)), 2)
                            
                            fill_price = curr_close + (self.spread / 2) if action == "BUY" else curr_close - (self.spread / 2)
                            
                            open_pos = {
                                "ticket": ticket_counter,
                                "type": action,
                                "entry_time": str(timestamp),
                                "entry_price": round(fill_price, self.price_precision),
                                "sl": sl,
                                "initial_sl": sl,
                                "tp": tp,
                                "lots": lot,
                                "rr_ratio": round(rr, 2)
                            }
                            ticket_counter += 1

            # Track Floating Equity
            floating = 0.0
            if open_pos is not None:
                curr_c = float(row['close'])
                if open_pos['type'] == "BUY":
                    floating = (curr_c - open_pos['entry_price']) * open_pos['lots'] * self.contract_size
                else:
                    floating = (open_pos['entry_price'] - curr_c) * open_pos['lots'] * self.contract_size
                    
            equity = round(balance + floating, 2)
            equity_curve.append(equity)

        # Close any leftover open position at final bar
        if open_pos is not None:
            last_close = float(df.iloc[-1]['close'])
            if open_pos['type'] == "BUY":
                pnl = (last_close - open_pos['entry_price']) * open_pos['lots'] * self.contract_size
            else:
                pnl = (open_pos['entry_price'] - last_close) * open_pos['lots'] * self.contract_size
            balance += round(pnl, 2)
            daily_closed_pnl += round(pnl, 2)
            trades.append({
                "ticket": open_pos['ticket'],
                "type": open_pos['type'],
                "entry_time": open_pos['entry_time'],
                "exit_time": str(df.iloc[-1]['timestamp']),
                "entry_price": open_pos['entry_price'],
                "exit_price": last_close,
                "lots": open_pos['lots'],
                "pnl_usd": round(pnl, 2),
                "exit_reason": "END_OF_DATA",
                "rr_ratio": open_pos['rr_ratio']
            })

        if current_day_str:
            daily_pnls[current_day_str] = round(daily_closed_pnl, 2)

        # Calculate Full Metrics
        metrics = calculate_performance_metrics(
            initial_balance=self.initial_balance,
            equity_curve=equity_curve,
            trades=trades,
            daily_pnls=daily_pnls,
            target_daily_pct=self.daily_target_pct
        )
        metrics["strategy_name"] = strategy_name
        metrics["trades_list"] = trades
        metrics["equity_curve"] = equity_curve
        metrics["daily_pnls"] = daily_pnls

        return metrics
