# Non-blocking implementation example

This is NOT the final code!

## Need to update terminology

All the example code below uses `AsyncConcurrentHandler` and `create_async_handler()`.
We want to call this `NonBlockingConcurrentHandler` and `create_nonblocking_handler()`."

We will later have a separate `AsyncConcurrentHandler` for async applications.

```python

# Clear and accurate
class NonBlockingConcurrentHandler(logging.Handler):
    """A non-blocking wrapper for CLH handlers using a background queue."""

def create_nonblocking_handler(...):
    """Create a non-blocking CLH handler with background queue processing."""
```

## Example implementation

```python

# concurrent_log_handler/async_handler.py

from typing import Optional, Union, List
import logging
import logging.handlers
import queue
import atexit
from concurrent_log_handler import ConcurrentRotatingFileHandler, ConcurrentTimedRotatingFileHandler


class AsyncConcurrentHandler(logging.Handler):
    """
    A non-blocking wrapper for CLH handlers with graceful degradation and priority-based routing.
    
    This handler provides:
    - Async logging through a queue for non-critical messages
    - Configurable sync logging for critical messages (e.g., ERROR and above)
    - Graceful degradation when the queue is full
    - Automatic cleanup on shutdown
    - Optional monitoring of queue depth
    """
    
    def __init__(
        self,
        handler: Union[ConcurrentRotatingFileHandler, ConcurrentTimedRotatingFileHandler],
        queue_size: int = 10000,
        sync_level: int = logging.ERROR,  # ERROR and above are written synchronously
        fallback_on_full: bool = True,    # Fall back to sync when queue is full
        monitor_interval: Optional[int] = None,  # Monitor queue depth every N seconds
    ):
        super().__init__()
        self.handler = handler
        self.sync_level = sync_level
        self.fallback_on_full = fallback_on_full
        
        # Set up the queue and async processing
        self.queue = queue.Queue(maxsize=queue_size)
        self.queue_handler = logging.handlers.QueueHandler(self.queue)
        
        # Use the handler's formatter and level
        self.setFormatter(handler.formatter)
        self.setLevel(handler.level)
        
        # Set up the listener
        self.listener = logging.handlers.QueueListener(
            self.queue,
            handler,
            respect_handler_level=True
        )
        
        # Statistics
        self.dropped_count = 0
        self.fallback_count = 0
        
        # Start the background thread
        self.listener.start()
        
        # Register cleanup
        atexit.register(self.stop)
        
        # Optional monitoring
        if monitor_interval:
            self._start_monitoring(monitor_interval)
    
    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a record, using async for non-critical and sync for critical messages.
        """
        # Critical messages always go synchronously
        if record.levelno >= self.sync_level:
            try:
                self.handler.emit(record)
            except Exception:
                self.handleError(record)
            return
        
        # Try to queue non-critical messages
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped_count += 1
            
            if self.fallback_on_full:
                # Fall back to synchronous logging
                self.fallback_count += 1
                try:
                    self.handler.emit(record)
                except Exception:
                    self.handleError(record)
            
            # Log a warning about dropped messages periodically
            if self.dropped_count % 1000 == 1:
                self._log_queue_warning()
    
    def stop(self) -> None:
        """Stop the background listener and clean up."""
        if hasattr(self, 'listener'):
            self.listener.stop()
    
    def _log_queue_warning(self) -> None:
        """Log a warning about dropped messages."""
        warning = logging.LogRecord(
            name=self.__class__.__name__,
            level=logging.WARNING,
            pathname=__file__,
            lineno=0,
            msg=f"Queue full: {self.dropped_count} dropped, {self.fallback_count} fell back to sync",
            args=(),
            exc_info=None
        )
        try:
            self.queue.put_nowait(warning)
        except queue.Full:
            pass
    
    def _start_monitoring(self, interval: int) -> None:
        """Start a monitoring thread for queue depth."""
        import threading
        import time
        
        def monitor():
            while True:
                time.sleep(interval)
                depth = self.queue.qsize()
                capacity = self.queue.maxsize
                utilization = depth / capacity * 100
                
                if utilization > 80:
                    print(f"WARNING: Log queue at {utilization:.1f}% capacity ({depth}/{capacity})")
        
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
    
    def get_stats(self) -> dict:
        """Get statistics about the handler's operation."""
        return {
            'queue_depth': self.queue.qsize(),
            'queue_capacity': self.queue.maxsize,
            'dropped_messages': self.dropped_count,
            'fallback_messages': self.fallback_count,
            'utilization_percent': self.queue.qsize() / self.queue.maxsize * 100
        }


def create_async_handler(
    filename: str,
    mode: str = 'a',
    maxBytes: int = 0,
    backupCount: int = 0,
    encoding: Optional[str] = None,
    # ... other CLH parameters ...
    # Async-specific parameters:
    queue_size: int = 10000,
    sync_level: int = logging.ERROR,
    fallback_on_full: bool = True,
    use_timed: bool = False,
    **kwargs
) -> AsyncConcurrentHandler:
    """
    Convenience function to create an async CLH handler with one call.
    
    Example:
        handler = create_async_handler(
            'app.log',
            maxBytes=10*1024*1024,
            backupCount=5,
            use_gzip=True,
            sync_level=logging.ERROR,  # ERROR and CRITICAL are synchronous
            queue_size=5000
        )
        
        logger = logging.getLogger()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    """
    # Create the appropriate CLH handler
    if use_timed:
        clh_handler = ConcurrentTimedRotatingFileHandler(
            filename, mode=mode, backupCount=backupCount,
            encoding=encoding, maxBytes=maxBytes, **kwargs
        )
    else:
        clh_handler = ConcurrentRotatingFileHandler(
            filename, mode, maxBytes, backupCount, encoding, **kwargs
        )
    
    # Wrap it in the async handler
    return AsyncConcurrentHandler(
        clh_handler,
        queue_size=queue_size,
        sync_level=sync_level,
        fallback_on_full=fallback_on_full
    )

```

