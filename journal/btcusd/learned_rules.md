# BTCUSD (Bitcoin) Specialist Learned Rules
> Dynamic Rulebook maintained by Bitcoin Specialist Agent.
> Backtested Optimal Strategy: **Strategy A (EMA Pullback Rejection - Hit 3% Target 10 Days)**

---

### RULE-BTC-001: Wick Rejection Confirmation on Crypto Pullback
- **Category**: Entry Confirmation
- **Condition**: For BUY orders, candle must form a lower rejection wick (hammer/pinbar) tapping EMA 20/50 while EMA 20 > EMA 50. For SELL orders, candle must form an upper rejection wick tapping EMA 20/50 while EMA 20 < EMA 50.
- **Action on Violation**: REJECT trade proposal.
- **Reason**: Bitcoin frequently performs aggressive stop-hunts past moving averages before resuming trend direction.

### RULE-BTC-002: Minimum Stop-Loss Buffer for Bitcoin Volatility
- **Category**: Volatility Buffer
- **Condition**: Stop-Loss distance must be at least 1.5 * ATR ($50.00 minimum distance).
- **Action on Violation**: ADJUST or REJECT order.
- **Reason**: Bitcoin crypto spreads and sudden 1-minute liquidation spikes trigger tight stops.

### RULE-BTC-003: 24/7 Weekend Liquidity Vigilance
- **Category**: Execution Environment
- **Condition**: On low-liquidity weekend periods, reduce lot size by 30% if ATR is below 20-period median ATR.
- **Action on Violation**: Scale down position size.
- **Reason**: Weekend crypto wash trading causes false breakouts.

### RULE-BTC-004: Respect Daily 3% Profit Lock
- **Category**: Capital Preservation
- **Condition**: Once realized daily profit hits +3.0%, stop new entries for the remainder of the session.
- **Action on Violation**: HALT Bitcoin trading until next UTC session.
