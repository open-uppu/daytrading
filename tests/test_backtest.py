"""
Unit tests for Backtest Engine, Data Loader, and Strategies.
"""

import pytest
import pandas as pd
import json
import urllib.request
from backtest.data_loader import generate_fallback_gold_data, generate_fallback_data, fetch_yahoo_candle_data
from backtest.engine import BacktestEngine
from backtest.strategies import strategy_mtf_momentum, strategy_ema_pullback, _price_precision_for


def test_fallback_data_generator():
    df = generate_fallback_gold_data(bars=100)
    assert len(df) == 100
    assert 'close' in df.columns
    assert 'timestamp' in df.columns
    assert (df['high'] >= df['low']).all()


def test_backtest_engine_execution():
    df = generate_fallback_gold_data(bars=200)
    engine = BacktestEngine(
        initial_balance=10000.0,
        risk_per_trade_pct=0.01,
        daily_target_pct=0.03,
        daily_max_loss_pct=0.02,
        spread=0.25
    )
    
    metrics = engine.run(df, strategy_mtf_momentum, strategy_name="TestMTF")
    
    assert "total_trades" in metrics
    assert "total_return_pct" in metrics
    assert "win_rate_pct" in metrics
    assert "profit_factor" in metrics
    assert "equity_curve" in metrics
    assert len(metrics["equity_curve"]) > 100


def test_default_min_sl_dist_rejects_forex_scale_signals():
    """The default 0.5 floor is tuned for Gold's ~2650 price scale. A market
    trading around ~1.08 (e.g. EURUSD) proposing realistic pip-scale stops
    must get every signal rejected under that default -- this is the bug
    that made GBPUSD show 0 trades across all 5 strategies."""
    df = generate_fallback_data(symbol="EURUSD", bars=200, timeframe="M15")
    engine = BacktestEngine(initial_balance=10000.0, spread=0.0001)

    def always_buy(window, idx=-1):
        price = float(window.iloc[-1]["close"])
        return {"action": "BUY", "sl": price - 0.0008, "tp": price + 0.0012}

    metrics = engine.run(df, always_buy, strategy_name="AlwaysBuy")
    assert metrics["total_trades"] == 0


def test_custom_min_sl_dist_allows_forex_scale_signals():
    """A caller-supplied floor sized for the market's own price scale (as
    evaluate_market_strategies now derives from ASSET_SPECS) must let the
    same realistic pip-scale signal through."""
    df = generate_fallback_data(symbol="EURUSD", bars=200, timeframe="M15")
    engine = BacktestEngine(initial_balance=10000.0, spread=0.0001, min_sl_dist=0.0005)

    def always_buy(window, idx=-1):
        price = float(window.iloc[-1]["close"])
        return {"action": "BUY", "sl": price - 0.0008, "tp": price + 0.0012}

    metrics = engine.run(df, always_buy, strategy_name="AlwaysBuy")
    assert metrics["total_trades"] > 0


def test_price_precision_for_gold_btc_eth_scale_is_unchanged():
    """Must stay 2 for Gold/BTC/ETH's price scale -- this is what makes the
    strategies.py rounding fix a no-op for their already-published results."""
    assert _price_precision_for(2650.0) == 2   # Gold
    assert _price_precision_for(63000.0) == 2  # BTC
    assert _price_precision_for(2600.0) == 2   # ETH


def test_price_precision_for_forex_and_small_commodity_scale():
    assert _price_precision_for(1.08) == 5   # EURUSD
    assert _price_precision_for(1.27) == 5   # GBPUSD
    assert _price_precision_for(3.0) == 5    # XNGUSD
    assert _price_precision_for(0.5) == 6


class _FakeYahooResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _yahoo_payload(closes):
    n = len(closes)
    return {"chart": {"result": [{
        "timestamp": list(range(1700000000, 1700000000 + n * 900, 900)),
        "indicators": {"quote": [{
            "open": closes, "high": closes, "low": closes, "close": closes,
            "volume": [100] * n,
        }]},
    }]}}


def test_fetch_yahoo_default_precision_matches_prior_gold_scale_behavior(monkeypatch):
    closes = [2650.1234, 2650.1298, 2650.1301]
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeYahooResponse(_yahoo_payload(closes)))
    df = fetch_yahoo_candle_data("GC=F")
    assert df["close"].tolist() == [2650.12, 2650.13, 2650.13]


