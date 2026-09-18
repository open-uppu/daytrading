"""
Multi-Asset Historical Market Data Loader for Gold (XAUUSD), Bitcoin (BTCUSD), and Ethereum (ETHUSD).
Downloads, cleans, caches, and enriches real historical candlestick data.
"""

from typing import Optional, Dict, Any
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

# Yahoo Finance Symbol Mapping
YAHOO_SYMBOL_MAP: Dict[str, str] = {
    "XAUUSD": "GC=F",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD"
}

# Asset Contract & Precision Specifications
ASSET_SPECS: Dict[str, Dict[str, Any]] = {
    "XAUUSD": {
        "name": "Gold",
        "contract_size": 100.0,    # 1 standard lot = 100 oz
        "typical_spread": 0.25,    # $0.25
        "min_lot": 0.01,
        "price_precision": 2,
        "market_type": "metals"
    },
    "BTCUSD": {
        "name": "Bitcoin",
        "contract_size": 1.0,      # 1 standard lot = 1 BTC
        "typical_spread": 12.0,    # ~$12 spread on Exness
        "min_lot": 0.01,
        "price_precision": 2,
        "market_type": "crypto"
    },
    "ETHUSD": {
        "name": "Ethereum",
        "contract_size": 1.0,      # 1 standard lot = 1 ETH
        "typical_spread": 1.50,    # ~$1.50 spread on Exness
        "min_lot": 0.01,
        "price_precision": 2,
        "market_type": "crypto"
    }
}


def fetch_yahoo_candle_data(yahoo_symbol: str, interval: str = "15m", range_str: str = "60d") -> pd.DataFrame:
    """Fetches real candlestick data from Yahoo Finance API for any supported symbol."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval={interval}&range={range_str}"
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
    symbol: str = "XAUUSD",
    timeframe: str = "M15",
    force_refresh: bool = False
) -> pd.DataFrame:
    """
    Loads historical data for XAUUSD, BTCUSD, or ETHUSD from local CSV or downloads fresh.
    """
    clean_sym = symbol.upper().replace("-", "").replace("/", "")
    file_path = DATA_DIR / f"{clean_sym.lower()}_{timeframe.lower()}.csv"
    
    if file_path.exists() and not force_refresh:
        logger.info(f"Loading cached {clean_sym} {timeframe} data from {file_path}")
        df = pd.read_csv(file_path, parse_dates=['timestamp'])
        return df

    yahoo_sym = YAHOO_SYMBOL_MAP.get(clean_sym, "GC=F")
    logger.info(f"Downloading fresh {clean_sym} ({yahoo_sym}) {timeframe} data...")
    
    try:
        if timeframe.upper() == "M15":
            df = fetch_yahoo_candle_data(yahoo_sym, interval="15m", range_str="60d")
        elif timeframe.upper() == "H1":
            df = fetch_yahoo_candle_data(yahoo_sym, interval="1h", range_str="730d")
        elif timeframe.upper() == "M5":
            df = fetch_yahoo_candle_data(yahoo_sym, interval="5m", range_str="60d")
        else:
            df = fetch_yahoo_candle_data(yahoo_sym, interval="15m", range_str="60d")
            
        df.to_csv(file_path, index=False)
        logger.info(f"Saved {len(df)} bars to {file_path}")
        return df
        
    except Exception as e:
        logger.warning(f"Failed to fetch live data for {clean_sym}: {e}. Generating fallback dataset.")
        return generate_fallback_data(symbol=clean_sym, bars=2000)


def generate_fallback_data(symbol: str = "XAUUSD", bars: int = 2000) -> pd.DataFrame:
    """Generates synthetic high-fidelity dataset if offline."""
    base_prices = {"XAUUSD": 2650.0, "BTCUSD": 63000.0, "ETHUSD": 2600.0}
    base = base_prices.get(symbol.upper(), 2600.0)
    vol_scale = base * 0.0015
    
    np.random.seed(101)
    dates = pd.date_range(end=datetime.now(), periods=bars, freq='15min')
    
    closes = [base]
    regime = 1
    
    for i in range(bars - 1):
        if i % 150 == 0:
            regime = np.random.choice([1, -1, 0], p=[0.45, 0.35, 0.20])
        drift = regime * (vol_scale * 0.2)
        noise = np.random.normal(0, vol_scale)
        closes.append(round(closes[-1] + drift + noise, 2))
        
    closes = np.array(closes)
    highs = np.round(closes + np.abs(np.random.normal(vol_scale * 0.6, vol_scale * 0.2, bars)), 2)
    lows = np.round(closes - np.abs(np.random.normal(vol_scale * 0.6, vol_scale * 0.2, bars)), 2)
    opens = np.round(closes + np.random.normal(0, vol_scale * 0.3, bars), 2)
    volume = np.random.randint(100, 5000, bars)
    
    return pd.DataFrame({
        'timestamp': dates,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volume
    })


# Backward compatibility alias
generate_fallback_gold_data = generate_fallback_data
