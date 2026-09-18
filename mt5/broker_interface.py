"""
Abstract Broker Interface for MT5 and Paper Trading.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import pandas as pd


class BaseBroker(ABC):
    """Abstract interface for broker connectivity and order management."""

    @abstractmethod
    def get_account_info(self) -> Dict[str, Any]:
        """Returns account balance, equity, free margin, and leverage."""
        pass

    @abstractmethod
    def get_market_data(self, symbol: str, timeframe: str = "M15", bars: int = 100) -> pd.DataFrame:
        """Fetches OHLCV candlestick data."""
        pass

    @abstractmethod
    def open_order(
        self,
        symbol: str,
        order_type: str,
        lots: float,
        sl: float,
        tp: float,
        comment: str = ""
    ) -> Dict[str, Any]:
        """Submits a BUY or SELL market order."""
        pass

    @abstractmethod
    def close_order(self, ticket: int) -> Dict[str, Any]:
        """Closes an open position by ticket."""
        pass

    @abstractmethod
    def modify_order(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None) -> Dict[str, Any]:
        """Modifies SL and/or TP for an open position."""
        pass

    @abstractmethod
    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Returns a list of all active open positions."""
        pass

    @abstractmethod
    def get_closed_orders(self) -> List[Dict[str, Any]]:
        """Returns closed orders history."""
        pass
