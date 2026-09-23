"""Min-lot risk-overshoot guard and restart-proof daily baseline."""

from risk.manager import RiskManager, day_baseline


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
