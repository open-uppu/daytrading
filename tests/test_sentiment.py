"""Unit tests for free sentiment fetchers and their TTL cache. No real network calls."""
import json
import httpx

from core.sentiment import (
    fetch_fear_greed_index,
    fetch_fear_greed_history,
    fetch_news_sentiment,
    get_cached_value,
)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def test_fetch_fear_greed_index_happy_path(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(json_data={"data": [{"value": "78"}]}))
    assert fetch_fear_greed_index() == 78


def test_fetch_fear_greed_index_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(status_code=500))
    assert fetch_fear_greed_index() is None


def test_fetch_fear_greed_index_returns_none_on_malformed_json(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(json_data={"unexpected": "shape"}))
    assert fetch_fear_greed_index() is None


def test_fetch_fear_greed_history_happy_path(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(json_data={"data": [
        {"value": "50", "timestamp": "1700000000"},
        {"value": "20", "timestamp": "1700086400"},
    ]}))
    df = fetch_fear_greed_history()
    assert list(df.columns) == ["timestamp", "value"]
    assert df["value"].tolist() == [50, 20]


def test_fetch_fear_greed_history_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(status_code=500))
    assert fetch_fear_greed_history() is None


BULLISH_RSS = """<rss><channel>
<item><title>Bitcoin Surges Past $90,000 in Rally</title></item>
<item><title>Analysts Bullish on BTC Breakout</title></item>
</channel></rss>"""

BEARISH_RSS = """<rss><channel>
<item><title>Bitcoin Crashes in Sell-off</title></item>
<item><title>Market Bearish as BTC Plunges</title></item>
</channel></rss>"""

EMPTY_RSS = """<rss><channel></channel></rss>"""


def test_fetch_news_sentiment_bullish_headlines_score_positive(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(text=BULLISH_RSS))
    score = fetch_news_sentiment("BTCUSD")
    assert score is not None and score > 0


def test_fetch_news_sentiment_bearish_headlines_score_negative(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(text=BEARISH_RSS))
    score = fetch_news_sentiment("BTCUSD")
    assert score is not None and score < 0


def test_fetch_news_sentiment_returns_none_on_no_headlines(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(text=EMPTY_RSS))
    assert fetch_news_sentiment("BTCUSD") is None


def test_fetch_news_sentiment_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(status_code=500))
    assert fetch_news_sentiment("XAUUSD") is None


def test_get_cached_value_fresh_file_skips_fetch(tmp_path):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"ts": 1000.0, "value": 42}))
    calls = []
    result = get_cached_value(cache_path, ttl_sec=900, fetch_fn=lambda: calls.append(1) or 99, now=1500.0)
    assert result == 42
    assert calls == []


def test_get_cached_value_stale_file_refetches_and_rewrites(tmp_path):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"ts": 1000.0, "value": 42}))
    result = get_cached_value(cache_path, ttl_sec=900, fetch_fn=lambda: 99, now=5000.0)
    assert result == 99
    saved = json.loads(cache_path.read_text())
    assert saved["value"] == 99 and saved["ts"] == 5000.0


def test_get_cached_value_missing_file_fetches(tmp_path):
    cache_path = tmp_path / "cache.json"
    result = get_cached_value(cache_path, ttl_sec=900, fetch_fn=lambda: 7, now=1.0)
    assert result == 7
    assert json.loads(cache_path.read_text())["value"] == 7


def test_get_cached_value_corrupt_file_fetches(tmp_path):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("not json")
    result = get_cached_value(cache_path, ttl_sec=900, fetch_fn=lambda: 8, now=1.0)
    assert result == 8
