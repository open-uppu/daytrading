"""
Silver (XAGUSD) Specialist Trading Agent.
Implements the M15-backtested winning strategy: Strategy C (Bollinger Bands & RSI Mean Reversion).
Dedicated learned rules in journal/xagusd/. M15-only -- M5 has zero validation for this market yet.
"""

from typing import Dict, Any, Optional
from pathlib import Path
import pandas as pd
import logging

from agents.base_agent import BaseSpecialistAgent
from backtest.strategies import strategy_bb_reversion, strategy_agentic_confluence
from backtest.data_loader import ASSET_SPECS
from mt4.broker_interface import BaseBroker

logger = logging.getLogger("xag_agent")


class SilverSpecialistAgent(BaseSpecialistAgent):
    """Silver (XAGUSD) Specialist Agent. M15 only: Strategy C (BB Reversion)."""

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
        spec = ASSET_SPECS["XAGUSD"]
        super().__init__(
            symbol="XAGUSD",
            asset_name="Silver",
            timeframe=timeframe,
            contract_size=spec["contract_size"],
            min_lot=spec["min_lot"],
            max_lot=10.0,
            min_sl_dist=spec["min_sl_dist"],
            broker=broker,
            broker_mode=broker_mode,
            initial_balance=initial_balance,
            journal_dir=journal_dir,
            strategy_type="reversion",
            max_open_positions=max_open_positions,
            min_entry_interval_sec=min_entry_interval_sec,
            magic=magic
        )

    @property
    def strategy_name(self) -> str:
        return "BB_Reversion_C"

    def evaluate_strategy_signal(self, df: pd.DataFrame, risk_band: str = "NORMAL") -> Dict[str, Any]:
        if self.timeframe != "M15":
            raise NotImplementedError("Silver only has a validated M15 strategy; M5 is a separate future spec.")
        if risk_band == "RECOVERY":
            # 2026-09-25 M15 backtest: Strategy E (agentic_confluence) had
            # both lower Max DD (0.67% vs 2.25%) and a positive return
            # (+0.40%) vs. this specialist's normal Strategy C -- the only
            # one of the 9 specialists where a genuinely better recovery
            # option exists.
            return strategy_agentic_confluence(df, current_idx=len(df) - 1)
        return strategy_bb_reversion(df, current_idx=len(df) - 1)
