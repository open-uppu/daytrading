"""Unit tests for the 6 new M15-only specialist agents (Silver, GBP, EUR, Platinum, UKOIL, Natural Gas)."""
import pytest
import pandas as pd

from backtest.data_loader import ASSET_SPECS
from mt4.paper_broker import PaperTradingBroker


@pytest.fixture
def broker():
    return PaperTradingBroker(initial_balance=10000.0)


def _assert_spec_matches(agent, symbol):
    spec = ASSET_SPECS[symbol]
    assert agent.symbol == symbol
    assert agent.contract_size == spec["contract_size"]
    assert agent.min_lot == spec["min_lot"]
    assert agent.min_sl_dist == spec["min_sl_dist"]
    assert agent.timeframe == "M15"


def test_silver_specialist_agent_spec(broker):
    from agents.xag_agent import SilverSpecialistAgent
    agent = SilverSpecialistAgent(broker=broker)
    _assert_spec_matches(agent, "XAGUSD")
    assert agent.asset_name == "Silver"
    assert agent.strategy_name == "BB_Reversion_C"


def test_gbp_specialist_agent_spec(broker):
    from agents.gbp_agent import GbpSpecialistAgent
    agent = GbpSpecialistAgent(broker=broker)
    _assert_spec_matches(agent, "GBPUSD")
    assert agent.asset_name == "British Pound"
    assert agent.strategy_name == "EMA_Pullback_Rejection_A"


def test_eur_specialist_agent_spec(broker):
    from agents.eur_agent import EurSpecialistAgent
    agent = EurSpecialistAgent(broker=broker)
    _assert_spec_matches(agent, "EURUSD")
    assert agent.asset_name == "Euro"
    assert agent.strategy_name == "MTF_Momentum_Cross_D"


def test_platinum_specialist_agent_spec(broker):
    from agents.xpt_agent import PlatinumSpecialistAgent
    agent = PlatinumSpecialistAgent(broker=broker)
    _assert_spec_matches(agent, "XPTUSD")
    assert agent.asset_name == "Platinum"
    assert agent.strategy_name == "Agentic_Confluence_E"


def test_ukoil_specialist_agent_spec(broker):
    from agents.ukoil_agent import UkoilSpecialistAgent
    agent = UkoilSpecialistAgent(broker=broker)
    _assert_spec_matches(agent, "UKOIL")
    assert agent.asset_name == "Brent Crude Oil"
    assert agent.strategy_name == "BB_Reversion_C"


def test_natural_gas_specialist_agent_spec(broker):
    from agents.xng_agent import NaturalGasSpecialistAgent
    agent = NaturalGasSpecialistAgent(broker=broker)
    _assert_spec_matches(agent, "XNGUSD")
    assert agent.asset_name == "Natural Gas"
    assert agent.strategy_name == "EMA_Pullback_Rejection_A"


AGENT_MODULES = [
    ("agents.xag_agent", "SilverSpecialistAgent"),
    ("agents.gbp_agent", "GbpSpecialistAgent"),
    ("agents.eur_agent", "EurSpecialistAgent"),
    ("agents.xpt_agent", "PlatinumSpecialistAgent"),
    ("agents.ukoil_agent", "UkoilSpecialistAgent"),
    ("agents.xng_agent", "NaturalGasSpecialistAgent"),
]


@pytest.mark.parametrize("module_path,class_name", AGENT_MODULES)
def test_non_m15_timeframe_raises_not_implemented(broker, module_path, class_name):
    """M5 has zero validation for these markets -- must fail loud, not silently HOLD forever."""
    import importlib
    cls = getattr(importlib.import_module(module_path), class_name)
    agent = cls(broker=broker, timeframe="M5")
    df = pd.DataFrame({"close": [1.0] * 40, "high": [1.0] * 40, "low": [1.0] * 40, "open": [1.0] * 40})
    with pytest.raises(NotImplementedError):
        agent.evaluate_strategy_signal(df)


def test_xag_recovery_band_switches_to_agentic_confluence(broker, monkeypatch):
    from agents.xag_agent import SilverSpecialistAgent
    import agents.xag_agent as xag_module
    agent = SilverSpecialistAgent(broker=broker)
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})

    monkeypatch.setattr(xag_module, "strategy_bb_reversion",
                         lambda df, current_idx: {"action": "HOLD", "picked": "normal"})
    monkeypatch.setattr(xag_module, "strategy_agentic_confluence",
                         lambda df, current_idx: {"action": "HOLD", "picked": "recovery"})

    assert agent.evaluate_strategy_signal(df)["picked"] == "normal"
    assert agent.evaluate_strategy_signal(df, risk_band="NORMAL")["picked"] == "normal"
    assert agent.evaluate_strategy_signal(df, risk_band="RECOVERY")["picked"] == "recovery"


@pytest.mark.parametrize("agent_module,agent_class,strategy_attr", [
    ("agents.eur_agent", "EurSpecialistAgent", "strategy_mtf_momentum"),
    ("agents.gbp_agent", "GbpSpecialistAgent", "strategy_ema_pullback"),
    ("agents.xpt_agent", "PlatinumSpecialistAgent", "strategy_agentic_confluence"),
    ("agents.ukoil_agent", "UkoilSpecialistAgent", "strategy_bb_reversion"),
    ("agents.xng_agent", "NaturalGasSpecialistAgent", "strategy_ema_pullback"),
])
def test_five_specialists_recovery_band_is_a_noop(broker, monkeypatch, agent_module, agent_class, strategy_attr):
    """Confirmed no-ops (2026-09-25 M15 backtest data found no alternative
    strategy for these 5 that beats their current live one) -- RECOVERY
    must call the exact same strategy function as NORMAL."""
    import importlib
    mod = importlib.import_module(agent_module)
    cls = getattr(mod, agent_class)
    agent = cls(broker=broker)
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})

    calls = []
    def fake_strategy(df, current_idx):
        calls.append(current_idx)
        return {"action": "HOLD"}
    monkeypatch.setattr(mod, strategy_attr, fake_strategy)

    agent.evaluate_strategy_signal(df, risk_band="NORMAL")
    agent.evaluate_strategy_signal(df, risk_band="RECOVERY")
    assert len(calls) == 2  # both calls went through -- same function, no branch skipped either
