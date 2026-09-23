"""
Unit tests for MetaTrader 5 (MT5) Bridge Server and MT5Broker adapter.
"""

import json
import threading
import time
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import mt5.bridge_server as bridge_server
from mt5.bridge_server import app, MT5BridgeBroker
from agents.gold_agent import GoldSpecialistAgent


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


def test_confirm_retcode_roundtrips_on_failure():
    """EA-reported retcode on a FAILED confirm must survive to execution_results
    (e.g. 10027 = AutoTrading disabled), so it's visible instead of always None."""
    client = TestClient(app)

    confirm_payload = {
        "command_id": "cmd_retcode_test",
        "status": "FAILED",
        "ticket": 0,
        "retcode": 10027,
        "message": "Retcode: 10027",
    }
    assert client.post("/api/mt5/confirm", json=confirm_payload).status_code == 200

    resp = client.get("/api/mt5/execution_results", params={"command_id": "cmd_retcode_test"})
    assert resp.status_code == 200
    assert resp.json()["result"]["retcode"] == 10027


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


def test_command_polling_is_fifo_and_never_discards_a_batch():
    """Older EAs execute one envelope; later queued commands must remain queued."""
    client = TestClient(app)
    # Earlier test cases intentionally leave an unconfirmed command behind.
    # Drain that in-process fixture state so this test asserts only its batch.
    while client.get("/api/mt5/commands").json()["commands"]:
        pass
    first = {
        "id": "fifo-first", "action": "ORDER_OPEN", "symbol": "BTCUSD",
        "type": "BUY", "volume": 0.01, "sl": 80000.0, "tp": 82500.0,
    }
    second = {
        "id": "fifo-second", "action": "ORDER_OPEN", "symbol": "BTCUSD",
        "type": "SELL", "volume": 0.01, "sl": 82500.0, "tp": 80000.0,
    }
    assert client.post("/api/mt5/queue_command", json=first).status_code == 200
    assert client.post("/api/mt5/queue_command", json=second).status_code == 200

    assert client.get("/api/mt5/commands").json()["commands"] == [first]
    assert client.get("/api/mt5/commands").json()["commands"] == [second]
    assert client.get("/api/mt5/commands").json()["commands"] == []


def test_queue_rejects_unprotected_or_malformed_open_order():
    client = TestClient(app)
    response = client.post(
        "/api/mt5/queue_command",
        json={
            "id": "invalid-open", "action": "ORDER_OPEN", "symbol": "BTCUSD",
            "type": "BUY", "volume": 0.01, "sl": 0.0, "tp": 82500.0,
        },
    )
    assert response.status_code == 422
    assert "sl must be a positive number" in response.json()["detail"]


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


def test_live_market_data_is_symbol_scoped_and_fails_closed_without_bars():
    """A live agent must never silently trade a backtest CSV or another symbol's bars."""
    client = TestClient(app)
    bridge_server._cached_bars.clear()
    broker = MT5BridgeBroker(in_process=True)

    with pytest.raises(RuntimeError, match="historical fallback"):
        broker.get_market_data("XAUUSD", "M15", bars=60)

    bars = [{"timestamp": i, "open": 100 + i, "high": 101 + i,
             "low": 99 + i, "close": 100.5 + i, "volume": 10} for i in range(60)]
    response = client.post("/api/mt5/bars", json={
        "symbol": "XAUUSD", "timeframe": "M15", "bars": bars,
    })
    assert response.status_code == 200
    assert len(broker.get_market_data("XAUUSD", "M15", bars=20)) == 20
    with pytest.raises(RuntimeError, match="historical fallback"):
        broker.get_market_data("BTCUSD", "M15", bars=20)


def test_live_market_data_rejects_stale_bars():
    bridge_server._cached_bars["XAUUSD:M15"] = {
        "bars": [{"open": 1, "high": 2, "low": 0, "close": 1, "volume": 1}],
        "received_at": bridge_server.monotonic_wall_time() - 91,
    }
    broker = MT5BridgeBroker(in_process=True)
    with pytest.raises(RuntimeError, match="stale"):
        broker.get_market_data("XAUUSD", "M15")


