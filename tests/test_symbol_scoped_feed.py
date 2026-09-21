"""Regressions: gold logged BTC/ETH closes as its own, and a frozen (closed-market) feed looked live."""

import pytest
from fastapi.testclient import TestClient

import mt5.bridge_server as bridge_server
from mt4.paper_broker import PaperTradingBroker
from mt5.bridge_server import app, MT5BridgeBroker


def _telemetry(closed):
    return {
        "account_number": 1, "server": "s", "balance": 500.0, "equity": 500.0,
        "symbol": "XAUUSD", "bid": 1.0, "ask": 1.1, "open_positions": [], "closed_orders": closed,
    }


def test_consume_recently_closed_only_pops_requested_symbol():
    client = TestClient(app)
    bridge_server._mt5_state["closed_orders"].clear()
    bridge_server._mt5_state["recently_closed"].clear()
    client.post("/api/mt5/telemetry", json=_telemetry([
        {"ticket": 1, "symbol": "BTCUSD", "profit": 1.0},
        {"ticket": 2, "symbol": "XAUUSD", "profit": 2.0},
        {"ticket": 3, "symbol": "ETHUSD", "profit": 3.0},
    ]))
    broker = MT5BridgeBroker(in_process=True)

    assert [t["ticket"] for t in broker.consume_recently_closed(symbol="XAUUSD")] == [2]
    assert sorted(t["ticket"] for t in broker.consume_recently_closed(symbol="BTCUSD")) == [1]
    assert [t["ticket"] for t in broker.consume_recently_closed(symbol="ETHUSD")] == [3]
    assert broker.consume_recently_closed() == []


def test_paper_consume_recently_closed_only_pops_requested_symbol():
    broker = PaperTradingBroker()
    broker.recently_closed_orders.extend([
        {"ticket": 1, "symbol": "BTCUSD"}, {"ticket": 2, "symbol": "XAUUSD"},
    ])
    assert [t["ticket"] for t in broker.consume_recently_closed(symbol="XAUUSD")] == [2]
    assert [t["ticket"] for t in broker.consume_recently_closed()] == [1]


def test_frozen_feed_is_stale_even_though_ea_keeps_reuploading_it():
    """Market closed: EA re-posts identical bars every second. Upload time must not count as fresh."""
    client = TestClient(app)
    bridge_server._cached_bars.clear()
    bars = [{"timestamp": i, "open": 1, "high": 2, "low": 0, "close": 1, "volume": 5} for i in range(60)]
    payload = {"symbol": "XAUUSD", "timeframe": "M5", "bars": bars}
    client.post("/api/mt5/bars", json=payload)
    bridge_server._cached_bars["XAUUSD:M5"]["changed_at"] -= 120  # feed last moved 2 min ago
    client.post("/api/mt5/bars", json=payload)  # identical re-upload

    broker = MT5BridgeBroker(in_process=True)
    with pytest.raises(bridge_server.MarketDataStale):
        broker.get_market_data("XAUUSD", "M5")

    bars[-1] = {**bars[-1], "close": 1.5, "volume": 6}  # a live tick arrives
    client.post("/api/mt5/bars", json={**payload, "bars": bars})
    assert len(broker.get_market_data("XAUUSD", "M5", bars=10)) == 10


def test_gold_step_on_frozen_feed_returns_market_closed_and_sends_no_order(tmp_path):
    from agents.gold_agent import GoldSpecialistAgent

    client = TestClient(app)
    bridge_server._cached_bars.clear()
    bridge_server._pending_commands.clear()
    client.post("/api/mt5/telemetry", json=_telemetry([]))
    agent = GoldSpecialistAgent(
        broker=MT5BridgeBroker(in_process=True), broker_mode="mt5",
        initial_balance=500.0, journal_dir=tmp_path / "xauusd",
    )
    bars = [{"timestamp": i, "open": 1, "high": 2, "low": 0, "close": 1, "volume": 5} for i in range(60)]
    client.post("/api/mt5/bars", json={"symbol": "XAUUSD", "timeframe": agent.timeframe, "bars": bars})
    bridge_server._cached_bars[f"XAUUSD:{agent.timeframe}"]["changed_at"] -= 120
    assert agent.step()["status"] == "MARKET_CLOSED"
    assert bridge_server._pending_commands == []
