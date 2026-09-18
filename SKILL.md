---
name: gold-day-trading-agent
description: Autonomous daily gold (XAUUSD) trading agent utilizing multi-timeframe technicals, chart vision analysis, MT4/paper execution, strict 3% daily profit targets, and self-learning mistake reflection stored in markdown files.
version: 1.0.0
triggers:
  - "trade gold"
  - "start gold agent"
  - "analyze xauusd"
  - "review gold trades"
---

# Gold Day Trading Agent (XAUUSD)

An autonomous, multi-modal day-trading agent designed to systematically trade Gold (`XAUUSD`) with a primary objective of achieving **>= 3% net daily profit on capital** while strictly managing drawdown, and continuously learning from mistakes recorded in Markdown format.

## System Workflow Loop

The agent runs an autonomous loop observing the market on M15 and H1 timeframes:

```
+------------------------------------------------------------------------------------+
| 1. SYNCHRONIZE ACCOUNT & RISK GATES                                                |
|    - Query Balance & Equity from Broker (MT4 or Paper)                             |
|    - Check Daily Target: Has >= +3.0% net gain been reached today?                 |
|      -> YES: Lock trading, protect gains, log to journal, enter STANDBY.           |
|    - Check Daily Drawdown: Has -2.0% max loss been reached today?                  |
|      -> YES: Cease trading, protect capital, trigger emergency post-mortem.         |
+-----------------------------------------+------------------------------------------+
                                          | Passed Risk Gates
                                          v
+------------------------------------------------------------------------------------+
| 2. MARKET DATA & CHART GENERATION                                                  |
|    - Fetch latest M15 and H1 OHLCV candlestick data for XAUUSD                     |
|    - Compute Indicators: EMA(20, 50, 200), ATR(14), RSI(14), S/R Key Zones        |
|    - Generate high-resolution annotated candlestick chart image                    |
+-----------------------------------------+------------------------------------------+
                                          |
                                          v
+------------------------------------------------------------------------------------+
| 3. MULTIMODAL CONFLUENCE ENGINE                                                    |
|    - Chart Vision: Scan visual patterns (pin bars, engulfing, trend breaks)        |
|    - Quantitative Rules: Trend alignment (M15 with H1 EMA), RSI pullback, ATR      |
|    - Compute Unified Confluence Score (-100 to +100)                               |
+-----------------------------------------+------------------------------------------+
                                          | Score >= +75 (BUY) or <= -75 (SELL)
                                          v
+------------------------------------------------------------------------------------+
| 4. PRE-TRADE MISTAKE PREVENTION FILTER                                             |
|    - Read active rules from `journal/learned_rules.md`                             |
|    - Read past mistakes from `journal/mistakes_database.md`                        |
|    - Validate setup against past failure patterns                                  |
|      -> If violated: Reject trade, log preventive rationale, return to loop.       |
+-----------------------------------------+------------------------------------------+
                                          | Passed All Mistake Checks
                                          v
+------------------------------------------------------------------------------------+
| 5. POSITION SIZING & EXECUTION                                                     |
|    - Calculate Lot Size: Max 1.0% - 1.5% equity risk divided by ATR stop distance  |
|    - SL placed at swing high/low +/- 1.5*ATR                                       |
|    - TP placed to guarantee at least 1:1.5 - 1:2 Risk-to-Reward ratio               |
|    - Dispatch Order to Broker (MT4 Expert Advisor or Paper Broker)                 |
+-----------------------------------------+------------------------------------------+
                                          |
                                          v
+------------------------------------------------------------------------------------+
| 6. POSITION MONITORING & EXIT                                                      |
|    - Track active orders (trailing stop, break-even shift at 1:1 RR)               |
|    - Detect TP / SL fill event                                                     |
+-----------------------------------------+------------------------------------------+
                                          | Trade Closed
                                          v
+------------------------------------------------------------------------------------+
| 7. SELF-LEARNING & POST-TRADE AUTOPSY                                              |
|    - Compare entry hypothesis with actual exit outcome                             |
|    - Identify root cause if loss or suboptimal exit occurred                       |
|    - Write post-trade report to `journal/trades/<trade_id>.md`                     |
|    - Update `journal/mistakes_database.md`                                         |
|    - Derive actionable rule and append to `journal/learned_rules.md`               |
+------------------------------------------------------------------------------------+
```

## Sub-Skills Directory

The agent relies on specialized sub-skills located under `skills/`:

| Skill | Path | Description |
|-------|------|-------------|
| **Market Analyzer** | `skills/market_analyzer/SKILL.md` | Quantitative technical analysis, indicators, S/R zones |
| **Chart Vision** | `skills/chart_vision/SKILL.md` | Candlestick rendering & visual pattern recognition |
| **Risk Manager** | `skills/risk_manager/SKILL.md` | 3% daily target lock, lot sizing, drawdown controls |
| **MT4 Bridge** | `skills/mt4_bridge/SKILL.md` | Communication protocol with MetaTrader 4 EA |
| **Trade Reflector** | `skills/trade_reflector/SKILL.md` | Post-trade autopsy & Markdown mistake learning |
