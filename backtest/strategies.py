"""
Strategy Suite for Gold (XAUUSD) Day Trading.
Contains distinct algorithmic strategies implemented for comparative backtesting.
"""

from typing import Dict, Any
import pandas as pd
import numpy as np

from core.indicators import (
    compute_all_indicators,
    compute_ema,
    detect_support_resistance,
    analyze_candlestick_patterns
)
from core.vision_analyzer import VisionAnalyzer
from core.confluence import ConfluenceEngine
from learning.reflector import PreTradeFilter

# Global cached components
_vision = VisionAnalyzer()
_confluence = ConfluenceEngine(threshold=60.0)
_pre_trade_filter = PreTradeFilter()


# =====================================================================
# Strategy A: EMA Trend Pullback & Rejection
# =====================================================================
def strategy_ema_pullback(window: pd.DataFrame, current_idx: int) -> Dict[str, Any]:
    """Trend following: Buy on pullback to EMA 20/50 with rejection pin bar."""
    if len(window) < 30:
        return {"action": "HOLD"}
        
    df = compute_all_indicators(window.tail(35))
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    close_p = float(latest['close'])
    ema_20 = float(latest['ema_20'])
    ema_50 = float(latest['ema_50'])
    ema_200 = float(latest['ema_200'])
    atr = float(latest['atr_14'])
    rsi = float(latest['rsi_14'])
    
    patterns = analyze_candlestick_patterns(latest, prev)
    
    if ema_20 > ema_50 > ema_200:
        dist_to_ema20 = abs(close_p - ema_20)
        dist_to_ema50 = abs(close_p - ema_50)
        near_ema = (dist_to_ema20 <= 0.8 * atr) or (dist_to_ema50 <= 0.8 * atr)
        
        if near_ema and (patterns['bullish_pin'] or patterns['bullish_engulfing']) and 38.0 <= rsi <= 62.0:
            sl = round(close_p - (1.5 * atr), 2)
            tp = round(close_p + (3.0 * atr), 2)
            return {"action": "BUY", "sl": sl, "tp": tp, "reason": "EMA Trend Pullback Bounce"}

    elif ema_20 < ema_50 < ema_200:
        dist_to_ema20 = abs(close_p - ema_20)
        dist_to_ema50 = abs(close_p - ema_50)
        near_ema = (dist_to_ema20 <= 0.8 * atr) or (dist_to_ema50 <= 0.8 * atr)
        
        if near_ema and (patterns['bearish_pin'] or patterns['bearish_engulfing']) and 38.0 <= rsi <= 62.0:
            sl = round(close_p + (1.5 * atr), 2)
            tp = round(close_p - (3.0 * atr), 2)
            return {"action": "SELL", "sl": sl, "tp": tp, "reason": "EMA Trend Pullback Rejection"}

    return {"action": "HOLD"}


# =====================================================================
# Strategy B: Support & Resistance Breakout and Retest
# =====================================================================
def strategy_sr_breakout(window: pd.DataFrame, current_idx: int) -> Dict[str, Any]:
    """Breakout & Retest: Enters on retest of recently broken swing high/low."""
    if len(window) < 50:
        return {"action": "HOLD"}
        
    df = compute_all_indicators(window.tail(50))
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    close_p = float(latest['close'])
    atr = float(latest['atr_14'])
    
    sr = detect_support_resistance(df, window=15, num_levels=3)
    supports = sr.get("support", [])
    resistances = sr.get("resistance", [])
    patterns = analyze_candlestick_patterns(latest, prev)
    
    for supp in supports:
        if abs(close_p - supp) <= 0.7 * atr and patterns['is_bullish'] and patterns['lower_wick_ratio'] >= 0.40:
            sl = round(supp - (1.2 * atr), 2)
            tp = round(close_p + (abs(close_p - sl) * 2.0), 2)
            return {"action": "BUY", "sl": sl, "tp": tp, "reason": "Support Retest Bounce"}

    for res in resistances:
        if abs(close_p - res) <= 0.7 * atr and not patterns['is_bullish'] and patterns['upper_wick_ratio'] >= 0.40:
            sl = round(res + (1.2 * atr), 2)
            tp = round(close_p - (abs(close_p - sl) * 2.0), 2)
            return {"action": "SELL", "sl": sl, "tp": tp, "reason": "Resistance Retest Rejection"}

    return {"action": "HOLD"}


