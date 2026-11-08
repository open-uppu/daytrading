"""
Paper broker that trades against LIVE bridge prices and survives restarts.

`PaperTradingBroker` fabricates a single synthetic Gold price series for every
symbol and keeps all state in memory.  This subclass instead:

* reads real OHLC bars per symbol from a data source (the MT5 bridge) and never
  sends an order to the real account -- orders are simulated locally;
* prices, spreads, contract sizes and SL/TP exits are tracked per symbol;
* persists balance, open positions and closed orders to a JSON file so a
  rebuild/restart of the container resumes where it left off.

Market-closed / stale feeds propagate as `MarketDataStale` from the data
source, exactly like the live MT5 broker, so agents stand by instead of
trading synthetic data.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.data_loader import ASSET_SPECS
from config import config
from mt4.paper_broker import PaperTradingBroker
from mt5.bridge_server import MT5BridgeBroker, normalize_symbol

logger = logging.getLogger("live_paper_broker")

STATE_VERSION = 1
MAX_CLOSED_KEPT = 2000


class LiveFeedPaperBroker(PaperTradingBroker):
    """Simulated execution on top of real market data, with durable state."""

    def __init__(
        self,
        state_path: Path,
        data_source: Optional[Any] = None,
        initial_balance: Optional[float] = None,
    ):
        self._source = data_source if data_source is not None else MT5BridgeBroker()
        self.state_path = Path(state_path)
        self._prices: Dict[str, float] = {}

        loaded = self._read_state()
        if loaded is not None:
            start_balance = float(loaded["balance"])
        elif initial_balance is not None and initial_balance > 0:
            start_balance = float(initial_balance)
        else:
            # Start from the real account's balance so sizing/limits are realistic.
            account = self._source.get_account_info()
            real_balance = account.get("balance")
            if not isinstance(real_balance, (int, float)) or real_balance <= 0:
                raise RuntimeError(
                    "Live account balance unavailable; cannot seed the paper account. "
                    "Check bridge telemetry or pass an explicit initial balance."
                )
            start_balance = float(real_balance)

        super().__init__(initial_balance=start_balance, symbol="MULTI")
        self.current_price = 0.0  # last price seen; per-symbol prices live in self._prices

        today = datetime.now(timezone.utc).date().isoformat()
        self.initial_balance_seed: float = start_balance
        self.state_day: str = today
        self.day_start_balance: float = start_balance

        if loaded is not None:
            self._apply_state(loaded)
            logger.info(
                "[LIVE-PAPER] Resumed from %s | balance $%.2f | %d open | %d closed",
                self.state_path, self.balance, len(self.open_positions), len(self.closed_orders),
            )
        else:
            logger.info("[LIVE-PAPER] Fresh paper account, balance $%.2f (seeded from live account)", start_balance)
            self._save()

    # ------------------------------------------------------------------ specs
    @staticmethod
    def _key(symbol: str) -> str:
        return normalize_symbol(symbol).upper()

    def _spec(self, symbol: str) -> Dict[str, Any]:
        return ASSET_SPECS.get(self._key(symbol), {})

    def _contract_size(self, symbol: str) -> float:
        return float(self._spec(symbol).get("contract_size", config.contract_size))

    def _spread(self, symbol: str) -> float:
        return float(self._spec(symbol).get("typical_spread", config.spread_points))

    def _precision(self, symbol: str) -> int:
        return int(self._spec(symbol).get("price_precision", 2))

    # ------------------------------------------------------------ persistence
    def _read_state(self) -> Optional[Dict[str, Any]]:
        if not self.state_path.exists():
            return None
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"Paper state file {self.state_path} is unreadable ({exc}); "
                "move or delete it to start a fresh paper account."
            ) from exc
        if data.get("version") != STATE_VERSION or "balance" not in data:
            raise RuntimeError(
                f"Paper state file {self.state_path} has an unsupported format; "
                "move or delete it to start a fresh paper account."
            )
        return data

    def _apply_state(self, data: Dict[str, Any]) -> None:
        self.balance = float(data["balance"])
        self.next_ticket = int(data.get("next_ticket", self.next_ticket))
        self.open_positions = {int(t): p for t, p in data.get("open_positions", {}).items()}
        self.closed_orders = list(data.get("closed_orders", []))
        self.initial_balance_seed = float(data.get("initial_balance", self.balance))
        self.state_day = data.get("day", self.state_day)
        self.day_start_balance = float(data.get("day_start_balance", self.balance))
        self._update_equity()

    def _save(self) -> None:
        payload = {
            "version": STATE_VERSION,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "initial_balance": self.initial_balance_seed,
            "balance": round(self.balance, 2),
            "next_ticket": self.next_ticket,
            "day": self.state_day,
            "day_start_balance": self.day_start_balance,
            "open_positions": {str(t): p for t, p in self.open_positions.items()},
            "closed_orders": self.closed_orders[-MAX_CLOSED_KEPT:],
        }
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError as exc:
            logger.error("[LIVE-PAPER] Could not persist paper state to %s: %s", self.state_path, exc)

    def day_baseline(self, balance: float) -> float:
        """Balance at the first moment of the current UTC day (survives restarts)."""
        today = datetime.now(timezone.utc).date().isoformat()
        if today != self.state_day:
            self.state_day = today
            self.day_start_balance = self.balance
            self._save()
        return self.day_start_balance

    # ---------------------------------------------------------------- account
    def get_account_info(self) -> Dict[str, Any]:
        self._update_equity()
        return {
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "open_positions_count": len(self.open_positions),
            "symbol": self.symbol,
            "bid": round(self.current_price, 2),
            "ask": round(self.current_price, 2),
            "connected": True,
        }

    def _update_equity(self) -> None:
        floating = 0.0
        for pos in self.open_positions.values():
            sym = pos["symbol"]
            price = self._prices.get(self._key(sym), pos["open_price"])
            spread = self._spread(sym)
            bid, ask = price - spread / 2, price + spread / 2
            contract = pos.get("contract_size") or self._contract_size(sym)
            if pos["type"] == "BUY":
                pnl = (bid - pos["open_price"]) * pos["lots"] * contract
            else:
                pnl = (pos["open_price"] - ask) * pos["lots"] * contract
            pos["unrealized_pnl"] = round(pnl, 2)
            pos["bid"], pos["ask"] = round(bid, 6), round(ask, 6)
            floating += pnl
        self.equity = round(self.balance + floating, 2)

    # ------------------------------------------------------------ market data
    def get_market_data(self, symbol: str = "XAUUSD", timeframe: str = "M5", bars: int = 100) -> pd.DataFrame:
        """Real bars from the data source; raises MarketDataStale when the market is closed."""
        df = self._source.get_market_data(symbol=symbol, timeframe=timeframe, bars=bars)
        self._on_bars(symbol, df)
        return df

    def _on_bars(self, symbol: str, df: pd.DataFrame) -> None:
        if df is None or len(df) == 0:
            return
        key = self._key(symbol)
        last = df.iloc[-1]
        price = float(last["close"])
        self._prices[key] = price
        self.current_price = price

        changed = False
        for ticket in [t for t, p in self.open_positions.items() if self._key(p["symbol"]) == key]:
            pos = self.open_positions.get(ticket)
            if pos is None:
                continue
            hi, lo = price, price
            open_ts = pos.get("open_bar_ts")
            if open_ts is not None and "timestamp" in df.columns:
                try:
                    # Only bars that began after the order opened can contribute their full range.
                    newer = df[df["timestamp"] > open_ts]
                    if len(newer):
                        hi = max(hi, float(newer["high"].max()))
                        lo = min(lo, float(newer["low"].min()))
                except TypeError:
                    pass
            changed |= self._check_exit(ticket, pos, hi, lo)
        self._update_equity()
        if changed:
            self._save()

    def _check_exit(self, ticket: int, pos: Dict[str, Any], hi: float, lo: float) -> bool:
        sl, tp = pos["sl"], pos["tp"]
        if pos["type"] == "BUY":
            if sl and lo <= sl:
                self._close_at(ticket, sl, "SL_HIT")
                return True
            if tp and hi >= tp:
                self._close_at(ticket, tp, "TP_HIT")
                return True
        else:
            if sl and hi >= sl:
                self._close_at(ticket, sl, "SL_HIT")
                return True
            if tp and lo <= tp:
                self._close_at(ticket, tp, "TP_HIT")
                return True
        return False

    def _latest_bar_ts(self, symbol: str) -> Optional[Any]:
        try:
            df = self._source.get_market_data(symbol=symbol, timeframe="M5", bars=1)
        except Exception:
            return None
        if df is not None and len(df) and "timestamp" in df.columns:
            value = df["timestamp"].iloc[-1]
            return value.item() if hasattr(value, "item") else value  # numpy scalar -> JSON-safe
        return None

    # ------------------------------------------------------------- execution
    def open_order(
        self,
        symbol: str,
        order_type: str,
        lots: float,
        sl: float,
        tp: float,
        comment: str = "",
        magic: int = 888999,
    ) -> Dict[str, Any]:
        key = self._key(symbol)
        price = self._prices.get(key)
        if price is None:
            self.get_market_data(symbol=symbol, timeframe="M5", bars=2)  # may raise MarketDataStale
            price = self._prices.get(key)
        if price is None:
            return {"status": "ERROR", "message": f"No live price for {symbol}"}

        spread = self._spread(symbol)
        digits = self._precision(symbol)
        fill = price + spread / 2 if order_type == "BUY" else price - spread / 2
        ticket = self.next_ticket
        self.next_ticket += 1

        position = {
            "ticket": ticket,
            "symbol": symbol,
            "type": order_type,
            "lots": lots,
            "open_price": round(fill, digits),
            "open_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "open_bar_ts": self._latest_bar_ts(symbol),
            "sl": round(sl, digits),
            "tp": round(tp, digits),
            "comment": comment,
            "magic": magic,
            "contract_size": self._contract_size(symbol),
            "unrealized_pnl": 0.0,
        }
        self.open_positions[ticket] = position
        self._save()
        logger.info("[LIVE-PAPER] Opened #%s %s %s %s lots @ %s (SL %s, TP %s)",
                    ticket, symbol, order_type, lots, position["open_price"], position["sl"], position["tp"])
        return {"status": "SUCCESS", "ticket": ticket, "fill_price": position["open_price"]}

    def _close_at(self, ticket: int, close_price: float, exit_reason: str) -> Dict[str, Any]:
        pos = self.open_positions.pop(ticket)
        contract = pos.get("contract_size") or self._contract_size(pos["symbol"])
        if pos["type"] == "BUY":
            pnl_usd = (close_price - pos["open_price"]) * pos["lots"] * contract
        else:
            pnl_usd = (pos["open_price"] - close_price) * pos["lots"] * contract
        pnl_usd = round(pnl_usd, 2)
        pnl_pct = round((pnl_usd / self.balance) * 100.0, 2) if self.balance else 0.0
        self.balance += pnl_usd
        self._update_equity()

        record = {
            "ticket": ticket,
            "symbol": pos["symbol"],
            "type": pos["type"],
            "lots": pos["lots"],
            "open_price": pos["open_price"],
            "close_price": round(close_price, self._precision(pos["symbol"])),
            "open_time": pos["open_time"],
            "close_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sl": pos["sl"],
            "tp": pos["tp"],
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "exit_reason": exit_reason,
            "comment": pos["comment"],
            "magic": pos.get("magic", 888999),
        }
        self.closed_orders.append(record)
        self.recently_closed_orders.append(record)
        logger.info("[LIVE-PAPER] Closed #%s %s @ %s | %s | PnL $%+.2f",
                    ticket, pos["symbol"], record["close_price"], exit_reason, pnl_usd)
        return {"status": "SUCCESS", "closed_order": record}

    def close_order(self, ticket: int, exit_reason: str = "MANUAL_CLOSE", magic: Optional[int] = None) -> Dict[str, Any]:
        pos = self.open_positions.get(ticket)
        if pos is None:
            return {"status": "ERROR", "message": f"Position #{ticket} not found"}
        price = self._prices.get(self._key(pos["symbol"]), pos["open_price"])
        half = self._spread(pos["symbol"]) / 2
        close_price = price - half if pos["type"] == "BUY" else price + half
        result = self._close_at(ticket, close_price, exit_reason)
        self._save()
        return result

    def modify_order(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None,
                     magic: Optional[int] = None) -> Dict[str, Any]:
        pos = self.open_positions.get(ticket)
        if pos is None:
            return {"status": "ERROR", "message": "Position not found"}
        digits = self._precision(pos["symbol"])
        if sl is not None:
            pos["sl"] = round(sl, digits)
        if tp is not None:
            pos["tp"] = round(tp, digits)
        self._save()
        return {"status": "SUCCESS", "position": pos}

    def get_open_positions(self) -> List[Dict[str, Any]]:
        self._update_equity()
        return list(self.open_positions.values())
