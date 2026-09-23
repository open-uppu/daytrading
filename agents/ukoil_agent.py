"""
Brent Crude Oil (UKOIL) Specialist Trading Agent.
Implements the M15-backtested winning strategy: Strategy C (Bollinger Bands & RSI Mean Reversion).
Dedicated learned rules in journal/ukoil/. M15-only -- M5 has zero validation for this market yet.

GATED: ASSET_SPECS["UKOIL"]["contract_size"] is an unverified industry-typical
placeholder (100 barrels/lot), not confirmed against this Exness account.
Verify via MT5 Market Watch -> right-click UKOIL -> Specification before
trusting any lot-size math this agent computes. Excluded from SquadManager's
"all" until confirmed -- only reachable via explicit --agent=ukoil.
"""

from typing import Dict, Any, Optional
from pathlib import Path
import pandas as pd
import logging

from agents.base_agent import BaseSpecialistAgent
from backtest.strategies import strategy_bb_reversion
from backtest.data_loader import ASSET_SPECS
from mt4.broker_interface import BaseBroker

logger = logging.getLogger("ukoil_agent")


class UkoilSpecialistAgent(BaseSpecialistAgent):
    """Brent Crude Oil (UKOIL) Specialist Agent. M15 only: Strategy C (BB Reversion)."""

    def __init__(
        self,
        broker: Optional[BaseBroker] = None,
        broker_mode: str = "paper",
        initial_balance: Optional[float] = None,
        journal_dir: Optional[Path] = None,
        timeframe: str = "M15",
        max_open_positions: Optional[int] = None,
        min_entry_interval_sec: Optional[int] = None
    ):
        spec = ASSET_SPECS["UKOIL"]
        super().__init__(
            symbol="UKOIL",
            asset_name="Brent Crude Oil",
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
            min_entry_interval_sec=min_entry_interval_sec
        )

    @property
    def strategy_name(self) -> str:
        return "BB_Reversion_C"

    def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        if self.timeframe != "M15":
            raise NotImplementedError("UKOIL only has a validated M15 strategy; M5 is a separate future spec.")
        return strategy_bb_reversion(df, current_idx=len(df) - 1)
