import pytest
from datetime import datetime, timedelta
from agents.gold_agent import GoldSpecialistAgent
from mt4.paper_broker import PaperTradingBroker
from config import config

def test_specialist_concurrency_settings():
    agent = GoldSpecialistAgent(broker=PaperTradingBroker(), timeframe="M5")
    assert agent.timeframe == "M5"
    assert agent.max_open_positions >= 3
    assert agent.min_entry_interval_sec in (300, 600)

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

    # Cooldown check immediately: should be within cooldown
    can_enter, reason = agent._check_entry_cooldown()
    assert not can_enter
    assert "cooldown" in reason.lower()

    # After cadence interval: should be allowed
    agent.last_entry_time = now - timedelta(seconds=agent.min_entry_interval_sec + 5)
    can_enter, reason = agent._check_entry_cooldown()
    assert can_enter


class FailOnceBroker(PaperTradingBroker):
    """Always rejects the order (no ticket, no position) -- mimics an EA
    FAILED confirmation (e.g. AutoTrading disabled)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.open_order_calls = 0

    def open_order(self, **kwargs):
        self.open_order_calls += 1
        raise RuntimeError("[MT5-EXEC] EA rejected: status=FAILED, retcode=10027")


def test_cooldown_blocks_retry_after_failed_order_dispatch(monkeypatch, tmp_path):
    """A FAILED order dispatch leaves no open position; the entry cooldown
    must still throttle the next attempt instead of retrying every loop tick."""
    broker = FailOnceBroker(initial_balance=10000.0, symbol="XAUUSD")
    agent = GoldSpecialistAgent(broker=broker, timeframe="M5", journal_dir=tmp_path)
    monkeypatch.setattr(config, "timeframe_htf", None)
    monkeypatch.setattr(config, "ml_filter_enabled", False)
    monkeypatch.setattr(agent.pre_trade_filter, "evaluate_proposal", lambda **kw: (True, "test bypass"))
    agent.evaluate_strategy_signal = lambda df: {
        "action": "BUY",
        "sl": round(float(df.iloc[-1]["close"]) - 10, 2),
        "tp": round(float(df.iloc[-1]["close"]) + 20, 2),
        "reason": "forced test signal",
    }

    first = agent.step()
    assert first["status"] == "BROKER_ERROR"
    assert agent.last_entry_time is not None
    assert broker.open_order_calls == 1

    second = agent.step()
    assert second["status"] == "COOLDOWN"
    assert broker.open_order_calls == 1  # not retried immediately


def test_cadence_pacer_uses_the_same_075_ml_threshold_as_real_signals(monkeypatch):
    """Cadence-pacer forced entries must be held to the SAME ML confidence
    bar as real strategy signals (0.75) -- a weaker bar let low-quality
    forced entries through and dragged live win-rate to ~38-41% (confirmed
    via a real-data cadence-pacer backtest: baseline WR sits at/below the
    ~40% breakeven needed at the pacer's 1:1.5 R:R)."""
    broker = PaperTradingBroker(initial_balance=10000.0)
    agent = GoldSpecialistAgent(broker=broker, timeframe="M5")
    agent.last_entry_time = datetime.now() - timedelta(seconds=agent.min_entry_interval_sec + 5)
    agent.evaluate_strategy_signal = lambda df: {"action": "HOLD"}
    monkeypatch.setattr(agent.pre_trade_filter, "evaluate_proposal", lambda **kw: (True, "test bypass"))

    captured = {}

    def fake_evaluate(signal, df_window, asset_symbol, custom_threshold):
        captured["threshold"] = custom_threshold
        captured["signal_type"] = signal.get("signal_type")
        return (True, 0.9, {"reason": "test-pass"})

    monkeypatch.setattr(agent.ml_filter, "evaluate_proposal", fake_evaluate)

    agent.step()

    assert captured.get("signal_type") == "CADENCE_PACER"
    assert captured.get("threshold") == 0.75
