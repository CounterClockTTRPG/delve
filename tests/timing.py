"""Time limits for the tests that measure speed (DEL-235). `make ci` runs the tests in parallel, and other work on
the machine can load it well past its cores: a limit then gets as much more time as the machine is loaded, measured
by the load average per core, from ×1 on a quiet machine to ×4 at most. The goals themselves stay as written."""

import os

MOST = 4.0


def load_factor() -> float:
    """The load average of the last minute per core, between 1 and `MOST`."""
    try:
        load = os.getloadavg()[0]
    except OSError:
        return 1.0
    return min(MOST, max(1.0, load / (os.cpu_count() or 1)))


def budget(limit: float) -> float:
    """`limit` (seconds or milliseconds), scaled by `load_factor`."""
    return limit * load_factor()
