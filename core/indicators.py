"""
Vectorized and robust technical indicator computations for Gold (XAUUSD).
"""

from typing import Dict, Any, List, Tuple
import numpy as np
import pandas as pd


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Calculates Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculates Average True Range."""
    high = df['high']
    low = df['low']
    close_prev = df['close'].shift(1)
    
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()
    # Fill early NaNs with expanding mean
    return atr.bfill().fillna(tr.mean())


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculates Relative Strength Index (RSI)."""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(window=period, min_periods=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period, min_periods=period).mean()
    
    rs = gain / (loss.replace(0, 0.00001))
    rsi = 100 - (100 / (1 + rs))
    return rsi.bfill().fillna(50.0)


def detect_support_resistance(df: pd.DataFrame, window: int = 20, num_levels: int = 4) -> Dict[str, List[float]]:
    """
    Identifies significant swing highs (resistance) and swing lows (support).
    """
    highs = df['high'].values
    lows = df['low'].values
    
    resistance_levels: List[float] = []
    support_levels: List[float] = []
    
    # Simple rolling peak/trough detection
    for i in range(window, len(df) - window):
        is_high = all(highs[i] >= highs[i - j] for j in range(1, window + 1)) and \
                  all(highs[i] >= highs[i + j] for j in range(1, window + 1))
        if is_high:
            resistance_levels.append(round(float(highs[i]), 2))
            
        is_low = all(lows[i] <= lows[i - j] for j in range(1, window + 1)) and \
                 all(lows[i] <= lows[i + j] for j in range(1, window + 1))
        if is_low:
            support_levels.append(round(float(lows[i]), 2))
            
    # Cluster close levels together (within 2 dollars for gold)
    def cluster_levels(levels: List[float], tolerance: float = 2.5) -> List[float]:
        if not levels:
            return []
        sorted_lvls = sorted(levels)
        clustered = []
        curr_cluster = [sorted_lvls[0]]
        for val in sorted_lvls[1:]:
            if val - curr_cluster[-1] <= tolerance:
                curr_cluster.append(val)
            else:
                clustered.append(float(np.mean(curr_cluster)))
                curr_cluster = [val]
        clustered.append(float(np.mean(curr_cluster)))
        return [round(x, 2) for x in clustered][-num_levels:]

    return {
        "resistance": cluster_levels(resistance_levels, tolerance=2.5),
        "support": cluster_levels(support_levels, tolerance=2.5)
    }


def analyze_candlestick_patterns(row: pd.Series, prev_row: pd.Series = None) -> Dict[str, Any]:
    """
    Analyzes candlestick geometry: body, upper wick, lower wick, and classical reversal patterns.
    """
    open_p = float(row['open'])
    close_p = float(row['close'])
    high_p = float(row['high'])
    low_p = float(row['low'])
    
    total_range = max(high_p - low_p, 0.01)
    body_size = abs(close_p - open_p)
    is_bullish = close_p >= open_p
    
    if is_bullish:
        upper_wick = high_p - close_p
        lower_wick = open_p - low_p
    else:
        upper_wick = high_p - open_p
        lower_wick = close_p - low_p
        
    lower_wick_ratio = lower_wick / total_range
    upper_wick_ratio = upper_wick / total_range
    body_ratio = body_size / total_range
    
    # Pin bar detection (wick >= 60% of total range, body <= 30%)
    bullish_pin = lower_wick_ratio >= 0.60 and body_ratio <= 0.35
    bearish_pin = upper_wick_ratio >= 0.60 and body_ratio <= 0.35
    
    # Engulfing detection
    bullish_engulfing = False
    bearish_engulfing = False
    if prev_row is not None:
        prev_open = float(prev_row['open'])
        prev_close = float(prev_row['close'])
        prev_is_bearish = prev_close < prev_open
        prev_is_bullish = prev_close > prev_open
        
        # Bullish engulfing: prev is red, curr is green and engulfs prev body
        if is_bullish and prev_is_bearish:
            if close_p > prev_open and open_p <= prev_close:
                bullish_engulfing = True
                
        # Bearish engulfing: prev is green, curr is red and engulfs prev body
        if not is_bullish and prev_is_bullish:
            if close_p < prev_open and open_p >= prev_close:
                bearish_engulfing = True

    return {
        "is_bullish": is_bullish,
        "body_ratio": round(body_ratio, 3),
        "upper_wick_ratio": round(upper_wick_ratio, 3),
        "lower_wick_ratio": round(lower_wick_ratio, 3),
        "bullish_pin": bullish_pin,
        "bearish_pin": bearish_pin,
        "bullish_engulfing": bullish_engulfing,
        "bearish_engulfing": bearish_engulfing,
        "total_range": round(total_range, 2)
    }


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Enriches OHLCV DataFrame with all required trading indicators."""
    df = df.copy()
    if 'close' not in df.columns:
        raise ValueError("DataFrame must contain 'close' column")
        
    df['ema_9'] = compute_ema(df['close'], 9)
    df['ema_21'] = compute_ema(df['close'], 21)
    df['ema_20'] = compute_ema(df['close'], 20)
    df['ema_50'] = compute_ema(df['close'], 50)
    df['ema_200'] = compute_ema(df['close'], 200)
    df['atr_14'] = compute_atr(df, 14)
    df['rsi_14'] = compute_rsi(df['close'], 14)
    
    return df
