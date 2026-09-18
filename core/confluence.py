"""
Confluence Scoring Engine.
Combines Quantitative Technical Indicators with Multimodal Chart Vision to produce high-probability trading signals.
"""

from typing import Dict, Any, Tuple
import pandas as pd
from config import config
from core.indicators import compute_all_indicators


class ConfluenceEngine:
    """Calculates unified confluence between quantitative indicator signals and visual chart insights."""

    def __init__(self, threshold: float = None):
        self.threshold = threshold or config.confluence_threshold

    def evaluate(
        self,
        df_m15: pd.DataFrame,
        vision_result: Dict[str, Any],
        df_h1: pd.DataFrame = None
    ) -> Dict[str, Any]:
        """
        Evaluates overall market state and returns trading signal decision.
        """
        df_m15_ind = compute_all_indicators(df_m15)
        latest = df_m15_ind.iloc[-1]
        
        close_p = float(latest['close'])
        ema_20 = float(latest['ema_20'])
        ema_50 = float(latest['ema_50'])
        ema_200 = float(latest['ema_200'])
        rsi = float(latest['rsi_14'])
        atr = float(latest['atr_14'])
        
        quant_score = 0
        quant_reasons = []
        
        # 1. Trend & Momentum Alignment (Quant)
        # Check EMA 20 / 50 cross if previous bar available
        prev_row = df_m15_ind.iloc[-2] if len(df_m15_ind) > 1 else latest
        prev_ema_20 = float(prev_row.get('ema_20', ema_20))
        prev_ema_50 = float(prev_row.get('ema_50', ema_50))
        bullish_cross = (prev_ema_20 <= prev_ema_50) and (ema_20 > ema_50)
        bearish_cross = (prev_ema_20 >= prev_ema_50) and (ema_20 < ema_50)

        if close_p > ema_200:
            if bullish_cross and 45.0 <= rsi <= 65.0:
                quant_score += 45
                quant_reasons.append("VALIDATED WINNER: Bullish EMA 20/50 Cross above EMA 200 with expanding RSI")
            elif close_p > ema_20 > ema_50:
                quant_score += 35
                quant_reasons.append("Bullish EMA alignment (Price > EMA20 > EMA50 > EMA200)")
            elif close_p > ema_50:
                quant_score += 20
                quant_reasons.append("Price above EMA50 & EMA200 uptrend")
        elif close_p < ema_200:
            if bearish_cross and 35.0 <= rsi <= 55.0:
                quant_score -= 45
                quant_reasons.append("VALIDATED WINNER: Bearish EMA 20/50 Cross below EMA 200 with declining RSI")
            elif close_p < ema_20 < ema_50:
                quant_score -= 35
                quant_reasons.append("Bearish EMA alignment (Price < EMA20 < EMA50 < EMA200)")
            elif close_p < ema_50:
                quant_score -= 20
                quant_reasons.append("Price below EMA50 & EMA200 downtrend")
            
        # Higher Timeframe Confirmation (if provided)
        if df_h1 is not None and len(df_h1) >= 20:
            df_h1_ind = compute_all_indicators(df_h1)
            h1_close = float(df_h1_ind.iloc[-1]['close'])
            h1_ema50 = float(df_h1_ind.iloc[-1]['ema_50'])
            if h1_close > h1_ema50:
                quant_score += 15
                quant_reasons.append("H1 Trend is Bullish (> EMA50)")
            else:
                quant_score -= 15
                quant_reasons.append("H1 Trend is Bearish (< EMA50)")
                
        # 2. RSI Momentum & Pullback Check
        if 42.0 <= rsi <= 60.0 and quant_score > 0:
            quant_score += 15
            quant_reasons.append(f"RSI in healthy bullish continuation zone ({rsi:.1f})")
        elif 40.0 <= rsi <= 58.0 and quant_score < 0:
            quant_score -= 15
            quant_reasons.append(f"RSI in healthy bearish continuation zone ({rsi:.1f})")
        elif rsi > 70.0:
            quant_score -= 20
            quant_reasons.append(f"RSI Overbought ({rsi:.1f}), avoiding chase")
        elif rsi < 30.0:
            quant_score += 20
            quant_reasons.append(f"RSI Oversold ({rsi:.1f}), avoiding sell-chase")

        # 3. Vision Analysis Integration
        vision_score = float(vision_result.get("vision_score", 0))
        vision_pattern = vision_result.get("pattern_detected", "NONE")
        vision_obs = vision_result.get("observations", [])
        
        # Weighted Final Score: 50% Quantitative + 50% Vision
        final_confluence_score = round(0.50 * quant_score + 0.50 * vision_score, 1)
        
        # Determine Decision
        action = "HOLD"
        reason = "Market in consolidation or lacking confluence"
        
        if final_confluence_score >= self.threshold:
            action = "BUY"
            reason = f"High Bullish Confluence ({final_confluence_score:.1f} >= {self.threshold}): {vision_pattern}"
        elif final_confluence_score <= -self.threshold:
            action = "SELL"
            reason = f"High Bearish Confluence ({final_confluence_score:.1f} <= -{self.threshold}): {vision_pattern}"
            
        return {
            "action": action,
            "confluence_score": final_confluence_score,
            "quant_score": quant_score,
            "vision_score": vision_score,
            "reason": reason,
            "current_price": close_p,
            "atr": atr,
            "rsi": rsi,
            "pattern_detected": vision_pattern,
            "quant_reasons": quant_reasons,
            "vision_observations": vision_obs
        }
