# News Blackout Filter — Design Spec

Date: 2026-09-23

## Problem

XAUUSD/BTCUSD/ETHUSD specialists (`agents/*_agent.py`) have tight M5 SL buffers
(Gold $1.00-$1.50, BTC $25, ETH $2.0 per AGENTS.md). High-impact USD news
events (NFP, FOMC, CPI) produce spikes/gaps that blow through these buffers
regardless of ATR-based sizing. There is currently no news-awareness in the
entry pipeline (`agents/base_agent.py::step()`).

## Goal

Add a news-awareness gate that:
1. Hard-blocks new entries only around the very highest-impact, most violent
   events (NFP, FOMC rate decisions, CPI) — spikes here are gappy enough that
   no SL/lot adjustment reliably helps.
2. For other USD High-impact events, reduces risk per trade instead of
   blocking entirely, so the system keeps trading opportunities open (user
   requirement: stay flexible, adjust rather than stop).
3. Never blocks trading due to a data-fetch failure — the feed is a free,
   unofficial JSON endpoint and must fail open.

Existing positions are never affected — only new-entry gating and lot sizing
change. This does not add a new agent, subsystem, or config surface beyond
what's listed below.

## Data Source

`https://nfs.faireconomy.media/ff_calendar_thisweek.json` — free, keyless,
official Forex Factory / FairEconomy redistribution feed used by MT4/MT5 news
filter EAs. Weekly refresh; JSON array with `title`, `country`, `date`,
`impact` (Low/Medium/High), `forecast`, `previous`, `actual`.

## Architecture

### New file: `core/news_calendar.py`

Follows the exact style of `core/sentiment.py` (module docstring, free
keyless fetch, broad-except → `None`, never raises).

```python
def fetch_ff_calendar() -> Optional[list[dict]]:
    """GET the weekly FF/FairEconomy calendar JSON. Returns a list of
    {title, country, date (datetime, UTC), impact, forecast, previous, actual}
    or None on any failure. Never raises."""

TOP_TIER_KEYWORDS = ("non-farm", "nonfarm", "fomc", "interest rate", "cpi")

def get_news_window_status(
    now: datetime,
    calendar: Optional[list[dict]],
    window_min: int = 15,
) -> dict:
    """Scans USD, High-impact events within ±window_min of `now`.
    Returns {"blackout": bool, "derisk": bool, "reason": str}.
    - calendar is None (fetch failed) -> fail-open: both False, reason notes
      calendar unavailable.
    - a matching event's title contains a TOP_TIER_KEYWORDS substring
      (case-insensitive) -> blackout=True.
    - any other USD High-impact event in window -> derisk=True.
    Never raises."""
```

Caching reuses `get_cached_value` from `core/sentiment.py` directly (no
duplicate cache logic). Cache file: `journal/ff_calendar_cache.json` — one
shared file, since all three symbols quote in USD and watch the same
calendar (no per-symbol calendar needed).

### Config additions (`config.py`)

```python
news_blackout_enabled: bool = True        # kill switch, same convention as smart_exit_enabled
news_blackout_window_min: int = 15        # minutes before/after a High-impact USD event
news_calendar_cache_ttl_sec: int = 3600   # feed refreshes weekly; hourly re-fetch is plenty
```

No separate derisk-factor config — reuses the existing
`daily_target_derisk_factor` (0.5) from `TradingConfig`. If real usage shows
the news case needs a different value than the daily-target case, split it
out then (not now — no data to justify it yet).

### Integration point: `agents/base_agent.py::step()`

Inserted as its own gate, same tier and return-shape as the existing
`can_trade` / `session_tracker.can_open_new_trade()` check (~line 493),
before the max-open-positions and cooldown checks:

```python
if config.news_blackout_enabled:
    calendar = get_cached_value(
        self.news_calendar_cache_file,
        config.news_calendar_cache_ttl_sec,
        fetch_ff_calendar,
    )
    news_status = get_news_window_status(
        datetime.now(timezone.utc), calendar, config.news_blackout_window_min
    )
    if news_status["blackout"]:
        return {
            "symbol": self.symbol, "asset": self.asset_name,
            "iteration": self.iteration_count,
            "status": "NEWS_BLACKOUT_ACTIVE",
            "reason": news_status["reason"],
            "session_summary": summary,
        }
else:
    news_status = {"blackout": False, "derisk": False, "reason": "disabled"}
```

`news_status["derisk"]` is carried forward (local var) to the risk-sizing
call later in the same `step()`.

### `risk/manager.py` changes

`RiskManager.calculate_lot_size` and `RiskManager.validate_trade_proposal`
gain an `extra_multiplier: float = 1.0` parameter, composed alongside the
existing `session_tracker.risk_multiplier`:

```python
risk_cash = equity * self.risk_pct * self.session_tracker.risk_multiplier * extra_multiplier
```

`base_agent.step()` passes
`extra_multiplier=config.daily_target_derisk_factor if news_status["derisk"] else 1.0`
into `validate_trade_proposal(...)`.

## Error Handling

- `fetch_ff_calendar` never raises (broad except → `None`), matching
  `core/sentiment.py` convention.
- `get_news_window_status` treats `calendar=None` as fail-open: no blackout,
  no derisk. Matches the user's explicit requirement to stay tradeable by
  default and only restrict when news is confirmed.
- `get_cached_value` already caches `None` results too (bounded by TTL), so a
  down feed isn't hammered every `step()` call.

## Testing

New `tests/test_news_calendar.py`:
- Parses a sample JSON payload into the expected dict shape.
- Window-edge math: event exactly at now ± window_min boundary.
- Top-tier keyword matching (case-insensitive, substring) triggers blackout.
- Any other USD High-impact event triggers derisk, not blackout.
- Non-USD or non-High-impact events are ignored.
- `calendar=None` -> fail-open (`blackout=False`, `derisk=False`).
- `fetch_ff_calendar` swallows exceptions (mocked `httpx.get` raising) and
  returns `None`.

`risk/manager.py` existing tests (`tests/test_risk_manager.py`,
`tests/test_risk_guards.py`) get a small addition verifying
`extra_multiplier` correctly halves `calculate_lot_size` output.

No changes to `tests/test_agents.py` beyond confirming the new gate doesn't
fire when `news_blackout_enabled=False` (kill switch works) — kept minimal,
not a full integration re-test of `step()`.

## Out of Scope

- Per-symbol currency mapping (all three symbols are USD-quoted; only USD
  events matter).
- A configurable top-tier keyword list (hardcoded tuple; revisit only if a
  real miss/false-positive shows up).
- Paid calendar API fallback (FMP/TradingEconomics) — only if the free feed
  proves unreliable in practice.
