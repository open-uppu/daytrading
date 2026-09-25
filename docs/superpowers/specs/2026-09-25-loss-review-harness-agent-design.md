# Loss-Review Harness Agent — Design Spec

Date: 2026-09-25

## Problem

`agents/squad_manager.py::check_new_session()` (line 220) resets the
portfolio's daily tracker on every new UTC day with no memory of prior
days. If the squad hits the max-loss cutoff (`PORTFOLIO_MAX_LOSS_CUTOFF`,
`agents/squad_manager.py:326-334`) today, tomorrow starts with a completely
fresh budget as if nothing happened — there is no cross-day circuit
breaker. Confirmed with the user (2026-09-25) this is a real, current gap:
the live account hit the loss cutoff on both 2026-09-24 (-4.67%) and
2026-09-25 (-3.55%, still active at time of writing), i.e. it is already
mid-way through the exact scenario this spec addresses.

The user wants: after the loss cutoff fires on 2 consecutive real trading
days, an agent runs before day 3 starts, analyzes what happened, and
re-plans day 3's trading — with the changes taking effect automatically,
no human approval step, because that was the user's explicit, repeated
preference across several rounds of clarification in this session.

Requiring full autonomy over what actually executes with real money
introduces real risk of its own (a hallucinated or buggy autonomous change
executing live trades unsupervised). The user was walked through this
concern directly and, in response, drew their own boundary rather than
accepting a same-day human-review gate: **existing, already-vetted live
code is never touched or overwritten by the harness.** All harness-authored
work happens in a separate area it has full freedom over; only that
separate area's output is allowed to influence live trading, and only
after passing an automated (not human) safety check. This spec formalizes
that boundary.

## Goal

Build a harness that, triggered by 2 consecutive real-trading days hitting
the max-loss cutoff, analyzes the underperforming specialists' recent
trades/backtest data/news context, authors a candidate replacement strategy
per underperforming specialist via an LLM call, validates each candidate
against an automated backtest gate, and — for candidates that pass —
automatically swaps that specialist onto the new strategy starting the next
trading day. No human approval step gates this; the automated gate is the
safety mechanism the user agreed to in its place.

**Explicitly out of scope:**
- Any change to specialists that were net profitable (or flat) over the
  2-day losing window — only specialists that were themselves net negative
  get a candidate strategy generated. A portfolio-level cutoff can fire
  while some specialists were fine (confirmed from the actual 2026-09-24
  dashboard log: Platinum was -$9.27 while Gold/BTC/XNG were positive) —
  the harness must not touch specialists that weren't part of the problem.
- Modifying `agents/*.py`, `backtest/strategies.py`, `agents/squad_manager.py`,
  `agents/base_agent.py`, any risk-cutoff value, the lot-sizing formula, or
  the harness's own trigger logic (N=2). These are the "fixed zone" and are
  never written to by the harness process itself.
- A human review/approval UI or workflow. The user explicitly chose
  automated-gate-only over a human-approval gate after this was offered as
  an alternative.
- This spec depends on
  `docs/superpowers/specs/2026-09-25-fixed-principal-risk-bands-design.md`
  shipping first: the automated gate's "must beat the specialist's current
  live strategy" comparison and the -5% trigger threshold both assume that
  spec's fixed-principal percentage math and recovery-band mechanism
  already exist.

## Architecture

### Consecutive-loss tracking

New file `journal/consecutive_loss_days.json`, schema:
```json
{"last_evaluated_date": "2026-09-24", "streak": 1, "today_hit_cutoff": false}
```

- The first time `max_loss_reached` becomes `True` on a given day
  (`agents/squad_manager.py:326`), set `today_hit_cutoff = true` for that
  date (idempotent — already-`true` stays `true` for the rest of the day).
