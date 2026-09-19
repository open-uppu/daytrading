import pytest
from datetime import datetime, timedelta
from agents.gold_agent import GoldSpecialistAgent
from mt4.paper_broker import PaperTradingBroker
from config import config

def test_specialist_concurrency_settings():
    agent = GoldSpecialistAgent(broker=PaperTradingBroker(), timeframe="M5")
    assert agent.timeframe == "M5"
    assert agent.max_open_positions >= 3
    assert agent.min_entry_interval_sec == 600

def test_specialist_allows_concurrent_positions():
    broker = PaperTradingBroker(initial_balance=10000.0)
    agent = GoldSpecialistAgent(broker=broker, timeframe="M5")
    
    # Simulate 1 open position
    broker.open_order(symbol="XAUUSD", order_type="BUY", lots=0.1, sl=1990.0, tp=2015.0)
    open_pos = broker.get_open_positions()
    assert len(open_pos) == 1
    
    # Should not be blocked by 1 open position since max is 3
    assert len(open_pos) < agent.max_open_positions

def test_specialist_cooldown_check():
    agent = GoldSpecialistAgent(broker=PaperTradingBroker(), timeframe="M5")
    now = datetime.now()
    agent.last_entry_time = now
    
    # Cooldown check immediately: should be within cooldown (< 600s)
    can_enter, reason = agent._check_entry_cooldown()
    assert not can_enter
    assert "cooldown" in reason.lower()
    
    # After 10 minutes (601 seconds): should be allowed
    agent.last_entry_time = now - timedelta(seconds=605)
    can_enter, reason = agent._check_entry_cooldown()
    assert can_enter
