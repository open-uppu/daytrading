---
name: chart-vision
description: Multimodal visual chart analysis skill that renders candlestick charts with indicators and identifies visual price action patterns (pin bars, engulfing, breakouts).
version: 1.0.0
---

# Chart Vision Skill

This skill converts numerical market data into high-contrast visual candlestick charts and performs vision-based price action analysis using either Multimodal LLMs (Gemini / OpenAI Vision) or a built-in computer vision heuristic engine.

## Visual Rendering Standards

- **Chart Style**: Dark theme (OLED black background, green bullish candles `#26a69a`, red bearish candles `#ef5350`).
- **Overlays**:
  - Yellow line: EMA(20)
  - Cyan line: EMA(50)
  - Magenta line: EMA(200)
  - Semi-transparent horizontal bands: Key Support (green) & Resistance (red)
  - Bottom panel: RSI(14) with 30, 50, 70 reference bounds
- **Resolution**: 1200x800 px, saved to `artifacts/charts/chart_<timeframe>_<timestamp>.png`.

## Visual Pattern Recognition Targets

1. **Pin Bar / Hammer Rejection**:
   - Long shadow at key EMA or S/R zone (wick length >= 60% of entire candle range).
   - Indicates sharp liquidity sweep and reversal rejection.

2. **Bullish / Bearish Engulfing**:
   - Candle body completely covers previous candle body after a healthy pullback.
   - Confirms institutional volume entering the market.

3. **Break & Retest Confirmation**:
   - Visible clean break through consolidation level followed by a low-volume retest and directional continuation candle.

4. **Multi-Candle Exhaustion**:
   - Diminishing candle bodies with expanding upper/lower wicks approaching a major level.

## Output Specification

```json
{
  "chart_image_path": "artifacts/charts/chart_M15_latest.png",
  "vision_model": "heuristic_vision_v1",
  "pattern_detected": "BULLISH_PIN_BAR_REJECTION",
  "confidence": 88,
  "visual_bias": "STRONG_BUY",
  "visual_observations": [
    "Clean bounce off EMA 50 support band at 2642.0",
    "Long lower wick showing buyer absorption",
    "No immediate overhead resistance for at least 12 dollars"
  ]
}
```
