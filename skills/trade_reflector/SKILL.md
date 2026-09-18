---
name: trade-reflector
description: Self-learning and post-trade autopsy skill analyzing trading mistakes, logging detailed trade autopsies in Markdown, updating learned rules, and enforcing pre-trade checks.
version: 1.0.0
---

# Trade Reflector Skill

This skill implements an autonomous self-learning feedback loop. Whenever a trade closes, the agent conducts a comprehensive post-trade autopsy, diagnoses mistakes, writes Markdown records, and continuously improves its trading rules.

## Core Files Maintained

1. **`journal/trades/YYYY-MM-DD_trade_<id>.md`**: Individual post-trade autopsy file.
2. **`journal/mistakes_database.md`**: Master catalog of mistakes, root causes, and frequency counters.
3. **`journal/learned_rules.md`**: Actionable negative & positive rules that the agent **must check before entering every future trade**.

## Post-Trade Autopsy Procedure

When a trade closes:
1. **Gather Telemetry**: Entry time/price, exit time/price, duration, PnL ($ and %), PnL vs Daily Target.
2. **Setup vs Reality Comparison**:
   - What was the initial thesis? (e.g. M15 break & retest)
   - Did price reach TP, hit SL, or trail out?
   - Did market structure change? (e.g. H1 reversal, consolidation chop)
3. **Mistake Classification**:
   - `MISTAKE_CHASING_EXTENDED_CANDLE`: Entered after a massive expansion candle with poor RR.
   - `MISTAKE_COUNTER_HTF_TREND`: Took BUY when H1/H4 EMA 200 was pointing down.
   - `MISTAKE_TRADING_INTO_MAJOR_SR`: Entered BUY right beneath a major daily/H4 resistance zone.
   - `MISTAKE_LOW_VOLATILITY_CHOP`: Entered when ATR was below threshold during off-session hours.
   - `MISTAKE_SL_TOO_TIGHT`: Placed SL inside normal noise range (< 1.0 ATR).
   - `MISTAKE_GREED_AFTER_TARGET`: Continued trading after the 3% daily target was already achieved.
4. **Actionable Rule Generation**:
   - If a new mistake is observed or repeated, generate an explicit, testable rule for `journal/learned_rules.md`.

## Pre-Trade Filter (Active Mistake Prevention)

Before placing any trade:
- The agent reads `journal/learned_rules.md`.
- Evaluates the prospective trade setup against every active rule.
- If the trade violates any rule (e.g. "Rule #3: Never BUY when current price is within 0.5 ATR of H4 resistance"), the trade is **immediately vetoed** and logged as:
  `[PREVENTED_MISTAKE] Trade vetoed by Rule #3: Proximity to H4 resistance.`
