import pytest
from frontend.feed_provider import DashboardFeedProvider

def test_feed_provider_fallback_paper_snapshot():
    provider = DashboardFeedProvider()
    snapshot = provider.get_snapshot(symbol="XAUUSD", timeframe="M5")
    
    assert "account" in snapshot
    assert "portfolio" in snapshot
    assert "bars" in snapshot
    assert "open_positions" in snapshot
    assert "closed_orders" in snapshot
    assert "specialists" in snapshot
    assert snapshot["symbol"] == "XAUUSD"
    assert snapshot["timeframe"] == "M5"
    assert isinstance(snapshot["bars"], list)
    assert len(snapshot["bars"]) > 0
    assert "close" in snapshot["bars"][-1]

def test_feed_provider_get_bars():
    provider = DashboardFeedProvider()
    payload = provider.get_bars_payload(symbol="BTCUSD", timeframe="M15")
    assert payload["symbol"] == "BTCUSD"
    assert payload["timeframe"] == "M15"
    assert len(payload["bars"]) > 0

def test_feed_provider_mt5_state_and_cached_bars():
    mt5_state = {
        "connected": True,
        "balance": 10500.0,
        "equity": 10650.0,
        "account_number": 123456,
        "server": "Demo-Server",
        "open_positions": [{"ticket": 1, "symbol": "XAUUSD", "profit": 150.0}],
        "closed_orders": [{"ticket": 0, "symbol": "BTCUSD", "profit": 50.0}],
        "last_sync": "2026-09-23T08:00:00Z"
    }
    cached_bars = {
        "XAUUSD:M5": {
            "bars": [
                {"time": 1700000000, "open": 2000.0, "high": 2005.0, "low": 1995.0, "close": 2002.0, "volume": 100}
            ]
        }
    }
    provider = DashboardFeedProvider(mt5_state_ref=mt5_state, cached_bars_ref=cached_bars)
    snapshot = provider.get_snapshot(symbol="XAUUSD", timeframe="M5")

    assert snapshot["account"]["connected"] is True
    assert snapshot["account"]["mode"] == "MT5 LIVE"
    assert snapshot["account"]["balance"] == 10500.0
    assert snapshot["account"]["equity"] == 10650.0
    assert snapshot["account"]["floating_pnl"] == 150.0
    assert len(snapshot["bars"]) == 1
    assert snapshot["bars"][0]["close"] == 2002.0
    assert len(snapshot["open_positions"]) == 1
    assert len(snapshot["closed_orders"]) == 1
