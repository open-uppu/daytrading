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
from backtest.strategies import strategy_bb_reversion
from mt4.broker_interface import BaseBroker

logger = logging.getLogger("eth_agent")


class EthSpecialistAgent(BaseSpecialistAgent):
    """
    Ethereum (ETHUSD) Specialist Agent.
    - Contract Size: 1.0 ETH ($1.00 move = $1.00 per lot).
    - Optimal Strategy: Strategy C (Bollinger Bands & RSI Mean Reversion - +10.22% Return, 3.28% Max DD).
    - Strategy Type: Reversion (Buys statistical extremes at lower BB, sells at upper BB).
    """

    def __init__(
        self,
        broker: Optional[BaseBroker] = None,
        broker_mode: str = "paper",
        initial_balance: Optional[float] = None,
        journal_dir: Optional[Path] = None
    ):
        super().__init__(
            symbol="ETHUSD",
            asset_name="Ethereum",
            timeframe="M15",
            contract_size=1.0,
            min_lot=0.01,
            max_lot=10.0,
            min_sl_dist=5.0,
            broker=broker,
            broker_mode=broker_mode,
            initial_balance=initial_balance,
            journal_dir=journal_dir,
            strategy_type="reversion"
        )

    @property
    def strategy_name(self) -> str:
        return "Bollinger_Bands_Reversion_C"

    def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Evaluates Strategy C: Bollinger Bands & RSI Mean Reversion on ETHUSD M15 data.
        """
        return strategy_bb_reversion(df, current_idx=len(df) - 1)
