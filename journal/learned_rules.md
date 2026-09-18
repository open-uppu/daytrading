# Dynamic Trading Rulebook (Learned Rules)

> [!NOTE]
> This rulebook is automatically updated by the Gold Day Trading Agent's Self-Learning Reflector.
> Every prospective trade is checked against these rules before execution.

## Active Rules

### RULE-001: Respect Higher-Timeframe Trend
- **Category**: Trend Alignment
- **Condition**: Do not take BUY orders when M15 and H1 price is below EMA 200, unless a confirmed double-bottom break and retest is verified on H1.
- **Action on Violation**: REJECT trade.
- **Confidence**: High

### RULE-002: Never Buy Directly into Resistance
- **Category**: Key Level Proximity
- **Condition**: If distance to nearest H1/M15 Resistance is less than 1.0 * ATR, do not execute a BUY order (Risk:Reward will be crushed).
- **Action on Violation**: REJECT trade.
- **Confidence**: High

### RULE-003: Never Sell Directly into Support
- **Category**: Key Level Proximity
- **Condition**: If distance to nearest H1/M15 Support is less than 1.0 * ATR, do not execute a SELL order.
- **Action on Violation**: REJECT trade.
- **Confidence**: High

### RULE-004: Minimum Stop-Loss Buffer
- **Category**: Volatility Protection
- **Condition**: Never place Stop-Loss closer than 1.2 * ATR. Tight stop-losses get hunted by normal Gold intraday noise.
- **Action on Violation**: Expand SL to 1.5 * ATR or REJECT trade.
- **Confidence**: High

### RULE-005: Lock In Profits at Daily Target (3%)
- **Category**: Capital Preservation
- **Condition**: Once daily cumulative profit reaches >= +3.0% of starting balance, all new trade entries are prohibited.
- **Action on Violation**: REJECT trade and lock session.
- **Confidence**: Critical

### RULE-006: Trend & Momentum Alignment (Validated #1 Strategy)
- **Category**: High-Probability Execution
- **Condition**: Prioritize trades where M15 EMA 20 and EMA 50 momentum alignment aligns strictly with the macro EMA 200 direction (Longs ONLY above EMA 200, Shorts ONLY below EMA 200).
- **Action on Violation**: Disallow non-aligned momentum trades.
- **Confidence**: Critical (Validated across 4,500+ M15 Gold bars with 74.1% Win Rate & +8.04% Net Return)

### RULE-007: Avoid Counter-Trend Reversion in Strong Trends
- **Category**: Mistake Prevention
- **Condition**: Do not attempt Bollinger Band mean reversion or picking tops/bottoms when Gold has a strong directional slope on EMA 50. Reversion lost -15.38% in backtesting due to Gold's strong trend continuation.
- **Action on Violation**: REJECT counter-trend reversion trades.
- **Confidence**: High
