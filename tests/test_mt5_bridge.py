"""
Unit tests for MetaTrader 5 (MT5) Bridge Server and MT5Broker adapter.
"""

import pytest
from fastapi.testclient import TestClient
from mt5.bridge_server import app, MT5BridgeBroker


def test_mt5_bridge_telemetry_and_command_cycle():
    client = TestClient(app)
    
    # 1. Health Status Check
    status_resp = client.get("/api/mt5/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "ONLINE"
    
    # 2. MT5 EA sends Telemetry
    telemetry_payload = {
        "account_number": 416387559,
        "server": "Exness-MT5Trial14",
        "balance": 10000.0,
        "equity": 10250.0,
        "symbol": "XAUUSD",
        "bid": 2650.50,
        "ask": 2650.75,
        "open_positions": [
            {
                "ticket": 555666,
                "symbol": "XAUUSD",
                "type": "BUY",
                "lots": 0.20,
                "open_price": 2645.00,
                "sl": 2640.00,
                "tp": 2655.00,
                "profit": 110.00
            }
        ],
        "closed_orders": [
            {
                "ticket": 555111,
                "pnl_usd": 150.00
            }
        ]
    }
    
    post_resp = client.post("/api/mt5/telemetry", json=telemetry_payload)
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "ACK"
    
    # Verify broker adapter reads updated telemetry
    broker = MT5BridgeBroker()
    acc_info = broker.get_account_info()
    assert acc_info["account_number"] == 416387559
    assert acc_info["server"] == "Exness-MT5Trial14"
    assert acc_info["balance"] == 10000.0
    assert acc_info["equity"] == 10250.0
    assert acc_info["open_positions_count"] == 1
    
    # 3. Python Agent queues an order
    res = broker.open_order(
        symbol="XAUUSD",
        order_type="BUY",
        lots=0.25,
        sl=2642.00,
        tp=2665.00,
        comment="TestMT5_BUY"
    )
    assert res["status"] == "QUEUED"
    cmd_id = res["command_id"]
    
    # 4. MT5 EA polls commands
    poll_resp = client.get("/api/mt5/commands")
    assert poll_resp.status_code == 200
    commands = poll_resp.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["id"] == cmd_id
    assert commands[0]["type"] == "BUY"
    assert commands[0]["volume"] == 0.25
    
    # 5. MT5 EA confirms execution
    confirm_payload = {
        "command_id": cmd_id,
        "status": "SUCCESS",
        "ticket": 777888,
        "retcode": 10009,
        "message": "Executed in MT5"
    }
    confirm_resp = client.post("/api/mt5/confirm", json=confirm_payload)
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "RECORDED"
