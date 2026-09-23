"""Min-lot risk-overshoot guard and restart-proof daily baseline."""

from risk.manager import RiskManager, day_baseline, load_daily_trade_state, save_daily_trade_state
from agents.btc_agent import BtcSpecialistAgent
from mt4.paper_broker import PaperTradingBroker


def make_rm(**kw) -> RiskManager:
    return RiskManager(contract_size=kw.get("contract_size", 1.0), min_lot=0.01, max_lot=5.0, risk_pct=0.005)


def test_min_lot_far_over_budget_is_rejected():
    """0.01 XAU with a $6.9 stop risks ~$6.9 against a $2.38 budget (2.9x) on a $475 account."""
    rm = make_rm(contract_size=100.0)
    ok, reason, lots = rm.validate_trade_proposal("SELL", 4350.0, 4356.9, 4340.0, equity=475.0)
    assert not ok and lots == 0.0 and "per-trade budget" in reason


def test_min_lot_slightly_over_budget_still_allowed():
    """Crypto stop that floors to 0.01 lot at 1.3x budget must keep trading."""
    rm = make_rm()
    ok, _, lots = rm.validate_trade_proposal("BUY", 81000.0, 80690.0, 81465.0, equity=475.0)  # $3.10 risk vs $2.38
    assert ok and lots == 0.01


def test_normally_sized_trade_unaffected():
    rm = make_rm()
    ok, _, _ = rm.validate_trade_proposal("BUY", 2650.0, 2640.0, 2665.0, equity=10000.0)
    assert ok


def test_baseline_survives_restart_and_resets_next_day(tmp_path):
    f = tmp_path / "daily_baseline.json"
    assert day_baseline(f, 497.22, today="2026-09-21") == 497.22
    assert day_baseline(f, 475.14, today="2026-09-21") == 497.22  # restart same day keeps the day's start
    assert day_baseline(f, 480.00, today="2026-09-22") == 480.00  # new UTC day starts fresh
    assert day_baseline(f, 470.00, today="2026-09-22") == 480.00


def test_corrupt_baseline_file_is_replaced(tmp_path):
    f = tmp_path / "daily_baseline.json"
    f.write_text("{not json")
    assert day_baseline(f, 500.0, today="2026-09-21") == 500.0
    assert day_baseline(f, 400.0, today="2026-09-21") == 500.0


def test_closed_trade_state_survives_restart_and_resets_next_day(tmp_path):
    """A specialist restart must not re-count an already-realized ticket's PnL."""
    f = tmp_path / "daily_trade_state.json"
    fresh = load_daily_trade_state(f, today="2026-09-21")
    assert fresh["closed_pnl_today"] == 0.0 and fresh["known_closed_tickets"] == []

    save_daily_trade_state(f, {
        "date": "2026-09-21", "closed_pnl_today": 4.31, "trades_count_today": 1,
        "wins_count_today": 1, "losses_count_today": 0, "known_closed_tickets": [3490820164],
    })

    restarted = load_daily_trade_state(f, today="2026-09-21")
    assert restarted["closed_pnl_today"] == 4.31
    assert 3490820164 in restarted["known_closed_tickets"]

    fresh_day = load_daily_trade_state(f, today="2026-09-22")
    assert fresh_day["closed_pnl_today"] == 0.0 and fresh_day["known_closed_tickets"] == []


class ReplayBroker:
    """Stub broker that keeps re-reporting the same closed trade every call,
    mimicking the EA's rolling-window telemetry re-sending old deals after a
    bridge/squad restart."""

    def __init__(self, closed_trades):
        self._closed_trades = closed_trades

    def consume_recently_closed(self, symbol=None, magic=None):
        return list(self._closed_trades)


def test_closed_ticket_is_not_recounted_after_specialist_restart(tmp_path):
    """A specialist restart must not re-add an already-realized ticket's PnL
    (false DAILY_TARGET_REACHED lock from re-counting old closed trades)."""
    broker = PaperTradingBroker(initial_balance=10000.0, symbol="BTCUSD")
    ticket = broker.open_order(symbol="BTCUSD", order_type="BUY", lots=0.10, sl=79500.0, tp=81000.0)["ticket"]
    broker.simulate_price_update(new_high=81050.0, new_low=80900.0, new_close=81000.0)  # hits TP

    agent1 = BtcSpecialistAgent(broker=broker, timeframe="M5", journal_dir=tmp_path)
    agent1._reconcile_closed_trades()
    pnl_after_first_session = agent1.session_tracker.closed_pnl_today
    assert pnl_after_first_session > 0 and ticket in agent1.known_closed_tickets

    # Simulate a squad/specialist restart: new process, same journal_dir. The
    # EA's rolling-window telemetry will independently re-report this same
    # already-realized ticket regardless of what the specialist remembers.
    replay_broker = ReplayBroker(broker.get_closed_orders())
    agent2 = BtcSpecialistAgent(broker=replay_broker, timeframe="M5", journal_dir=tmp_path)

    # Restored from disk BEFORE any reconcile call — a buggy in-memory-only
    # tracker would start both of these at zero/empty here.
    assert ticket in agent2.known_closed_tickets
    assert agent2.session_tracker.closed_pnl_today == pnl_after_first_session

    # Replayed ticket must be skipped, not re-added.
    agent2._reconcile_closed_trades()
    assert agent2.session_tracker.closed_pnl_today == pnl_after_first_session
