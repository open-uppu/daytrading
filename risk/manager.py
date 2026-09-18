"""
Risk Management and Daily Profit Target Engine for Gold (XAUUSD).
Guarantees strict compliance with the 3% daily profit goal and capital preservation.
"""

from typing import Dict, Any, Tuple, Optional
from datetime import datetime, date, timezone
import logging
from config import config

logger = logging.getLogger("risk_manager")


class DailySessionTracker:
    """Tracks daily session PnL, locks trading when 3% profit is reached or max loss is hit."""

    def __init__(
        self,
        starting_balance: float = 10000.0,
        target_pct: float = None,
        max_loss_pct: float = None
    ):
        self.session_date: date = datetime.now(timezone.utc).date()
        self.starting_balance: float = starting_balance
        self.target_pct: float = target_pct or config.daily_target_pct
        self.max_loss_pct: float = max_loss_pct or config.daily_max_loss_pct
        
        self.target_profit_usd: float = self.starting_balance * self.target_pct
        self.max_loss_usd: float = self.starting_balance * self.max_loss_pct
        
        self.closed_pnl_today: float = 0.0
        self.trades_count_today: int = 0
        self.wins_count_today: int = 0
        self.losses_count_today: int = 0

    def check_new_session(self, current_balance: float) -> None:
        """Resets session stats if a new UTC day has started."""
        today = datetime.now(timezone.utc).date()
        if today != self.session_date:
            logger.info(f"New trading session started: {today}. Resetting daily tracking.")
            self.session_date = today
            self.starting_balance = current_balance
            self.target_profit_usd = self.starting_balance * self.target_pct
            self.max_loss_usd = self.starting_balance * self.max_loss_pct
            self.closed_pnl_today = 0.0
            self.trades_count_today = 0
            self.wins_count_today = 0
            self.losses_count_today = 0

    def record_closed_trade(self, profit_usd: float) -> None:
        """Records a realized trade outcome."""
        self.closed_pnl_today += profit_usd
        self.trades_count_today += 1
        if profit_usd > 0:
            self.wins_count_today += 1
        elif profit_usd < 0:
            self.losses_count_today += 1

    @property
    def daily_return_pct(self) -> float:
        """Returns the current realized return percentage for the day."""
        if self.starting_balance <= 0:
            return 0.0
        return round((self.closed_pnl_today / self.starting_balance) * 100.0, 4)

    @property
    def is_target_reached(self) -> bool:
        """Checks if the >= 3% daily target has been reached."""
        return self.closed_pnl_today >= self.target_profit_usd

    @property
    def is_max_loss_hit(self) -> bool:
        """Checks if the daily loss limit has been breached."""
        return self.closed_pnl_today <= -self.max_loss_usd

    def can_open_new_trade(self) -> Tuple[bool, str]:
        """
        Determines if the agent is authorized to take new trades today.
        """
        if self.is_target_reached:
            return False, (
                f"DAILY_TARGET_REACHED: Daily profit +{self.closed_pnl_today:.2f} USD "
                f"(+{self.daily_return_pct:.2f}%) met or exceeded target of "
                f"+{self.target_profit_usd:.2f} USD (+{self.target_pct*100:.1f}%). "
                f"Trading locked to protect capital!"
            )
            
        if self.is_max_loss_hit:
            return False, (
                f"DAILY_LOSS_LIMIT_HIT: Daily loss {self.closed_pnl_today:.2f} USD "
                f"({self.daily_return_pct:.2f}%) hit max cutoff of "
                f"-{self.max_loss_usd:.2f} USD (-{self.max_loss_pct*100:.1f}%). "
                f"Trading ceased for safety!"
            )
            
        return True, "AUTHORIZED: Within daily risk and profit bounds."

    def get_summary(self) -> Dict[str, Any]:
        """Returns session summary dictionary."""
        return {
            "session_date": str(self.session_date),
            "starting_balance": self.starting_balance,
            "target_profit_usd": round(self.target_profit_usd, 2),
            "max_loss_usd": round(self.max_loss_usd, 2),
            "closed_pnl_today": round(self.closed_pnl_today, 2),
            "daily_return_pct": round(self.daily_return_pct, 2),
            "target_reached": self.is_target_reached,
            "max_loss_hit": self.is_max_loss_hit,
            "trades_count": self.trades_count_today,
            "wins": self.wins_count_today,
            "losses": self.losses_count_today
        }


