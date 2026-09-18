# XAUUSD (Gold) Specialist Learned Rules
> Dynamic Rulebook maintained by Gold Specialist Agent.
> Backtested Winning Strategy: **Strategy D (MTF Momentum Cross - +8.04% Return, 74.1% Win Rate)**

---

### RULE-GOLD-001: Respect Higher Timeframe Macro Trend
- **Category**: Trend Alignment
- **Condition**: Only BUY when price is above EMA 200 on M15/H1. Only SELL when price is below EMA 200.
- **Action on Violation**: REJECT trade proposal.
- **Reason**: Gold exhibits violent momentum expansions; counter-trend scalp positions suffer heavy drawdowns.

### RULE-GOLD-002: Avoid Entering Directly into Key Support / Resistance
- **Category**: Price Action Obstacles
- **Condition**: Distance between entry price and nearest opposing key S/R level must be at least 1.0 * ATR.
- **Action on Violation**: REJECT trade proposal.
- **Reason**: Entering directly into prior swing highs/lows leads to immediate rejection and adverse excursion.

### RULE-GOLD-003: Minimum Stop-Loss Buffer
- **Category**: Volatility Buffer
- **Condition**: Stop-Loss distance must be at least 1.2 * ATR ($2.00 minimum).
- **Action on Violation**: ADJUST or REJECT order.
- **Reason**: Gold M15 noise and spread expansion during session overlaps trigger premature stops.

### RULE-GOLD-004: Respect Daily 3% Profit Lock
- **Category**: Capital Preservation
- **Condition**: Once realized daily profit hits +3.0% (e.g. $300 on $10,000), cease all new trade entries.
- **Action on Violation**: HALT Gold trading until next UTC session.
- **Reason**: Protect accumulated gains and eliminate over-trading risk.
