# ETHUSD (Ethereum) Specialist Learned Rules
> Dynamic Rulebook maintained by Ethereum Specialist Agent.
> Backtested Winning Strategy: **Strategy C (Bollinger Bands & RSI Mean Reversion - +10.22% Return, 3.28% Max Drawdown)**

---

### RULE-ETH-001: Extreme Bollinger Band Boundary Touch Confirmation
- **Category**: Mean Reversion Timing
- **Condition**: For BUY orders, price must pierce or touch the Lower Bollinger Band (20, 2.0) and RSI(14) must be < 35. For SELL orders, price must pierce or touch the Upper Bollinger Band (20, 2.0) and RSI(14) must be > 65.
- **Action on Violation**: REJECT trade proposal.
- **Reason**: Ethereum respects cyclical statistical bands with high reliability; entering in the middle of bands incurs severe chop.

### RULE-ETH-002: Minimum Stop-Loss Buffer for Ethereum
- **Category**: Volatility Buffer
- **Condition**: Stop-Loss distance must be at least 1.5 * ATR ($5.00 minimum distance).
- **Action on Violation**: ADJUST or REJECT order.
- **Reason**: Protects against brief liquidity wicks below lower Bollinger band before snap-back reversal.

### RULE-ETH-003: Band Walking Exit Protocol
- **Category**: Trend Risk Protection
- **Condition**: If price breaks and closes outside the Bollinger band for 3 consecutive M15 candles, trend expansion is underway; exit immediately to preserve capital.
- **Action on Violation**: CLOSE open mean-reversion position.
- **Reason**: Rare high-momentum crypto regime shifts can "walk the bands" and invalidate mean reversion.

### RULE-ETH-004: Respect Daily 3% Profit Lock
- **Category**: Capital Preservation
- **Condition**: Once realized daily profit hits +3.0%, cease all new trade entries.
- **Action on Violation**: HALT Ethereum trading until next UTC session.
