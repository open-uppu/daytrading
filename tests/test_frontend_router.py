import pytest
import asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from frontend.router import frontend_router, mount_frontend, ws_hub

def test_frontend_mount_and_index():
    app = FastAPI()
    mount_frontend(app)
    client = TestClient(app)
    
    # Test index route
    res_root = client.get("/")
    assert res_root.status_code == 200

    # Test health/snapshot api
    res = client.get("/api/dashboard/snapshot?symbol=XAUUSD&timeframe=M5")
    assert res.status_code == 200
    data = res.json()
    assert data["type"] == "snapshot"
    assert "account" in data

def test_websocket_connection_and_subscription():
    app = FastAPI()
    mount_frontend(app)
    client = TestClient(app)
    
    with client.websocket_connect("/ws/live") as websocket:
        # First message should be initial snapshot
        init_data = websocket.receive_json()
        assert init_data["type"] == "snapshot"
        assert init_data["symbol"] == "XAUUSD"
        
        # Send subscription request for BTCUSD M15
        websocket.send_json({"action": "subscribe", "symbol": "BTCUSD", "timeframe": "M15"})
        resp = websocket.receive_json()
        assert resp["type"] == "bars"
        assert resp["symbol"] == "BTCUSD"
        assert resp["timeframe"] == "M15"

        # Send ping
        websocket.send_json({"action": "ping"})
        pong_resp = websocket.receive_json()
        assert pong_resp["type"] == "pong"

def test_ws_hub_broadcast():
    app = FastAPI()
    mount_frontend(app)
    client = TestClient(app)

    with client.websocket_connect("/ws/live") as websocket:
        init_data = websocket.receive_json()
        assert init_data["type"] == "snapshot"

        # Run broadcast via event loop
        test_msg = {"type": "test_broadcast", "data": "hello"}
        asyncio.run(ws_hub.broadcast(test_msg))

        received = websocket.receive_json()
        assert received["type"] == "test_broadcast"
        assert received["data"] == "hello"

def test_bridge_server_includes_frontend():
    from mt5.bridge_server import app as bridge_app
    client = TestClient(bridge_app)
    res = client.get("/api/dashboard/snapshot?symbol=XAUUSD&timeframe=M5")
    assert res.status_code == 200
    data = res.json()
    assert data["type"] == "snapshot"
    assert "account" in data
