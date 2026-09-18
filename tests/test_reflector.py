"""
Unit tests for self-learning trade reflection and mistake prevention.
"""

import pytest
from pathlib import Path
from learning.reflector import TradeReflector, TradeOutcome, PreTradeFilter


def test_reflector_losing_trade_and_rule_generation(tmp_path):
    trades_dir = tmp_path / "trades"
    rules_file = tmp_path / "learned_rules.md"
    mistakes_file = tmp_path / "mistakes_db.md"
    
    rules_file.write_text("# Dynamic Trading Rulebook\n\n## Active Rules\n")
    mistakes_file.write_text("# Mistakes DB\n")
    
    reflector = TradeReflector(
        trades_dir=trades_dir,
        learned_rules_file=rules_file,
        mistakes_db_file=mistakes_file
    )
    
    # Simulate a losing BUY trade below EMA 200 (counter-trend)
    bad_trade = TradeOutcome(
        ticket=1001,
        symbol="XAUUSD",
        order_type="BUY",
        open_time="2026-09-18 10:00:00",
        close_time="2026-09-18 10:45:00",
        entry_price=2640.0,
        close_price=2634.0,
        lot_size=0.25,
        sl_price=2634.0,
        tp_price=2652.0,
        pnl_usd=-150.0,
        pnl_pct=-1.5,
        exit_reason="SL_HIT",
        confluence_score=60.0,
        pattern_detected="WEAK_PIN",
        ema_200=2655.0,  # Entry was below EMA 200!
        atr=4.0,
        rsi=45.0
    )
    
    result = reflector.process_closed_trade(bad_trade)
    
    assert result["diagnosis_code"] == "MISTAKE_COUNTER_HTF_TREND"
    assert result["proposed_rule"] is not None
    assert Path(result["autopsy_path"]).exists()
    
    # Verify autopsy markdown content
    autopsy_text = Path(result["autopsy_path"]).read_text()
    assert "# Trade Autopsy: #1001 [LOSS]" in autopsy_text
    assert "MISTAKE_COUNTER_HTF_TREND" in autopsy_text
    
    # Verify rule added to learned_rules.md
    updated_rules = rules_file.read_text()
    assert "Mistake Counter Htf Trend" in updated_rules


def test_pre_trade_filter_blocks_violations():
    filter_engine = PreTradeFilter()
    
    # 1. Attempt BUY below EMA 200
    passed, reason = filter_engine.evaluate_proposal(
        action="BUY",
        entry_price=2640.0,
        sl_price=2634.0,
        ema_200=2650.0,  # Below EMA 200
        atr=4.0
    )
    assert passed is False
    assert "RULE-001" in reason
    
    # 2. Attempt BUY right into Resistance
    passed, reason = filter_engine.evaluate_proposal(
        action="BUY",
        entry_price=2650.0,
        sl_price=2644.0,
        ema_200=2630.0,  # Above EMA 200 (OK)
        atr=4.0,
        nearest_sr=2651.0  # Only 1.0 point away (< 1.0 ATR)
    )
    assert passed is False
    assert "RULE-002" in reason
    
    # 3. Clean Setup should PASS
    passed, reason = filter_engine.evaluate_proposal(
        action="BUY",
        entry_price=2650.0,
        sl_price=2644.0,  # 6.0 dist >= 1.2 * ATR (4.8)
        ema_200=2630.0,
        atr=4.0,
        nearest_sr=2670.0  # 20.0 points away
    )
    assert passed is True
