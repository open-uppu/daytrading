"""
Unit and Integration Tests for Multi-Asset Specialist Squad Architecture.
Tests GoldSpecialistAgent, BtcSpecialistAgent, EthSpecialistAgent, and SquadManager portfolio coordination.
"""

import json
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


def test_config_fixed_principal_and_risk_band_thresholds():
    assert config.fixed_principal_usd == 300.0
    assert config.daily_recovery_loss_pct == 0.03
    assert config.daily_max_loss_pct == 0.05


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


def test_squad_manager_assigns_per_timeframe_magic_and_journal_dir(tmp_path):
    """Every timeframe-instance must get its own MT5 magic number and journal
    directory so concurrent same-symbol instances never share state or
    silently steal each other's positions. M5 must keep the exact magic the
    live account's open positions already use."""
    from agents.squad_manager import TIMEFRAME_MAGIC
    broker = PaperTradingBroker(initial_balance=10000.0)

    squad_m5 = SquadManager(broker=broker, initial_balance=10000.0,
                             agents_to_enable=["gold"], timeframe="M5",
                             journal_dir=tmp_path / "m5")
    assert squad_m5.specialists["gold"].magic == 888999
    assert squad_m5.specialists["gold"].journal_dir == tmp_path / "m5" / "xauusd"

    squad_m15 = SquadManager(broker=broker, initial_balance=10000.0,
                              agents_to_enable=["gold"], timeframe="M15",
                              journal_dir=tmp_path / "m15")
    assert squad_m15.specialists["gold"].magic == TIMEFRAME_MAGIC["M15"]
    assert squad_m15.specialists["gold"].magic != 888999
    assert squad_m15.specialists["gold"].journal_dir == tmp_path / "m15" / "xauusd"


def test_squad_manager_writes_read_only_specialist_runtime_snapshot(tmp_path):
    squad = SquadManager(
        broker=PaperTradingBroker(), agents_to_enable=["gold"], timeframe="M5", journal_dir=tmp_path,
    )
    squad.specialists["gold"].last_ml_confidence = 0.87
    squad._publish_specialist_runtime({
        "gold": {"status": "WAITING_FOR_SETUP", "signal": {"action": "HOLD"}},
    })

    runtime_file = tmp_path / "specialist_runtime" / "m5.json"
    payload = json.loads(runtime_file.read_text(encoding="utf-8"))
    gold = payload["specialists"]["gold"]
    assert gold["symbol"] == "XAUUSD"
    assert gold["timeframe"] == "M5"
    assert gold["status"] == "WAITING_FOR_SETUP"
    assert gold["action"] == "HOLD"
    assert gold["confidence"] == 0.87


