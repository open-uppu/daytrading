"""Free, keyless sentiment signals: Fear & Greed index and Google News headline scoring, TTL-cached."""
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

import httpx
import pandas as pd

NEWS_QUERIES = {"xau": "gold price when:2d", "gold": "gold price when:2d",
                 "btc": "bitcoin price when:2d", "eth": "ethereum price when:2d"}
BULLISH_KEYWORDS = ("surge", "rally", "soar", "breakout", "bullish", "jump", "rebound")
BEARISH_KEYWORDS = ("plunge", "crash", "sell-off", "selloff", "bearish", "tumble", "dump", "slump")


def fetch_fear_greed_index() -> Optional[int]:
    """Current crypto Fear & Greed value (0-100) from alternative.me. Never raises."""
    try:
        resp = httpx.get("https://api.alternative.me/fng/?limit=1&format=json", timeout=10.0)
        resp.raise_for_status()
        return int(resp.json()["data"][0]["value"])
    except Exception:
        return None


def fetch_fear_greed_history() -> Optional[pd.DataFrame]:
    """Full daily F&G history (limit=0), for a point-in-time-accurate backtest
    merge_asof -- same trick as the funding-rate history ablation. Never raises."""
    try:
        resp = httpx.get("https://api.alternative.me/fng/?limit=0&format=json", timeout=15.0)
        resp.raise_for_status()
        df = pd.DataFrame(resp.json()["data"])
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="s", utc=True)
        df["value"] = df["value"].astype(int)
        return df[["timestamp", "value"]].sort_values("timestamp").reset_index(drop=True)
    except Exception:
        return None


def fetch_news_sentiment(symbol: str) -> Optional[float]:
    """Net bullish-minus-bearish keyword hits across the latest ~20 Google News
    headlines for `symbol`. Free, keyless, CURRENT tone only -- no historical
    archive. Never raises; None on failure or zero parsed headlines (distinct
    from a genuinely neutral 0.0 score)."""
    sym = symbol.lower()
    query = next((q for key, q in NEWS_QUERIES.items() if key in sym), f"{symbol} price when:2d")
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = httpx.get(url, timeout=10.0)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        titles = [(item.findtext("title") or "").lower() for item in root.iter("item")][:20]
        if not titles:
            return None
        score = sum(1 for t in titles for kw in BULLISH_KEYWORDS if kw in t)
        score -= sum(1 for t in titles for kw in BEARISH_KEYWORDS if kw in t)
        return float(score)
    except Exception:
        return None


def get_cached_value(cache_path: Path, ttl_sec: int, fetch_fn: Callable[[], Any],
                      now: Optional[float] = None) -> Optional[Any]:
    """Generic TTL cache for one fetch_fn's JSON-serializable result. Same
    broad-except-fallback style as risk.manager.day_baseline. Caches None
    results too (bounded by ttl_sec) so a down API isn't hammered every call.
    Not safe for concurrent writers."""
    now = now if now is not None else time.time()
    try:
        cached = json.loads(cache_path.read_text())
        if now - float(cached["ts"]) < ttl_sec:
            return cached["value"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    value = fetch_fn()
    try:
        cache_path.write_text(json.dumps({"ts": now, "value": value}))
    except OSError:
        pass
    return value
