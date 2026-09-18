"""
Unit tests for MetaTrader 5 (MT5) Bridge Server and MT5Broker adapter.
"""

import json

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
    
    # Verify broker adapter reads updated telemetry.
    # in_process=True: the TestClient app runs in THIS process, so the broker
    # must read module state rather than dial a REST server that isn't running.
    broker = MT5BridgeBroker(in_process=True)
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
        comment="TestMT5_BUY",
        await_confirm=False
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


def test_open_order_raises_when_bridge_unreachable():
    """
    Regression guard for the silent-failure bug.

    open_order() used to wrap its HTTP call in `except Exception: pass`, append
    the command to a module-level list and return "QUEUED". A missing `import
    httpx` therefore produced a phantom success: the agent reported ORDER_PLACED
    while the command never left the process and the EA never saw it.

    Pointing the broker at a dead port must raise, not pretend.
    """
    broker = MT5BridgeBroker(host="127.0.0.1", port=9, in_process=False)

    with pytest.raises(RuntimeError) as exc_info:
        broker.open_order(
            symbol="XAUUSD",
            order_type="BUY",
            lots=0.10,
            sl=2640.0,
            tp=2660.0,
            comment="ShouldFail",
        )

    message = str(exc_info.value)
    assert "Cannot reach MT5 bridge" in message
    assert "was NOT queued" in message


def test_open_order_reports_unconfirmed_when_ea_silent():
    """
    A reachable bridge with no EA polling must yield confirmed=False, never a
    silent claim that the trade is live.
    """
    client = TestClient(app)
    broker = MT5BridgeBroker(in_process=True)

    res = broker.open_order(
        symbol="BTCUSD",
        order_type="BUY",
        lots=0.01,
        sl=80000.0,
        tp=82500.0,
        comment="NoEaAttached",
        await_confirm=True,
        confirm_timeout=0.1,  # no confirmation will ever arrive
    )

    assert res["confirmed"] is False
    assert res["status"] == "QUEUED"


def test_execution_results_endpoint_roundtrip():
    """The confirm -> execution_results path the broker polls must work."""
    client = TestClient(app)

    confirm_payload = {
        "command_id": "cmd_roundtrip_test",
        "status": "SUCCESS",
        "ticket": 424242,
        "message": "Executed in MT5",
    }
    assert client.post("/api/mt5/confirm", json=confirm_payload).status_code == 200

    resp = client.get("/api/mt5/execution_results", params={"command_id": "cmd_roundtrip_test"})
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["status"] == "SUCCESS"
    assert result["ticket"] == 424242

    # An unknown id must return null rather than inventing a status.
    missing = client.get("/api/mt5/execution_results", params={"command_id": "nope"})
    assert missing.status_code == 200
    assert missing.json()["result"] is None


def test_telemetry_accepts_mql5_trailing_null_terminator():
    """MQL5 StringToCharArray appends NUL unless an explicit size is supplied."""
    client = TestClient(app)
    telemetry = {
        "account_number": 416387559,
        "server": "Exness-MT5Trial14",
        "balance": 499.94,
        "equity": 499.94,
        "symbol": "BTCUSD",
        "bid": 80945.90,
        "ask": 80952.90,
        "open_positions": [],
        "closed_orders": [],
    }

    response = client.post(
        "/api/mt5/telemetry",
        content=(json.dumps(telemetry) + "\x00").encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ACK"


def test_command_ids_are_unique_across_brokers_and_command_types():
    """Confirmations must never be shared by independently-created brokers."""
    first = MT5BridgeBroker(in_process=True)
    second = MT5BridgeBroker(in_process=True)

    open_result = first.open_order(
        symbol="BTCUSD", order_type="BUY", lots=0.01, sl=80000.0, tp=82500.0,
        await_confirm=False,
    )
    close_result = second.close_order(123456, await_confirm=False)
    modify_result = first.modify_order(123456, sl=80100.0, tp=82400.0, await_confirm=False)

    command_ids = {
        open_result["command_id"],
        close_result["command_id"],
        modify_result["command_id"],
    }
    assert len(command_ids) == 3
