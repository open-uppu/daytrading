"""
End-to-End Integration Tests for Pilotfish Quant Terminal & MT5 Bridge.
Verifies HTML shell, static assets, REST snapshots, WebSocket subscriptions,
and asynchronous telemetry/bars broadcasts from MT5 EA to connected Web clients.
"""

import time
import argparse
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from mt5.bridge_server import app, _mt5_state, _cached_bars
from frontend.router import ws_hub


def test_full_bridge_dashboard_lifecycle():
    """Tests complete HTTP and WebSocket lifecycle for terminal dashboard."""
    client = TestClient(app)

    # 1. Test index page returns 200 and loads HTML terminal shell
    resp = client.get("/")
    assert resp.status_code == 200
    assert "PILOTFISH QUANT TERMINAL" in resp.text
    assert "id=\"tv-chart\"" in resp.text
    assert "id=\"specialist-squad-container\"" in resp.text

    # 2. Test static assets are served properly
    resp_css = client.get("/static/css/terminal.css")
    assert resp_css.status_code == 200
    assert "pulse-green" in resp_css.text

    resp_dash = client.get("/static/js/dashboard.js")
    assert resp_dash.status_code == 200
    assert "PilotfishDashboard" in resp_dash.text

    resp_chart = client.get("/static/js/chart.js")
    assert resp_chart.status_code == 200
    assert "PilotfishChart" in resp_chart.text

    # 3. Test REST snapshot endpoint
    resp_snap = client.get("/api/dashboard/snapshot?symbol=XAUUSD&timeframe=M5")
    assert resp_snap.status_code == 200
    snap_data = resp_snap.json()
    assert snap_data["type"] == "snapshot"
    assert "account" in snap_data
    assert "portfolio" in snap_data
    assert "bars" in snap_data
    assert snap_data["symbol"] == "XAUUSD"
    assert snap_data["timeframe"] == "M5"

    # 4. Test WebSocket connection receives snapshot and responds to subscription
    with client.websocket_connect("/ws/live") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert "account" in snapshot
        assert "portfolio" in snapshot
        assert "bars" in snapshot
        assert "open_positions" in snapshot
        assert "closed_orders" in snapshot
        assert "specialists" in snapshot

        # Ping-Pong heartbeat
        ws.send_json({"action": "ping"})
        pong = ws.receive_json()
        assert pong["type"] == "pong"

        # Subscribe to ETHUSD M5
        ws.send_json({"action": "subscribe", "symbol": "ETHUSD", "timeframe": "M5"})
        bars_eth = ws.receive_json()
        assert bars_eth["type"] == "bars"
        assert bars_eth["symbol"] == "ETHUSD"
        assert bars_eth["timeframe"] == "M5"
        assert isinstance(bars_eth["bars"], list)

        # Subscribe to BTCUSD M15
        ws.send_json({"action": "subscribe", "symbol": "BTCUSD", "timeframe": "M15"})
        bars_btc = ws.receive_json()
        assert bars_btc["type"] == "bars"
        assert bars_btc["symbol"] == "BTCUSD"
        assert bars_btc["timeframe"] == "M15"
        assert isinstance(bars_btc["bars"], list)


def test_telemetry_broadcast_to_websocket():
    """Verifies EA telemetry POST is broadcasted to connected WebSocket clients."""
    client = TestClient(app)

    with client.websocket_connect("/ws/live") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"

        # Simulate MT5 EA uploading live telemetry
        telemetry_payload = {
            "account_number": 99887766,
            "server": "Exness-MT5Real",
            "balance": 12500.50,
            "equity": 12850.75,
            "symbol": "XAUUSD",
            "bid": 2685.20,
            "ask": 2685.45,
            "open_positions": [
                {
                    "ticket": 12345,
                    "symbol": "XAUUSD",
                    "type": "BUY",
                    "volume": 0.5,
                    "open_price": 2680.00,
                    "sl": 2675.00,
                    "tp": 2695.00,
                    "profit": 260.00
                }
            ],
            "closed_orders": [
                {
                    "ticket": 12340,
                    "symbol": "BTCUSD",
                    "type": "BUY",
                    "volume": 0.1,
                    "open_price": 64000.0,
                    "close_price": 64500.0,
                    "profit": 50.0
                }
            ]
        }

        post_resp = client.post("/api/mt5/telemetry", json=telemetry_payload)
        assert post_resp.status_code == 200
        assert post_resp.json()["status"] == "ACK"

        # WebSocket client should receive live telemetry message
        ws_msg = ws.receive_json()
        assert ws_msg["type"] == "telemetry"
        assert ws_msg["account"]["account_number"] == 99887766
        assert ws_msg["account"]["server"] == "Exness-MT5Real"
        assert ws_msg["account"]["mode"] == "MT5 LIVE"
        assert ws_msg["account"]["balance"] == 12500.50
        assert ws_msg["account"]["equity"] == 12850.75
        assert ws_msg["account"]["bid"] == 2685.20
        assert ws_msg["account"]["ask"] == 2685.45
        assert len(ws_msg["open_positions"]) == 1
        assert ws_msg["open_positions"][0]["ticket"] == 12345
        assert len(ws_msg["closed_orders"]) == 1
        assert "portfolio" in ws_msg


def test_bars_broadcast_to_websocket():
    """Verifies EA bars POST is broadcasted to connected WebSocket clients."""
    client = TestClient(app)

    with client.websocket_connect("/ws/live") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"

        # Simulate MT5 EA uploading new bars
        now_ts = int(time.time())
        bars_data = [
            {"time": now_ts - 300, "open": 2680.0, "high": 2684.0, "low": 2679.0, "close": 2683.5, "volume": 120},
            {"time": now_ts, "open": 2683.5, "high": 2687.0, "low": 2682.0, "close": 2686.0, "volume": 95},
        ]
        bars_payload = {
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "bars": bars_data
        }

        post_resp = client.post("/api/mt5/bars", json=bars_payload)
        assert post_resp.status_code == 200
        assert post_resp.json()["status"] == "BARS_STORED"

        # WebSocket client should receive bars broadcast
        ws_msg = ws.receive_json()
        assert ws_msg["type"] == "bars"
        assert ws_msg["symbol"] == "XAUUSD"
        assert ws_msg["timeframe"] == "M5"
        assert len(ws_msg["bars"]) >= 2
        last_bar = ws_msg["bars"][-1]
        assert last_bar["close"] == 2686.0


def test_cli_web_argument_and_banner():
    """Verifies main.py CLI arguments include --web flag for run and loop."""
    from main import build_parser

    args_default = build_parser().parse_args(["run"])
    assert args_default.web is False

    args_run = build_parser().parse_args(["run", "--web"])
    assert args_run.web is True

    args_loop = build_parser().parse_args(["loop", "--web"])
    assert args_loop.web is True


def test_dashboard_js_fixes():
    """Verifies bugfixes in dashboard.js for starting_balance and destroy onclose."""
    js_path = Path(__file__).parent.parent / "frontend" / "static" / "js" / "dashboard.js"
    assert js_path.exists()
    content = js_path.read_text(encoding="utf-8")

    # 1. Verify state.portfolio?.starting_balance in updateKpiCards
    assert "state.portfolio?.starting_balance" in content
    assert "newTodayPnl = newBalance - Number(state.portfolio.starting_balance);" in content

    # 2. Verify state.ws.onclose = null in destroy()
    assert "state.ws.onclose = null;" in content
