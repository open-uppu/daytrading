"""
High-Fidelity Paper Trading Broker for Gold (XAUUSD).
Provides realistic order execution, spread, tick simulation, and position lifecycle tracking.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import numpy as np
import pandas as pd
import logging
from config import config
from mt4.broker_interface import BaseBroker

logger = logging.getLogger("paper_broker")


class PaperTradingBroker(BaseBroker):
    """Simulates a live broker terminal with realistic Gold market dynamics."""

    def __init__(self, initial_balance: float = 10000.0, symbol: str = "XAUUSD", contract_size: Optional[float] = None):
        self.symbol = symbol
        self.balance: float = initial_balance
        self.equity: float = initial_balance
        self.spread: float = config.spread_points  # 0.25 on gold
        if contract_size is not None:
            self.contract_size = contract_size
        elif any(c in symbol.upper() for c in ["BTC", "ETH"]):
            self.contract_size = 1.0
        else:
            self.contract_size = config.contract_size  # 100.0

        
        self.next_ticket: int = 100001
        self.open_positions: Dict[int, Dict[str, Any]] = {}
        self.closed_orders: List[Dict[str, Any]] = []
        self.recently_closed_orders: List[Dict[str, Any]] = []

        # Historical / Cached Candles.  Keep both timeframes because the M5
        # squad (default paper mode, and the new Docker image CMD) calls
        # get_market_data(..., timeframe="M5"), while analyze / older flows
        # still ask for M15.
        self.m15_data: pd.DataFrame = self._generate_initial_data(bars=120, timeframe="M15")
        self.m5_data: pd.DataFrame = self._generate_initial_data(bars=240, timeframe="M5")
        self.current_price: float = float(self.m5_data.iloc[-1]['close'])

    def _generate_initial_data(self, bars: int = 120, timeframe: str = "M15") -> pd.DataFrame:
        """Generates realistic trending and oscillating Gold candlestick data."""
        np.random.seed(42)
        base = 2650.0
        closes = [base]

        # Create moderate trends and pullbacks
        for i in range(bars - 1):
            drift = 0.2 * np.sin(i / 10.0)
            noise = np.random.normal(0, 1.8)
            closes.append(round(closes[-1] + drift + noise, 2))

        closes = np.array(closes)
        highs = np.round(closes + np.abs(np.random.normal(1.2, 0.6, bars)), 2)
        lows = np.round(closes - np.abs(np.random.normal(1.2, 0.6, bars)), 2)
        opens = np.round(closes + np.random.normal(0, 0.8, bars), 2)
        volume = np.random.randint(100, 2500, bars)

        freq = '5min' if timeframe.upper() == 'M5' else '15min'
        dates = pd.date_range(end=datetime.now(), periods=bars, freq=freq)

        return pd.DataFrame({
            'timestamp': dates,
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': volume
        })

    def get_quote(self, symbol: str = "XAUUSD") -> Dict[str, Any]:
        """Synthetic bid/ask so paper tests exercise the spread gate without MT5."""
        spread = float(self.spread if self.spread > 0 else config.spread_points)
        mid = float(self.current_price or 0.0)
        return {
            "symbol": symbol,
            "bid": round(mid - spread / 2.0, 5),
            "ask": round(mid + spread / 2.0, 5),
            "spread": spread,
            "age_sec": 0.0,
        }

    def get_account_info(self) -> Dict[str, Any]:
        """Returns live account balance, equity, and margin."""
        self._update_equity()
        return {
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "open_positions_count": len(self.open_positions),
            "symbol": self.symbol,
            "bid": round(self.current_price - (self.spread / 2), 2),
            "ask": round(self.current_price + (self.spread / 2), 2)
        }

    def get_market_data(self, symbol: str = "XAUUSD", timeframe: str = "M15", bars: int = 100) -> pd.DataFrame:
        """Returns recent OHLCV bars for the requested timeframe (M5 or M15)."""
        if timeframe.upper() == "M5":
            return self.m5_data.tail(bars).copy().reset_index(drop=True)
        return self.m15_data.tail(bars).copy().reset_index(drop=True)

    def open_order(
        self,
        symbol: str,
        order_type: str,
        lots: float,
        sl: float,
        tp: float,
        comment: str = "",
        magic: int = 888999
    ) -> Dict[str, Any]:
        """Executes a market order with simulated spread."""
        bid = self.current_price - (self.spread / 2)
        ask = self.current_price + (self.spread / 2)

        fill_price = ask if order_type == "BUY" else bid
        ticket = self.next_ticket
        self.next_ticket += 1

        position = {
            "ticket": ticket,
            "symbol": symbol,
            "type": order_type,
            "lots": lots,
            "open_price": round(fill_price, 2),
            "open_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "comment": comment,
            "magic": magic,
            "unrealized_pnl": 0.0
        }

        self.open_positions[ticket] = position
        logger.info(f"[PAPER] Opened #{ticket} {order_type} {lots} lots at {fill_price:.2f} (SL: {sl:.2f}, TP: {tp:.2f})")
        return {"status": "SUCCESS", "ticket": ticket, "fill_price": fill_price}

    def close_order(self, ticket: int, exit_reason: str = "MANUAL_CLOSE", magic: Optional[int] = None) -> Dict[str, Any]:
        """Closes an open order and updates realized account balance."""
        if ticket not in self.open_positions:
            return {"status": "ERROR", "message": f"Position #{ticket} not found"}

        pos = self.open_positions.pop(ticket)
        bid = self.current_price - (self.spread / 2)
        ask = self.current_price + (self.spread / 2)
        close_price = bid if pos["type"] == "BUY" else ask

        # Calculate Realized PnL
        if pos["type"] == "BUY":
            pnl_usd = (close_price - pos["open_price"]) * pos["lots"] * self.contract_size
        else:
            pnl_usd = (pos["open_price"] - close_price) * pos["lots"] * self.contract_size

        pnl_usd = round(pnl_usd, 2)
        pnl_pct = round((pnl_usd / self.balance) * 100.0, 2)
        self.balance += pnl_usd
        self._update_equity()

        closed_record = {
            "ticket": ticket,
            "symbol": pos["symbol"],
            "type": pos["type"],
            "lots": pos["lots"],
            "open_price": pos["open_price"],
            "close_price": round(close_price, 2),
            "open_time": pos["open_time"],
            "close_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sl": pos["sl"],
            "tp": pos["tp"],
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "exit_reason": exit_reason,
            "comment": pos["comment"],
            "magic": pos.get("magic", 888999)
        }

        self.closed_orders.append(closed_record)
        self.recently_closed_orders.append(closed_record)
        logger.info(f"[PAPER] Closed #{ticket} at {close_price:.2f} | Reason: {exit_reason} | PnL: ${pnl_usd:+.2f}")
        return {"status": "SUCCESS", "closed_order": closed_record}

    def modify_order(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None,
                      magic: Optional[int] = None) -> Dict[str, Any]:
        """Updates SL/TP of an active position."""
        if ticket not in self.open_positions:
            return {"status": "ERROR", "message": "Position not found"}
        if sl is not None:
            self.open_positions[ticket]["sl"] = round(sl, 2)
        if tp is not None:
            self.open_positions[ticket]["tp"] = round(tp, 2)
        return {"status": "SUCCESS", "position": self.open_positions[ticket]}

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Returns all open positions with current unrealized PnL."""
        self._update_equity()
        return list(self.open_positions.values())

    def get_closed_orders(self) -> List[Dict[str, Any]]:
        """Returns closed orders history."""
        return self.closed_orders

    def consume_recently_closed(self, symbol: Optional[str] = None, magic: Optional[int] = None) -> List[Dict[str, Any]]:
        """Pops and returns closed orders that haven't been reflected upon yet
        (only `symbol`'s / `magic`'s when given)."""
        recent = [
            o for o in self.recently_closed_orders
            if (not symbol or o.get("symbol") == symbol)
            and (magic is None or o.get("magic", 888999) == magic)
        ]
        self.recently_closed_orders[:] = [o for o in self.recently_closed_orders if o not in recent]
        return recent

    def simulate_price_update(self, new_high: float, new_low: float, new_close: float) -> None:
        """
        Simulates an incoming bar or tick and triggers automatic SL / TP executions.
        """
        self.current_price = new_close
        
        # Check active positions for SL or TP triggers
        active_tickets = list(self.open_positions.keys())
        for ticket in active_tickets:
            if ticket not in self.open_positions:
                continue
            pos = self.open_positions[ticket]
            sl = pos["sl"]
            tp = pos["tp"]
            
            if pos["type"] == "BUY":
                # Check TP first then SL
                if new_high >= tp:
                    self.current_price = tp
                    self.close_order(ticket, exit_reason="TP_HIT", magic=pos.get("magic", 888999))
                elif new_low <= sl:
                    self.current_price = sl
                    self.close_order(ticket, exit_reason="SL_HIT", magic=pos.get("magic", 888999))
            elif pos["type"] == "SELL":
                if new_low <= tp:
                    self.current_price = tp
                    self.close_order(ticket, exit_reason="TP_HIT", magic=pos.get("magic", 888999))
                elif new_high >= sl:
                    self.current_price = sl
                    self.close_order(ticket, exit_reason="SL_HIT", magic=pos.get("magic", 888999))

        self.current_price = new_close
        self._update_equity()

    def _update_equity(self) -> None:
        """Recalculates floating equity based on current price."""
        floating_pnl = 0.0
        bid = self.current_price - (self.spread / 2)
        ask = self.current_price + (self.spread / 2)
        
        for pos in self.open_positions.values():
            if pos["type"] == "BUY":
                pnl = (bid - pos["open_price"]) * pos["lots"] * self.contract_size
            else:
                pnl = (pos["open_price"] - ask) * pos["lots"] * self.contract_size
            pos["unrealized_pnl"] = round(pnl, 2)
            floating_pnl += pnl
            
        self.equity = round(self.balance + floating_pnl, 2)
