"""
Bitcoin (BTCUSD) Specialist Trading Agent.
Implements the backtested #1 winning strategy: Strategy A (EMA Pullback Rejection).
Dedicated learned rules in journal/btcusd/.
"""

from typing import Dict, Any, Optional
from pathlib import Path
import pandas as pd
import logging

from agents.base_agent import BaseSpecialistAgent
from backtest.strategies import strategy_ema_pullback, strategy_m5_scalper
from mt4.broker_interface import BaseBroker

logger = logging.getLogger("btc_agent")


class BtcSpecialistAgent(BaseSpecialistAgent):
    """
    Bitcoin (BTCUSD) Specialist Agent.
    - Contract Size: 1.0 BTC ($1.00 move = $1.00 per lot).
    - Optimal Strategy on M5: High-Frequency M5 Scalper (Pullback, Breakout, Cross).
    - Session Awareness: 24/7 continuous crypto liquidity, high weekend volatility filter.
    """

    def __init__(
        self,
        broker: Optional[BaseBroker] = None,
        broker_mode: str = "paper",
        initial_balance: Optional[float] = None,
        journal_dir: Optional[Path] = None,
        timeframe: str = "M15",
        max_open_positions: Optional[int] = None,
        min_entry_interval_sec: Optional[int] = None,
        magic: Optional[int] = None
    ):
        min_sl = 25.0 if timeframe == "M5" else 50.0
        super().__init__(
            symbol="BTCUSD",
            asset_name="Bitcoin",
            timeframe=timeframe,
            contract_size=1.0,
            min_lot=0.01,
            max_lot=10.0,
            min_sl_dist=min_sl,
            broker=broker,
            broker_mode=broker_mode,
            initial_balance=initial_balance,
            journal_dir=journal_dir,
            strategy_type="trend",
            max_open_positions=max_open_positions,
            min_entry_interval_sec=min_entry_interval_sec,
            magic=magic
        )

    @property
    def strategy_name(self) -> str:
        return "M5_Scalper_BTC" if self.timeframe == "M5" else "EMA_Pullback_Rejection_A"

    def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Evaluates M5 Scalper or M15 Strategy A.
        """
        if self.timeframe == "M5":
            return strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc")
        return strategy_ema_pullback(df, current_idx=len(df) - 1)