class RiskManager:
    """Manages position sizing, Stop-Loss, Take-Profit, and trade validation."""

    def __init__(self, session_tracker: DailySessionTracker = None):
        self.session_tracker = session_tracker or DailySessionTracker(config.initial_balance)
        self.risk_pct = config.risk_per_trade_pct
        self.min_rr = config.min_rr_ratio
        self.target_rr = config.target_rr_ratio
        self.contract_size = config.contract_size

    def calculate_lot_size(
        self,
        equity: float,
        entry_price: float,
        sl_price: float
    ) -> float:
        """
        Calculates exact lot size for Gold (XAUUSD) based on risk percentage and stop-loss distance.
        1 standard lot = 100 oz ($1.00 move = $100 per lot).
        """
        sl_distance = abs(entry_price - sl_price)
        if sl_distance <= 0.1:
            raise ValueError(f"Stop loss distance too small: {sl_distance:.2f}")

        # Maximum cash risk on this trade
        risk_cash = equity * self.risk_pct
        
        # Loss per 1.00 standard lot for this stop loss distance
        loss_per_lot = sl_distance * self.contract_size
        
        raw_lot = risk_cash / loss_per_lot
        
        # Apply broker min/max bounds and 2 decimal precision
        lot_size = round(max(config.min_lot, min(config.max_lot, raw_lot)), 2)
        return lot_size

    def compute_sl_tp(
        self,
        action: str,
        entry_price: float,
        atr: float,
        sr_levels: Dict[str, Any] = None
    ) -> Tuple[float, float, float]:
        """
        Computes dynamic ATR-based SL and TP ensuring minimum 1:1.5 to 1:2.0 Risk-Reward.
        Returns: (sl_price, tp_price, rr_ratio)
        """
        atr_sl_dist = max(round(1.5 * atr, 2), 2.0)  # Minimum 2 dollars for gold
        
        if action == "BUY":
            sl_price = round(entry_price - atr_sl_dist, 2)
            # TP aiming for target RR (e.g. 2.0)
            tp_price = round(entry_price + (atr_sl_dist * self.target_rr), 2)
        elif action == "SELL":
            sl_price = round(entry_price + atr_sl_dist, 2)
            tp_price = round(entry_price - (atr_sl_dist * self.target_rr), 2)
        else:
            raise ValueError(f"Invalid action: {action}")

        sl_dist = abs(entry_price - sl_price)
        tp_dist = abs(entry_price - tp_price)
        rr_ratio = round(tp_dist / sl_dist, 2)
        
        return sl_price, tp_price, rr_ratio

    def validate_trade_proposal(
        self,
        action: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        equity: float
    ) -> Tuple[bool, str, float]:
        """
        Performs full risk verification before allowing order dispatch.
        Returns: (is_valid, reason, lot_size)
        """
        # 1. Check Daily Session Limits
        can_trade, reason = self.session_tracker.can_open_new_trade()
        if not can_trade:
            return False, reason, 0.0

        # 2. Check Risk-to-Reward Ratio
        sl_dist = abs(entry_price - sl_price)
        tp_dist = abs(entry_price - tp_price)
        if sl_dist <= 0:
            return False, "Invalid SL distance (0)", 0.0
            
        rr_ratio = tp_dist / sl_dist
        if rr_ratio < self.min_rr:
            return False, f"Risk-Reward {rr_ratio:.2f} is below minimum allowed ({self.min_rr})", 0.0

        # 3. Calculate Lot Size
        lot_size = self.calculate_lot_size(equity, entry_price, sl_price)
        
        # Verify potential loss does not breach daily loss cutoff
        potential_loss = lot_size * sl_dist * self.contract_size
        remaining_loss_allowance = (
            (self.session_tracker.starting_balance * self.session_tracker.max_loss_pct) +
            self.session_tracker.closed_pnl_today
        )
        if potential_loss > remaining_loss_allowance and self.session_tracker.closed_pnl_today < 0:
            return False, f"Potential loss (${potential_loss:.1f}) exceeds remaining daily allowance (${remaining_loss_allowance:.1f})", 0.0

        return True, "Risk validation passed", lot_size
