<!-- markdownlint-disable MD026 -->

# Performance Patterns for Concurrent Log Handler

## Overview

This guide shows how to implement non-blocking logging with Concurrent Log
Handler (CLH) using Python's standard library tools. CLH is focused on reliable,
synchronous file operations while your application is responsible for
controlling threading behavior.

**Important**: Most applications don't need these patterns. CLH's recent performance
improvements (keeping files open) make synchronous logging fast enough for the
majority of use cases.

### About multiprocessing spawn mode

**Important**: If you are using `multiprocessing` especially with the `spawn`
mode, all logging setup must be done separately in each child process. For
example, call the `setup_non_blocking_logging()` function below in _each_ child
process in your child startup function.

This does **not** usually apply to child processes created with the `fork` mode,
or directly using the `fork()` system call or wrappers, because typically the
file descriptors are inherited correctly. When processes are started in `spawn`
mode, they do not inherit the parent's file descriptors and do not de-serialize
correctly.

Also this does not apply if you are using a single process application with
threads.

## Quick Start: The 80% Solution

If you need non-blocking logging, start here. This pattern handles most use cases:

```python
import logging
import logging.handlers
import atexit
from concurrent_log_handler import ConcurrentRotatingFileHandler


def setup_non_blocking_logging(filename="app.log", max_bytes=10 * 1024 * 1024):
    """
    Set up non-blocking logging with CLH and Python's standard QueueHandler
    and a 10 MB file size limit.

    This ensures that your application threads never block on I/O when logging.

    Check notes about multiprocessing above if applicable; you may need
    to call this in each child process separately.
    """
    # Create the CLH handler for actual file writing.
    file_handler = ConcurrentRotatingFileHandler(
        filename,
        maxBytes=max_bytes,
        backupCount=5,
        use_gzip=True
    )

    # Set your desired log format
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    )

    # Create queue and queue handler with a max size to prevent memory issues.
    # Rule of thumb: 100-1000 for most apps, higher for burst-heavy applications
    import queue
    log_queue = queue.Queue(maxsize=10000)
    queue_handler = logging.handlers.QueueHandler(log_queue)

    # Create queue listener that writes to the file handler
    queue_listener = logging.handlers.QueueListener(
        log_queue,
        file_handler,
        respect_handler_level=True  # Respect handler's level filtering
    )

    # Start the background thread
    queue_listener.start()

    # Ensure clean shutdown
    atexit.register(queue_listener.stop)

    # Configure root logger to use the queue
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(queue_handler)

    return queue_listener  # Return for manual control if needed


# Usage:  (check notes about multiprocessing above)
setup_non_blocking_logging()
logging.info("This log message won't block the calling thread!")
```

## Contents