- Inside `check_new_session()`'s existing new-day branch
  (`agents/squad_manager.py:220-230`), before resetting the portfolio
  tracker: read the file. If `last_evaluated_date` is yesterday relative to
  the new session date, finalize yesterday's outcome: `streak = streak + 1
  if today_hit_cutoff else 0`. Write `last_evaluated_date = <new date>`,
  `today_hit_cutoff = false`, keep the (possibly just-incremented) `streak`.
- If the finalized `streak >= 2`: call `harness.loss_review.run(specialists,
  streak)` **synchronously, before this `check_new_session()` call
  returns** — i.e. before any specialist evaluates a new-day signal. The
  squad already isn't mid-position at this point (yesterday's HALT closed
  everything), so blocking the loop for the harness's analysis + LLM call +
  backtest gate (dominated by one LLM round-trip, low tens of seconds) costs
  no missed trading opportunity. After `run()` returns, reset `streak = 0`
  (a harness cycle always resolves the streak, pass or fail per specialist)
  and continue `check_new_session()` as normal.

### Which specialists get a candidate

`harness.loss_review.run()` first reads each specialist's trade journal
entries (`journal/<symbol>/trades/*.md`) for the 2 flagged calendar days and
sums realized PnL per specialist. Only specialists with a negative 2-day sum
proceed to candidate generation; the rest are left exactly as they are
(whatever `agents/squad_manager.py` already assigns them — their normal
strategy, or `RECOVERY` band strategy from the fixed-principal-risk-bands
spec, depending on where the new day's equity % lands).

### Data gathered per flagged specialist

Per the user's "ทำทั้งหมดที่เป็นไปได้" (do everything possible) answer:
- Its trade journal entries for the 2 flagged days (`journal/<symbol>/trades/*.md`).
- Its Max DD leaderboard row from `evaluate_market_strategies(symbol,
  timeframe="M15")` (`backtest/run_cross_market_comparison.py:33`) — this
  same call already produces every generic strategy's Return%/Win
  Rate/Max DD for that symbol, including whichever strategy the specialist
  currently runs live, and is re-run fresh (not cached) so the gate
  compares against current data.
- News/sentiment context for that symbol:
  `journal/sentiment_news_<SYMBOL>.json` and the FF calendar cache
  (`config.journal_dir / "ff_calendar_cache.json"` pattern already used by
  `agents/base_agent.py`'s news-blackout check).

### Candidate generation (the "sandbox zone")

New package `harness/`:
- `harness/loss_review.py` — orchestrator described in this section.
- `harness/sandbox_strategies/` — every LLM-authored candidate is written
  here as its own timestamped file
  (`<symbol>_<YYYYMMDD_HHMMSS>.py`), never overwritten, never touching any
  path outside this directory. This directory is the entirety of the
  "harness does whatever it wants" zone the user asked for.

For each flagged specialist, build one Anthropic Messages API call (model:
`claude-sonnet-5`) with the gathered data above and a system prompt that:
states the exact required function contract — a single Python function
`def strategy_<symbol>_<timestamp>(window: pd.DataFrame, current_idx: int) -> Dict[str, Any]`
returning the same shape every existing `backtest/strategies.py` function
returns (`{"action": "BUY"|"SELL"|"HOLD", "sl": float, "tp": float, ...}` —
copy the exact existing return contract, e.g. from
`strategy_bb_reversion`, `backtest/strategies.py:127-166`, into the
prompt as a concrete example) — and asks it to author a new, different
signal function informed by the supplied trade/backtest/news context.
Use `httpx` (already a dependency, `requirements.txt`) to call
`https://api.anthropic.com/v1/messages` directly — no new package needed.
New `config.py` fields: `anthropic_api_key: str =
os.getenv("ANTHROPIC_API_KEY", "")` and `harness_model: str =
"claude-sonnet-5"`.

Parse the response's code block, write it verbatim to its sandbox file, then
`importlib.util.spec_from_file_location` it to obtain the callable. If the
response doesn't parse as valid Python or doesn't expose a function matching
the required signature, treat that specialist as a gate failure (see
Fallback) — no retry loop in this spec (YAGNI; add one later if this proves
to be a frequent failure mode in practice).

### Automated gate (the fixed↔sandbox bridge)

For each successfully-parsed candidate, run it through the existing
`BacktestEngine` (`backtest/engine.py:60`, `.run(df, signal_fn,
strategy_name, warmup_bars=50)`) over the same `df` that
`evaluate_market_strategies` already loaded for that symbol/timeframe in
the data-gathering step above — so the candidate and the specialist's
current live strategy are scored on the identical historical window.

Look up the specialist's current live strategy's own row from that same
`evaluate_market_strategies` result (matched by strategy name string, e.g.
`GoldSpecialistAgent`'s M15 path currently runs `strategy_mtf_momentum`,
matching `"Strategy D: MTF Momentum Cross"` in the leaderboard) to get its
`total_return_pct` and `max_drawdown_pct` for comparison.

**Gate — a candidate must pass all three (matches what the user confirmed:
"ทั้งหมด" combined with "ดีกว่า...เดิม"):**
1. `candidate.total_return_pct > 0`
2. `candidate.max_drawdown_pct <= 5.0`
3. `candidate.total_return_pct >= live.total_return_pct` **and**
   `candidate.max_drawdown_pct <= live.max_drawdown_pct`

### On pass: auto-apply

Persist to `journal/harness_active_overrides.json`
(`{"gold": {"module_path": "harness/sandbox_strategies/xauusd_20260925_140213.py",
"function_name": "strategy_xauusd_20260925_140213", "applied_date":
"2026-09-26", "backtest_return_pct": 4.1, "backtest_max_dd_pct": 3.9}, ...}`).

Wire it into the live path with one new check in
`agents/base_agent.py::step()`, placed immediately before the existing
`signal = self.evaluate_strategy_signal(df_main, risk_band)` call
(`agents/base_agent.py:642`):
```python
override = self._harness_override_fn  # set at squad-manager init / after each harness run; None otherwise
signal = override(df_main, len(df_main) - 1) if override else self.evaluate_strategy_signal(df_main, risk_band)
```
`SquadManager` loads `journal/harness_active_overrides.json` once at
startup and again immediately after every harness run, and sets
`specialist._harness_override_fn` (dynamically imported from the recorded
`module_path`/`function_name`) for each specialist that has an active
entry. This takes priority over both the normal and `RECOVERY` strategy
paths, in every risk band, until a future harness run replaces or clears
that specialist's entry — the user's "แผนใหม่" (new plan) is a standing
replacement, not a single day's patch, until superseded.

### On fail: fallback

That specialist's entry (if any) is removed from
`harness_active_overrides.json` (falls back to normal/`RECOVERY` handling
from the fixed-principal-risk-bands spec) and the failure is recorded in
the human-readable report (below) so the user can see what was tried and
why it didn't clear the bar. No trading pause beyond what the risk-bands
spec already provides.

### Human-readable report (transparency, not a gate)

`journal/harness_reports/<YYYY-MM-DD>.md` — one file per harness run,
listing: which specialists were flagged, their 2-day PnL, each candidate's
backtest Return%/Max DD% vs. the live strategy's own, gate pass/fail per
specialist, and which override (if any) is now active. Written after the
decision is already applied — purely informational, matches "auto-apply,
no waiting on a human" while keeping the user able to see what happened.

## Testing

- `journal/consecutive_loss_days.json` streak logic: hit → hit → non-hit
  → hit → hit sequences, asserting `streak` reaches 2 only on truly
  consecutive hit days and resets on any intervening non-hit day (mirrors
  the Day 1-7 simulation worked through with the user in this session).
- Specialist filtering: given fabricated 2-day journal PnL sums, only
  net-negative specialists are passed to candidate generation.
- Gate logic: table-driven tests over the three conditions (positive
  return / DD ≤ 5% / beats live strategy) — each one independently
  causing a fail when violated, all three passing when all are met.
- `httpx` call to the Anthropic API is mocked in all tests — no test hits
  the network or requires `ANTHROPIC_API_KEY`.
- Malformed/unparsable LLM response is treated as a gate failure for that
  specialist, not a crash of the whole harness run (other flagged
  specialists still get evaluated).
- `agents/base_agent.py::step()`: with `_harness_override_fn` set, it is
  called instead of `evaluate_strategy_signal` regardless of `risk_band`;
  with it unset (`None`, the default), behavior is byte-identical to
  before this spec.
- Run `pytest tests/ -q` after each change; must stay green throughout.

## Self-Review Notes

- **Placeholder scan:** none — model name, gate thresholds, file paths,
  and the override-persistence scope are all concrete decisions, not TBDs.
- **Internal consistency:** the gate's condition 3 (beat the specialist's
  own current live strategy) depends on
  `2026-09-25-fixed-principal-risk-bands-design.md`'s recovery-strategy
  selection already having identified each specialist's normal live
  strategy by name — this spec's data-gathering step reuses that same
  `evaluate_market_strategies` call rather than inventing a second lookup
  path, so the two specs can't drift out of sync on "what is this
  specialist's current strategy."
- **Scope check:** single cohesive subsystem (trigger → gather → generate
  → gate → apply → report); the LLM-call plumbing and the gate logic are
  the two genuinely separate concerns inside it, both small enough to stay
  in one plan.
- **Ambiguity check:** override persistence duration ("until superseded,"
  not "one day only") is called out explicitly as the interpretation taken
  — flagging it here since it's the one place this spec extrapolated
  beyond an exact user confirmation; the user reviews this written spec
  before the plan is written, per the brainstorming flow, and can correct
  it here if that reading is wrong.
