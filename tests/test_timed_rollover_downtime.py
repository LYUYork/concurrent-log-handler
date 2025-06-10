# ruff: noqa: INP001

import logging
import time
from pathlib import Path

from concurrent_log_handler import ConcurrentTimedRotatingFileHandler


def test_timed_rollover_on_startup_after_downtime(tmp_path: Path, monkeypatch):
    """
    Tests the fix for the missed rollover on startup bug.

    This test simulates the following scenario:
    1. A handler runs and sets a future rollover time in the lock file.
    2. The application stops (simulated by closing the handler).
    3. Time passes, moving beyond the scheduled rollover time (simulated with monkeypatch).
    4. The application restarts (simulated by creating a new handler instance).

    - With the BUGGY code: The new handler will see the past-due rollover time,
      but will only update the timestamp to the next future rollover, *without*
      actually rotating the old log file. The test will FAIL.
    - With the FIXED code: The new handler will see the past-due time and
      immediately trigger `doRollover()`, correctly rotating the old log file.
      The test will PASS.
    """
    # --- 1. Setup Phase ---
    log_file = tmp_path / "test_startup_rollover.log"
    rollover_interval_seconds = 2  # A short interval for the test
    initial_time = time.time()

    # Monkeypatch time.time() to a fixed initial value
    monkeypatch.setattr(time, "time", lambda: initial_time)

    # Create the first handler instance to establish an initial state
    # This will create the log file and the lock file with a rollover time
    h1 = ConcurrentTimedRotatingFileHandler(
        log_file,
        when="S",  # Rollover every N seconds
        interval=rollover_interval_seconds,
        backupCount=5,
        utc=True,
    )
    # The first 'emit' is crucial to trigger the lazy file/lock creation and
    # writing of the initial rollover time.
    h1.emit(logging.makeLogRecord({"msg": "initial log to create files"}))
    h1.close()  # VERY IMPORTANT: close the handler to flush and release files

    # --- 2. Simulate a "Downtime" ---
    # We jump forward in time, past the scheduled rollover boundary, without sleeping.
    time_after_downtime = initial_time + rollover_interval_seconds + 1
    monkeypatch.setattr(time, "time", lambda: time_after_downtime)

    # --- 3. Re-initialize the Handler (Simulate App Restart) ---
    # This is the critical step that will trigger the buggy or fixed logic in
    # the handler's __init__ -> initialize_rollover_time() method.
    h2 = ConcurrentTimedRotatingFileHandler(
        log_file,
        when="S",
        interval=rollover_interval_seconds,
        backupCount=5,
        utc=True,
    )
    h2.close()  # Close the handler to ensure all startup logic has completed

    # --- 4. Assert the Outcome ---
    # List all files in the temporary directory.
    # We expect to find the main log, the lock file, AND a rotated log file.
    files_in_dir = list(tmp_path.glob("*"))
    rotated_log_files = [
        f for f in files_in_dir if str(f.name).startswith(log_file.name + ".")
    ]

    print(f"Files found in test directory: {[f.name for f in files_in_dir]}")

    assert (
        len(rotated_log_files) >= 1
    ), "A rotated log file should have been created on startup, but was not."