* [When to Use These Patterns](#when-to-use-these-patterns)
    * [You might need non-blocking logging if:](#you-might-need-non-blocking-logging-if)
    * [You probably DON'T need it if:](#you-probably-dont-need-it-if)
* [Pattern 1: Basic Queue Handler](#pattern-1-basic-queue-handler)
* [Pattern 2: Graceful Degradation](#pattern-2-graceful-degradation)
* [Pattern 3: Critical vs Background Logging](#pattern-3-critical-vs-background-logging)
* [Pattern 4: Web Framework Integration](#pattern-4-web-framework-integration)
    * [Django](#django)
    * [Flask](#flask)
    * [FastAPI](#fastapi)
* [Pattern 5: Production Considerations](#pattern-5-production-considerations)
    * [Monitoring Queue Depth](#monitoring-queue-depth)
    * [Error Handling](#error-handling)
    * [Graceful Shutdown](#graceful-shutdown)
* [Common Pitfalls](#common-pitfalls)
    * [Multiprocessing Spawn Mode](#multiprocessing-spawn-mode)
    * [1. Creating Multiple QueueListeners](#1-creating-multiple-queuelisteners)
    * [2. Unbounded Queues](#2-unbounded-queues)
    * [3. Not Handling queue.Full](#3-not-handling-queuefull)
    * [4. Forgetting Cleanup](#4-forgetting-cleanup)
* [Performance Comparison](#performance-comparison)
* [Migration from Deprecated queue.py](#migration-from-deprecated-queuepy)
    * [Before (deprecated):](#before-deprecated)
    * [After (recommended):](#after-recommended)
    * [Key differences:](#key-differences)
* [Further Reading](#further-reading)

## When to Use These Patterns

### You might need non-blocking logging if:

- Multiple threads log heavily during error conditions
- Request threads in web apps block on logging I/O
- You see thread contention in profiling
- Your application has strict latency requirements

### You probably DON'T need it if:

- Your application has moderate logging volume (< 100 msgs/sec)
- You're already using async frameworks (they have better patterns)
- You need guaranteed log delivery (sync is more reliable)
- You're debugging logging issues (sync is simpler)

## Pattern 1: Basic Queue Handler

The fundamental pattern using Python's standard library:

```python
import logging
import logging.handlers
import queue
import atexit
from concurrent_log_handler import ConcurrentRotatingFileHandler

# Create a queue for log records
log_queue = queue.Queue(maxsize=10000)

# Create the actual file handler
# Important: if using `multiprocessing`, all this must be done separately in each child!!
file_handler = ConcurrentRotatingFileHandler(
    "app.log",
    maxBytes=50 * 1024 * 1024,  # 50MB
    backupCount=10
)
file_handler.setFormatter(
    logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
)

# Create queue handler that puts records into the queue
queue_handler = logging.handlers.QueueHandler(log_queue)

# Create listener that pulls from queue and writes to file
listener = logging.handlers.QueueListener(
    log_queue,
    file_handler,
    respect_handler_level=True
)

# Start the background thread
listener.start()

# Register cleanup
atexit.register(listener.stop)

# Configure your logger
logger = logging.getLogger(__name__)
logger.addHandler(queue_handler)
logger.setLevel(logging.INFO)

# Now logging is non-blocking!
logger.info("This returns immediately")
```

## Pattern 2: Graceful Degradation

Handle queue full scenarios without losing critical logs:

```python
import logging
import logging.handlers
import queue
import time
from concurrent_log_handler import ConcurrentRotatingFileHandler


class GracefulQueueHandler(logging.handlers.QueueHandler):
    """
    QueueHandler that falls back to synchronous logging when queue is full.

    This ensures critical messages are never lost, at the cost of occasional blocking.
    """

    def __init__(self, queue, fallback_handler=None):
        super().__init__(queue)
        self.fallback_handler = fallback_handler
        self.dropped_count = 0

    def emit(self, record):
        try:
            # Try non-blocking put
            self.enqueue(record)
        except queue.Full:
            self.dropped_count += 1

            # For critical logs, fall back to synchronous
            if record.levelno >= logging.ERROR and self.fallback_handler:
                try:
                    self.fallback_handler.emit(record)
                except Exception:
                    self.handleError(record)

            # Periodically log queue full warnings
            if self.dropped_count % 1000 == 1:
                # Create a warning record
                warning = logging.LogRecord(
                    name="GracefulQueueHandler",
                    level=logging.WARNING,
                    pathname=__file__,
                    lineno=0,
                    msg=f"Queue full, dropped {self.dropped_count} messages",
                    args=(),
                    exc_info=None
                )
                try:
                    # Try to queue the warning
                    self.queue.put_nowait(warning)
                except queue.Full:
                    pass  # Even the warning couldn't be queued


# Usage example
log_queue = queue.Queue(maxsize=5000)

# Create both async and sync handlers. Note this shows how you can separate
# the critical content in a separate file. If you want everything in one file, 
# just give the same file name to both handlers. But then they must also share all
# other settings like maxBytes, backupCount, etc.
async_file_handler = ConcurrentRotatingFileHandler("app.log", maxBytes=10 * 1024 * 1024)
sync_file_handler = ConcurrentRotatingFileHandler("app_critical.log", maxBytes=10 * 1024 * 1024)

# Use graceful handler with fallback
queue_handler = GracefulQueueHandler(log_queue, fallback_handler=sync_file_handler)

# Set up listener for normal async logging
listener = logging.handlers.QueueListener(log_queue, async_file_handler)
listener.start()

# Register cleanup for the listener
import atexit

atexit.register(listener.stop)

# Configure the root logger to use our graceful handler
logger = logging.getLogger()
logger.addHandler(queue_handler)
logger.setLevel(logging.INFO)

# Now you can log, and it will handle queue full scenarios gracefully
logger.info("This will go to the async queue.")
```

## Pattern 3: Critical vs Background Logging

Some logs must be written immediately (audit, errors), while others can be queued.
A powerful way to implement this is with a custom `logging.Filter` that directs
records to different handlers based on their level:

```python
import logging
import logging.handlers
from concurrent_log_handler import ConcurrentRotatingFileHandler


class CriticalityFilter:
    """
    Filter that routes log records based on criticality.

    Returns True only for records that should go through this handler.
    """

    def __init__(self, min_level=logging.ERROR):
        self.min_level = min_level

    def filter(self, record):
        return record.levelno >= self.min_level


# Set up handlers
critical_handler = ConcurrentRotatingFileHandler(
    "critical.log",
    maxBytes=100 * 1024 * 1024,  # 100MB for critical logs
    backupCount=20
)

# Queue for non-critical logs
import queue

log_queue = queue.Queue(maxsize=10000)
queue_handler = logging.handlers.QueueHandler(log_queue)

# Background handler for non-critical
background_handler = ConcurrentRotatingFileHandler(
    "app.log",
    maxBytes=50 * 1024 * 1024,
    backupCount=10
)


# Set up filters

class CriticalOnlyFilter:
    def filter(self, record):
        return record.levelno >= logging.ERROR


class NonCriticalFilter:
    def filter(self, record):
        return record.levelno < logging.ERROR


critical_handler.addFilter(CriticalOnlyFilter())
queue_handler.addFilter(NonCriticalFilter())  # INFO and above but not ERROR

# Configure logger with both handlers
logger = logging.getLogger()
logger.addHandler(critical_handler)  # Synchronous for critical
logger.addHandler(queue_handler)  # Async for non-critical

# Start background processing
listener = logging.handlers.QueueListener(log_queue, background_handler)
listener.start()

# Usage
logger.info("This goes to queue")  # Non-blocking
logger.error("This is written immediately")  # Blocking but critical
```

## Pattern 4: Web Framework Integration

### Django

```python
# settings.py
import queue
import atexit
import logging.handlers
from concurrent_log_handler import ConcurrentRotatingFileHandler

# Create global queue and listener
LOG_QUEUE = queue.Queue(maxsize=10000)
LOG_LISTENER = None


def setup_logging():
    global LOG_LISTENER

    # Create file handler
    file_handler = ConcurrentRotatingFileHandler(
        '/var/log/django/app.log',
        maxBytes=100 * 1024 * 1024,
        backupCount=10
    )
    file_handler.setFormatter(
        logging.Formatter('[%(asctime)s] %(levelname)s %(name)s: %(message)s')
    )

    # Create listener
    LOG_LISTENER = logging.handlers.QueueListener(
        LOG_QUEUE,
        file_handler,
        respect_handler_level=True
    )
    LOG_LISTENER.start()
    atexit.register(LOG_LISTENER.stop)


# Call setup_logging() in your Django project's __init__.py 
# or in settings.py at module level (not inside a function)
setup_logging()

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'queue': {
            'class': 'logging.handlers.QueueHandler',
            'queue': LOG_QUEUE,
        },
    },
    'root': {
        'handlers': ['queue'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['queue'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
```

### Flask

```python
# app.py or create_app()
import logging
import logging.handlers
import queue
import atexit
from concurrent_log_handler import ConcurrentRotatingFileHandler


def create_app():
    app = Flask(__name__)

    # Set up non-blocking logging
    log_queue = queue.Queue(maxsize=10000)

    # File handler
    file_handler = ConcurrentRotatingFileHandler(
        'flask_app.log',
        maxBytes=50 * 1024 * 1024,
        backupCount=5
    )
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    )

    # Queue handler for app logger
    queue_handler = logging.handlers.QueueHandler(log_queue)
    app.logger.addHandler(queue_handler)
    app.logger.setLevel(logging.INFO)

    # Start background listener
    listener = logging.handlers.QueueListener(
        log_queue,
        file_handler,
        respect_handler_level=True
    )
    listener.start()

    # Ensure cleanup
    atexit.register(listener.stop)

    return app
```

### FastAPI

```python
# main.py
import logging
import logging.handlers
import queue
from contextlib import asynccontextmanager
from fastapi import FastAPI
from concurrent_log_handler import ConcurrentRotatingFileHandler

# Global listener reference
log_listener = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    global log_listener

    # Startup
    log_queue = queue.Queue(maxsize=10000)

    file_handler = ConcurrentRotatingFileHandler(
        "fastapi_app.log",
        maxBytes=100 * 1024 * 1024,
        backupCount=10
    )

    # Configure queue handler
    queue_handler = logging.handlers.QueueHandler(log_queue)
    logging.getLogger().addHandler(queue_handler)
    logging.getLogger().setLevel(logging.INFO)

    # Start listener
    log_listener = logging.handlers.QueueListener(
        log_queue,
        file_handler,
        respect_handler_level=True
    )
    log_listener.start()

    yield  # Application runs

    # Shutdown
    log_listener.stop()


app = FastAPI(lifespan=lifespan)

# Use standard logging
logger = logging.getLogger(__name__)


@app.get("/")
async def root():
    logger.info("Request received")  # Non-blocking
    return {"message": "Hello World"}
```

## Pattern 5: Production Considerations

### Monitoring Queue Depth

```python
import logging
import threading
import time


class MonitoredQueueHandler(logging.handlers.QueueHandler):
    """QueueHandler with queue depth monitoring."""

    def __init__(self, queue):
        super().__init__(queue)
        self.max_depth_seen = 0
        self.total_messages = 0
        self.start_monitoring()

    def enqueue(self, record):
        super().enqueue(record)
        self.total_messages += 1
        current_depth = self.queue.qsize()
        self.max_depth_seen = max(self.max_depth_seen, current_depth)

    def start_monitoring(self):
        def monitor():
            while True:
                time.sleep(60)  # Report every minute
                depth = self.queue.qsize()
                if depth > 0.8 * self.queue.maxsize:
                    # Log warning using a different logger to avoid recursion
                    print(f"WARNING: Log queue at {depth}/{self.queue.maxsize} capacity")

                # Could also send to monitoring system
                # statsd.gauge('logging.queue.depth', depth)
                # statsd.gauge('logging.queue.max_depth', self.max_depth_seen)

        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
```

### Error Handling

```python
import logging
import logging.handlers
import sys


class RobustQueueListener(logging.handlers.QueueListener):
    """QueueListener with better error handling."""

    def __init__(self, queue, *handlers, error_handler=None):
        super().__init__(queue, *handlers, respect_handler_level=True)
        self.error_handler = error_handler or self.default_error_handler
        self.error_count = 0

    def default_error_handler(self, record, exception):
        """Default error handler - print to stderr."""
        self.error_count += 1
        print(f"Logging error #{self.error_count}: {exception}", file=sys.stderr)
        if self.error_count % 100 == 0:
            print(f"Total logging errors: {self.error_count}", file=sys.stderr)

    def handle(self, record):
        """Override to add error handling."""
        for handler in self.handlers:
            try:
                handler.handle(record)
            except Exception as e:
                self.error_handler(record, e)
```

### Graceful Shutdown

```python
import signal
import logging
import logging.handlers
import sys


class GracefulLoggingShutdown:
    """Ensures all logs are written on shutdown."""

    def __init__(self, listener, timeout=30):
        self.listener = listener
        self.timeout = timeout
        self.setup_signal_handlers()

    def setup_signal_handlers(self):
        """Register signal handlers for graceful shutdown."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self.signal_handler)

    def signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print(f"\nReceived signal {signum}, shutting down gracefully...")

        # Stop accepting new logs
        logging.getLogger().disabled = True

        # Wait for queue to empty (with timeout)
        import time
        start_time = time.time()
        while self.listener.queue.qsize() > 0:
            if time.time() - start_time > self.timeout:
                print(f"Timeout waiting for log queue to empty, "
                      f"{self.listener.queue.qsize()} messages may be lost")
                break
            time.sleep(0.1)

        # Stop the listener
        self.listener.stop()

        print("Logging shutdown complete")
        sys.exit(0)


# Usage
listener = logging.handlers.QueueListener(log_queue, file_handler)
listener.start()
shutdown_handler = GracefulLoggingShutdown(listener)
```

## Common Pitfalls

### Multiprocessing Spawn Mode

Be sure to read the 
[remarks above about multiprocessing spawn mode](#about-multiprocessing-spawn-mode)
as this is a common pitfall when using Concurrent Log Handler.

### 1. Creating Multiple QueueListeners

```python
# WRONG - Creates multiple background threads
for handler in handlers:
    listener = logging.handlers.QueueListener(queue, handler)
    listener.start()

# CORRECT - One listener, multiple handlers
listener = logging.handlers.QueueListener(queue, *handlers)
listener.start()
```

### 2. Unbounded Queues

```python
# WRONG - Can consume unlimited memory
log_queue = queue.Queue()  # No maxsize!

# CORRECT - Limit queue size
log_queue = queue.Queue(maxsize=10000)
```

### 3. Not Handling queue.Full

```python
# WRONG - Loses messages silently
try:
    queue_handler.emit(record)
except queue.Full:
    pass  # Message lost!

# CORRECT - Track or handle full queue
except queue.Full:
    dropped_counter.increment()
    if record.levelno >= logging.ERROR:
        # Use fallback for critical messages
        sync_handler.emit(record)
```

### 4. Forgetting Cleanup

```python
# WRONG - Background thread keeps running
listener.start()
# Application exits...

# CORRECT - Register cleanup
listener.start()
atexit.register(listener.stop)

# OR use context manager
from contextlib import contextmanager


@contextmanager
def managed_listener(queue, *handlers):
    listener = logging.handlers.QueueListener(queue, *handlers)
    listener.start()
    try:
        yield listener
    finally:
        listener.stop()
```

## Performance Comparison

| Pattern          | Relative Latency         | Throughput | Memory Usage | Complexity |
|------------------|--------------------------|------------|--------------|------------|
| Synchronous CLH  | Baseline (I/O Bound)     | Medium     | Low          | Low        |
| QueueHandler     | Very Low (~1000x faster) | High       | Medium       | Medium     |
| Direct to stdout | Low (~10-100x faster)    | High       | Low          | Low        |

_Note: Actual performance depends on disk speed, file size, and system load._

## Migration from Deprecated queue.py

If you're currently using `concurrent_log_handler.queue.setup_logging_queues()`:

### Before (deprecated):

```python
from concurrent_log_handler.queue import setup_logging_queues

# This modified ALL handlers to be non-blocking
setup_logging_queues()
```

### After (recommended):

Be sure to check the
[remarks above about multiprocessing spawn mode](#about-multiprocessing-spawn-mode).

```python
import logging
import logging.handlers
import queue
import atexit
from concurrent_log_handler import ConcurrentRotatingFileHandler

# Explicit queue setup
log_queue = queue.Queue(maxsize=10000)

# Your CLH handler
clh_handler = ConcurrentRotatingFileHandler("app.log", maxBytes=10 * 1024 * 1024)

# Queue handler for non-blocking
queue_handler = logging.handlers.QueueHandler(log_queue)

# Listener for background processing
listener = logging.handlers.QueueListener(log_queue, clh_handler)
listener.start()
atexit.register(listener.stop)

# Configure logging
logging.getLogger().addHandler(queue_handler)
```

### Key differences:

- More explicit control
- Better error visibility
- Standard library patterns
- No monkey patching

## Further Reading

- [Python Logging Cookbook - QueueHandler](https://docs.python.org/3/howto/logging-cookbook.html#dealing-with-handlers-that-block)
- [Concurrent Log Handler Documentation](../README.md)
- [Python logging.handlers documentation](https://docs.python.org/3/library/logging.handlers.html)
