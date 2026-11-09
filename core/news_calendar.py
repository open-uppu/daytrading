"""Free, keyless USD economic calendar: FF/FairEconomy weekly JSON feed, for a news blackout/derisk gate."""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FF_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
TOP_TIER_KEYWORDS = ("non-farm", "nonfarm", "fomc", "interest rate", "cpi")


def _parse_events(payload: list) -> list[dict]:
    events = []
    for item in payload:
        events.append({
            "title": item["title"],
            "country": item["country"],
            "impact": item["impact"],
            # ISO string, not a datetime object: this list is cached as JSON.
            "date": datetime.fromisoformat(item["date"]).isoformat(),
            "forecast": item.get("forecast", ""),
            "previous": item.get("previous", ""),
            "actual": item.get("actual", ""),
        })
    return events


def fetch_ff_calendar() -> Optional[list[dict]]:
    """This week's economic events from the free FF/FairEconomy feed.
    Never raises; None on failure. Retries once. A browser User-Agent avoids
    the bare-client HTTP 429 that previously left the cache null."""
    headers = {"User-Agent": FF_USER_AGENT, "Accept": "application/json"}
    last_error: Optional[Exception] = None
    for _ in range(2):
        try:
            resp = httpx.get(FF_CALENDAR_URL, timeout=10.0, headers=headers)
            resp.raise_for_status()
            return _parse_events(resp.json())
        except Exception as exc:
            last_error = exc
    return None if last_error is not None else None


def load_news_calendar(
    cache_path: Path,
    fetch_fn: Callable[[], Optional[list[dict]]],
    now: Optional[float] = None,
    ttl_sec: int = 3600,
    none_ttl_sec: int = 60,
    stale_max_sec: int = 6 * 3600,
) -> tuple[Optional[list[dict]], str]:
    """Return (events, freshness).

    freshness is ``ok`` (fresh successful fetch or fresh cache), ``stale``
    (last successful list, still inside stale_max_sec, used because the live
    fetch failed), or ``unavailable`` (no usable list). A failed fetch is
    negative-cached for none_ttl_sec and must NOT overwrite a successful list.
    """
    now = time.time() if now is None else now
    cached_value: Any = None
    cached_age: Optional[float] = None
    try:
        cached = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        cached_age = now - float(cached["ts"])
        cached_value = cached.get("value")
    except (OSError, ValueError, KeyError, TypeError):
        cached_value = None
        cached_age = None

    if isinstance(cached_value, list) and cached_age is not None and cached_age < ttl_sec:
        return cached_value, "ok"
    if cached_value is None and cached_age is not None and cached_age < none_ttl_sec:
        return None, "unavailable"

    fetched = fetch_fn()
    if isinstance(fetched, list):
        _write_calendar_cache(cache_path, fetched, now)
        return fetched, "ok"
    if isinstance(cached_value, list) and cached_age is not None and cached_age < stale_max_sec:
        return cached_value, "stale"
    _write_calendar_cache(cache_path, None, now)
    return None, "unavailable"


def _write_calendar_cache(cache_path: Path, value: Any, now: float) -> None:
    try:
        path = Path(cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ts": now, "value": value}), encoding="utf-8")
    except OSError:
        pass


def get_news_window_status(now: datetime, calendar: Optional[list[dict]], window_min: int = 15) -> dict:
    """Scans USD High-impact events within +/-window_min of `now`.
    Top-tier titles (NFP/FOMC/CPI/rate decisions) -> blackout; any other
    USD High-impact event -> derisk. calendar=None (fetch failed and no
    usable cache) fails closed: block new entries."""
    if calendar is None:
        return {"blackout": True, "derisk": False, "reason": "NEWS_CALENDAR_UNAVAILABLE"}

    window = timedelta(minutes=window_min)
    blackout = False
    derisk = False
    reason = "no high-impact USD news in window"

    for event in calendar:
        if event.get("country") != "USD" or event.get("impact") != "High":
            continue
        event_date = event["date"]
        if not isinstance(event_date, datetime):
            event_date = datetime.fromisoformat(event_date)
        if abs(event_date - now) > window:
            continue
        title_lower = event["title"].lower()
        if any(kw in title_lower for kw in TOP_TIER_KEYWORDS):
            blackout = True
            reason = f"NEWS_BLACKOUT_ACTIVE: top-tier USD event '{event['title']}' within {window_min}min"
            break
        derisk = True
        reason = f"NEWS_DERISK_ACTIVE: USD High-impact event '{event['title']}' within {window_min}min"

    return {"blackout": blackout, "derisk": derisk, "reason": reason}
