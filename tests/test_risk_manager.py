"""
Unit tests for Risk Management and 3% Daily Profit Target.
"""

import pytest
from risk.manager import DailySessionTracker, RiskManager


def test_daily_session_tracker_3_pct_soft_target_derisks_not_locks():
    # Account 10,000, soft target 3% ($300) now only halves risk per trade -- it
    # must NOT lock trading (that's the 10% hard target's job).
    tracker = DailySessionTracker(starting_balance=10000.0, target_pct=0.03, max_loss_pct=0.02)

    assert tracker.target_profit_usd == 300.0
    assert tracker.max_loss_usd == 200.0
    assert tracker.is_target_reached is False
    assert tracker.risk_multiplier == 1.0

    can_trade, msg = tracker.can_open_new_trade()
    assert can_trade is True

    # Trade 1: +$180 profit
    tracker.record_closed_trade(180.0)
    assert tracker.is_target_reached is False
    assert tracker.daily_return_pct == 1.8
    can_trade, _ = tracker.can_open_new_trade()
    assert can_trade is True

    # Trade 2: +$140 profit (Total: $320 -> 3.2% > soft 3% target)
    tracker.record_closed_trade(140.0)
    assert tracker.is_target_reached is True
    assert tracker.daily_return_pct == 3.2
    assert tracker.risk_multiplier == 0.5  # derisked, not locked

    can_trade, reason = tracker.can_open_new_trade()
    assert can_trade is True
    assert "AUTHORIZED_DERISKED" in reason
    assert tracker.is_hard_target_reached is False


def test_daily_session_tracker_10_pct_hard_target_locks():
    tracker = DailySessionTracker(starting_balance=10000.0, target_pct=0.03, hard_target_pct=0.10, max_loss_pct=0.02)
    assert tracker.hard_target_profit_usd == 1000.0

    tracker.record_closed_trade(320.0)   # past soft 3%, still under hard 10%
    assert tracker.is_hard_target_reached is False
    can_trade, _ = tracker.can_open_new_trade()
    assert can_trade is True

    tracker.record_closed_trade(700.0)   # total $1020 -> 10.2% > hard 10%
    assert tracker.is_hard_target_reached is True

    can_trade, reason = tracker.can_open_new_trade()
    assert can_trade is False
    assert "DAILY_HARD_TARGET_REACHED" in reason


def test_daily_session_tracker_max_loss_cutoff():
    tracker = DailySessionTracker(starting_balance=10000.0, target_pct=0.03, max_loss_pct=0.02)
    
    # Trade: -$210 loss (> $200 max loss)
    tracker.record_closed_trade(-210.0)
    assert tracker.is_max_loss_hit is True
    
    can_trade, reason = tracker.can_open_new_trade()
    assert can_trade is False
    assert "DAILY_LOSS_LIMIT_HIT" in reason


def test_lot_size_calculation_for_gold():
    tracker = DailySessionTracker(starting_balance=10000.0)
    rm = RiskManager(session_tracker=tracker)
    
    # Equity = $10,000, 1% risk = $100
    # Entry = 2650.00, SL = 2646.00 (Distance = $4.00)
    # 1 standard lot moves $100 for $1 move.
    # For $4 move, 1 lot loses $400.
    # Desired risk = $100.
    # Expected lot = 100 / 400 = 0.25 lots.
    lot = rm.calculate_lot_size(equity=10000.0, entry_price=2650.00, sl_price=2646.00)
    assert lot == 0.25


def test_lot_size_halves_once_soft_target_derisks():
    tracker = DailySessionTracker(starting_balance=10000.0)
    rm = RiskManager(session_tracker=tracker)

    full_lot = rm.calculate_lot_size(equity=10000.0, entry_price=2650.00, sl_price=2646.00)
    tracker.record_closed_trade(320.0)  # past soft 3% target ($300)
    assert tracker.risk_multiplier == 0.5

    derisked_lot = rm.calculate_lot_size(equity=10000.0, entry_price=2650.00, sl_price=2646.00)
    assert derisked_lot == round(full_lot / 2, 2)


def test_lot_size_halves_with_extra_multiplier():
    tracker = DailySessionTracker(starting_balance=10000.0)
    rm = RiskManager(session_tracker=tracker)

    full_lot = rm.calculate_lot_size(equity=10000.0, entry_price=2650.00, sl_price=2646.00)
    news_derisked_lot = rm.calculate_lot_size(equity=10000.0, entry_price=2650.00, sl_price=2646.00, extra_multiplier=0.5)
    assert news_derisked_lot == round(full_lot / 2, 2)


def test_dynamic_sl_tp_and_validation():
    tracker = DailySessionTracker(starting_balance=10000.0)
    rm = RiskManager(session_tracker=tracker)
    
    entry = 2650.00
    atr = 4.00
    sl, tp, rr = rm.compute_sl_tp("BUY", entry, atr)
    
    # ATR 4.0 * 1.5 = 6.0 SL distance -> SL = 2644.00
    assert sl == 2644.00
    # Target RR 2.0 -> TP distance 12.0 -> TP = 2662.00
    assert tp == 2662.00
    assert rr >= 1.5
    
    valid, msg, lot = rm.validate_trade_proposal("BUY", entry, sl, tp, equity=10000.0)
    assert valid is True
    assert lot > 0
