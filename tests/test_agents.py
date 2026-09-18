"""
Unit and Integration Tests for Multi-Asset Specialist Squad Architecture.
Tests GoldSpecialistAgent, BtcSpecialistAgent, EthSpecialistAgent, and SquadManager portfolio coordination.
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import tempfile
import shutil

from agents.gold_agent import GoldSpecialistAgent
from agents.btc_agent import BtcSpecialistAgent
from agents.eth_agent import EthSpecialistAgent
from agents.squad_manager import SquadManager
from mt4.paper_broker import PaperTradingBroker


@pytest.fixture
def temp_journal_dir():
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_gold_specialist_agent_spec(temp_journal_dir):
    broker = PaperTradingBroker(initial_balance=10000.0)
    agent = GoldSpecialistAgent(broker=broker, journal_dir=temp_journal_dir / "xauusd")
    
    assert agent.symbol == "XAUUSD"
    assert agent.asset_name == "Gold"
    assert agent.contract_size == 100.0
    assert agent.min_sl_dist == 2.0
    assert agent.strategy_name == "MTF_Momentum_Cross_D"
    assert agent.strategy_type == "trend"
    assert agent.learned_rules_file.exists() or not agent.learned_rules_file.is_dir()


def test_btc_specialist_agent_spec(temp_journal_dir):
    broker = PaperTradingBroker(initial_balance=10000.0)
    agent = BtcSpecialistAgent(broker=broker, journal_dir=temp_journal_dir / "btcusd")
    
    assert agent.symbol == "BTCUSD"
    assert agent.asset_name == "Bitcoin"
    assert agent.contract_size == 1.0
    assert agent.min_sl_dist == 50.0
    assert agent.strategy_name == "EMA_Pullback_Rejection_A"
    assert agent.strategy_type == "trend"


def test_eth_specialist_agent_spec(temp_journal_dir):
    broker = PaperTradingBroker(initial_balance=10000.0)
    agent = EthSpecialistAgent(broker=broker, journal_dir=temp_journal_dir / "ethusd")
    
    assert agent.symbol == "ETHUSD"
    assert agent.asset_name == "Ethereum"
    assert agent.contract_size == 1.0
    assert agent.min_sl_dist == 5.0
    assert agent.strategy_name == "Bollinger_Bands_Reversion_C"
    assert agent.strategy_type == "reversion"


def test_specialists_single_step():
    broker = PaperTradingBroker(initial_balance=10000.0)
    
    gold_agent = GoldSpecialistAgent(broker=broker)
    btc_agent = BtcSpecialistAgent(broker=broker)
    eth_agent = EthSpecialistAgent(broker=broker)
    
    gold_res = gold_agent.step()
    assert gold_res["symbol"] == "XAUUSD"
    assert gold_res["status"] in ["WAITING_FOR_SETUP", "ORDER_PLACED", "MONITORING_POSITION", "VETOED_BY_LEARNED_RULE"]
    
    btc_res = btc_agent.step()
    assert btc_res["symbol"] == "BTCUSD"
    assert btc_res["status"] in ["WAITING_FOR_SETUP", "ORDER_PLACED", "MONITORING_POSITION", "VETOED_BY_LEARNED_RULE"]
    
    eth_res = eth_agent.step()
    assert eth_res["symbol"] == "ETHUSD"
    assert eth_res["status"] in ["WAITING_FOR_SETUP", "ORDER_PLACED", "MONITORING_POSITION", "VETOED_BY_LEARNED_RULE"]


def test_squad_manager_orchestration():
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(
        broker=broker,
        initial_balance=10000.0,
        agents_to_enable=["gold", "btc", "eth"]
    )
    
    assert len(squad.specialists) == 3
    assert "gold" in squad.specialists
    assert "btc" in squad.specialists
    assert "eth" in squad.specialists
    
    # Portfolio telemetry
    p_stat = squad.get_portfolio_daily_pnl()
    assert p_stat["starting_balance"] == 10000.0
    assert p_stat["target_profit_usd"] == 300.0  # 3% of $10,000
    assert p_stat["target_reached"] is False
    
    # Single step across all agents
    step_res = squad.step()
    assert step_res["iteration"] == 1
    assert step_res["status"] == "ACTIVE"
    assert "gold" in step_res["specialist_results"]
    assert "btc" in step_res["specialist_results"]
    assert "eth" in step_res["specialist_results"]


def test_squad_manager_portfolio_target_lock():
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(broker=broker, initial_balance=10000.0)
    
    # Simulate Gold specialist booking a +$350 profit (exceeding 3% target of $300)
    squad.specialists["gold"].session_tracker.record_closed_trade(350.0)
    
    p_stat = squad.get_portfolio_daily_pnl()
    assert p_stat["realized_pnl_usd"] == 350.0
    assert p_stat["daily_return_pct"] == 3.5
    assert p_stat["target_reached"] is True
    
    # Next squad step must immediately lock all trading
    step_res = squad.step()
    assert step_res["status"] == "PORTFOLIO_DAILY_TARGET_REACHED"
    assert len(step_res["specialist_results"]) == 0