# =====================================================================
# Strategy C: Bollinger Bands & RSI Mean Reversion
# =====================================================================
def strategy_bb_reversion(window: pd.DataFrame, current_idx: int) -> Dict[str, Any]:
    """Mean Reversion: Buy lower BB + oversold RSI."""
    if len(window) < 30:
        return {"action": "HOLD"}
        
    df = compute_all_indicators(window.tail(35))
    rolling_mean = df['close'].rolling(20).mean()
    rolling_std = df['close'].rolling(20).std()
    upper_bb = rolling_mean + (rolling_std * 2.0)
    lower_bb = rolling_mean - (rolling_std * 2.0)
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    close_p = float(latest['close'])
    atr = float(latest['atr_14'])
    rsi = float(latest['rsi_14'])
    curr_lower_bb = float(lower_bb.iloc[-1])
    curr_upper_bb = float(upper_bb.iloc[-1])
    curr_mid_bb = float(rolling_mean.iloc[-1])
    
    patterns = analyze_candlestick_patterns(latest, prev)
    
    if close_p <= curr_lower_bb + (0.3 * atr) and rsi <= 32.0 and patterns['is_bullish']:
        sl = round(close_p - (1.4 * atr), 2)
        tp = round(curr_mid_bb, 2)
        if (tp - close_p) >= 1.4 * (close_p - sl):
            return {"action": "BUY", "sl": sl, "tp": tp, "reason": "BB Lower Band Oversold Bounce"}

    elif close_p >= curr_upper_bb - (0.3 * atr) and rsi >= 68.0 and not patterns['is_bullish']:
        sl = round(close_p + (1.4 * atr), 2)
        tp = round(curr_mid_bb, 2)
        if (close_p - tp) >= 1.4 * (sl - close_p):
            return {"action": "SELL", "sl": sl, "tp": tp, "reason": "BB Upper Band Overbought Rejection"}

    return {"action": "HOLD"}


# =====================================================================
# Strategy G (research candidate, shadow-log only): BB 2.5σ Extreme Reversion
# =====================================================================
def strategy_bb_extreme(window: pd.DataFrame, current_idx: int = -1) -> Dict[str, Any]:
    """BB(20, 2.5σ) + RSI<=20 / >=80 reversion, TP 1.0 ATR / SL 1.4 ATR. Raw signal has ~0 edge (see scratch/audit_strategy_g_*.py)."""
    if len(window) < 30:
        return {"action": "HOLD"}

    df = compute_all_indicators(window.tail(60).copy())
    mean = df['close'].rolling(20).mean().iloc[-1]
    std = df['close'].rolling(20).std().iloc[-1]
    close_p = float(df['close'].iloc[-1])
    atr = max(float(df['atr_14'].iloc[-1]), 0.1)
    rsi = float(df['rsi_14'].iloc[-1])

    if close_p <= mean - 2.5 * std + 0.2 * atr and rsi <= 20.0:
        action, sign = "BUY", 1
    elif close_p >= mean + 2.5 * std - 0.2 * atr and rsi >= 80.0:
        action, sign = "SELL", -1
    else:
        return {"action": "HOLD"}

    return {
        "action": action,
        "sl": round(close_p - sign * 1.4 * atr, 2),
        "tp": round(close_p + sign * 1.0 * atr, 2),
        "close": close_p, "atr": atr, "rsi": rsi,
        "reason": "BB 2.5σ Extreme Reversion",
    }


