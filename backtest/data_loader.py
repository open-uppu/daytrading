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
    "ETHUSD": "ETH-USD",
    "XAGUSD": "SI=F",       # Silver futures
    "XPTUSD": "PL=F",       # Platinum futures
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "UKOIL": "BZ=F",        # Brent Crude futures
    "XNGUSD": "NG=F",       # Henry Hub Natural Gas futures
}

# Asset Contract & Precision Specifications
ASSET_SPECS: Dict[str, Dict[str, Any]] = {
    "XAUUSD": {
        "name": "Gold",
        "contract_size": 100.0,    # 1 standard lot = 100 oz
        "typical_spread": 0.25,    # $0.25
        "min_lot": 0.01,
        "price_precision": 2,
        "market_type": "metals",
        "min_sl_dist": 0.5         # engine.py default -- keep XAUUSD's tested/published numbers unchanged
    },
    "BTCUSD": {
        "name": "Bitcoin",
        "contract_size": 1.0,      # 1 standard lot = 1 BTC
        "typical_spread": 12.0,    # ~$12 spread on Exness
        "min_lot": 0.01,
        "price_precision": 2,
        "market_type": "crypto",
        "min_sl_dist": 0.5         # engine.py default -- keep BTCUSD's tested/published numbers unchanged
    },
    "ETHUSD": {
        "name": "Ethereum",
        "contract_size": 1.0,      # 1 standard lot = 1 ETH
        "typical_spread": 1.50,    # ~$1.50 spread on Exness
        "min_lot": 0.01,
        "price_precision": 2,
        "market_type": "crypto",
        "min_sl_dist": 0.5         # engine.py default -- keep ETHUSD's tested/published numbers unchanged
    },
    "XAGUSD": {
        "name": "Silver",
        "contract_size": 5000.0,   # 1 standard lot = 5000 troy oz (confirmed Exness spec)
        "typical_spread": 0.03,
        "min_lot": 0.01,
        "price_precision": 3,
        "market_type": "metals",
        "min_sl_dist": 0.5         # verified non-zero trade counts at this floor
    },
    "XPTUSD": {
        "name": "Platinum",
        "contract_size": 100.0,    # 1 standard lot = 100 troy oz (confirmed Exness spec)
        "typical_spread": 1.50,
        "min_lot": 0.01,
        "price_precision": 2,
        "market_type": "metals"
    },
    "EURUSD": {
        "name": "Euro/US Dollar",
        "contract_size": 100000.0,  # 1 standard lot = 100,000 EUR (universal forex convention)
        "typical_spread": 0.00010,
        "min_lot": 0.01,
        "price_precision": 5,
        "market_type": "forex",
        # engine.py's default 0.5 floor is tuned for Gold's ~2650 price scale;
        # EURUSD trades around ~1.08, so that floor rejects every real signal
        # (confirmed: GBPUSD with the old hardcoded 0.5 produced 0 trades on
        # all 5 strategies). ~8 pips, well under a realistic M15 ATR.
        "min_sl_dist": 0.0008,
        # engine.py's default breakeven buffer (0.20) is ~2000 pips here --
        # confirmed it fabricated phantom fills at entry+/-0.20 mislabeled
        # "SL_HIT" (actually huge unrealistic wins). ~2 pips, small like the
        # Gold default is relative to Gold's own scale.
        "breakeven_buffer": 0.0002
    },
    "GBPUSD": {
        "name": "British Pound/US Dollar",
        "contract_size": 100000.0,  # 1 standard lot = 100,000 GBP (universal forex convention)
        "typical_spread": 0.00015,
        "min_lot": 0.01,
        "price_precision": 5,
        "market_type": "forex",
        "min_sl_dist": 0.0012,     # ~12 pips; see EURUSD note above
        "breakeven_buffer": 0.0003  # ~3 pips; see EURUSD note above
    },
    "UKOIL": {
        "name": "Brent Crude Oil",
        # ponytail: contract_size unconfirmed against this Exness account -- industry-typical
        # value used as a placeholder. Verify via MT5 Market Watch -> right-click UKOIL ->
        # Specification before trusting any lot-size math derived from this.
        "contract_size": 100.0,     # barrels per lot (typical; NOT verified for this account)
        "typical_spread": 0.03,
        "min_lot": 0.01,
        "price_precision": 2,
        "market_type": "energy"
    },
    "XNGUSD": {
        "name": "Natural Gas",
        # ponytail: same caveat as UKOIL above -- verify in MT5 before trusting lot-size math.
        "contract_size": 10000.0,   # MMBtu per lot (typical; NOT verified for this account)
        "typical_spread": 0.003,
        "min_lot": 0.01,
        "price_precision": 3,
        "market_type": "energy",
        # price trades around ~2-4, so Gold's 0.5 floor would reject every signal like EURUSD did.
        "min_sl_dist": 0.02,
        "breakeven_buffer": 0.006  # see EURUSD note above
    }
}