## Example unit tests

```python
# tests/test_async_handler.py
#!/usr/bin/env python
# ruff: noqa: S101, PT006

"""
Comprehensive unit tests for AsyncConcurrentHandler.
Tests async logging, graceful degradation, queue management, and multiprocessing scenarios.
"""

import logging
import multiprocessing
import os
import queue
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from concurrent_log_handler import ConcurrentRotatingFileHandler, ConcurrentTimedRotatingFileHandler
from concurrent_log_handler.async_handler import AsyncConcurrentHandler, create_async_handler


class TestAsyncConcurrentHandler:
    """Test cases for AsyncConcurrentHandler basic functionality."""

    def test_basic_async_logging(self, tmp_path):
        """Test that basic async logging works correctly."""
        log_file = tmp_path / "test.log"
        
        # Create handler with small queue for easier testing
        handler = create_async_handler(
            str(log_file),
            maxBytes=1024 * 10,
            backupCount=2,
            queue_size=100
        )
        
        logger = logging.getLogger("test_async")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        
        # Log some messages
        for i in range(50):
            logger.info(f"Test message {i}")
        
        # Give time for async processing
        time.sleep(0.5)
        
        # Verify messages were written
        handler.stop()
        assert log_file.exists()
        
        content = log_file.read_text()
        for i in range(50):
            assert f"Test message {i}" in content

    def test_sync_critical_messages(self, tmp_path):
        """Test that critical messages are written synchronously."""
        log_file = tmp_path / "test.log"
        
        # Mock the handler to track sync vs async calls
        mock_handler = Mock(spec=ConcurrentRotatingFileHandler)
        mock_handler.level = logging.DEBUG
        mock_handler.formatter = logging.Formatter("%(message)s")
        
        async_handler = AsyncConcurrentHandler(
            mock_handler,
            queue_size=100,
            sync_level=logging.ERROR
        )
        
        # Create records at different levels
        info_record = logging.LogRecord(
            "test", logging.INFO, "", 0, "info message", (), None
        )
        error_record = logging.LogRecord(
            "test", logging.ERROR, "", 0, "error message", (), None
        )
        critical_record = logging.LogRecord(
            "test", logging.CRITICAL, "", 0, "critical message", (), None
        )
        
        # Emit records
        async_handler.emit(info_record)
        async_handler.emit(error_record)
        async_handler.emit(critical_record)
        
        # Sync messages should be emitted immediately
        assert mock_handler.emit.call_count == 2  # ERROR and CRITICAL
        
        # Stop handler to process async messages
        async_handler.stop()

    def test_queue_full_fallback(self, tmp_path):
        """Test graceful degradation when queue is full."""
        log_file = tmp_path / "test.log"
        
        # Create handler with tiny queue
        handler = create_async_handler(
            str(log_file),
            queue_size=2,  # Tiny queue
            sync_level=logging.ERROR,
            fallback_on_full=True
        )
        
        logger = logging.getLogger("test_full")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        
        # Pause the listener to let queue fill up
        handler.listener.stop()
        
        # Try to log many messages
        for i in range(10):
            logger.info(f"Message {i}")
        
        # Check statistics
        stats = handler.get_stats()
        assert stats['dropped_messages'] > 0
        assert stats['fallback_messages'] > 0
        
        # Restart listener and wait
        handler.listener.start()
        time.sleep(0.5)
        handler.stop()
        
        # Verify messages were still written (via fallback)
        content = log_file.read_text()
        # At least some messages should be there
        assert "Message" in content

    def test_no_fallback_drops_messages(self, tmp_path):
        """Test that messages are dropped when fallback is disabled."""
        log_file = tmp_path / "test.log"
        
        handler = create_async_handler(
            str(log_file),
            queue_size=2,
            fallback_on_full=False
        )
        
        # Stop listener to fill queue
        handler.listener.stop()
        
        logger = logging.getLogger("test_drop")
        logger.addHandler(handler)
        
        # Log many messages
        for i in range(10):
            logger.info(f"Message {i}")
        
        stats = handler.get_stats()
        assert stats['dropped_messages'] > 0
        assert stats['fallback_messages'] == 0
        
        handler.stop()

    def test_proper_cleanup(self, tmp_path):
        """Test that handler cleans up properly on shutdown."""
        log_file = tmp_path / "test.log"
        
        handler = create_async_handler(str(log_file))
        logger = logging.getLogger("test_cleanup")
        logger.addHandler(handler)
        
        # Log a message
        logger.info("Test message")
        
        # Check listener is running
        assert handler.listener._thread is not None
        assert handler.listener._thread.is_alive()
        
        # Stop handler
        handler.stop()
        
        # Listener should be stopped
        assert handler.listener._thread is None or not handler.listener._thread.is_alive()

    def test_statistics_tracking(self, tmp_path):
        """Test that statistics are tracked correctly."""
        log_file = tmp_path / "test.log"
        
        handler = create_async_handler(
            str(log_file),
            queue_size=5
        )
        
        initial_stats = handler.get_stats()
        assert initial_stats['dropped_messages'] == 0
        assert initial_stats['fallback_messages'] == 0
        assert initial_stats['queue_depth'] >= 0
        assert initial_stats['utilization_percent'] >= 0
        
        # Stop listener and fill queue
        handler.listener.stop()
        
        logger = logging.getLogger("test_stats")
        logger.addHandler(handler)
        
        for i in range(20):
            logger.info(f"Message {i}")
        
        final_stats = handler.get_stats()
        assert final_stats['dropped_messages'] > 0
        assert final_stats['queue_depth'] == 5  # Queue is full
        assert final_stats['utilization_percent'] == 100.0
        
        handler.stop()

    @patch('builtins.print')
    def test_monitoring(self, mock_print, tmp_path):
        """Test queue depth monitoring."""
        log_file = tmp_path / "test.log"
        
        # Create handler with monitoring
        handler = create_async_handler(
            str(log_file),
            queue_size=5,
            monitor_interval=0.1  # 100ms for quick test
        )
        
        # Stop listener to fill queue
        handler.listener.stop()
        
        logger = logging.getLogger("test_monitor")
        logger.addHandler(handler)
        
        # Fill the queue
        for i in range(10):
            logger.info(f"Message {i}")
        
        # Wait for monitoring to trigger
        time.sleep(0.3)
        
        # Check that warning was printed
        mock_print.assert_called()
        warning_call = str(mock_print.call_args)
        assert "WARNING" in warning_call
        assert "capacity" in warning_call
        
        handler.stop()


class TestAsyncHandlerMultiprocessing:
    """Test AsyncConcurrentHandler in multiprocessing scenarios."""

    def worker_function(self, log_file: str, worker_id: int, message_count: int):
        """Worker function for multiprocessing tests."""
        # IMPORTANT: Create handler in each process
        handler = create_async_handler(
            log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=5
        )
        
        logger = logging.getLogger(f"worker_{worker_id}")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        for i in range(message_count):
            logger.info(f"Worker {worker_id} message {i}")
            if i % 10 == 0:
                # Some critical messages
                logger.error(f"Worker {worker_id} error {i}")
        
        # Clean shutdown
        handler.stop()

    def test_multiprocessing_spawn(self, tmp_path):
        """Test with multiprocessing spawn mode."""
        log_file = str(tmp_path / "mp_test.log")
        num_processes = 4
        messages_per_process = 100
        
        # Force spawn mode
        ctx = multiprocessing.get_context('spawn')
        processes = []
        
        for i in range(num_processes):
            p = ctx.Process(
                target=self.worker_function,
                args=(log_file, i, messages_per_process)
            )
            p.start()
            processes.append(p)
        
        # Wait for all processes
        for p in processes:
            p.join()
        
        # Verify all messages were written
        content = Path(log_file).read_text()
        
        # Check that messages from all workers are present
        for worker_id in range(num_processes):
            assert f"Worker {worker_id}" in content
            # Check some specific messages
            assert f"Worker {worker_id} message 50" in content
            assert f"Worker {worker_id} error 30" in content

    def test_thread_safety(self, tmp_path):
        """Test thread safety within a single process."""
        log_file = tmp_path / "thread_test.log"
        
        handler = create_async_handler(
            str(log_file),
            queue_size=1000
        )
        
        logger = logging.getLogger("thread_test")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        def thread_worker(thread_id, count):
            for i in range(count):
                logger.info(f"Thread {thread_id} message {i}")
        
        # Create multiple threads
        threads = []
        num_threads = 10
        messages_per_thread = 50
        
        for i in range(num_threads):
            t = threading.Thread(
                target=thread_worker,
                args=(i, messages_per_thread)
            )
            t.start()
            threads.append(t)
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Wait for async processing
        time.sleep(0.5)
        handler.stop()
        
        # Verify all messages
        content = log_file.read_text()
        total_messages = content.count("Thread")
        expected_messages = num_threads * messages_per_thread
        assert total_messages == expected_messages


class TestAsyncHandlerIntegration:
    """Integration tests with CLH handlers."""

    def test_with_rotating_handler(self, tmp_path):
        """Test integration with ConcurrentRotatingFileHandler."""
        log_file = tmp_path / "rotating.log"
        
        # Create CLH handler
        clh_handler = ConcurrentRotatingFileHandler(
            str(log_file),
            maxBytes=1024,  # Small for testing
            backupCount=3,
            use_gzip=True
        )
        
        # Wrap in async handler
        async_handler = AsyncConcurrentHandler(clh_handler)
        
        logger = logging.getLogger("test_rotating")
        logger.addHandler(async_handler)
        logger.setLevel(logging.INFO)
        
        # Log enough to trigger rotation
        for i in range(100):
            logger.info(f"This is a test message number {i} with some padding")
        
        # Wait and stop
        time.sleep(1)
        async_handler.stop()
        
        # Check that rotation occurred
        log_files = list(tmp_path.glob("rotating.log*"))
        assert len(log_files) > 1
        
        # Check for gzipped files
        gz_files = list(tmp_path.glob("*.gz"))
        assert len(gz_files) > 0

    def test_with_timed_handler(self, tmp_path):
        """Test integration with ConcurrentTimedRotatingFileHandler."""
        log_file = tmp_path / "timed.log"
        
        # Create timed handler with very short interval
        clh_handler = ConcurrentTimedRotatingFileHandler(
            str(log_file),
            when='S',
            interval=1,  # 1 second
            backupCount=3
        )
        
        async_handler = AsyncConcurrentHandler(clh_handler)
        
        logger = logging.getLogger("test_timed")
        logger.addHandler(async_handler)
        logger.setLevel(logging.INFO)
        
        # Log over multiple seconds
        for i in range(30):
            logger.info(f"Timed message {i}")
            time.sleep(0.1)
        
        async_handler.stop()
        
        # Check that time-based rotation occurred
        log_files = list(tmp_path.glob("timed.log*"))
        assert len(log_files) > 1


class TestAsyncHandlerStress:
    """Stress tests for AsyncConcurrentHandler."""

    def test_high_volume_logging(self, tmp_path):
        """Test handler under high volume."""
        log_file = tmp_path / "stress.log"
        
        handler = create_async_handler(
            str(log_file),
            maxBytes=50 * 1024 * 1024,
            queue_size=10000,
            fallback_on_full=True
        )
        
        logger = logging.getLogger("stress_test")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        # Log many messages quickly
        message_count = 10000
        start_time = time.time()
        
        for i in range(message_count):
            logger.info(f"Stress test message {i}")
            if i % 100 == 0:
                logger.error(f"Stress test error {i}")
        
        # Wait for processing
        while handler.queue.qsize() > 0:
            time.sleep(0.1)
        
        elapsed = time.time() - start_time
        handler.stop()
        
        # Verify performance
        print(f"Logged {message_count} messages in {elapsed:.2f} seconds")
        print(f"Rate: {message_count/elapsed:.0f} messages/second")
        
        # Verify all messages were written
        content = log_file.read_text()
        # Spot check some messages
        assert "Stress test message 5000" in content
        assert "Stress test error 900" in content
        
        # Check statistics
        stats = handler.get_stats()
        print(f"Final stats: {stats}")

    def test_queue_overflow_recovery(self, tmp_path):
        """Test recovery from queue overflow conditions."""
        log_file = tmp_path / "overflow.log"
        
        handler = create_async_handler(
            str(log_file),
            queue_size=100,  # Small queue
            fallback_on_full=True
        )
        
        logger = logging.getLogger("overflow_test")
        logger.addHandler(handler)
        
        # Temporarily stop listener
        handler.listener.stop()
        
        # Overflow the queue
        for i in range(200):
            logger.info(f"Overflow message {i}")
        
        stats_before = handler.get_stats()
        assert stats_before['dropped_messages'] > 0
        
        # Restart listener
        handler.listener.start()
        
        # Should recover and process remaining messages
        time.sleep(0.5)
        
        # Log more messages
        for i in range(50):
            logger.info(f"Recovery message {i}")
        
        time.sleep(0.5)
        handler.stop()
        
        # Verify recovery
        content = log_file.read_text()
        assert "Recovery message" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```
