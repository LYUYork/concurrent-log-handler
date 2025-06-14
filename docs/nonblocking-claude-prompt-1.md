# Claude Code prompt

This is for the first phase of your plan: implementing the thread-based
`NonBlockingConcurrentHandler`. It specifies the "what" and the "how," providing
the AI with a precise blueprint for success.

## Instructions to Claude

Hello Claude. You are an expert Python developer specializing in concurrent
programming and the standard `logging` module. Your task is to implement a new
`NonBlockingConcurrentHandler` for the `concurrent-log-handler` library.

This handler will act as a non-blocking, thread-safe wrapper around an existing
`ConcurrentRotatingFileHandler`. It will use a background thread and a queue to
prevent application code from blocking on log I/O operations.

You can look within this project and resources that are critical to your missing:

1. The full design document in the file:
   `Non-Blocking-and-Async.md`
    This includes the main action plan and additional background material and considerations,
    including discussion of the later Phase 2 (Full Async) plan.

2. The current source code to the sync / blocking CLH log handlers in the
   `./src/concurrent_log_handler` package.

Please implement the new handler based on the following requirements.

### **1. New File and Class Structure**

Place all new code in a new file: `src/concurrent_log_handler/nonblocking.py`.

Create a new class named `NonBlockingConcurrentHandler` that inherits from
`logging.Handler`. It should use composition, not inheritance, to manage the
underlying file handler. It should support the option of using either pure
size-based rotation (the base handler) or the "Timed" rotation handler which
also supports size-based rotation through composition.

### **2. `NonBlockingConcurrentHandler` Requirements**

#### **Constructor:**

The constructor signature should be: `__init__(self, handler, queue_size=10000,
sync_level=logging.ERROR, fallback_on_full=True)`

- `handler`: The underlying handler instance to wrap (e.g.,
  `ConcurrentRotatingFileHandler`).
- `queue_size`: The maximum number of log records to buffer.
- `sync_level`: The logging level at which messages will bypass the queue and be
  handled synchronously.
- `fallback_on_full`: A boolean indicating whether to handle a message
  synchronously if the queue is full.

#### **Core Logic:**

- Use the standard library `queue.Queue` for the buffer.
- Use the standard library `logging.handlers.QueueListener` to manage the
  background worker thread that dequeues records and passes them to the wrapped
  handler.
- **Synchronous Override:** Records with a level at or above `sync_level` must
  bypass the queue and be emitted directly by the wrapped handler's `emit`
  method.
- **Graceful Degradation:** If `fallback_on_full` is `True` and the queue is
  full, the handler should emit the record synchronously. If `False`, the record
  should be dropped.
- **Statistics:** Implement a `get_stats()` method that returns a dictionary
  with the current queue depth, total capacity, and counts of any dropped or
  fallback messages.

Cleanup / atexit behavior:

```python
# Should the handler automatically register cleanup?
import atexit
atexit.register(self.stop)
```

#### **Lifecycle Methods:**

- Implement `start()` and `stop()` methods to start and stop the `QueueListener`
  background thread. The handler should start the listener upon instantiation.

### **3. Factory Function**

For user convenience, also create a factory function in the same
`nonblocking.py` file: `create_nonblocking_handler(filename, **kwargs)`

- This function should accept the same arguments as
  `ConcurrentRotatingFileHandler` (e.g., `filename`, `maxBytes`, `backupCount`).
- It should also accept the `NonBlockingConcurrentHandler` arguments
  (`queue_size`, `sync_level`, etc.).
- Inside the function, instantiate the `ConcurrentRotatingFileHandler` with its
  arguments, then instantiate and return the `NonBlockingConcurrentHandler`,
  passing the file handler to it.

We should easily support using either the base size-based rotation handler
or the timed handler (which also supports size).

```python
def create_nonblocking_handler(filename, use_timed=False, **kwargs):
    if use_timed:
        base_handler = ConcurrentTimedRotatingFileHandler(...)
    else:
        base_handler = ConcurrentRotatingFileHandler(...)
```

### **4. Package Integration**

In `src/concurrent_log_handler/__init__.py`, import the new
`NonBlockingConcurrentHandler` and `create_nonblocking_handler` so they are
accessible to users directly from the top-level package.

### **5. Testing Requirements**

Using `pytest`, create a new test file: `tests/test_nonblocking.py`.

The test suite must verify the following core behaviors:

1. A standard log message is successfully passed through the queue and written
   by the wrapped handler.
2. A log message at or above `sync_level` bypasses the queue and is written
   synchronously.
3. When the queue is full and `fallback_on_full=True`, a message is written
   synchronously.
4. When the queue is full and `fallback_on_full=False`, a message is dropped.
5. The `stop()` method correctly shuts down the listener and ensures all queued
   messages are flushed.
6. The `get_stats()` method accurately reports queue state and counters.

### **Final Deliverables**

Please provide the complete contents for the two new files:

1. `src/concurrent_log_handler/nonblocking.py`
2. `tests/test_nonblocking.py`

Also, provide the necessary small modifications to
`src/concurrent_log_handler/__init__.py` for the imports.
