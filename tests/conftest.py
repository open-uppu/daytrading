"""Shared test fixtures: keep the test suite network-free by default."""
import pytest


@pytest.fixture(autouse=True)
def _no_real_news_calendar_fetch(monkeypatch):
    """agents.base_agent.step() checks the FF/FairEconomy news calendar every
    call. Default it to a successful empty calendar so the suite stays
    network-free. A failed fetch now fail-closes (blocks new entries); tests
    that exercise that path override this monkeypatch."""
    monkeypatch.setattr("agents.base_agent.fetch_ff_calendar", lambda: [])