def test_squad_manager_shares_one_magic_across_all_specialists(tmp_path):
    """Every specialist in a SquadManager process shares ONE magic number,
    keyed by the squad's OWN timeframe -- exactly like they already share
    one journal_dir root. xag/gbp/eur/xpt are forced to trade M15 strategy
    logic regardless of the squad's own timeframe (see SPECIALIST_REGISTRY),
    but that only changes their `.timeframe` (which strategy logic runs),
    never their `.magic` (which identifies positions for this process)."""
    from agents.squad_manager import TIMEFRAME_MAGIC
    broker = PaperTradingBroker(initial_balance=10000.0)

    # A squad started at the M5 default: xag is forced to M15 strategy logic
    # internally, but must still share the squad's own M5 magic with gold.
    squad_m5 = SquadManager(broker=broker, initial_balance=10000.0,
                             agents_to_enable=["all"], timeframe="M5",
                             journal_dir=tmp_path)
    assert squad_m5.specialists["gold"].magic == 888999
    assert squad_m5.specialists["xag"].magic == 888999
    assert squad_m5.specialists["xag"].timeframe == "M15"  # strategy logic unaffected

    # A dedicated M15 squad: ALL specialists (forced or not) share the M15
    # magic uniformly.
    broker2 = PaperTradingBroker(initial_balance=10000.0)
    squad_m15 = SquadManager(broker=broker2, initial_balance=10000.0,
                              agents_to_enable=["all"], timeframe="M15",
                              journal_dir=tmp_path)
    assert squad_m15.specialists["gold"].magic == TIMEFRAME_MAGIC["M15"]
    assert squad_m15.specialists["xag"].magic == TIMEFRAME_MAGIC["M15"]


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
        fixed_principal_usd=10000.0,
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
    squad = SquadManager(broker=broker, initial_balance=10000.0, fixed_principal_usd=10000.0, journal_dir=tmp_path)

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
    squad = SquadManager(broker=broker, initial_balance=10000.0, fixed_principal_usd=10000.0, journal_dir=tmp_path)

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
            return {"balance": 500.0, "equity": 480.0}  # -6.67% equity against the fixed $300 principal, past the 5% max loss cutoff

    squad = SquadManager(
        broker=LiveBroker(initial_balance=10_000.0),
        broker_mode="mt5",
        initial_balance=10_000.0,
        agents_to_enable=[],
    )

    status = squad.get_portfolio_daily_pnl()
    assert status["starting_balance"] == 500.0
    assert status["target_profit_usd"] == 9.0
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
    squad.fixed_principal_usd = 5_000.0
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
    squad.fixed_principal_usd = 5_000.0

    squad.run_loop(max_iterations=3, interval_sec=0)

    # Cutoff stayed hit every iteration (realized loss persists); the loop
    # must still have run all 3 iterations instead of breaking after the 1st.
    assert squad.iteration_count == 3


def test_symbol_positions_filtered_by_own_magic(tmp_path):
    """Two timeframe-instances of the same symbol share one broker/account in
    live MT5 mode. An instance must only see and manage its own positions --
    not another instance's, even though both trade the same symbol."""
    broker = PaperTradingBroker(initial_balance=10000.0)
    agent_m5 = GoldSpecialistAgent(broker=broker, timeframe="M5",
                                    journal_dir=tmp_path / "m5", magic=888999)
    agent_m15 = GoldSpecialistAgent(broker=broker, timeframe="M15",
                                     journal_dir=tmp_path / "m15", magic=888915)

    entry = broker.current_price
    res_m5 = broker.open_order(symbol="XAUUSD", order_type="BUY", lots=0.1,
                                sl=entry - 5.0, tp=entry + 50.0, magic=888999)
    res_m15 = broker.open_order(symbol="XAUUSD", order_type="BUY", lots=0.1,
                                 sl=entry - 5.0, tp=entry + 50.0, magic=888915)

    result_m5 = agent_m5.step(allow_new_entry=False)
    result_m15 = agent_m15.step(allow_new_entry=False)

    assert result_m5["position"]["ticket"] == res_m5["ticket"]
    assert result_m15["position"]["ticket"] == res_m15["ticket"]


def test_fixed_principal_usd_denominator_overridable(tmp_path):
    """Percentages must compute against fixed_principal_usd, not
    starting_portfolio_balance, even when the two differ (e.g. account
    already grew from a prior day's profit)."""
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(
        broker=broker, broker_mode="mt5", initial_balance=10000.0,
        fixed_principal_usd=300.0, journal_dir=tmp_path,
    )
    # Simulate a prior day's profit already baked into starting_portfolio_balance,
    # decoupled from fixed_principal_usd.
    squad.starting_portfolio_balance = 309.0
    broker.balance = 315.0
    broker.equity = 315.0

    p_stat = squad.get_portfolio_daily_pnl()
    # Numerator: today's real dollar move (315 - 309 = 6), unaffected by this change.
    assert p_stat["realized_pnl_usd"] == pytest.approx(6.0)
    # Denominator: fixed_principal_usd (300), NOT starting_portfolio_balance (309).
    assert p_stat["daily_return_pct"] == pytest.approx(2.0)  # 6 / 300 * 100


