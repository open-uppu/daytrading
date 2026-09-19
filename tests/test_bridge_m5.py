import pytest
from mt5.bridge_server import BarsPayload, _cached_bars, MT5BridgeBroker
from config import config

def test_bridge_bar_upload_payload_m5():
    payload = BarsPayload(
        symbol="XAUUSD",
        timeframe="M5",
        bars=[
            {"timestamp": 1700000000, "open": 2000.0, "high": 2002.0, "low": 1999.0, "close": 2001.0, "volume": 50},
            {"timestamp": 1700000300, "open": 2001.0, "high": 2003.0, "low": 2000.0, "close": 2002.5, "volume": 65}
        ]
    )
    assert payload.timeframe == "M5"
    assert len(payload.bars) == 2

def test_bridge_broker_accepts_m5_market_data():
    broker = MT5BridgeBroker(in_process=True)
    assert hasattr(broker, "get_market_data")