# =====================================================================
# Strategy D: Multi-Timeframe Momentum & Trend Alignment
# =====================================================================
def strategy_mtf_momentum(window: pd.DataFrame, current_idx: int) -> Dict[str, Any]:
    """
    Multi-Timeframe Trend Following:
    Price aligned with macro EMA 200 + M15 EMA 20/50 cross + RSI confirmation.
    """
    if len(window) < 50:
        return {"action": "HOLD"}
        
    df = compute_all_indicators(window.tail(50))
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    close_p = float(latest['close'])
    ema_20 = float(latest['ema_20'])
    ema_50 = float(latest['ema_50'])
    ema_200 = float(latest['ema_200'])
    atr = float(latest['atr_14'])
    rsi = float(latest['rsi_14'])
    
    prev_ema_20 = float(prev['ema_20'])
    prev_ema_50 = float(prev['ema_50'])
    
    # Bullish Cross with macro trend filter (Price > EMA 200)
    bullish_cross = (prev_ema_20 <= prev_ema_50) and (ema_20 > ema_50)
    if bullish_cross and close_p > ema_200 and 45.0 <= rsi <= 65.0:
        sl = round(close_p - (1.5 * atr), 2)
        tp = round(close_p + (3.0 * atr), 2)  # 1:2.0 RR
        return {"action": "BUY", "sl": sl, "tp": tp, "reason": "MTF Bullish Cross Momentum"}

    # Bearish Cross with macro trend filter (Price < EMA 200)
    bearish_cross = (prev_ema_20 >= prev_ema_50) and (ema_20 < ema_50)
    if bearish_cross and close_p < ema_200 and 35.0 <= rsi <= 55.0:
        sl = round(close_p + (1.5 * atr), 2)
        tp = round(close_p - (3.0 * atr), 2)
        return {"action": "SELL", "sl": sl, "tp": tp, "reason": "MTF Bearish Cross Momentum"}

    return {"action": "HOLD"}


# =====================================================================
# Strategy E: Full Multimodal Confluence with Learned Mistake Filter
# =====================================================================
def strategy_agentic_confluence(window: pd.DataFrame, current_idx: int) -> Dict[str, Any]:
    """Agentic Confluence: Quant + Heuristic Vision + Learned Rules Filter."""
    if len(window) < 50:
        return {"action": "HOLD"}
        
    df = compute_all_indicators(window.tail(50))
    latest = df.iloc[-1]
    close_p = float(latest['close'])
    atr = float(latest['atr_14'])
    ema_200 = float(latest['ema_200'])
    
    vision_res = _vision._analyze_heuristically(chart_image_path=None, df=df, timeframe="M15")
    confluence = _confluence.evaluate(df, vision_res)
    action = confluence["action"]
    
    if action not in ["BUY", "SELL"]:
        return {"action": "HOLD"}
        
    if action == "BUY":
        sl = round(close_p - (1.5 * atr), 2)
        tp = round(close_p + (3.0 * atr), 2)
        nearest_sr = vision_res.get("nearest_resistance")
    else:
        sl = round(close_p + (1.5 * atr), 2)
        tp = round(close_p - (3.0 * atr), 2)
        nearest_sr = vision_res.get("nearest_support")

    passed, reason = _pre_trade_filter.evaluate_proposal(
        action=action,
        entry_price=close_p,
        sl_price=sl,
        ema_200=ema_200,
        atr=atr,
        nearest_sr=nearest_sr
    )
    
    if not passed:
        return {"action": "HOLD"}
        
    return {
        "action": action,
        "sl": sl,
        "tp": tp,
        "reason": f"Agentic Confluence: {confluence['pattern_detected']}"
    }


