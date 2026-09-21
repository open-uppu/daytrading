"""
Unit tests for real exit attribution in the trade journal.
Verifies that a closed trade is journaled with how it ACTUALLY ended:
Smart Profit Exit, breakeven stop-out, or the broker's own TP/SL attribution.
"""

from config import config
from agents.btc_agent import BtcSpecialistAgent
from mt4.paper_broker import PaperTradingBroker
from tests.test_smart_profit_exit import create_mock_bars


def open_buy(broker: PaperTradingBroker, price: float = 80000.0) -> int:
    """Opens a 0.10 lot BTCUSD BUY at `price` and returns its ticket."""
    broker.current_price = price
    res = broker.open_order(symbol="BTCUSD", order_type="BUY", lots=0.10, sl=79500.0, tp=81000.0)
    return res["ticket"]


def read_autopsy(agent: BtcSpecialistAgent) -> str:
    """Returns the markdown text of the single autopsy written for this agent."""
    files = list(agent.trades_dir.glob("*.md"))
    assert len(files) == 1, f"expected exactly 1 autopsy, got {files}"
    return files[0].read_text(encoding="utf-8")


def test_smart_exit_is_journaled_as_smart_exit(tmp_path, monkeypatch):
    """A winner cut early by the Smart Profit Exit engine must not be journaled as TP_HIT."""
    monkeypatch.setattr(config, "smart_exit_enabled", True)
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="BTCUSD")
    open_buy(broker)
    broker.current_price = 80500.0
    pos = broker.get_open_positions()[0]
    assert pos["unrealized_pnl"] > 0

    agent = BtcSpecialistAgent(broker=broker, timeframe="M5", journal_dir=tmp_path)

    df = create_mock_bars(30, base_price=80000.0, trend="bullish")
    df.loc[df.index[-1], "close"] = 80500.0  # Surge above the Upper Bollinger Band

    assert agent._manage_active_position(pos, df_main=df) is True
    assert "**Exit Trigger**: `SMART_EXIT:" in read_autopsy(agent)
    assert agent.exit_reasons == {}


def trail_to_breakeven(broker: PaperTradingBroker, agent: BtcSpecialistAgent, ticket: int) -> float:
    """Runs price up past +1.0R so the Dynamic Trailing Break-Even parks SL at breakeven."""
    broker.current_price = 80600.0
    assert agent._manage_active_position(broker.get_open_positions()[0]) is False
    be_level = agent.be_sl_levels[ticket]
    assert broker.get_open_positions()[0]["sl"] == be_level
    return be_level


def test_breakeven_stop_out_is_journaled_as_be_stop(tmp_path):
    """A trade stopped out on the trailing breakeven SL must be journaled as BE_STOP, not SL_HIT."""
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="BTCUSD")
    ticket = open_buy(broker)
    agent = BtcSpecialistAgent(broker=broker, timeframe="M5", journal_dir=tmp_path)
    be_level = trail_to_breakeven(broker, agent, ticket)

    # Price falls back and the BROKER executes that stop itself (the production path)
    broker.simulate_price_update(new_high=80600.0, new_low=be_level - 5.0, new_close=be_level - 5.0)
    assert broker.get_closed_orders()[0]["exit_reason"] == "SL_HIT"  # broker label we override

    agent._reconcile_closed_trades()
    assert "**Exit Trigger**: `BE_STOP`" in read_autopsy(agent)
    assert agent.be_sl_levels == {}


def test_trailed_ticket_that_reaches_tp_is_still_journaled_as_tp_hit(tmp_path):
    """The BE_STOP override must not swallow a trailed trade that ran all the way to TP."""
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="BTCUSD")
    ticket = open_buy(broker)
    agent = BtcSpecialistAgent(broker=broker, timeframe="M5", journal_dir=tmp_path)
    trail_to_breakeven(broker, agent, ticket)

    broker.simulate_price_update(new_high=81050.0, new_low=80900.0, new_close=81000.0)
    agent._reconcile_closed_trades()

    autopsy = read_autopsy(agent)
    assert "**Exit Trigger**: `TP_HIT`" in autopsy
    assert "BE_STOP" not in autopsy


def test_broker_exit_reason_wins_over_pnl_sign_fallback(tmp_path):
    """An untrailed stop-out that happened to be profitable is the broker's SL_HIT, not a TP_HIT guess."""
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="BTCUSD")
    broker.current_price = 80000.0
    # Stop sitting above entry (e.g. a broker-side trailing stop), so it closes in profit
    broker.open_order(symbol="BTCUSD", order_type="BUY", lots=0.10, sl=80500.0, tp=81000.0)
    agent = BtcSpecialistAgent(broker=broker, timeframe="M5", journal_dir=tmp_path)

    broker.simulate_price_update(new_high=80600.0, new_low=80400.0, new_close=80400.0)
    closed = broker.get_closed_orders()[0]
    assert closed["exit_reason"] == "SL_HIT" and closed["pnl_usd"] > 0

    agent._reconcile_closed_trades()
    assert "**Exit Trigger**: `SL_HIT`" in read_autopsy(agent)
