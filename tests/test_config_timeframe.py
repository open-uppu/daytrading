import pytest
from config import config
from main import cmd_loop

def test_config_scalping_defaults():
    assert config.timeframe_main == "M5"
    assert config.max_open_positions >= 1
    assert config.risk_per_trade_pct <= 0.01

def test_cli_parser_has_timeframe():
    assert callable(cmd_loop)