def test_recovery_reached_only_in_band(tmp_path):
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(
        broker=broker, initial_balance=10000.0,
        fixed_principal_usd=300.0, journal_dir=tmp_path,
    )
    squad.starting_portfolio_balance = 300.0

    # -2%: above recovery threshold (-3%) -- neither band active.
    broker.balance = 294.0
    broker.equity = 294.0
    p_stat = squad.get_portfolio_daily_pnl()
    assert p_stat["recovery_reached"] is False
    assert p_stat["max_loss_reached"] is False

    # -4%: inside (-5%, -3%] recovery band.
    broker.balance = 288.0
    broker.equity = 288.0
    p_stat = squad.get_portfolio_daily_pnl()
    assert p_stat["recovery_reached"] is True
    assert p_stat["max_loss_reached"] is False

    # -6%: past the hard -5% cutoff -- recovery_reached also stays True but
    # max_loss_reached governs (squad halts entirely, see step()).
    broker.balance = 282.0
    broker.equity = 282.0
    p_stat = squad.get_portfolio_daily_pnl()
    assert p_stat["max_loss_reached"] is True


def test_step_passes_recovery_risk_band_to_specialists(tmp_path, monkeypatch):
    broker = PaperTradingBroker(initial_balance=10000.0)
    squad = SquadManager(
        broker=broker, initial_balance=10000.0,
        fixed_principal_usd=300.0, agents_to_enable=["xag"], journal_dir=tmp_path,
    )
    squad.starting_portfolio_balance = 300.0
    broker.balance = 288.0  # -4%: inside recovery band
    broker.equity = 288.0

    seen_risk_bands = []
    original_step = squad.specialists["xag"].step
    def spy_step(*args, **kwargs):
        seen_risk_bands.append(kwargs.get("risk_band"))
        return original_step(*args, **kwargs)
    monkeypatch.setattr(squad.specialists["xag"], "step", spy_step)

    squad.step()
    assert seen_risk_bands == ["RECOVERY"]


def test_base_agent_step_threads_risk_band_to_evaluate_strategy_signal(temp_journal_dir, monkeypatch):
    broker = PaperTradingBroker(initial_balance=10000.0)
    agent = GoldSpecialistAgent(broker=broker, journal_dir=temp_journal_dir / "xauusd", timeframe="M15")

    seen = []
    def fake_evaluate(df, risk_band="NORMAL"):
        seen.append(risk_band)
        return {"action": "HOLD"}
    monkeypatch.setattr(agent, "evaluate_strategy_signal", fake_evaluate)

    n = 60
    mock_df = pd.DataFrame({
        "timestamp": pd.date_range("2026-08-01 10:00", periods=n, freq="15min"),
        "open": [2000.0] * n, "high": [2001.0] * n, "low": [1999.0] * n,
        "close": [2000.0] * n, "volume": [100] * n,
    })
    agent.broker.get_market_data = lambda symbol, timeframe="M15", bars=60: mock_df.copy()

    agent.step(risk_band="RECOVERY")
    assert seen == ["RECOVERY"]

    agent.step()  # default
    assert seen == ["RECOVERY", "NORMAL"]


def test_gold_btc_eth_ignore_risk_band_stay_on_m5_scalper(temp_journal_dir):
    broker = PaperTradingBroker(initial_balance=10000.0)
    agent = GoldSpecialistAgent(broker=broker, journal_dir=temp_journal_dir / "xauusd", timeframe="M5")
    n = 60
    mock_df = pd.DataFrame({
        "timestamp": pd.date_range("2026-08-01 10:00", periods=n, freq="5min"),
        "open": [2000.0] * n, "high": [2001.0] * n, "low": [1999.0] * n,
        "close": [2000.0 + i * 0.1 for i in range(n)], "volume": [100] * n,
    })
    sig_normal = agent.evaluate_strategy_signal(mock_df, risk_band="NORMAL")
    sig_recovery = agent.evaluate_strategy_signal(mock_df, risk_band="RECOVERY")
    # Same strategy fn (strategy_m5_scalper) is deterministic on identical
    # input regardless of risk_band -- both calls must agree on action.
    assert sig_normal["action"] == sig_recovery["action"]
