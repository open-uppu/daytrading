"""
Ethereum (ETHUSD) Specialist Trading Agent.
Implements the backtested #1 winning strategy: Strategy C (Bollinger Bands & RSI Mean Reversion).
Dedicated learned rules in journal/ethusd/.
"""

from typing import Dict, Any, Optional
from pathlib import Path
import pandas as pd
import logging

from agents.base_agent import BaseSpecialistAgent
from backtest.strategies import strategy_bb_reversion, strategy_m5_scalper
from mt4.broker_interface import BaseBroker

logger = logging.getLogger("eth_agent")


class EthSpecialistAgent(BaseSpecialistAgent):
    """
    Ethereum (ETHUSD) Specialist Agent.
    - Contract Size: 1.0 ETH ($1.00 move = $1.00 per lot).
    - Optimal Strategy on M5: High-Frequency M5 Scalper (Pullback, Breakout, Cross).
    - Strategy Type: Trend / Scalping on M5, Reversion on M15.
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
        min_sl = 2.0 if timeframe == "M5" else 5.0
        strat_type = "trend" if timeframe == "M5" else "reversion"
        super().__init__(
            symbol="ETHUSD",
            asset_name="Ethereum",
            timeframe=timeframe,
            contract_size=1.0,
            min_lot=0.01,
            max_lot=10.0,
            min_sl_dist=min_sl,
            broker=broker,
            broker_mode=broker_mode,
            initial_balance=initial_balance,
            journal_dir=journal_dir,
            strategy_type=strat_type,
            max_open_positions=max_open_positions,
            min_entry_interval_sec=min_entry_interval_sec,
            magic=magic
        )

    @property
    def strategy_name(self) -> str:
        return "M5_Scalper_ETH" if self.timeframe == "M5" else "Bollinger_Bands_Reversion_C"

    def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Evaluates M5 Scalper or M15 Strategy C.
        """
        if self.timeframe == "M5":
            return strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="eth")
        return strategy_bb_reversion(df, current_idx=len(df) - 1)
