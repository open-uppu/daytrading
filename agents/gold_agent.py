"""
Gold (XAUUSD) Specialist Trading Agent.
Implements the backtested #1 winning strategy: Strategy D (MTF Momentum Cross).
Dedicated learned rules in journal/xauusd/.
"""

from typing import Dict, Any, Optional
from pathlib import Path
import pandas as pd
import logging

from agents.base_agent import BaseSpecialistAgent
from backtest.strategies import strategy_mtf_momentum, strategy_m5_scalper
from mt4.broker_interface import BaseBroker

logger = logging.getLogger("gold_agent")


class GoldSpecialistAgent(BaseSpecialistAgent):
    """
    Gold (XAUUSD) Specialist Agent.
    - Contract Size: 100.0 oz ($1.00 move = $100 per lot).
    - Optimal Strategy on M5: High-Frequency M5 Scalper (Pullback, Breakout, Cross).
    - Session Awareness: London & New York session momentum expansion.
    """

    def __init__(
        self,
        broker: Optional[BaseBroker] = None,
        broker_mode: str = "paper",
        initial_balance: Optional[float] = None,
        journal_dir: Optional[Path] = None,
        timeframe: str = "M5",
        max_open_positions: Optional[int] = None,
        min_entry_interval_sec: int = 600
    ):
        min_sl = 0.8 if timeframe == "M5" else 2.0
        super().__init__(
            symbol="XAUUSD",
            asset_name="Gold",
            timeframe=timeframe,
            contract_size=100.0,
            min_lot=0.01,
            max_lot=10.0,
            min_sl_dist=min_sl,
            broker=broker,
            broker_mode=broker_mode,
            initial_balance=initial_balance,
            journal_dir=journal_dir,
            strategy_type="trend",
            max_open_positions=max_open_positions,
            min_entry_interval_sec=min_entry_interval_sec
        )

    @property
    def strategy_name(self) -> str:
        return "M5_Scalper_Gold" if self.timeframe == "M5" else "MTF_Momentum_Cross_D"

    def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Evaluates M5 High-Frequency Scalper or M15 Strategy D.
        """
        if self.timeframe == "M5":
            return strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="gold")
        return strategy_mtf_momentum(df, current_idx=len(df) - 1)
