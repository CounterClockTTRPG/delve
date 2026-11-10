import pytest

from delve.conversions import runner


@pytest.fixture(autouse=True)
def no_retry_waits(monkeypatch):
    """A quick conversion's chunk is asked again after a failure (`runner.RETRY_DELAYS`): here at once, not after
    the 40 seconds a real job waits."""
    monkeypatch.setattr(runner, "RETRY_DELAYS", (0.0, 0.0))
