"""
Gold (XAUUSD) Specialist Trading Agent.
Implements the backtested #1 winning strategy: Strategy D (MTF Momentum Cross).
Dedicated learned rules in journal/xauusd/.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pathlib import Path
import json
import pandas as pd
import logging

from agents.base_agent import BaseSpecialistAgent
from backtest.strategies import strategy_mtf_momentum, strategy_m5_scalper, strategy_bb_extreme
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
        timeframe: str = "M15",
        max_open_positions: Optional[int] = None,
        min_entry_interval_sec: Optional[int] = None,
        magic: Optional[int] = None
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
            min_entry_interval_sec=min_entry_interval_sec,
            magic=magic
        )

    @property
    def strategy_name(self) -> str:
        return "M5_Scalper_Gold" if self.timeframe == "M5" else "MTF_Momentum_Cross_D"

    def _shadow_log_strategy_g(self, df: pd.DataFrame) -> None:
        """Record Strategy G signals to journal (no orders). One line per closed bar."""
        try:
            closed = df.iloc[:-1]  # MT5 feed includes the still-forming bar
            sig = strategy_bb_extreme(closed)
            if sig["action"] == "HOLD":
                return
            bar_ts = str(closed["timestamp"].iloc[-1]) if "timestamp" in closed.columns else str(len(closed))
            if bar_ts == getattr(self, "_shadow_last_bar", None):
                return
            self._shadow_last_bar = bar_ts
            row = {"bar_ts": bar_ts, "logged_at": datetime.now(timezone.utc).isoformat(),
                   **{k: sig[k] for k in ("action", "close", "atr", "rsi", "sl", "tp")}}
            with open(self.journal_dir / "shadow_strategy_g.jsonl", "a") as f:
                f.write(json.dumps(row) + "\n")
        except Exception as e:  # experimental logging must never affect live trading
            logger.debug(f"shadow Strategy G skipped: {e}")

    def evaluate_strategy_signal(self, df: pd.DataFrame, risk_band: str = "NORMAL") -> Dict[str, Any]:
        """
        Evaluates M5 High-Frequency Scalper or M15 Strategy D.
        """
        self._shadow_log_strategy_g(df)
        if self.timeframe == "M5":
            return strategy_m5_scalper(df, current_idx=len(df) - 1, asset_type="gold")
        return strategy_mtf_momentum(df, current_idx=len(df) - 1)
