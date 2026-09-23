"""
Unit tests for PaperTradingBroker and MT4 Bridge Server.
"""

import pytest
from fastapi.testclient import TestClient
from mt4.paper_broker import PaperTradingBroker
from mt4.bridge_server import app, MT4BridgeBroker


def test_paper_broker_order_lifecycle():
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="XAUUSD")
    
    # 1. Check Initial State
    info = broker.get_account_info()
    assert info["balance"] == 10000.0
    assert info["equity"] == 10000.0
    assert info["open_positions_count"] == 0
    
    # 2. Open BUY Order
    entry_price = broker.current_price
    sl = entry_price - 5.0
    tp = entry_price + 10.0
    lots = 0.20
    
    res = broker.open_order(
        symbol="XAUUSD",
        order_type="BUY",
        lots=lots,
        sl=sl,
        tp=tp,
        comment="TestTrade"
    )
    
    assert res["status"] == "SUCCESS"
    ticket = res["ticket"]
    assert len(broker.get_open_positions()) == 1
    
    # 3. Simulate Price Movement hitting TP
    # New high moves above TP
    broker.simulate_price_update(new_high=tp + 1.0, new_low=entry_price, new_close=tp)
    
    # Position should be closed
    assert len(broker.get_open_positions()) == 0
    closed = broker.consume_recently_closed()
    assert len(closed) == 1
    assert closed[0]["ticket"] == ticket
    assert closed[0]["exit_reason"] == "TP_HIT"
    assert closed[0]["pnl_usd"] > 0
    assert broker.balance > 10000.0  # Profit credited


def test_paper_broker_filters_recently_closed_by_magic():
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="XAUUSD")

    entry = broker.current_price
    res_a = broker.open_order(symbol="XAUUSD", order_type="BUY", lots=0.1,
                               sl=entry - 5.0, tp=entry + 10.0, magic=888999)
    res_b = broker.open_order(symbol="XAUUSD", order_type="BUY", lots=0.1,
                               sl=entry - 5.0, tp=entry + 10.0, magic=888915)

    # Close both by pushing price through both take-profits.
    broker.simulate_price_update(new_high=entry + 11.0, new_low=entry, new_close=entry + 10.5)
    assert len(broker.get_open_positions()) == 0

    only_a = broker.consume_recently_closed(symbol="XAUUSD", magic=888999)
    assert [o["ticket"] for o in only_a] == [res_a["ticket"]]

    only_b = broker.consume_recently_closed(symbol="XAUUSD", magic=888915)
    assert [o["ticket"] for o in only_b] == [res_b["ticket"]]


def test_mt4_bridge_api():
    client = TestClient(app)
    
    # 1. Telemetry Post
    telemetry_data = {
        "account_number": 888123,
        "balance": 15000.0,
        "equity": 15200.0,
        "symbol": "XAUUSD",
        "bid": 2655.0,
        "ask": 2655.25,
        "open_positions": [],
        "closed_orders": []
    }
    resp = client.post("/api/mt4/telemetry", json=telemetry_data)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACK"
    
    # 2. Broker adapter queues command (in_process: the TestClient app runs in
    #    this same process, so the module-level queue is reachable)
    broker = MT4BridgeBroker(in_process=True)
    queue_res = broker.open_order(
        symbol="XAUUSD",
        order_type="BUY",
        lots=0.3,
        sl=2645.0,
        tp=2670.0,
        comment="AgenticTest",
        await_confirm=False
    )
    assert queue_res["status"] == "QUEUED"
    
    # 3. MT4 polls commands
    poll_resp = client.get("/api/mt4/commands")
    assert poll_resp.status_code == 200
    commands = poll_resp.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["type"] == "BUY"
    assert commands[0]["volume"] == 0.3
