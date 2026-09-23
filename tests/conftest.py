"""Shared test fixtures: keep the test suite network-free by default."""
import pytest


@pytest.fixture(autouse=True)
def _no_real_news_calendar_fetch(monkeypatch):
    """agents.base_agent.step() checks the FF/FairEconomy news calendar every
    call. Default it to a failed fetch (fail-open: no blackout, no derisk) so
    the rest of the test suite stays network-free and behaves as it did
    before this feature existed. Tests exercising the news gate itself
    override this with their own monkeypatch."""
    monkeypatch.setattr("agents.base_agent.fetch_ff_calendar", lambda: None)