def test_single_specialist_smoke_cycle_reaches_ea_confirmation():
    """One supervised live-style cycle must finish only after EA confirmation."""
    client = TestClient(app)
    bridge_server._pending_commands.clear()
    bridge_server._execution_results.clear()
    bridge_server._cached_bars.clear()
    client.post("/api/mt5/telemetry", json={
        "account_number": 416387559, "server": "Exness-MT5Trial14",
        "balance": 10000.0, "equity": 10000.0, "symbol": "XAUUSD",
        "bid": 2650.0, "ask": 2650.25, "open_positions": [], "closed_orders": [],
    })
    bars = [{"timestamp": i, "open": 2650.0, "high": 2651.0,
             "low": 2649.0, "close": 2650.0, "volume": 100} for i in range(60)]
    assert client.post("/api/mt5/bars", json={
        "symbol": "XAUUSD", "timeframe": "M15", "bars": bars,
    }).status_code == 200

    broker = MT5BridgeBroker(in_process=True)
    with tempfile.TemporaryDirectory() as tmp:
        agent = GoldSpecialistAgent(
            broker=broker, broker_mode="mt5", initial_balance=10000.0,
            journal_dir=Path(tmp) / "xauusd",
        )
        agent.evaluate_strategy_signal = lambda _df: {
            "action": "BUY", "sl": 2648.0, "tp": 2654.0,
            "reason": "smoke-test",
        }
        agent.pre_trade_filter.evaluate_proposal = lambda **_kwargs: (True, "")
        agent.ml_filter.evaluate_proposal = lambda **_kwargs: (True, 0.85, {"reason": "smoke-pass"})

        def simulated_ea():
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                commands = client.get("/api/mt5/commands").json()["commands"]
                if commands:
                    command = commands[0]
                    client.post("/api/mt5/confirm", json={
                        "command_id": command["id"], "status": "SUCCESS",
                        "ticket": 900001, "retcode": 10009, "message": "smoke fill",
                    })
                    return
                time.sleep(0.01)

        ea_thread = threading.Thread(target=simulated_ea)
        ea_thread.start()
        result = agent.step()
        ea_thread.join(timeout=3.0)

    assert result["status"] == "ORDER_PLACED"
    assert result["order"]["confirmed"] is True
    assert result["order"]["ticket"] == 900001


def test_pop_recently_closed_scopes_by_magic_not_just_symbol():
    """Regression guard: two same-symbol timeframe-instances must not steal
    each other's closed-trade records out of the shared queue."""
    bridge_server._mt5_state["recently_closed"] = [
        {"ticket": 1, "symbol": "XAUUSD", "magic": 888999, "pnl_usd": 12.5},
        {"ticket": 2, "symbol": "XAUUSD", "magic": 888915, "pnl_usd": -3.0},
    ]

    only_m5 = bridge_server._pop_recently_closed("XAUUSD", 888999)
    assert [o["ticket"] for o in only_m5] == [1]

    # The M15 instance's record must still be in the queue -- not stolen.
    remaining = bridge_server._mt5_state["recently_closed"]
    assert [o["ticket"] for o in remaining] == [2]

    only_m15 = bridge_server._pop_recently_closed("XAUUSD", 888915)
    assert [o["ticket"] for o in only_m15] == [2]
    assert bridge_server._mt5_state["recently_closed"] == []


def test_pop_recently_closed_without_magic_still_pops_whole_symbol():
    """Backward compatibility: a caller that never opts into per-instance
    magic (e.g. the current production M5 path before it's updated) must
    keep seeing every closed record for its symbol, exactly like today."""
    bridge_server._mt5_state["recently_closed"] = [
        {"ticket": 1, "symbol": "XAUUSD", "magic": 888999},
        {"ticket": 2, "symbol": "XAUUSD", "magic": 888915},
        {"ticket": 3, "symbol": "BTCUSD", "magic": 888999},
    ]
    taken = bridge_server._pop_recently_closed("XAUUSD")
    assert sorted(o["ticket"] for o in taken) == [1, 2]
    assert [o["ticket"] for o in bridge_server._mt5_state["recently_closed"]] == [3]


def test_get_open_positions_in_process_reads_state_directly_never_network(monkeypatch):
    """
    Regression guard: unlike every other method on this class,
    get_open_positions() used to skip the `if not self.in_process` guard and
    always attempt `httpx.get(...)` first. On a machine with a real MT5
    bridge server also running, an `in_process=True` test broker silently
    leaked real production account data into what should be isolated test
    state.

    Mutate `_mt5_state["open_positions"]` directly (never via an HTTP
    telemetry POST) so this proves the in-process path reads the dict
    in-process, without ever attempting the network branch. Patch
    bridge_server.httpx.get itself (the exact name get_open_positions calls)
    to fail the test if reached, so this doesn't rely on nothing being
    listening on host:port -- it deterministically fails the moment the
    network branch is attempted, on any machine.
    """
    def _fail_if_called(*args, **kwargs):
        pytest.fail("network attempted in in_process mode (httpx.get called)")

    monkeypatch.setattr(bridge_server.httpx, "get", _fail_if_called)

    sentinel = [{"ticket": 999999999, "symbol": "__SENTINEL__", "magic": 1}]
    bridge_server._mt5_state["open_positions"] = sentinel

    broker = MT5BridgeBroker(in_process=True)
    assert broker.get_open_positions() == sentinel


def test_get_closed_orders_in_process_reads_state_directly_never_network(monkeypatch):
    """Same guard as above, for get_closed_orders() / closed_orders."""
    def _fail_if_called(*args, **kwargs):
        pytest.fail("network attempted in in_process mode (httpx.get called)")

    monkeypatch.setattr(bridge_server.httpx, "get", _fail_if_called)

    sentinel = [{"ticket": 888888888, "pnl_usd": 42.0}]
    bridge_server._mt5_state["closed_orders"] = sentinel

    broker = MT5BridgeBroker(in_process=True)
    assert broker.get_closed_orders() == sentinel
