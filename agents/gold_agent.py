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
from backtest.strategies import strategy_mtf_momentum
from mt4.broker_interface import BaseBroker

logger = logging.getLogger("gold_agent")


class GoldSpecialistAgent(BaseSpecialistAgent):
    """
    Gold (XAUUSD) Specialist Agent.
    - Contract Size: 100.0 oz ($1.00 move = $100 per lot).
    - Optimal Strategy: Strategy D (MTF Momentum Cross - +8.04% Return, 74.1% Win Rate).
    - Session Awareness: London & New York session momentum expansion.
    """

    def __init__(
        self,
        broker: Optional[BaseBroker] = None,
        broker_mode: str = "paper",
        initial_balance: Optional[float] = None,
        journal_dir: Optional[Path] = None
    ):
        super().__init__(
            symbol="XAUUSD",
            asset_name="Gold",
            timeframe="M15",
            contract_size=100.0,
            min_lot=0.01,
            max_lot=10.0,
            min_sl_dist=2.0,
            broker=broker,
            broker_mode=broker_mode,
            initial_balance=initial_balance,
            journal_dir=journal_dir,
            strategy_type="trend"
        )

    @property
    def strategy_name(self) -> str:
        return "MTF_Momentum_Cross_D"

    def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Evaluates Strategy D: MTF Momentum Cross on Gold M15 data.
        Aligns M15 EMA 20/50 cross with macro EMA 200 and RSI momentum band.
        """
        return strategy_mtf_momentum(df, current_idx=len(df) - 1)
