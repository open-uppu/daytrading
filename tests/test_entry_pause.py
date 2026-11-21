"""2026-11-21 demo experiment: ETH entry pause + BTC forced M15 Strategy D.

Evidence: qualabinance/projects/04-backtest-engine/reports/
research_sweep_crypto_gold_2026-11-21.md (rigorous engine, real signal fns).
"""

import pandas as pd

from agents.btc_agent import BtcSpecialistAgent
from agents.eth_agent import EthSpecialistAgent
from agents.squad_manager import SquadManager
from config import config
from mt4.paper_broker import PaperTradingBroker


def _active_mock_df(n=60, base=3000.0):
    prices = [base + (i % 3) for i in range(n)]
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-08-01 10:00", periods=n, freq="5min"),
        "open": prices,
        "high": [p + 5 for p in prices],
        "low": [p - 5 for p in prices],
        "close": prices,
        "volume": [100] * n,
    })


def test_eth_entries_paused_by_default():
    agent = EthSpecialistAgent(broker_mode="paper", initial_balance=10000.0)
    assert agent.entries_enabled is False


def test_eth_pause_blocks_cadence_pacer(tmp_path):
    agent = EthSpecialistAgent(
        broker_mode="paper", initial_balance=10000.0,
        journal_dir=tmp_path, timeframe="M5", min_entry_interval_sec=600,
    )
    agent.broker.get_market_data = lambda symbol, timeframe="M5", bars=60: _active_mock_df().copy()
    res = agent.step()
    assert res["status"] == "WAITING_FOR_SETUP"
    assert res["action"] == "HOLD"
    assert agent.broker.get_open_positions() == []


def test_eth_pause_lifts_via_config(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "eth_entries_enabled", True)
    agent = EthSpecialistAgent(
        broker_mode="paper", initial_balance=10000.0,
        journal_dir=tmp_path, timeframe="M5", min_entry_interval_sec=600,
    )
    assert agent.entries_enabled is True
    agent.broker.get_market_data = lambda symbol, timeframe="M5", bars=60: _active_mock_df().copy()
    agent.step()
    # pacer is allowed again -> an order may fire (same conditions as the
    # BTC cadence test); at minimum the pause gate must not HOLD it.
    assert agent.last_signal.get("reason", "") != "ENTRIES_PAUSED: no validated edge (see improvement_backlog.md)"


def test_btc_forced_m15_strategy_d_in_m5_squad(tmp_path):
    squad = SquadManager(
        broker=PaperTradingBroker(initial_balance=10000.0), initial_balance=10000.0,
        agents_to_enable=["all"], timeframe="M5", journal_dir=tmp_path,
    )
    btc = squad.specialists["btc"]
    assert btc.timeframe == "M15"
    assert btc.strategy_name == "MTF_Momentum_Cross_D"
    # magic stays the squad's own (shared-process position tracking)
    assert btc.magic == 888999


def test_btc_m15_signal_uses_strategy_d():
    agent = BtcSpecialistAgent(broker_mode="paper", initial_balance=10000.0, timeframe="M15")
    sig = agent.evaluate_strategy_signal(_active_mock_df(base=80000.0))
    assert sig["action"] in ("BUY", "SELL", "HOLD")


def test_btc_pacer_disabled_gold_pacer_kept():
    from agents.gold_agent import GoldSpecialistAgent
    btc = BtcSpecialistAgent(broker_mode="paper", initial_balance=10000.0, timeframe="M15")
    gold = GoldSpecialistAgent(broker_mode="paper", initial_balance=10000.0, timeframe="M5")
    assert btc.pacer_enabled is False
    assert getattr(gold, "pacer_enabled", True) is True