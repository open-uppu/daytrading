"""Unit tests for the FF/FairEconomy news calendar fetcher and blackout/derisk window logic. No real network calls."""
import json
from datetime import datetime, timedelta, timezone

import httpx

from core.news_calendar import fetch_ff_calendar, get_news_window_status, load_news_calendar


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._json


SAMPLE_PAYLOAD = [
    {
        "title": "Non-Farm Employment Change",
        "country": "USD",
        "date": "2026-09-23T12:30:00-04:00",
        "impact": "High",
        "forecast": "150K",
        "previous": "142K",
        "actual": "",
    },
    {
        "title": "German Ifo Business Climate",
        "country": "EUR",
        "date": "2026-09-23T04:00:00-04:00",
        "impact": "Medium",
        "forecast": "88.5",
        "previous": "88.1",
        "actual": "",
    },
]


def test_fetch_ff_calendar_happy_path(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(json_data=SAMPLE_PAYLOAD))
    calendar = fetch_ff_calendar()
    assert calendar is not None
    assert len(calendar) == 2
    event = calendar[0]
    assert event["title"] == "Non-Farm Employment Change"
    assert event["country"] == "USD"
    assert event["impact"] == "High"
    # JSON-safe (must survive get_cached_value's json.dumps) -- an ISO string, not a datetime object.
    assert isinstance(event["date"], str)
    assert datetime.fromisoformat(event["date"]).tzinfo is not None


def test_fetch_ff_calendar_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(status_code=500))
    assert fetch_ff_calendar() is None


def test_fetch_ff_calendar_returns_none_on_malformed_json(monkeypatch):
    def raise_get(*a, **k):
        raise httpx.ConnectError("boom")
    monkeypatch.setattr(httpx, "get", raise_get)
    assert fetch_ff_calendar() is None


def _event(title, country, impact, minutes_from_now, now):
    return {
        "title": title,
        "country": country,
        "impact": impact,
        "date": now + timedelta(minutes=minutes_from_now),
    }


def test_window_status_calendar_none_fails_closed():
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    status = get_news_window_status(now, None, window_min=15)
    assert status["blackout"] is True
    assert status["reason"] == "NEWS_CALENDAR_UNAVAILABLE"


def test_window_status_top_tier_event_triggers_blackout():
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    calendar = [_event("Non-Farm Employment Change", "USD", "High", 10, now)]
    status = get_news_window_status(now, calendar, window_min=15)
    assert status["blackout"] is True
    assert status["derisk"] is False


def test_window_status_other_high_impact_usd_triggers_derisk_not_blackout():
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    calendar = [_event("Retail Sales m/m", "USD", "High", -5, now)]
    status = get_news_window_status(now, calendar, window_min=15)
    assert status["blackout"] is False
    assert status["derisk"] is True


def test_window_status_non_usd_ignored():
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    calendar = [_event("FOMC Statement", "EUR", "High", 5, now)]
    status = get_news_window_status(now, calendar, window_min=15)
    assert status["blackout"] is False
    assert status["derisk"] is False


def test_window_status_low_medium_impact_ignored():
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    calendar = [_event("CPI m/m", "USD", "Medium", 5, now)]
    status = get_news_window_status(now, calendar, window_min=15)
    assert status["blackout"] is False
    assert status["derisk"] is False


def test_window_status_event_outside_window_ignored():
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    calendar = [_event("Non-Farm Employment Change", "USD", "High", 16, now)]
    status = get_news_window_status(now, calendar, window_min=15)
    assert status["blackout"] is False
    assert status["derisk"] is False


def test_load_news_calendar_uses_stale_success_when_fetch_fails(tmp_path):
    cache = tmp_path / "ff_calendar_cache.json"
    cache.write_text(json.dumps({"ts": 1_000.0, "value": [{"title": "CPI", "country": "USD"}]}), encoding="utf-8")
    events, freshness = load_news_calendar(
        cache, fetch_fn=lambda: None, now=1_000.0 + 7_000, ttl_sec=3600, none_ttl_sec=60, stale_max_sec=6 * 3600,
    )
    assert freshness == "stale"
    assert events[0]["title"] == "CPI"
    # Failed fetch must not erase the last good list.
    assert json.loads(cache.read_text(encoding="utf-8"))["value"][0]["title"] == "CPI"


def test_load_news_calendar_unavailable_when_no_cache_and_fetch_fails(tmp_path):
    cache = tmp_path / "ff_calendar_cache.json"
    events, freshness = load_news_calendar(
        cache, fetch_fn=lambda: None, now=10.0, ttl_sec=3600, none_ttl_sec=60, stale_max_sec=3600,
    )
    assert events is None
    assert freshness == "unavailable"


def test_window_status_event_at_exact_boundary_included():
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    calendar = [_event("Non-Farm Employment Change", "USD", "High", 15, now)]
    status = get_news_window_status(now, calendar, window_min=15)
    assert status["blackout"] is True
