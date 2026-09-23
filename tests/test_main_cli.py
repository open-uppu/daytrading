"""
Unit tests for main.py's CLI helper functions.
"""

from pathlib import Path
from config import config
from main import _default_journal_dir


def test_default_journal_dir_m5_keeps_todays_production_path():
    """The live M5 squad's journal path must not move -- no flag change
    should be required to keep it running exactly as it does today."""
    assert _default_journal_dir("M5") == config.project_root / "journal"
    assert _default_journal_dir("m5") == config.project_root / "journal"


def test_default_journal_dir_other_timeframes_get_a_distinct_path():
    assert _default_journal_dir("M15") == config.project_root / "journal_m15"
    assert _default_journal_dir("H4") == config.project_root / "journal_h4"


def test_backtest_parser_accepts_new_timeframe_choices():
    from main import build_parser
    parser = build_parser()
    for tf in ["M30", "H1", "D1"]:
        args = parser.parse_args(["backtest", "--market", "gold", "--timeframe", tf])
        assert args.timeframe == tf


def test_cmd_backtest_forwards_timeframe_to_all_three_non_m5_paths(monkeypatch):
    """market=all -> run_cross_market_study, market=gold -> run_all_strategies,
    any other market -> evaluate_market_strategies. All three must receive
    the CLI's --timeframe, not silently default to M15."""
    import main
    from main import build_parser, cmd_backtest

    captured = {}

    def fake_study(initial_balance, timeframe="M15"):
        captured["study_tf"] = timeframe

    def fake_all_strategies(initial_balance, save_chart=True, timeframe="M15"):
        captured["gold_tf"] = timeframe
        return []

    def fake_evaluate(symbol, initial_balance, timeframe="M15"):
        captured["single_tf"] = timeframe
        return {"winner": {
            "strategy_name": "x", "total_return_pct": 0.0, "win_rate_pct": 0.0,
            "profit_factor": 0.0, "max_drawdown_pct": 0.0, "days_hit_3pct_target": 0
        }}

    monkeypatch.setattr("backtest.run_cross_market_comparison.run_cross_market_study", fake_study)
    monkeypatch.setattr("backtest.run_comparison.run_all_strategies", fake_all_strategies)
    monkeypatch.setattr("backtest.run_cross_market_comparison.evaluate_market_strategies", fake_evaluate)

    parser = build_parser()

    cmd_backtest(parser.parse_args(["backtest", "--market", "all", "--timeframe", "M30"]))
    assert captured["study_tf"] == "M30"

    cmd_backtest(parser.parse_args(["backtest", "--market", "gold", "--timeframe", "H1"]))
    assert captured["gold_tf"] == "H1"

    cmd_backtest(parser.parse_args(["backtest", "--market", "silver", "--timeframe", "D1"]))
    assert captured["single_tf"] == "D1"
