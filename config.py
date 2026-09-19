"""
Configuration for Agentic Gold (XAUUSD) Day Trading System
"""

import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent

class TradingConfig(BaseSettings):
    # Trading Symbol & Broker
    symbol: str = "XAUUSD"
    broker_mode: str = "paper"  # "paper" or "mt4"
    
    # Financial & Risk Parameters
    initial_balance: float = 10000.0
    daily_target_pct: float = 0.03   # 3% target per day ($300 on $10,000)
    daily_max_loss_pct: float = 0.02 # 2% max daily loss cutoff ($200 on $10,000)
    risk_per_trade_pct: float = 0.005  # 0.5% per trade for scalping
    min_rr_ratio: float = 1.5        # Minimum 1:1.5 Risk-to-Reward ratio
    target_rr_ratio: float = 2.0     # Preferred 1:2.0 Risk-to-Reward ratio
    trailing_be_enabled: bool = True # Enable Dynamic Breakeven Trailing for 80%+ Win Rate
    trailing_be_trigger_r: float = 0.80 # Move SL to Breakeven when trade reaches +0.8R
    ml_filter_enabled: bool = True   # Enable ML Meta-Labeling confidence filter
    ml_confidence_threshold: float = 0.75 # Confidence threshold (0.75 - 0.85)
    
    # Gold specific contract details
    contract_size: float = 100.0     # 1 standard lot = 100 oz
    min_lot: float = 0.01
    max_lot: float = 5.0
    spread_points: float = 0.25      # 25 cents spread ($25 on 1 lot)
    
    # Technical Analysis Parameters
    timeframe_main: str = "M5"
    timeframe_htf: str = "M15"
    ema_fast: int = 9
    ema_medium: int = 21
    ema_slow: int = 200
    atr_period: int = 14
    rsi_period: int = 14
    confluence_threshold: float = 75.0  # Confluence score >= 75 required for entry
    
    # Loop & Observation settings
    loop_interval_sec: int = 10       # Poll every 10 seconds for high-frequency scalping
    max_open_positions: int = 3       # Allow up to 3 concurrent scalp positions per asset
    
    # Paths
    project_root: Path = BASE_DIR
    artifacts_dir: Path = BASE_DIR / "artifacts"
    charts_dir: Path = BASE_DIR / "artifacts" / "charts"
    journal_dir: Path = BASE_DIR / "journal"
    trades_dir: Path = BASE_DIR / "journal" / "trades"
    learned_rules_file: Path = BASE_DIR / "journal" / "learned_rules.md"
    mistakes_db_file: Path = BASE_DIR / "journal" / "mistakes_database.md"
    
    # MT5 Bridge & Account Settings
    mt5_server: str = os.getenv("MT5_SERVER", "Exness-MT5Trial14")
    mt5_login: int = int(os.getenv("MT5_LOGIN", "416387559"))
    # Credentials must come from the runtime environment; never ship a
    # broker password in source control or use a source-code fallback.
    mt5_password: str = os.getenv("MT5_PASSWORD", "")
    mt5_host: str = os.getenv("MT5_HOST", "127.0.0.1")
    mt5_port: int = int(os.getenv("MT5_PORT", "8000"))
    mt5_files_dir: str = os.getenv("MT5_FILES_DIR", "")
    
    # MT4 Legacy Bridge Settings
    mt4_host: str = "127.0.0.1"
    mt4_port: int = 8000
    mt4_files_dir: str = ""
    
    # Vision Model Settings
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    ai_base_url: str = os.getenv("AI_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://ollama.com/v1"))
    ai_api_key: str = os.getenv("AI_API_KEY", "")
    ai_model: str = os.getenv("AI_MODEL", "minimax-m3:cloud")
    vision_provider: str = os.getenv("VISION_PROVIDER", "auto")  # "ollama", "gemini", "openai", "heuristic", or "auto"

    model_config = {"env_file": ".env", "extra": "allow"}

config = TradingConfig()

# Ensure directories exist
config.artifacts_dir.mkdir(parents=True, exist_ok=True)
config.charts_dir.mkdir(parents=True, exist_ok=True)
config.journal_dir.mkdir(parents=True, exist_ok=True)
config.trades_dir.mkdir(parents=True, exist_ok=True)
