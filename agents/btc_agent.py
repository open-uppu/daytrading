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
from backtest.strategies import strategy_ema_pullback
from mt4.broker_interface import BaseBroker

logger = logging.getLogger("btc_agent")


class BtcSpecialistAgent(BaseSpecialistAgent):
    """
    Bitcoin (BTCUSD) Specialist Agent.
    - Contract Size: 1.0 BTC ($1.00 move = $1.00 per lot).
    - Optimal Strategy: Strategy A (EMA Pullback Rejection - Hit 3% Target 10 Days).
    - Session Awareness: 24/7 continuous crypto liquidity, high weekend volatility filter.
    """

    def __init__(
        self,
        broker: Optional[BaseBroker] = None,
        broker_mode: str = "paper",
        initial_balance: Optional[float] = None,
        journal_dir: Optional[Path] = None
    ):
        super().__init__(
            symbol="BTCUSD",
            asset_name="Bitcoin",
            timeframe="M15",
            contract_size=1.0,
            min_lot=0.01,
            max_lot=10.0,
            min_sl_dist=50.0,
            broker=broker,
            broker_mode=broker_mode,
            initial_balance=initial_balance,
            journal_dir=journal_dir,
            strategy_type="trend"
        )

    @property
    def strategy_name(self) -> str:
        return "EMA_Pullback_Rejection_A"

    def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Evaluates Strategy A: EMA Pullback with Rejection Candlestick on BTCUSD M15 data.
        """
        return strategy_ema_pullback(df, current_idx=len(df) - 1)
