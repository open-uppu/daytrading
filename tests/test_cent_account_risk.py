"""Test Cent Account Scaling and Daily Profit/Loss Target calculations in SquadManager."""
import pytest
from unittest.mock import MagicMock
from agents.squad_manager import SquadManager
from mt5.bridge_server import MT5BridgeBroker


def test_cent_account_squad_scaling():
    # Mock MT5BridgeBroker reporting Cent account telemetry
    mock_broker = MagicMock(spec=MT5BridgeBroker)
    mock_broker.in_process = True
    from datetime import datetime, timezone
    mock_broker.get_account_info.return_value = {
        "account_number": 9876543,
        "server": "Exness-MT5Cent",
        "balance": 5700.0,  # 5,700 USC (~$57 USD / 2,000 THB)
        "equity": 5700.0,
        "currency": "USC",
        "is_cent": True,
        "connected": True,
        "last_sync": datetime.now(timezone.utc).isoformat()
    }
    # Mock get_market_data returning fresh dummy dataframe
    import pandas as pd
    dummy_df = pd.DataFrame([{
        "time": 1700000000, "open": 2650.0, "high": 2655.0, "low": 2649.0, "close": 2652.0, "volume": 100
    }])
    mock_broker.get_market_data.return_value = dummy_df

    squad = SquadManager(
        broker=mock_broker,
        broker_mode="mt5",
        initial_balance=None,
        agents_to_enable=["gold"]
    )

    assert squad.is_cent is True
    assert squad.fixed_principal_usd == 5700.0
    # 3% of 5,700 USC = 171 USC (~60 THB)
    assert squad.target_profit_usd == pytest.approx(171.0)
