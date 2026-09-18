"""
Historical Market Data Loader for Gold (XAUUSD).
Downloads, cleans, caches, and enriches real historical candlestick data.
"""

from typing import Optional
from pathlib import Path
import json
import urllib.request
import logging
import pandas as pd
import numpy as np
from datetime import datetime

from config import config

logger = logging.getLogger("data_loader")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def fetch_yahoo_gold_data(interval: str = "15m", range_str: str = "60d") -> pd.DataFrame:
    """Fetches real Gold (GC=F) candlestick data from Yahoo Finance API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval={interval}&range={range_str}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = json.loads(resp.read().decode('utf-8'))
        
    result = raw['chart']['result'][0]
    timestamps = result['timestamp']
    quote = result['indicators']['quote'][0]
    
    opens = quote.get('open', [])
    highs = quote.get('high', [])
    lows = quote.get('low', [])
    closes = quote.get('close', [])
    volumes = quote.get('volume', [])
    
    dates = [datetime.fromtimestamp(ts) for ts in timestamps]
    
    df = pd.DataFrame({
        'timestamp': dates,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes
    })
    
    # Drop rows with nulls
    df = df.dropna().reset_index(drop=True)
    for col in ['open', 'high', 'low', 'close']:
        df[col] = df[col].astype(float).round(2)
        
    df['volume'] = df['volume'].fillna(100).astype(int)
    return df


def load_historical_data(
    timeframe: str = "M15",
    force_refresh: bool = False
) -> pd.DataFrame:
    """
    Loads historical Gold data from local CSV cache or downloads fresh data.
    """
    file_path = DATA_DIR / f"xauusd_{timeframe.lower()}.csv"
    
    if file_path.exists() and not force_refresh:
        logger.info(f"Loading cached {timeframe} data from {file_path}")
        df = pd.read_csv(file_path, parse_dates=['timestamp'])
        return df

    logger.info(f"Downloading fresh {timeframe} Gold historical data from Yahoo Finance...")
    try:
        if timeframe.upper() == "M15":
            df = fetch_yahoo_gold_data(interval="15m", range_str="60d")
        elif timeframe.upper() == "H1":
            df = fetch_yahoo_gold_data(interval="1h", range_str="730d")
        elif timeframe.upper() == "M5":
            df = fetch_yahoo_gold_data(interval="5m", range_str="60d")
        else:
            df = fetch_yahoo_gold_data(interval="15m", range_str="60d")
            
        df.to_csv(file_path, index=False)
        logger.info(f"Saved {len(df)} bars to {file_path}")
        return df
        
    except Exception as e:
        logger.warning(f"Failed to fetch live data from Yahoo Finance: {e}. Generating high-fidelity simulation.")
        return generate_fallback_gold_data(bars=2000)


def generate_fallback_gold_data(bars: int = 2000) -> pd.DataFrame:
    """Generates synthetic high-fidelity gold dataset if offline."""
    np.random.seed(101)
    base = 2600.0
    dates = pd.date_range(end=datetime.now(), periods=bars, freq='15min')
    
    # Regime switching walk
    closes = [base]
    regime = 1  # 1 = bull, -1 = bear, 0 = chop
    
    for i in range(bars - 1):
        if i % 150 == 0:
            regime = np.random.choice([1, -1, 0], p=[0.45, 0.35, 0.20])
            
        drift = regime * 0.4
        noise = np.random.normal(0, 2.0)
        closes.append(round(closes[-1] + drift + noise, 2))
        
    closes = np.array(closes)
    highs = np.round(closes + np.abs(np.random.normal(1.5, 0.8, bars)), 2)
    lows = np.round(closes - np.abs(np.random.normal(1.5, 0.8, bars)), 2)
    opens = np.round(closes + np.random.normal(0, 0.9, bars), 2)
    volume = np.random.randint(100, 3000, bars)
    
    return pd.DataFrame({
        'timestamp': dates,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volume
    })
