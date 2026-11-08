"""Dual-mode data provider for the Pilotfish Real-time Web Dashboard."""
from typing import Dict, Any, List, Optional
import time
from datetime import datetime, timezone
import pandas as pd
from config import config
from mt4.paper_broker import PaperTradingBroker

class DashboardFeedProvider:
    """Provides snapshot and live candle/account data from MT5 state or PaperTrading fallback."""

    def __init__(self, mt5_state_ref: Optional[Dict[str, Any]] = None, cached_bars_ref: Optional[Dict[str, Any]] = None):
        self._mt5_state = mt5_state_ref
        self._cached_bars = cached_bars_ref
        self._paper_broker = PaperTradingBroker(initial_balance=config.initial_balance)

    def get_account_data(self) -> Dict[str, Any]:
        """Returns account balance, equity, and connectivity status."""
        if self._mt5_state and self._mt5_state.get("connected"):
            balance = float(self._mt5_state.get("balance", config.initial_balance))
            equity = float(self._mt5_state.get("equity", balance))
            floating = equity - balance
            currency = self._mt5_state.get("currency", "USD")
            is_cent = bool(self._mt5_state.get("is_cent", currency == "USC"))
            return {
                "account_number": self._mt5_state.get("account_number", config.mt5_login),
                "server": self._mt5_state.get("server", config.mt5_server),
                "balance": round(balance, 2),
                "equity": round(equity, 2),
                "floating_pnl": round(floating, 2),
                "connected": True,
                "currency": currency,
                "is_cent": is_cent,
                "last_sync": self._mt5_state.get("last_sync", datetime.now(timezone.utc).isoformat()),
                "mode": "MT5 LIVE"
            }
        
        # Paper fallback
        acc = self._paper_broker.get_account_info()
        balance = float(acc["balance"])
        equity = float(acc["equity"])
        floating = equity - balance
        return {
            "account_number": 99999999,
            "server": "PaperTrading-Simulation",
            "balance": round(balance, 2),
            "equity": round(equity, 2),
            "floating_pnl": round(floating, 2),
            "connected": True,
            "currency": "USD",
            "is_cent": False,
            "last_sync": datetime.now(timezone.utc).isoformat(),
            "mode": "PAPER SIMULATION"
        }

    def get_portfolio_metrics(self) -> Dict[str, Any]:
        """Calculates daily target progress metrics."""
        account = self.get_account_data()
        if account.get("is_cent") or (account.get("mode") == "MT5 LIVE" and self._mt5_state):
            # In live mode (including Cent accounts), baseline dynamically tracks session starting balance
            start_bal = float(self._mt5_state.get("starting_balance", account["balance"]))
            if "starting_balance" not in self._mt5_state:
                self._mt5_state["starting_balance"] = start_bal
        else:
            start_bal = config.initial_balance

        realized = account["balance"] - start_bal
        daily_pct = round((realized / start_bal) * 100.0, 2) if start_bal > 0 else 0.0
        equity_pnl = account["equity"] - start_bal
        equity_pct = round((equity_pnl / start_bal) * 100.0, 2) if start_bal > 0 else 0.0

        return {
            "starting_balance": start_bal,
            "realized_pnl_usd": round(realized, 2),
            "equity_pnl_usd": round(equity_pnl, 2),
            "daily_return_pct": daily_pct,
            "equity_return_pct": equity_pct,
            "target_pct": config.daily_target_pct * 100.0,
            "target_profit_usd": round(start_bal * config.daily_target_pct, 2),
            "hard_target_pct": config.daily_target_hard_pct * 100.0,
            "hard_target_profit_usd": round(start_bal * config.daily_target_hard_pct, 2),
            "max_loss_pct": config.daily_max_loss_pct * 100.0,
            "max_loss_usd": round(start_bal * config.daily_max_loss_pct, 2),
            "target_reached": daily_pct >= (config.daily_target_pct * 100.0),
            "hard_target_reached": daily_pct >= (config.daily_target_hard_pct * 100.0),
            "max_loss_reached": equity_pct <= -(config.daily_max_loss_pct * 100.0)
        }

    def get_bars_list(self, symbol: str, timeframe: str = "M5") -> List[Dict[str, Any]]:
        """Returns formatted bars for TradingView Lightweight Charts (time in unix sec)."""
        key = f"{symbol.upper()}:{timeframe.upper()}"
        if self._cached_bars and key in self._cached_bars and self._cached_bars[key].get("bars"):
            raw_bars = self._cached_bars[key]["bars"]
            # Ensure time is unix timestamp integer
            formatted = []
            for b in raw_bars:
                t = b.get("time") or b.get("timestamp") or time.time()
                if isinstance(t, str):
                    try:
                        t = int(pd.to_datetime(t).timestamp())
                    except Exception:
                        t = int(time.time())
                formatted.append({
                    "time": int(t),
                    "open": float(b["open"]),
                    "high": float(b["high"]),
                    "low": float(b["low"]),
                    "close": float(b["close"]),
                    "volume": float(b.get("volume", b.get("tick_volume", 0)))
                })
            return formatted

        # Fallback to PaperTradingBroker
        df = self._paper_broker.get_market_data(symbol=symbol.upper(), timeframe=timeframe.upper(), bars=100)
        formatted = []
        for idx, row in df.iterrows():
            if isinstance(idx, pd.Timestamp):
                t = int(idx.timestamp())
            else:
                t = int(pd.to_datetime(row.get("timestamp", time.time())).timestamp())
            formatted.append({
                "time": t,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0))
            })
        return formatted

    def get_bars_payload(self, symbol: str, timeframe: str = "M5") -> Dict[str, Any]:
        return {
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            "bars": self.get_bars_list(symbol, timeframe)
        }

    def get_open_positions(self) -> List[Dict[str, Any]]:
        if self._mt5_state and self._mt5_state.get("connected"):
            return self._mt5_state.get("open_positions", [])
        return self._paper_broker.get_open_positions()

    def get_closed_orders(self) -> List[Dict[str, Any]]:
        if self._mt5_state and self._mt5_state.get("connected"):
            return self._mt5_state.get("closed_orders", [])
        return self._paper_broker.get_closed_orders()

    def get_specialist_status(self) -> Dict[str, Any]:
        return {
            "gold": {
                "name": "GoldSpecialistAgent",
                "symbol": "XAUUSD",
                "strategy": "MTF Momentum Cross",
                "status": "ACTIVE"
            },
            "btc": {
                "name": "BtcSpecialistAgent",
                "symbol": "BTCUSD",
                "strategy": "EMA Pullback Rejection",
                "status": "ACTIVE"
            },
            "eth": {
                "name": "EthSpecialistAgent",
                "symbol": "ETHUSD",
                "strategy": "Bollinger Bands Reversion",
                "status": "ACTIVE"
            }
        }

    def get_snapshot(self, symbol: str = "XAUUSD", timeframe: str = "M5") -> Dict[str, Any]:
        return {
            "type": "snapshot",
            "account": self.get_account_data(),
            "portfolio": self.get_portfolio_metrics(),
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            "bars": self.get_bars_list(symbol, timeframe),
            "open_positions": self.get_open_positions(),
            "closed_orders": self.get_closed_orders(),
            "specialists": self.get_specialist_status()
        }