def fetch_yahoo_candle_data(yahoo_symbol: str, interval: str = "15m", range_str: str = "60d", price_precision: int = 2) -> pd.DataFrame:
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
        # Default 2 is unchanged behavior for Gold/BTC/ETH's price scale. A
        # forex pair (~1.08, moves fractions of a cent per bar) rounded to 2
        # collapses ~98% of bars into duplicate/flat closes -- a fabricated
        # staircase pattern that isn't real price action, and made a mean-
        # reversion strategy show a fake +139% return / 100% win rate.
        df[col] = df[col].astype(float).round(price_precision)
        
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
    price_precision = ASSET_SPECS.get(clean_sym, {}).get("price_precision", 2)
    logger.info(f"Downloading fresh {clean_sym} ({yahoo_sym}) {timeframe} data...")

    try:
        if timeframe.upper() == "M15":
            df = fetch_yahoo_candle_data(yahoo_sym, interval="15m", range_str="60d", price_precision=price_precision)
        elif timeframe.upper() == "H1":
            df = fetch_yahoo_candle_data(yahoo_sym, interval="1h", range_str="730d", price_precision=price_precision)
        elif timeframe.upper() == "M5":
            df = fetch_yahoo_candle_data(yahoo_sym, interval="5m", range_str="60d", price_precision=price_precision)
        else:
            df = fetch_yahoo_candle_data(yahoo_sym, interval="15m", range_str="60d", price_precision=price_precision)
            
        df.to_csv(file_path, index=False)
        logger.info(f"Saved {len(df)} bars to {file_path}")
        return df
        
    except Exception as e:
        logger.warning(f"Failed to fetch live data for {clean_sym}: {e}. Generating fallback dataset.")
        df = generate_fallback_data(symbol=clean_sym, bars=2500, timeframe=timeframe)
        try:
            df.to_csv(file_path, index=False)
        except Exception:
            pass
        return df


def generate_fallback_data(symbol: str = "XAUUSD", bars: int = 2500, timeframe: str = "M5") -> pd.DataFrame:
    """Generates synthetic high-fidelity dataset if offline."""
    base_prices = {
        "XAUUSD": 2650.0, "BTCUSD": 63000.0, "ETHUSD": 2600.0,
        "XAGUSD": 32.0, "XPTUSD": 980.0, "EURUSD": 1.08, "GBPUSD": 1.27,
        "UKOIL": 75.0, "XNGUSD": 3.0,
    }
    base = base_prices.get(symbol.upper(), 2600.0)
    vol_scale = base * 0.0008 if timeframe.upper() == "M5" else base * 0.0015
    freq_str = '5min' if timeframe.upper() == "M5" else '15min'
    
    np.random.seed(101)
    dates = pd.date_range(end=datetime.now(), periods=bars, freq=freq_str)
    
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
