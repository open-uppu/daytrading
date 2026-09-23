"""Free, keyless USD economic calendar: FF/FairEconomy weekly JSON feed, for a news blackout/derisk gate."""
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
TOP_TIER_KEYWORDS = ("non-farm", "nonfarm", "fomc", "interest rate", "cpi")


def fetch_ff_calendar() -> Optional[list[dict]]:
    """This week's USD/EUR/etc economic events from the free FF/FairEconomy feed.
    Never raises; None on failure."""
    try:
        resp = httpx.get(FF_CALENDAR_URL, timeout=10.0)
        resp.raise_for_status()
        events = []
        for item in resp.json():
            events.append({
                "title": item["title"],
                "country": item["country"],
                "impact": item["impact"],
                # ISO string, not a datetime object: this list is cached
                # via get_cached_value's json.dumps, which can't serialize datetimes.
                "date": datetime.fromisoformat(item["date"]).isoformat(),
                "forecast": item.get("forecast", ""),
                "previous": item.get("previous", ""),
                "actual": item.get("actual", ""),
            })
        return events
    except Exception:
        return None


def get_news_window_status(now: datetime, calendar: Optional[list[dict]], window_min: int = 15) -> dict:
    """Scans USD High-impact events within +/-window_min of `now`.
    Top-tier titles (NFP/FOMC/CPI/rate decisions) -> blackout; any other
    USD High-impact event -> derisk. calendar=None (fetch failed) fails
    open: no blackout, no derisk."""
    if calendar is None:
        return {"blackout": False, "derisk": False, "reason": "calendar unavailable, trading normally"}

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