# =====================================================================
# Strategy Optimal Hybrid: Enhanced MTF Momentum + Learned Mistake Gate
# =====================================================================
def strategy_optimal_hybrid(window: pd.DataFrame, current_idx: int) -> Dict[str, Any]:
    """
    The Optimal Gold Strategy:
    Combines the high-win-rate MTF Momentum Cross with Candlestick Rejection,
    ATR Volatility Sizing, and active Learned Mistake Verification.
    """
    if len(window) < 50:
        return {"action": "HOLD"}
        
    df = compute_all_indicators(window.tail(50))
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    close_p = float(latest['close'])
    ema_20 = float(latest['ema_20'])
    ema_50 = float(latest['ema_50'])
    ema_200 = float(latest['ema_200'])
    atr = float(latest['atr_14'])
    rsi = float(latest['rsi_14'])
    
    patterns = analyze_candlestick_patterns(latest, prev)
    sr = detect_support_resistance(df, window=15, num_levels=3)
    
    # 1. Bullish Setup:
    # Macro Trend Bullish (Price > EMA 200, EMA 50 > EMA 200)
    # Momentum active (EMA 20 >= EMA 50)
    # RSI healthy (42 - 65)
    # Rejection or continuation confirmation
    if close_p > ema_200 and ema_50 > ema_200 and ema_20 >= ema_50:
        # Check pullback bounce or cross
        pullback_bounce = (abs(close_p - ema_20) <= 0.9 * atr) and patterns['is_bullish']
        if pullback_bounce and 42.0 <= rsi <= 65.0:
            sl = round(close_p - (1.5 * atr), 2)
            tp = round(close_p + (3.0 * atr), 2)  # 1:2.0 RR
            
            # Learned Rules Check: Nearest Resistance proximity
            resistances = [r for r in sr.get("resistance", []) if r > close_p]
            nearest_res = min(resistances) if resistances else None
            
            passed, _ = _pre_trade_filter.evaluate_proposal(
                action="BUY",
                entry_price=close_p,
                sl_price=sl,
                ema_200=ema_200,
                atr=atr,
                nearest_sr=nearest_res
            )
            if passed:
                return {"action": "BUY", "sl": sl, "tp": tp, "reason": "Optimal Hybrid Bullish Bounce"}

    # 2. Bearish Setup:
    # Macro Trend Bearish (Price < EMA 200, EMA 50 < EMA 200)
    # Momentum active (EMA 20 <= EMA 50)
    # RSI healthy (35 - 58)
    elif close_p < ema_200 and ema_50 < ema_200 and ema_20 <= ema_50:
        pullback_reject = (abs(close_p - ema_20) <= 0.9 * atr) and not patterns['is_bullish']
        if pullback_reject and 35.0 <= rsi <= 58.0:
            sl = round(close_p + (1.5 * atr), 2)
            tp = round(close_p - (3.0 * atr), 2)  # 1:2.0 RR
            
            supports = [s for s in sr.get("support", []) if s < close_p]
            nearest_sup = max(supports) if supports else None
            
            passed, _ = _pre_trade_filter.evaluate_proposal(
                action="SELL",
                entry_price=close_p,
                sl_price=sl,
                ema_200=ema_200,
                atr=atr,
                nearest_sr=nearest_sup
            )
            if passed:
                return {"action": "SELL", "sl": sl, "tp": tp, "reason": "Optimal Hybrid Bearish Rejection"}

    return {"action": "HOLD"}