def test_default_breakeven_buffer_fabricates_phantom_fill_on_forex_scale():
    """Reproduces the bug: the 0.20 breakeven buffer, applied to a SELL on a
    ~1.14 price, sets an unreachable-on-the-correct-side 'stop' that the
    trigger check then treats as an immediate fill at entry-0.20 -- a price
    the market never touched, mislabeled SL_HIT while actually a huge
    fabricated win (pnl == lots * contract_size * 0.20 exactly)."""
    import pandas as pd
    bars = []
    entry_price = 1.14500
    # First bar: triggers the SELL entry. Next bars: price drifts down just
    # enough to trip the breakeven-move check (entry_p - low >= sl_dist).
    prices = [entry_price] + [entry_price - 0.0010 - i * 0.00005 for i in range(1, 20)]
    for i, p in enumerate(prices):
        bars.append({"timestamp": f"2026-07-01 {i:02d}:00:00", "open": p, "high": p + 0.0001, "low": p - 0.0001, "close": p, "volume": 100})
    df = pd.DataFrame(bars)

    call_count = {"n": 0}

    def sell_once(window, idx=-1):
        call_count["n"] += 1
        if call_count["n"] == 1:
            price = float(window.iloc[-1]["close"])
            return {"action": "SELL", "sl": price + 0.0015, "tp": price - 0.0030}
        return {"action": "HOLD"}

    engine = BacktestEngine(initial_balance=10000.0, spread=0.0001, min_sl_dist=0.0008, contract_size=100000.0)
    metrics = engine.run(df, sell_once, strategy_name="BreakevenRepro", warmup_bars=0)
    assert metrics["total_trades"] == 1
    trade = metrics["trades_list"][0]
    # The bug: exit lands exactly entry - 0.20 (a price the market never
    # touched) instead of somewhere realistic near the actual price drift.
    assert abs(trade["exit_price"] - (trade["entry_price"] - 0.20)) > 0.01


def test_custom_breakeven_buffer_avoids_phantom_fill():
    import pandas as pd
    bars = []
    entry_price = 1.14500
    prices = [entry_price] + [entry_price - 0.0010 - i * 0.00005 for i in range(1, 20)]
    for i, p in enumerate(prices):
        bars.append({"timestamp": f"2026-07-01 {i:02d}:00:00", "open": p, "high": p + 0.0001, "low": p - 0.0001, "close": p, "volume": 100})
    df = pd.DataFrame(bars)

    call_count = {"n": 0}

    def sell_once(window, idx=-1):
        call_count["n"] += 1
        if call_count["n"] == 1:
            price = float(window.iloc[-1]["close"])
            return {"action": "SELL", "sl": price + 0.0015, "tp": price - 0.0030}
        return {"action": "HOLD"}

    engine = BacktestEngine(
        initial_balance=10000.0, spread=0.0001, min_sl_dist=0.0008,
        contract_size=100000.0, breakeven_buffer=0.0003
    )
    metrics = engine.run(df, sell_once, strategy_name="BreakevenFixed", warmup_bars=0)
    assert metrics["total_trades"] == 1
    trade = metrics["trades_list"][0]
    assert abs(trade["exit_price"] - (trade["entry_price"] - 0.20)) > 0.01
    # pnl must come from a realistic price move, not the fabricated $0.20 offset.
    assert abs(trade["pnl_usd"]) < 5000


def test_fetch_yahoo_forex_precision_preserves_sub_cent_movement(monkeypatch):
    """The bug: rounding EURUSD-scale closes to 2 decimals collapsed ~98% of
    bars into duplicate flat closes -- a fabricated staircase that made a
    mean-reversion strategy show a fake +139% return / 100% win rate."""
    closes = [1.14012, 1.14034, 1.14019]
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeYahooResponse(_yahoo_payload(closes)))
    df = fetch_yahoo_candle_data("EURUSD=X", price_precision=5)
    assert df["close"].tolist() == [1.14012, 1.14034, 1.14019]
    assert df["close"].nunique() == 3


def test_load_historical_data_m30_and_d1_use_correct_yahoo_intervals(monkeypatch, tmp_path):
    """M30/D1 must hit their own Yahoo interval, not silently fall through
    to the M15 branch's interval="15m" (which is what happens today for
    any timeframe string the if/elif chain doesn't recognize)."""
    import backtest.data_loader as data_loader

    monkeypatch.setattr(data_loader, "DATA_DIR", tmp_path)

    calls = []

    def fake_fetch(yahoo_symbol, interval="15m", range_str="60d", price_precision=2):
        calls.append({"interval": interval, "range_str": range_str})
        return pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=5, freq="D"),
            "open": [1.0] * 5, "high": [1.0] * 5, "low": [1.0] * 5,
            "close": [1.0] * 5, "volume": [100] * 5
        })

    monkeypatch.setattr(data_loader, "fetch_yahoo_candle_data", fake_fetch)

    data_loader.load_historical_data(symbol="XAUUSD", timeframe="M30")
    data_loader.load_historical_data(symbol="XAUUSD", timeframe="D1")

    assert calls[0] == {"interval": "30m", "range_str": "60d"}
    assert calls[1] == {"interval": "1d", "range_str": "730d"}
