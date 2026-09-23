"""
Natural Gas (XNGUSD) Specialist Trading Agent.
Implements the M15-backtested winning strategy: Strategy A (EMA Pullback Rejection).
Dedicated learned rules in journal/xngusd/. M15-only -- M5 has zero validation for this market yet.

GATED: ASSET_SPECS["XNGUSD"]["contract_size"] is an unverified industry-typical
placeholder (10000 MMBtu/lot), not confirmed against this Exness account.
Verify via MT5 Market Watch -> right-click XNGUSD -> Specification before
trusting any lot-size math this agent computes. Excluded from SquadManager's
"all" until confirmed -- only reachable via explicit --agent=xng.
"""

from typing import Dict, Any, Optional
from pathlib import Path
import pandas as pd
import logging

from agents.base_agent import BaseSpecialistAgent
from backtest.strategies import strategy_ema_pullback
from backtest.data_loader import ASSET_SPECS
from mt4.broker_interface import BaseBroker

logger = logging.getLogger("xng_agent")


class NaturalGasSpecialistAgent(BaseSpecialistAgent):
    """Natural Gas (XNGUSD) Specialist Agent. M15 only: Strategy A (EMA Pullback Rejection)."""

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
        spec = ASSET_SPECS["XNGUSD"]
        super().__init__(
            symbol="XNGUSD",
            asset_name="Natural Gas",
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
        return "EMA_Pullback_Rejection_A"

    def evaluate_strategy_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        if self.timeframe != "M15":
            raise NotImplementedError("XNGUSD only has a validated M15 strategy; M5 is a separate future spec.")
        return strategy_ema_pullback(df, current_idx=len(df) - 1)
