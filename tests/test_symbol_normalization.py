"""Tests for symbol normalization (broker suffix handling) and Cent account scaling."""
import pytest
from fastapi.testclient import TestClient
from mt5.bridge_server import app, _cached_bars, _mt5_state, normalize_symbol, canonical_symbol_key
from frontend.feed_provider import DashboardFeedProvider


def test_normalize_symbol():
    # Canonical symbols should match regardless of broker suffix
    assert normalize_symbol("XAUUSD") == "XAUUSD"
    assert normalize_symbol("XAUUSDm") == "XAUUSD"
    assert normalize_symbol("XAUUSDc") == "XAUUSD"
    assert normalize_symbol("BTCUSD.m") == "BTCUSD"
    assert normalize_symbol("BTCUSDc") == "BTCUSD"
    assert normalize_symbol("EURUSD_i") == "EURUSD"
    assert normalize_symbol("UKOILm") == "UKOIL"
    assert normalize_symbol("XNGUSDm") == "XNGUSD"


def test_bars_ingestion_canonical_alias():
    client = TestClient(app)
    # Clear cache
    _cached_bars.clear()

    # Upload bars with Exness 'm' suffix
    sample_bars = [
        {"timestamp": 1700000000, "open": 2650.0, "high": 2655.0, "low": 2649.0, "close": 2652.0, "volume": 100}
    ]
    resp = client.post("/api/mt5/bars", json={
        "symbol": "XAUUSDm",
        "timeframe": "M5",
        "bars": sample_bars
    })
    assert resp.status_code == 200

    # Query with canonical 'XAUUSD'
    resp_canon = client.get("/api/mt5/bars?symbol=XAUUSD&timeframe=M5")
    assert resp_canon.status_code == 200
    data_canon = resp_canon.json()
    assert len(data_canon["bars"]) == 1
    assert data_canon["bars"][0]["close"] == 2652.0

    # Query with suffixed 'XAUUSDm'
    resp_suff = client.get("/api/mt5/bars?symbol=XAUUSDm&timeframe=M5")
    assert resp_suff.status_code == 200
    data_suff = resp_suff.json()
    assert len(data_suff["bars"]) == 1

    # Status endpoint reflects normalized market data
    status_resp = client.get("/api/mt5/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert "XAUUSD:M5" in status_data["market_data"]


def test_cent_account_feed_metrics():
    # Simulate Cent account state in telemetry
    cent_state = {
        "account_number": 1234567,
        "server": "Exness-MT5Cent",
        "balance": 5700.0,  # 5,700 USC (~$57 USD)
        "equity": 5700.0,
        "symbol": "XAUUSDc",
        "bid": 2650.0,
        "ask": 2650.25,
        "open_positions": [],
        "closed_orders": [],
        "last_sync": "2026-11-08T10:00:00+00:00",
        "connected": True,
        "currency": "USC",
        "is_cent": True
    }
    provider = DashboardFeedProvider(mt5_state_ref=cent_state)
    acc = provider.get_account_data()
    assert acc["mode"] == "MT5 LIVE"
    assert acc["currency"] == "USC"
    assert acc["is_cent"] is True

    # Portfolio metrics should scale to actual initial balance (5700 USC)
    metrics = provider.get_portfolio_metrics()
    assert metrics["starting_balance"] == 5700.0
    assert metrics["target_pct"] == 3.0
    assert metrics["target_profit_usd"] == 171.0  # 3% of 5,700 USC = 171 USC (~60 THB)
    assert metrics["realized_pnl_usd"] == 0.0
    assert metrics["daily_return_pct"] == 0.0
