"""
High-resolution candlestick chart generator for Multimodal Vision Analysis.
Produces clean, annotated dark-mode charts suitable for LLM vision models and human inspection.
"""

from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime
import matplotlib
matplotlib.use('Agg')  # Headless backend
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import pandas as pd
import numpy as np

from config import config
from core.indicators import compute_all_indicators, detect_support_resistance


def generate_candlestick_chart(
    df: pd.DataFrame,
    timeframe: str = "M15",
    symbol: str = "XAUUSD",
    save_path: Optional[Path] = None,
    num_candles: int = 50
) -> Path:
    """
    Renders a multi-panel candlestick chart with EMAs, S/R zones, and RSI.
    Returns the Path to the saved chart image.
    """
    if len(df) < 20:
        raise ValueError("Need at least 20 bars of data to generate chart")
        
    df_enriched = compute_all_indicators(df)
    subset = df_enriched.tail(num_candles).copy().reset_index(drop=True)
    sr_levels = detect_support_resistance(df_enriched.tail(100))
    
    # Setup Figure and Subplots (Upper: Candlesticks + EMAs, Lower: RSI)
    fig, (ax_main, ax_rsi) = plt.subplots(
        2, 1, figsize=(14, 8),
        gridspec_kw={'height_ratios': [3.5, 1]},
        facecolor='#121417'
    )
    
    ax_main.set_facecolor('#121417')
    ax_rsi.set_facecolor('#121417')
    
    # 1. Render Candlesticks on ax_main
    width = 0.6
    width2 = 0.1
    
    for i, row in subset.iterrows():
        open_p = row['open']
        close_p = row['close']
        high_p = row['high']
        low_p = row['low']
        
        color = '#00E676' if close_p >= open_p else '#FF5252'
        
        # Wick
        ax_main.plot([i, i], [low_p, high_p], color=color, linewidth=1.2, zorder=2)
        # Body
        lower_body = min(open_p, close_p)
        body_height = max(abs(close_p - open_p), 0.05)
        rect = patches.Rectangle(
            (i - width / 2, lower_body),
            width, body_height,
            linewidth=0.5, edgecolor=color, facecolor=color, zorder=3
        )
        ax_main.add_patch(rect)
        
    # 2. Overlay EMAs
    x_coords = np.arange(len(subset))
    if 'ema_20' in subset.columns:
        ax_main.plot(x_coords, subset['ema_20'], label='EMA 20', color='#FFD600', linewidth=1.4, alpha=0.9)
    if 'ema_50' in subset.columns:
        ax_main.plot(x_coords, subset['ema_50'], label='EMA 50', color='#00E5FF', linewidth=1.4, alpha=0.9)
    if 'ema_200' in subset.columns:
        ax_main.plot(x_coords, subset['ema_200'], label='EMA 200', color='#E040FB', linewidth=1.6, alpha=0.9)
        
    # 3. Overlay Support & Resistance Zones
    for supp in sr_levels.get("support", []):
        if subset['low'].min() <= supp <= subset['high'].max():
            ax_main.axhline(supp, color='#00C853', linestyle='--', linewidth=0.9, alpha=0.6)
            ax_main.text(0, supp, f" Supp {supp:.1f}", color='#00C853', fontsize=9, va='bottom')
            
    for res in sr_levels.get("resistance", []):
        if subset['low'].min() <= res <= subset['high'].max():
            ax_main.axhline(res, color='#D50000', linestyle='--', linewidth=0.9, alpha=0.6)
            ax_main.text(0, res, f" Res {res:.1f}", color='#D50000', fontsize=9, va='top')
            
    # Mark Latest Price
    latest_close = float(subset.iloc[-1]['close'])
    ax_main.axhline(latest_close, color='#FFFFFF', linestyle=':', linewidth=1.0, alpha=0.7)
    ax_main.text(
        len(subset) - 1, latest_close, f" {latest_close:.2f}",
        color='#FFFFFF', fontsize=10, weight='bold',
        bbox=dict(boxstyle="square,pad=0.2", fc="#263238", ec="#FFFFFF", lw=0.8)
    )
    
    # Configure ax_main cosmetics
    ax_main.set_xlim(-1, len(subset) + 3)
    ax_main.grid(True, color='#263238', linestyle=':', alpha=0.5)
    ax_main.set_title(
        f"{symbol} - {timeframe} Intraday Chart | Daily Target: 3% | Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        color='#ECEFF1', fontsize=12, pad=10, weight='bold'
    )
    ax_main.tick_params(colors='#90A4AE', labelsize=9)
    ax_main.legend(loc='upper left', facecolor='#1A232A', edgecolor='#37474F', labelcolor='#CFD8DC')
    
    # 4. Render RSI on ax_rsi
    if 'rsi_14' in subset.columns:
        ax_rsi.plot(x_coords, subset['rsi_14'], color='#7C4DFF', linewidth=1.5, label='RSI 14')
        ax_rsi.axhline(70, color='#FF5252', linestyle='--', linewidth=0.8, alpha=0.6)
        ax_rsi.axhline(50, color='#78909C', linestyle=':', linewidth=0.8, alpha=0.5)
        ax_rsi.axhline(30, color='#00E676', linestyle='--', linewidth=0.8, alpha=0.6)
        ax_rsi.fill_between(x_coords, 30, 70, color='#311B92', alpha=0.15)
        ax_rsi.set_ylim(15, 85)
        ax_rsi.set_ylabel("RSI(14)", color='#90A4AE', fontsize=9)
        ax_rsi.tick_params(colors='#90A4AE', labelsize=8)
        ax_rsi.grid(True, color='#263238', linestyle=':', alpha=0.5)
        
    plt.tight_layout()
    
    # Save Image
    if save_path is None:
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = config.charts_dir / f"chart_{symbol}_{timeframe}_{timestamp_str}.png"
        
    fig.savefig(save_path, dpi=120, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    
    return save_path
