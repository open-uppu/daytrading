"""
Bitcoin (BTCUSD) Specialist Trading Agent.
M15: Strategy D (MTF Momentum Cross) — validated 2026-11-21 by the
qualabinance rigorous engine (only crypto variant positive in all folds).
M5: legacy scalper (negative edge in validation; squad forces M15).
Dedicated learned rules in journal/btcusd/.
"""

from typing import Dict, Any, Optional
from pathlib import Path
import pandas as pd
import logging

from agents.base_agent import BaseSpecialistAgent
from backtest.strategies import strategy_mtf_momentum, strategy_m5_scalper
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
        # 2026-11-21: pacer disabled for BTC — rigorous validation of the pacer
        # mechanism itself: -0.103R over 1,398 M5 trades (negative in 3/4 folds),
        # and live closed orders show the same small-loss churn. Entries must
        # come from the validated M15 Strategy D signal only. Gold keeps its
        # pacer (+0.093R, positive in all 4 folds).
        self.pacer_enabled = False

    @property
    def strategy_name(self) -> str:
        return "M5_Scalper_BTC" if self.timeframe == "M5" else "MTF_Momentum_Cross_D"

    def evaluate_strategy_signal(self, df: pd.DataFrame, risk_band: str = "NORMAL") -> Dict[str, Any]:
        """
        Evaluates M5 Scalper or M15 Strategy D.

        2026-11-21 (qualabinance rigorous validation, demo account): M15
        Strategy D was the only crypto variant positive in all 4 walk-forward
        folds (+0.239R, PF 1.42, 45 trades); Strategy A on M15 was -0.045R.
        See qualabinance/projects/04-backtest-engine/reports/research_sweep_crypto_gold_2026-11-21.md
        """
        if self.timeframe == "M5":
            return strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="btc")
        return strategy_mtf_momentum(df, current_idx=len(df) - 1)
