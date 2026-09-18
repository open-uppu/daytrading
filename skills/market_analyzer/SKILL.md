---
name: market-analyzer
description: Quantitative technical analysis skill for Gold (XAUUSD) computing EMA(20, 50, 200), ATR(14), RSI(14), and key Support/Resistance break-and-retest zones.
version: 1.0.0
---

# Market Analyzer Skill

This skill performs quantitative technical analysis on Gold (`XAUUSD`) across multiple timeframes (primarily **M15** for execution and **H1/H4** for higher-timeframe trend context).

## Technical Indicators

1. **Exponential Moving Averages (EMA)**:
   - `EMA(20)`: Fast momentum guide.
   - `EMA(50)`: Medium trend line.
   - `EMA(200)`: Macro directional baseline.
   - **Bullish Confluence**: Price > EMA(20) > EMA(50) > EMA(200).
   - **Bearish Confluence**: Price < EMA(20) < EMA(50) < EMA(200).

2. **Average True Range (ATR 14)**:
   - Measures intraday gold volatility in dollars/points.
   - Used for dynamic Stop-Loss (`SL_dist = 1.5 * ATR`) and Take-Profit calculations.
   - Low volatility warning: If ATR < 40% of 20-period average ATR, avoid entering (chop/consolidation).

3. **Relative Strength Index (RSI 14)**:
   - **Bullish Pullback**: In an uptrend, RSI pulls back to 40 - 50 and bounces upward (not overbought).
   - **Bearish Pullback**: In a downtrend, RSI pulls back to 50 - 60 and turns downward (not oversold).
   - Reject BUY if RSI > 70 (overextended).
   - Reject SELL if RSI < 30 (overextended).

4. **Support & Resistance (S/R) Dynamic Detection**:
   - Identifies local swing highs and swing lows over 50 bars.
   - Flags Break & Retest setups: Candle closes through level, retests with rejection wick.

## Output Specification

The analyzer produces a structured quantitative signal dictionary:
```json
{
  "symbol": "XAUUSD",
  "timeframe": "M15",
  "timestamp": "2026-09-18T16:00:00Z",
  "current_price": 2650.50,
  "trend": "BULLISH",
  "indicators": {
    "ema_20": 2648.20,
    "ema_50": 2642.10,
    "ema_200": 2630.00,
    "atr_14": 4.50,
    "rsi_14": 54.2
  },
  "setup_type": "BREAK_AND_RETEST_SUPPORT",
  "quant_score": 85
}
```
