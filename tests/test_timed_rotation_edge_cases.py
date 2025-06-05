# ruff: noqa: S101, INP001, PGH003

import datetime
import time
from pathlib import Path

from concurrent_log_handler import (
    ConcurrentTimedRotatingFileHandler,
)

# A known "bad" timestamp, like the start of the Unix Epoch
BAD_TIMESTAMP = 0.0


def test_rollover_with_bad_time(monkeypatch, tmp_path: Path):
    """
    Verify doRollover() doesn't create a malformed filename and correctly
    computes the next rollover time if time.time() fails mid-operation.
    """
    log_file = tmp_path / "test.log"

    # Let the handler initialize normally with a valid future rollover time.
    handler = ConcurrentTimedRotatingFileHandler(
        log_file, when="S", interval=10, debug=True
    )
    assert handler.rolloverAt > handler.MIN_VALID_TIMESTAMP

    # To trigger the rollover, set the rollover time to the past, but keep it
    # a valid timestamp. This avoids the initial sanity check in doRollover().
    handler.rolloverAt = int(time.time()) - 1

    # Now, patch time.time() to return the bad value. This will be hit by the
    # parent TimedRotatingFileHandler.shouldRollover logic.
    monkeypatch.setattr(time, "time", lambda: BAD_TIMESTAMP)

    # Trigger the rollover. Inside doRollover, the call to _get_current_time will
    # be activated, detect the bad timestamp, and recover.
    handler.doRollover()
    handler.close()

    # The key validation: check that no file with an epoch date stamp was created.
    found_files = list(tmp_path.glob("*"))
    for f in found_files:
        assert "1969" not in f.name
        assert "1970" not in f.name

    # Crucial check: doRollover should have successfully recovered and calculated
    # a new *future* rollover time based on the *recovered* time.
    # To verify this, we must get the real time, bypassing the monkeypatch.
    good_current_time = datetime.datetime.now().timestamp()  # noqa: DTZ005
    assert handler.rolloverAt > good_current_time
