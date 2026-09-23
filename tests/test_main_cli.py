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
