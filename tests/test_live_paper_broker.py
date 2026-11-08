"""Tests for LiveFeedPaperBroker: real per-symbol prices, simulated exits, durable state."""

import json

import pandas as pd
import pytest

from mt4.live_paper_broker import LiveFeedPaperBroker
from mt5.bridge_server import MarketDataStale


class FakeSource:
    """Stands in for MT5BridgeBroker: serves scripted bars per symbol."""

    def __init__(self, balance=500.0):
        self.balance = balance
        self.bars = {}
        self.stale = set()

    def set_bars(self, symbol, rows):
        self.bars[symbol.upper()] = pd.DataFrame(rows)

    def get_account_info(self):
        return {"balance": self.balance, "equity": self.balance, "connected": True}

    def get_market_data(self, symbol, timeframe="M5", bars=100):
        if symbol.upper() in self.stale:
            raise MarketDataStale(f"{symbol} stale")
        return self.bars[symbol.upper()].tail(bars).copy().reset_index(drop=True)


def bar(ts, o, h, l, c):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": 1}


@pytest.fixture
def source():
    s = FakeSource(balance=500.0)
    s.set_bars("BTCUSD", [bar("2026-11-08 10:00", 75000, 75010, 74990, 75000)])
    s.set_bars("ETHUSD", [bar("2026-11-08 10:00", 2200, 2201, 2199, 2200)])
    return s


def make(tmp_path, source):
    return LiveFeedPaperBroker(state_path=tmp_path / "paper_state.json", data_source=source)


def test_seeds_balance_from_live_account(tmp_path, source):
    broker = make(tmp_path, source)
    assert broker.balance == 500.0
    assert (tmp_path / "paper_state.json").exists()


def test_each_symbol_keeps_its_own_price(tmp_path, source):
    broker = make(tmp_path, source)
    btc = broker.get_market_data("BTCUSD", "M5", 30)
    eth = broker.get_market_data("ETHUSD", "M5", 30)
    assert btc["close"].iloc[-1] == 75000
    assert eth["close"].iloc[-1] == 2200

    broker.open_order("BTCUSD", "BUY", 0.01, sl=74000, tp=76000, magic=1)
    broker.open_order("ETHUSD", "BUY", 0.1, sl=2100, tp=2300, magic=1)
    prices = {p["symbol"]: p for p in broker.get_open_positions()}
    # Fills must be near each symbol's own price, not one shared price.
    assert abs(prices["BTCUSD"]["open_price"] - 75000) < 50
    assert abs(prices["ETHUSD"]["open_price"] - 2200) < 5


def test_stop_loss_and_take_profit_trigger_from_later_bars(tmp_path, source):
    broker = make(tmp_path, source)
    broker.get_market_data("BTCUSD", "M5", 30)
    res = broker.open_order("BTCUSD", "BUY", 0.1, sl=74900, tp=75200, magic=7)
    assert res["status"] == "SUCCESS"

    # New bar spikes above TP -> take profit at tp.
    source.set_bars("BTCUSD", [
        bar("2026-11-08 10:00", 75000, 75010, 74990, 75000),
        bar("2026-11-08 10:05", 75000, 75250, 74995, 75100),
    ])
    broker.get_market_data("BTCUSD", "M5", 30)
    assert broker.get_open_positions() == []
    closed = broker.consume_recently_closed(symbol="BTCUSD", magic=7)
    assert len(closed) == 1 and closed[0]["exit_reason"] == "TP_HIT"
    assert closed[0]["pnl_usd"] > 0
    assert broker.balance > 500.0


def test_range_before_open_does_not_trigger_exit(tmp_path, source):
    broker = make(tmp_path, source)
    # The forming bar already printed a wide range before we opened.
    source.set_bars("BTCUSD", [bar("2026-11-08 10:00", 75000, 75500, 74500, 75000)])
    broker.get_market_data("BTCUSD", "M5", 30)
    broker.open_order("BTCUSD", "BUY", 0.1, sl=74600, tp=75400, magic=7)
    broker.get_market_data("BTCUSD", "M5", 30)  # same bar, same close
    assert len(broker.get_open_positions()) == 1


def test_stale_feed_propagates_instead_of_synthetic_data(tmp_path, source):
    broker = make(tmp_path, source)
    source.stale.add("ETHUSD")
    with pytest.raises(MarketDataStale):
        broker.get_market_data("ETHUSD", "M5", 30)
    with pytest.raises(MarketDataStale):
        broker.open_order("ETHUSD", "BUY", 0.1, sl=2100, tp=2300)


def test_state_survives_restart(tmp_path, source):
    broker = make(tmp_path, source)
    broker.get_market_data("BTCUSD", "M5", 30)
    broker.open_order("BTCUSD", "BUY", 0.1, sl=74900, tp=75200, magic=7)
    broker.get_market_data("BTCUSD", "M5", 30)
    source.set_bars("BTCUSD", [
        bar("2026-11-08 10:00", 75000, 75010, 74990, 75000),
        bar("2026-11-08 10:05", 75000, 75010, 74800, 74850),
    ])
    broker.get_market_data("BTCUSD", "M5", 30)  # SL hit
    broker.get_market_data("ETHUSD", "M5", 30)
    broker.open_order("ETHUSD", "SELL", 0.1, sl=2300, tp=2100, magic=7)
    balance, closed_n = broker.balance, len(broker.closed_orders)

    source.balance = 99999.0  # a restart must NOT re-seed from the live account
    reborn = make(tmp_path, source)
    assert reborn.balance == balance
    assert len(reborn.closed_orders) == closed_n == 1
    assert len(reborn.open_positions) == 1
    only = next(iter(reborn.open_positions.values()))
    assert only["symbol"] == "ETHUSD" and isinstance(next(iter(reborn.open_positions)), int)
    # New tickets continue after the persisted ones.
    nxt = reborn.open_order("ETHUSD", "BUY", 0.1, sl=2100, tp=2300)
    assert nxt["ticket"] > only["ticket"]


def test_day_baseline_is_persisted(tmp_path, source):
    broker = make(tmp_path, source)
    assert broker.day_baseline(123.0) == 500.0
    again = make(tmp_path, source)
    assert again.day_baseline(0.0) == 500.0


def test_corrupt_state_file_is_never_silently_reset(tmp_path, source):
    (tmp_path / "paper_state.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError):
        make(tmp_path, source)
    (tmp_path / "paper_state.json").write_text(json.dumps({"version": 99, "balance": 1}), encoding="utf-8")
    with pytest.raises(RuntimeError):
        make(tmp_path, source)


def test_unavailable_live_balance_refuses_to_start(tmp_path):
    src = FakeSource(balance=0.0)
    with pytest.raises(RuntimeError):
        LiveFeedPaperBroker(state_path=tmp_path / "s.json", data_source=src)
