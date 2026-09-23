"""
Platinum (XPTUSD) Specialist Trading Agent.
Implements the M15-backtested winning strategy: Strategy E (Agentic Multimodal Confluence).
Dedicated learned rules in journal/xptusd/. M15-only -- M5 has zero validation for this market yet.
"""

from typing import Dict, Any, Optional
from pathlib import Path
import pandas as pd
import logging

from agents.base_agent import BaseSpecialistAgent
from backtest.strategies import strategy_agentic_confluence
from backtest.data_loader import ASSET_SPECS
from mt4.broker_interface import BaseBroker

logger = logging.getLogger("xpt_agent")


class PlatinumSpecialistAgent(BaseSpecialistAgent):
    """Platinum (XPTUSD) Specialist Agent. M15 only: Strategy E (Agentic Confluence)."""

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
        spec = ASSET_SPECS["XPTUSD"]
        super().__init__(
            symbol="XPTUSD",
            asset_name="Platinum",
            timeframe=timeframe,
            contract_size=spec["contract_size"],
            min_lot=spec["min_lot"],
            max_lot=10.0,
            min_sl_dist=spec["min_sl_dist"],
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
        return "Agentic_Confluence_E"

    def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        if self.timeframe != "M15":
            raise NotImplementedError("XPTUSD only has a validated M15 strategy; M5 is a separate future spec.")
        return strategy_agentic_confluence(df, current_idx=len(df) - 1)
