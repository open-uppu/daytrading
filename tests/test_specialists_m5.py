import pytest
from agents.gold_agent import GoldSpecialistAgent
from agents.btc_agent import BtcSpecialistAgent
from agents.eth_agent import EthSpecialistAgent
from agents.squad_manager import SquadManager
from mt4.paper_broker import PaperTradingBroker
import pandas as pd
import numpy as np

def generate_sample_m5_bars(count=45):
    prices = [2000.0]
    for _ in range(count - 1):
        prices.append(prices[-1] + np.random.uniform(-1, 1))
    return pd.DataFrame({
        "open": prices,
        "high": [p + 1.0 for p in prices],
        "low": [p - 1.0 for p in prices],
        "close": prices,
        "volume": [100] * count
    })

def test_specialists_defaults_m5():
    broker = PaperTradingBroker()
    g = GoldSpecialistAgent(broker=broker, timeframe="M5")
    b = BtcSpecialistAgent(broker=broker, timeframe="M5")
    e = EthSpecialistAgent(broker=broker, timeframe="M5")
    
    assert g.timeframe == "M5"
    assert b.timeframe == "M5"
    assert e.timeframe == "M5"
    assert g.min_sl_dist == 0.8
    assert b.min_sl_dist == 25.0
    assert e.min_sl_dist == 2.0
    assert "M5_Scalper" in g.strategy_name or "Scalp" in g.strategy_name

def test_specialists_evaluate_m5_signal():
    broker = PaperTradingBroker()
    g = GoldSpecialistAgent(broker=broker)
    df = generate_sample_m5_bars()
    sig = g.evaluate_strategy_signal(df)
    assert "action" in sig
    assert sig["action"] in ["BUY", "SELL", "HOLD"]

def test_squad_manager_timeframe_propagation():
    from agents.squad_manager import SPECIALIST_REGISTRY
    forced = {k: tf for k, (_, _, tf) in SPECIALIST_REGISTRY.items() if tf}
    squad = SquadManager(timeframe="M5", broker_mode="paper")
    for key, agent in squad.specialists.items():
        # forced-M15 specialists (xag/gbp/eur/xpt/btc) keep their validated
        # timeframe; everyone else follows the squad's own timeframe
        assert agent.timeframe == forced.get(key, "M5")