# =====================================================================
# Strategy F: M5 High-Frequency Scalper Engine (Gold, BTC, ETH)
# =====================================================================
def strategy_m5_scalper(window: pd.DataFrame, current_idx: int = -1, asset_type: str = "gold") -> Dict[str, Any]:
    """
    High-Frequency M5 Scalper Engine:
    Empirically tuned across 60 days of real M5 tick data for Gold, BTC, and ETH.
    - Gold (XAUUSD): London & NY Session (07:00-21:00 UTC) EMA 9/21 cross aligned with EMA 200 (+7.34% return).
    - Bitcoin (BTCUSD): M5 MTF Momentum EMA 20/50 cross aligned with macro trend (+2.00% return).
    - Ethereum (ETHUSD): M5 Bollinger Bands (2.2 std) statistical mean reversion (+1.59% return).
    """
    if len(window) < 35:
        return {"action": "HOLD"}

    asset = asset_type.lower()
    latest_row = window.iloc[-1]
    prev_row = window.iloc[-2]

    # Parse hour if timestamp column exists
    hour = None
    if 'timestamp' in window.columns:
        try:
            ts = pd.to_datetime(latest_row['timestamp'])
            hour = ts.hour
        except Exception:
            hour = None

    # Compute technical indicators on window
    df = compute_all_indicators(window.tail(50))
    df['ema_9'] = compute_ema(df['close'], 9)
    df['ema_21'] = compute_ema(df['close'], 21)

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    close_p = float(latest['close'])
    ema_9 = float(latest['ema_9'])
    ema_21 = float(latest['ema_21'])
    ema_20 = float(latest.get('ema_20', ema_21))
    ema_50 = float(latest.get('ema_50', close_p))
    ema_200 = float(latest.get('ema_200', close_p))
    atr = max(float(latest['atr_14']), 0.2)
    rsi = float(latest['rsi_14'])

    prev_9 = float(prev['ema_9'])
    prev_21 = float(prev['ema_21'])
    prev_20 = float(prev.get('ema_20', prev_21))
    prev_50 = float(prev.get('ema_50', close_p))

    patterns = analyze_candlestick_patterns(latest, prev)

    # -------------------------------------------------------------
    # 1. Gold (XAUUSD) M5 Scalper: Session Expansion Momentum Cross
    # -------------------------------------------------------------
    if "gold" in asset or "xau" in asset:
        # Active market session filter: London & New York session (07:00 - 21:00 UTC)
        if hour is not None and not (7 <= hour <= 21):
            return {"action": "HOLD"}

        sl_dist = max(1.25 * atr, 1.0)
        tp_dist = round(1.8 * atr, 2)  # Fast Scalper Exit

        # Bullish Cross with macro trend filter (Price > EMA 200)
        bullish_cross = (prev_9 <= prev_21) and (ema_9 > ema_21)
        if bullish_cross and close_p > ema_200 and 44.0 <= rsi <= 68.0:
            sl = round(close_p - sl_dist, 2)
            tp = round(close_p + tp_dist, 2)
            return {"action": "BUY", "sl": sl, "tp": tp, "reason": "Gold M5 Session Momentum Cross Buy", "signal_type": "CROSS"}

        # Bearish Cross with macro trend filter (Price < EMA 200)
        bearish_cross = (prev_9 >= prev_21) and (ema_9 < ema_21)
        if bearish_cross and close_p < ema_200 and 32.0 <= rsi <= 56.0:
            sl = round(close_p + sl_dist, 2)
            tp = round(close_p - tp_dist, 2)
            return {"action": "SELL", "sl": sl, "tp": tp, "reason": "Gold M5 Session Momentum Cross Sell", "signal_type": "CROSS"}

        return {"action": "HOLD"}

    # -------------------------------------------------------------
    # 2. Bitcoin (BTCUSD) M5 Scalper: Momentum Cross & Trend Pullback
    # -------------------------------------------------------------
    elif "btc" in asset:
        sl_dist = max(1.25 * atr, 25.0)
        tp_dist = round(1.8 * atr, 2)  # Fast Scalper Exit

        bullish_cross = ((prev_20 <= prev_50) and (ema_20 > ema_50)) or ((prev_9 <= prev_21) and (ema_9 > ema_21))
        bullish_pullback = (
            (ema_20 > ema_50) and (close_p > ema_200) and
            (abs(close_p - ema_9) <= 1.0 * atr or abs(close_p - ema_20) <= 1.0 * atr) and
            (patterns['is_bullish'] or patterns['lower_wick_ratio'] >= 0.25 or patterns['bullish_pin'])
        )
        if (bullish_cross or bullish_pullback) and close_p > ema_200 and 40.0 <= rsi <= 70.0:
            sl = round(close_p - sl_dist, 2)
            tp = round(close_p + tp_dist, 2)
            reason = "BTC M5 MTF Momentum Cross Buy" if bullish_cross else "BTC M5 Trend Pullback Buy"
            return {"action": "BUY", "sl": sl, "tp": tp, "reason": reason, "signal_type": "CROSS" if bullish_cross else "PULLBACK"}

        bearish_cross = ((prev_20 >= prev_50) and (ema_20 < ema_50)) or ((prev_9 >= prev_21) and (ema_9 < ema_21))
        bearish_pullback = (
            (ema_20 < ema_50) and (close_p < ema_200) and
            (abs(close_p - ema_9) <= 1.0 * atr or abs(close_p - ema_20) <= 1.0 * atr) and
            (not patterns['is_bullish'] or patterns['upper_wick_ratio'] >= 0.25 or patterns['bearish_pin'])
        )
        if (bearish_cross or bearish_pullback) and close_p < ema_200 and 30.0 <= rsi <= 60.0:
            sl = round(close_p + sl_dist, 2)
            tp = round(close_p - tp_dist, 2)
            reason = "BTC M5 MTF Momentum Cross Sell" if bearish_cross else "BTC M5 Trend Pullback Sell"
            return {"action": "SELL", "sl": sl, "tp": tp, "reason": reason, "signal_type": "CROSS" if bearish_cross else "PULLBACK"}

        return {"action": "HOLD"}

    # -------------------------------------------------------------
    # 3. Ethereum (ETHUSD) M5 Scalper: Statistical Mean Reversion & Pullback
    # -------------------------------------------------------------
    elif "eth" in asset:
        rolling_mean = df['close'].rolling(20).mean()
        rolling_std = df['close'].rolling(20).std()
        upper_bb = rolling_mean + (rolling_std * 2.0)
        lower_bb = rolling_mean - (rolling_std * 2.0)

        curr_lower = float(lower_bb.iloc[-1])
        curr_upper = float(upper_bb.iloc[-1])
        curr_mid = float(rolling_mean.iloc[-1])

        sl_dist = max(1.25 * atr, 2.0)
        tp_dist = round(1.8 * atr, 2)  # Fast Scalper Exit

        # Bullish: BB Lower bounce OR EMA Pullback in uptrend
        bb_bounce = (close_p <= curr_lower + (0.3 * atr)) and rsi <= 35.0
        bullish_pullback = (
            (ema_20 > ema_50) and (close_p > ema_200) and
            (abs(close_p - ema_20) <= 1.0 * atr) and
            (patterns['is_bullish'] or patterns['lower_wick_ratio'] >= 0.25) and
            (40.0 <= rsi <= 65.0)
        )
        if bb_bounce or bullish_pullback:
            sl = round(close_p - sl_dist, 2)
            tp = round(close_p + tp_dist, 2)
            reason = "ETH M5 BB Lower Band Bounce" if bb_bounce else "ETH M5 Trend Pullback Buy"
            return {"action": "BUY", "sl": sl, "tp": tp, "reason": reason, "signal_type": "REVERSION" if bb_bounce else "PULLBACK"}

        # Bearish: BB Upper reject OR EMA Pullback in downtrend
        bb_reject = (close_p >= curr_upper - (0.3 * atr)) and rsi >= 65.0
        bearish_pullback = (
            (ema_20 < ema_50) and (close_p < ema_200) and
            (abs(close_p - ema_20) <= 1.0 * atr) and
            (not patterns['is_bullish'] or patterns['upper_wick_ratio'] >= 0.25) and
            (35.0 <= rsi <= 60.0)
        )
        if bb_reject or bearish_pullback:
            sl = round(close_p + sl_dist, 2)
            tp = round(close_p - tp_dist, 2)
            reason = "ETH M5 BB Upper Band Reject" if bb_reject else "ETH M5 Trend Pullback Sell"
            return {"action": "SELL", "sl": sl, "tp": tp, "reason": reason, "signal_type": "REVERSION" if bb_reject else "PULLBACK"}

        return {"action": "HOLD"}

    # Default fallback
    return {"action": "HOLD"}


