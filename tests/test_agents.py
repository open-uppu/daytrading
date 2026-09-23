"""
Unit and Integration Tests for Multi-Asset Specialist Squad Architecture.
Tests GoldSpecialistAgent, BtcSpecialistAgent, EthSpecialistAgent, and SquadManager portfolio coordination.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import shutil

from config import config
from agents.gold_agent import GoldSpecialistAgent
from agents.btc_agent import BtcSpecialistAgent
from agents.eth_agent import EthSpecialistAgent
from agents.squad_manager import SquadManager
from mt4.paper_broker import PaperTradingBroker
from mt5.bridge_server import MT5BridgeBroker
import mt5.bridge_server as mt5_state


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
    
    expected_statuses = ["WAITING_FOR_SETUP", "ORDER_PLACED", "MONITORING_POSITION",
                         "VETOED_BY_LEARNED_RULE", "VETOED_BY_ML_CONFIDENCE"]

    gold_res = gold_agent.step()
    assert gold_res["symbol"] == "XAUUSD"
    assert gold_res["status"] in expected_statuses

    btc_res = btc_agent.step()
    assert btc_res["symbol"] == "BTCUSD"
    assert btc_res["status"] in expected_statuses

    eth_res = eth_agent.step()
    assert eth_res["symbol"] == "ETHUSD"
    assert eth_res["status"] in expected_statuses


def test_news_blackout_active_blocks_new_entry(monkeypatch, temp_journal_dir):
    monkeypatch.setattr("agents.base_agent.fetch_ff_calendar", lambda: [{
        "title": "Non-Farm Employment Change",
        "country": "USD",
        "impact": "High",
        "date": datetime.now(timezone.utc).isoformat(),
    }])
    broker = PaperTradingBroker(initial_balance=10000.0)
    agent = GoldSpecialistAgent(broker=broker, journal_dir=temp_journal_dir / "xauusd")

    result = agent.step()

    assert result["status"] == "NEWS_BLACKOUT_ACTIVE"


def test_news_blackout_kill_switch_disables_gate(monkeypatch, temp_journal_dir):
    monkeypatch.setattr("agents.base_agent.fetch_ff_calendar", lambda: [{
        "title": "Non-Farm Employment Change",
        "country": "USD",
        "impact": "High",
        "date": datetime.now(timezone.utc).isoformat(),
    }])
    monkeypatch.setattr(config, "news_blackout_enabled", False)
    broker = PaperTradingBroker(initial_balance=10000.0)
    agent = GoldSpecialistAgent(broker=broker, journal_dir=temp_journal_dir / "xauusd")

    result = agent.step()

    assert result["status"] != "NEWS_BLACKOUT_ACTIVE"


def test_squad_manager_all_enables_seven_not_nine(tmp_path):
    """'all' expands to the 7 registered specialists (gold/btc/eth + the 4
    new markets with confirmed contract specs) -- ukoil/xng stay gated
    behind explicit opt-in until their contract_size is verified in MT5."""
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(broker=broker, initial_balance=10000.0, agents_to_enable=["all"], journal_dir=tmp_path)
    assert len(squad.specialists) == 7
    assert "ukoil" not in squad.specialists
    assert "xng" not in squad.specialists
    assert set(squad.specialists.keys()) == {"gold", "btc", "eth", "xag", "gbp", "eur", "xpt"}


def test_squad_manager_m5_default_still_runs_new_m15_only_agents(tmp_path):
    """Live production runs the squad on M5 (see main.py's timeframe default).
    The 6 new agents only have a validated M15 strategy -- they must always
    run M15 regardless of the squad's own timeframe, not error every step()."""
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(broker=broker, initial_balance=10000.0, agents_to_enable=["all"], timeframe="M5", journal_dir=tmp_path)
    assert squad.specialists["gold"].timeframe == "M5"
    assert squad.specialists["xag"].timeframe == "M15"
    assert squad.specialists["gbp"].timeframe == "M15"
    assert squad.specialists["eur"].timeframe == "M15"
    assert squad.specialists["xpt"].timeframe == "M15"
    step_res = squad.step()
    for key in ["xag", "gbp", "eur", "xpt"]:
        assert step_res["specialist_results"][key]["status"] != "ERROR"


def test_squad_manager_gated_specialist_reachable_by_explicit_name(tmp_path):
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(broker=broker, initial_balance=10000.0, agents_to_enable=["ukoil"], journal_dir=tmp_path)
    assert "ukoil" in squad.specialists
    assert len(squad.specialists) == 1


def test_portfolio_open_risk_uses_real_contract_size_for_new_markets(monkeypatch):
    """The old hardcoded 3-entry dict defaulted unknown symbols to contract_size=1.0.
    A EURUSD position (real contract_size 100000) would have had its risk
    under-counted by ~100,000x, silently disabling the max-loss circuit breaker."""
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(broker=broker, initial_balance=10000.0, agents_to_enable=["eur"])
    monkeypatch.setattr(broker, "get_open_positions", lambda: [
        {"symbol": "EURUSD", "open_price": 1.0800, "sl": 1.0790, "lots": 1.0}
    ])
    # True risk: 0.0010 distance * 1.0 lots * 100000 contract_size = $100
    risk = squad._portfolio_open_risk_usd()
    assert risk == pytest.approx(100.0, rel=0.01)  # would be $0.001 under the old 1.0 fallback


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


def test_squad_manager_portfolio_soft_target_does_not_lock(tmp_path):
    """Past the 3% soft target but under the 10% hard target must NOT stop
    the squad -- only the per-specialist risk_multiplier derisks."""
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(broker=broker, initial_balance=10000.0, journal_dir=tmp_path)

    # Simulate Gold specialist booking a +$350 profit (exceeding 3% soft target of $300)
    squad.specialists["gold"].session_tracker.record_closed_trade(350.0)

    p_stat = squad.get_portfolio_daily_pnl()
    assert p_stat["realized_pnl_usd"] == 350.0
    assert p_stat["daily_return_pct"] == 3.5
    assert p_stat["target_reached"] is True
    assert p_stat["hard_target_reached"] is False

    # Squad must keep running specialists, not lock
    step_res = squad.step()
    assert step_res["status"] == "ACTIVE"
    assert len(step_res["specialist_results"]) == 3


def test_squad_manager_portfolio_hard_target_locks(tmp_path):
    """Past the 20% hard target must lock all trading."""
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(broker=broker, initial_balance=10000.0, journal_dir=tmp_path)

    # Simulate Gold specialist booking a +$2050 profit (exceeding 20% hard target of $2000)
    squad.specialists["gold"].session_tracker.record_closed_trade(2050.0)

    p_stat = squad.get_portfolio_daily_pnl()
    assert p_stat["daily_return_pct"] == 20.5
    assert p_stat["hard_target_reached"] is True

    step_res = squad.step()
    assert step_res["status"] == "PORTFOLIO_DAILY_TARGET_REACHED"
    assert len(step_res["specialist_results"]) == 0


def test_live_squad_uses_terminal_balance_not_cli_default(monkeypatch):
    """A live risk limit must be based on the actual account, not $10k."""
    class LiveBroker(PaperTradingBroker):
        def get_account_info(self):
            return {"balance": 500.0, "equity": 480.0}  # -4% equity, past the 3% max loss cutoff

    squad = SquadManager(
        broker=LiveBroker(initial_balance=10_000.0),
        broker_mode="mt5",
        initial_balance=10_000.0,
        agents_to_enable=[],
    )

    status = squad.get_portfolio_daily_pnl()
    assert status["starting_balance"] == 500.0
    assert status["target_profit_usd"] == 15.0
    assert status["max_loss_reached"] is True


def test_real_mt5_squad_refuses_disconnected_placeholder_state(monkeypatch):
    """The bridge's in-memory defaults are not valid authorization for live trading."""
    monkeypatch.setitem(mt5_state._mt5_state, "connected", False)
    monkeypatch.setitem(mt5_state._mt5_state, "last_sync", "")
    broker = MT5BridgeBroker(in_process=True)
    with pytest.raises(RuntimeError, match="not connected"):
        SquadManager(broker=broker, broker_mode="mt5", agents_to_enable=[])


def test_portfolio_loss_cutoff_closes_floating_loss_positions():
    """Max loss is an equity guard and must liquidate active paper/live positions."""
    broker = PaperTradingBroker(initial_balance=10_000.0)
    opened = broker.open_order(
        symbol="XAUUSD", order_type="BUY", lots=1.0,
        sl=broker.current_price - 10.0, tp=broker.current_price + 30.0, comment="cutoff-test",
    )
    current = broker.current_price
    broker.simulate_price_update(current - 3.0, current - 3.0, current - 3.0)
    squad = SquadManager(
        broker=broker, broker_mode="paper", initial_balance=10_000.0,
        agents_to_enable=[],
    )
    # Preserve the pre-existing position while making the session reference
    # balance explicit for this deterministic test.
    squad.starting_portfolio_balance = 10_000.0
    result = squad.step()
    assert result["status"] == "PORTFOLIO_MAX_LOSS_CUTOFF"
    assert opened["ticket"] not in [p["ticket"] for p in broker.get_open_positions()]


def test_run_loop_pauses_on_max_loss_cutoff_instead_of_exiting():
    """Hitting the loss cutoff must idle the loop (keep the process/container
    alive, no new trades), not terminate it -- a full exit needs a manual
    restart to resume trading, an idle loop resumes itself next day."""
    broker = PaperTradingBroker(initial_balance=10_000.0)
    broker.open_order(
        symbol="XAUUSD", order_type="BUY", lots=1.0,
        sl=broker.current_price - 10.0, tp=broker.current_price + 30.0, comment="cutoff-test",
    )
    current = broker.current_price
    broker.simulate_price_update(current - 3.0, current - 3.0, current - 3.0)
    squad = SquadManager(
        broker=broker, broker_mode="paper", initial_balance=10_000.0,
        agents_to_enable=[],
    )
    squad.starting_portfolio_balance = 10_000.0

    squad.run_loop(max_iterations=3, interval_sec=0)

    # Cutoff stayed hit every iteration (realized loss persists); the loop
    # must still have run all 3 iterations instead of breaking after the 1st.
    assert squad.iteration_count == 3
