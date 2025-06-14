<!-- markdownlint-disable MD040 -->

# Non-Blocking and Async Logging in CLH

This is our strategy guide for enhancing Concurrent Log Handler (CLH) to support
non-blocking and async logging patterns directly instead of just documenting
common patterns.

The goal is to provide robust, high-performance logging solutions that cater to
both traditional synchronous applications and modern async frameworks.

## Summary: Enhancing CLH with Non-Blocking Features

### The Opportunity

CLH has strong usage but could become the premier Python logging solution by
packaging best practices for non-blocking logging rather than just providing
patterns documentation.

### Key Decisions

1. **Replace Deprecated `setup_logging_queues()`**

   - Instead of "magic" that modifies all handlers globally
   - Provide explicit, well-designed handler classes
   - Give users control and visibility

2. **Two New Handler Classes**

   **`NonBlockingConcurrentHandler`** (Thread-based)

   - Uses `queue.Queue` + background thread
   - For traditional apps needing non-blocking I/O
   - Key features:
     - Graceful degradation to sync when queue full
     - Configurable sync for critical messages (e.g. `ERROR`+)
     - Queue monitoring and statistics
     - Automatic cleanup

   **`AsyncConcurrentHandler`** (Asyncio-native)

   - Uses `asyncio.Queue` + thread pool executor
   - For async/await applications (FastAPI, aiohttp)
   - Key features:
     - True async interface (fire-and-forget + awaitable)
     - Multiple fallback modes (drop/block/nowait)
     - Respects event loop patterns
     - Optional sync for critical messages

3. **Naming Convention**
   - Use "non-blocking" not "async" to avoid confusion with Python's async/await

#### Other requirements

- Ideal is to maintain support for Python 3.6, especially for the
  `NonBlockingConcurrentHandler`.

- Async support can require Python 3.9/3.10 era features potentially.

### Architecture Highlights

**NonBlockingConcurrentHandler:**

```python
# Simple upgrade path
handler = create_nonblocking_handler(
    'app.log',
    sync_level=logging.ERROR,  # ERROR+ are synchronous
    fallback_on_full=True  # Degrade gracefully
)
```

**AsyncConcurrentHandler:**

```python
# For async apps
handler = create_async_concurrent_handler(
   'app.log',
   fallback_mode='nowait',  # Best effort without blocking
   sync_level=logging.CRITICAL  # Only CRITICAL blocks
)
```

### Testing Strategy

- Comprehensive test suites for both handlers
- Special attention to multiprocessing scenarios
- Async testing patterns using pytest-asyncio
- Stress tests for queue overflow conditions

### Migration Path

- Clear documentation for moving from deprecated `setup_logging_queues()`
- Examples for common patterns
- Explicit about multiprocessing requirements (create handler in each process)

### Documentation Evolution

Transform patterns document into comprehensive guide:

1. Decision tree for choosing the right handler
2. Simple → Non-blocking → Async progression
3. Real-world examples for each use case
4. Clear tradeoffs and performance characteristics

### The Vision

CLH becomes a complete logging solution:

- **Basic use**: ConcurrentRotatingFileHandler (unchanged)
- **Performance needs**: NonBlockingConcurrentHandler
- **Async apps**: AsyncConcurrentHandler
- **Complex needs**: Mix and match handlers

Each handler has a clear purpose, making CLH valuable for everything from simple
scripts to high-performance async applications while maintaining its core
strength: reliable multi-process file logging.

### Next Steps

1. Implement NonBlockingConcurrentHandler with comprehensive tests
2. Evaluate real-world usage and feedback
3. Consider implementing AsyncConcurrentHandler based on demand
4. Update documentation with new patterns and migration guides

## Example migration guide

The deprecated `setup_logging_queues()` function automatically converted ALL
your handlers to use async queues. The new `AsyncConcurrentHandler` gives you
explicit control over which handlers are async and how they behave.

### Key Differences

| Old (setup_logging_queues)     | New (AsyncConcurrentHandler)         |
| ------------------------------ | ------------------------------------ |
| Modifies ALL existing handlers | You explicitly create async handlers |
| No control over queue size     | Configurable queue size              |
| No fallback for full queues    | Graceful degradation options         |
| Complex recovery logic         | Simple, predictable behavior         |
| Global state management        | Self-contained handlers              |

### Migration Steps

### Step 1: Remove setup_logging_queues()

**Before:**

```python
from concurrent_log_handler.queue import setup_logging_queues

# This modified ALL handlers globally
setup_logging_queues()

# Your existing logging setup
logging.basicConfig(level=logging.INFO)
file_handler = ConcurrentRotatingFileHandler('app.log', maxBytes=10 * 1024 * 1024)
logging.getLogger().addHandler(file_handler)
```

## CLH Non-Blocking and Async Implementation Plan

### Overview

Implement two new handler classes to provide non-blocking logging capabilities
while maintaining CLH's core multi-process safety guarantees.

### Phase 1: NonBlockingConcurrentHandler

#### Architecture

- Wrapper around existing CLH handlers (both Rotating and TimedRotating)
- Uses `queue.Queue` with configurable maxsize (default: 10000)
- Single `QueueListener` with background thread for dequeuing
- Preserves all CLH handler configuration options

#### Key Features

1. **Synchronous Priority Levels**

   - `sync_level` parameter (default: `logging.ERROR`)
   - Records >= sync_level bypass queue, emit directly

2. **Graceful Degradation**

   - `fallback_on_full` (default: True)
   - When queue full: sync emit for fallback, track statistics
   - Periodic warning injection (every 1000 drops)

3. **Statistics API**

   - `get_stats()`: queue_depth, capacity, dropped_count, fallback_count
   - Optional monitoring thread with configurable interval

4. **Lifecycle Management**
   - `atexit` registration for cleanup
   - Explicit `stop()` method
   - Handle in `__del__` as safety net

#### Implementation Notes

- The new code should be in one or more new files under
  `src/concurrent_log_handler/`.
- Use composition, not inheritance from CLH handlers
- `create_nonblocking_handler()` factory function for convenience
- Multiprocessing: Document requirement for per-process instantiation
- Thread safety: Rely on queue.Queue guarantees

### Multiprocessing concerns

It's important to note that while the handler instance is created per-process,
each process gets its own queue and listener thread, but all threads will still
serialize through the single underlying file lock. This is the desired behavior,
but it's a key concept to clarify. This will need special attention in the
planned "Non-Blocking and Async Logging Performance Patterns" document.

```python
# For multiprocessing.Pool users
pool = multiprocessing.Pool(
    processes=4,
    initializer=setup_logging  # Each worker sets up its own handler
)
```

### Phase 2: AsyncConcurrentHandler (Future)

#### Async Architecture

- Uses `asyncio.Queue` instead of `queue.Queue`
- `asyncio.run_in_executor()` for actual file operations
- Dedicated thread pool executor (size: min(32, cpu_count + 4))

#### Key Differentiators

1. **Fallback Modes**

   - `drop`: Pure async, no blocking (default)
   - `block`: Block event loop for critical (opt-in)
   - `nowait`: Direct to executor when queue full
     - may result in "extremely out of order" logs

2. **Awaitable Interface**
   - Standard emit returns None (fire-and-forget)
   - `await handler.emit_async(record)` for confirmation
   - Returns Future for critical messages if requested

### Testing Requirements

#### NonBlockingConcurrentHandler

- Basic: Queue operations, sync fallback, statistics
- Multiprocessing: Both spawn and fork modes
- Stress: Queue overflow, recovery, performance benchmarks
- Integration: With both CLH handler types, rotation, compression

#### AsyncConcurrentHandler

- Use `pytest-asyncio` throughout
- Event loop isolation per test
- Verify no blocking in main loop (mock executor calls)
- Multi-process async scenarios

### Migration Support

1. **Deprecation Path**

   - Add DeprecationWarning to `setup_logging_queues()` ✓
   - Point to migration guide in warning message
   - Remove in next major version

2. **Documentation Updates**
   - Migration guide with before/after examples
   - Decision tree for handler selection
   - Patterns document becomes advanced usage guide

### Performance Targets

- NonBlockingConcurrentHandler: <1ms latency for non-blocking path
- Queue full degradation: <10ms for sync fallback
- Memory: Bounded by queue size (10K records ≈ 10MB)

### API Compatibility

- Maintain drop-in compatibility with logging.Handler interface
- Additional methods (get_stats, stop) are additive only
- Configuration via kwargs to preserve existing signatures

### Implementation Priority

1. NonBlockingConcurrentHandler with full test suite
2. Migration documentation and examples
3. Real-world usage feedback collection
4. AsyncConcurrentHandler based on demand

### Risk Mitigation

- Default configurations favor reliability over performance
- Explicit opt-in for any behavior that could lose messages
- Comprehensive logging of degradation events
- Clear documentation of tradeoffs

### Success Criteria

- Zero message loss in default configuration
- Performance improvement demonstrable via benchmarks
- Clean migration path from deprecated `queue.py`
- Maintainable test coverage (>80%)

## Background notes

### Python's Async Concepts

**Coroutines**: Functions defined with `async def` that can pause execution at
`await` points. They're like JavaScript's async functions:

```python
async def fetch_data():
    await asyncio.sleep(1)  # Pauses here, yields control
    return "data"
```

**Event Loop**: A single-threaded loop that manages all coroutines, similar to
JavaScript's event loop. It runs tasks, handles I/O, and switches between
coroutines when they hit `await` points.

**Key difference from threads**: With threads, the OS switches execution
(preemptive). With asyncio, code explicitly yields control (cooperative).

### The Interaction Challenge

Here's where it gets interesting. In an asyncio application:

1. **The event loop runs in one thread** - All your async code executes in this
   thread
2. **Blocking calls freeze the entire event loop** - If you do blocking I/O, ALL
   coroutines stop
3. **Thread-safe != asyncio-safe** - Even our NonBlockingConcurrentHandler uses
   threads, which means potential issues

### Three Approaches for Asyncio Apps

#### 1. Sync Logging (Often Best!)

In asyncio apps, sync logging to stdout/stderr is often fine because:

- Terminal I/O is usually fast enough not to matter
- You'll use a log aggregator in production anyway
- No thread safety concerns

#### 2. Thread-Based Non-Blocking (Our Handler)

Works but with caveats:

- The background thread is outside the event loop
- Must be careful about thread safety when calling from coroutines
- Adds complexity (two concurrency models in one app)

#### 3. True Async Logging

Using asyncio-native approaches:

- `aiologger` or similar async logging libraries
- Custom async handler using `asyncio.Queue`
- Ensures everything stays in the event loop

### Real-World Recommendations

For asyncio-heavy apps (FastAPI, aiohttp, etc.), I'd typically recommend:

1. **Development**: Just use sync logging to console - it's simple and fast
   enough
2. **Production**:
   - Container environments: Sync logging to stdout, let infrastructure handle
     it
   - Traditional deployment: Consider our NonBlockingConcurrentHandler if you
     need file rotation
   - High-performance: True async logging libraries

The irony is that asyncio apps often need non-blocking logging LESS than
threaded apps because:

- They're already designed around non-blocking I/O
- They often run behind reverse proxies that handle logging
- They typically log to stdout in containers

### Why NonBlockingConcurrentHandler Still Makes Sense

Even in async apps, you might want it for:

1. Legacy integration (existing file-based log analysis)
2. Regulatory requirements (must write to specific rotated files)
3. Hybrid apps (both sync and async code)

The key is understanding that our handler creates a "parallel universe" - a
thread that handles logging outside your carefully orchestrated async world.
This is usually fine, but it's not "pure" async.

Think of it like this:

- **JavaScript Promise** = Python coroutine
- **JavaScript setTimeout** = Python's `asyncio.create_task`
- **Web Worker** = Our background thread (outside the main event loop)

Would you use a Web Worker for logging in Node.js? Sometimes yes, but often the
async I/O is fast enough that you don't need to.

## Why async is different and aiologger is not a complete solution

You're absolutely right on all counts! The "just use stdout" advice completely
misses CLH's value proposition. Let me address your key insights:

### You're Right About the Use Case

People use CLH specifically because they need:

- File rotation based on size/time
- Multiple specialized log files (SQL.log, requests.log, jobs.log)
- Multi-process safety across potentially multiple hosts
- Fine-grained control over retention and compression

None of that is solved by "just log to stdout."

### The Async Paradox

You've identified the key issue: in async apps, you don't want to block
coroutines on file I/O, but you also don't want to introduce a separate
threading model. This suggests we need TWO non-blocking variants:

#### 1. Thread-Based (What we've designed)

```python
class NonBlockingConcurrentHandler  # Uses background thread + queue.Queue
```

#### 2. AsyncIO-Native

```python
class AsyncConcurrentHandler  # Uses asyncio.Queue + thread pool for file ops
```

### About aiologger and Similar Libraries

You're correct - `aiologger` and similar async logging libraries do NOT handle
multi-process file locking. They're designed for async within a single process.
They can't replace CLH's core capability.

### The Ideal Async CLH Design

Here's what an asyncio-native CLH would look like conceptually:

1. **Async Interface**: Fire-and-forget by default, but awaitable for critical
   logs
2. **Asyncio Queue**: Instead of threading.Queue
3. **Thread Pool for File Ops**: Since file locking is inherently blocking, we'd
   use `asyncio.run_in_executor()` for the actual file operations
4. **Maintains CLH guarantees**: Multi-process safety via portalocker

The architecture would be:

- Coroutine logs message → asyncio.Queue → background task → thread pool → CLH
  file operations

This gives you:

- Non-blocking logging from coroutines
- No threading in your main async code
- All CLH features (rotation, compression, multi-process safety)
- Optional await for critical messages

### Why Both Versions Make Sense

Different apps have different needs:

**Thread-Based NonBlockingConcurrentHandler**:

- Traditional threaded applications
- Django, Flask (non-async views)
- Mixed sync/async code
- Simpler mental model

**AsyncConcurrentHandler**:

- Pure asyncio applications
- FastAPI, aiohttp, Sanic
- When you want to `await` critical logs
- Integrated with async monitoring/metrics

### The "Fire and Forget" vs "Await" Pattern

You nailed it - most logs are fire-and-forget, but sometimes you want
confirmation:

```python
# Fire and forget (99% of cases)
logger.info("User logged in")  # Returns immediately

# Await critical logs
await async_logger.critical("Payment processed", ensure_written=True)

# Make using sync more explicit with naming
await handler.emit_sync(record)

# Or with callback
async_logger.error("Failed to connect", callback=handle_log_completion)
```

### Multi-Instance Async Apps

Your scenario is exactly right - multiple instances of an async app writing to
shared logs:

- Instance 1 (FastAPI on port 8001) → shared-api.log
- Instance 2 (FastAPI on port 8002) → shared-api.log
- Background worker (asyncio) → shared-jobs.log

They all need CLH's file locking, but they also need non-blocking logging within
their async code.

### Summary

You've correctly identified that:

1. Stdout logging doesn't solve CLH use cases
2. Async apps still need non-blocking file logging
3. We should offer both thread-based and asyncio-native solutions
4. Existing async logging libraries don't provide multi-process safety
5. The async version should support both fire-and-forget and awaitable patterns

This makes the case for building both versions even stronger. The thread-based
one we've designed is great for many use cases, but an asyncio-native version
would make CLH the complete solution for Python logging.

## Test framework requirements

Absolutely! Testing async code has some unique challenges, but the patterns are
well-established. Here's the conceptual structure:

## Test Framework Requirements

First, you'd need `pytest-asyncio` which provides:

- `@pytest.mark.asyncio` decorator for async test functions
- Proper event loop management per test
- Async fixtures

### Conceptual Test Structure

#### 1. **Basic Async Operations**

```
test_async_fire_and_forget()
- Log messages without await
- Verify they eventually get written
- Use asyncio.sleep() to allow processing

test_await_critical_logs()
- Test the await pattern for critical messages
- Verify the await completes only after write
- Test timeout behavior
```

#### 2. **Queue Management in Async Context**

```
test_asyncio_queue_behavior()
- Test queue full scenarios with asyncio.Queue
- Verify backpressure handling
- Test queue.Full with async put vs put_nowait

test_queue_draining_on_shutdown()
- Ensure all queued messages are written
- Test graceful shutdown with pending items
```

#### 3. **Thread Pool Executor Integration**

```
test_executor_pool_management()
- Verify proper thread pool sizing
- Test executor shutdown/cleanup
- Monitor thread creation/destruction

test_blocking_operations_in_executor()
- Ensure file I/O happens in thread pool
- Verify main event loop isn't blocked
- Test concurrent file operations
```

#### 4. **Error Handling in Async Context**

```
test_coroutine_exception_handling()
- Exceptions in logging shouldn't crash event loop
- Test exception propagation for await mode
- Verify fire-and-forget errors are captured

test_executor_thread_exceptions()
- File I/O errors in thread pool
- Lock acquisition failures
- Recovery from thread pool exhaustion
```

#### 5. **Multi-Process with Asyncio**

```
test_multiple_async_processes()
- Similar to sync version but each process runs event loop
- Use asyncio.run() in each process
- Verify file locking still works

test_mixed_sync_async_processes()
- Some processes using AsyncConcurrentHandler
- Others using regular ConcurrentRotatingFileHandler
- Verify they cooperate correctly
```

#### 6. **Performance and Timing**

```
test_async_performance_characteristics()
- Measure latency of fire-and-forget
- Compare await vs fire-and-forget timing
- Test under high concurrency

test_event_loop_starvation()
- Ensure logging doesn't starve other coroutines
- Test with CPU-bound coroutines
- Verify fair scheduling
```

#### 7. **Integration with Async Frameworks**

```
test_with_fastapi_lifespan()
- Proper startup/shutdown in ASGI lifespan
- Test request context logging
- Background task logging

test_with_aiohttp_app()
- Application factory pattern
- Middleware integration
- WebSocket logging scenarios
```

### Key Testing Patterns

#### Time Control

```python
# Instead of time.sleep(), use:
await asyncio.sleep(0.1)

# For precise timing control:
with freeze_time() as frozen:
    await logger.info("msg")
    frozen.tick(1.0)  # Advance time
```

#### Async Context Managers

```python
async with AsyncConcurrentHandler(...) as handler:
    # Test lifecycle management
    await handler.log(...)
# Verify cleanup happened
```

#### Mock Verification in Async

```python
# Verify async methods were awaited
mock_handler.write.assert_awaited_with(...)

# Check number of await calls
assert mock_handler.write.await_count == 3
```

#### Event Loop Isolation

Each test should get a fresh event loop to avoid state pollution:

```python
@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
```

### Testing Challenges Unique to Async

1. **Race Conditions**: More subtle than threading

   - Test with `asyncio.gather()` for concurrent operations
   - Use `asyncio.Lock` assertions

2. **Deterministic Ordering**: Harder to guarantee

   - Test that critical logs maintain order
   - Accept that info logs may be reordered

3. **Resource Cleanup**: Event loops and thread pools

   - Test for proper cleanup
   - Watch for "Event loop is closed" errors

4. **Blocking Detection**: Ensure truly non-blocking
   - Use loop.run_in_executor assertions
   - Test with slow file I/O scenarios

### Coverage Strategy

The test suite would need to verify:

- All code paths in both fire-and-forget and await modes
- Thread pool executor usage for ALL file operations
- Proper asyncio.Queue usage (not threading.Queue)
- Event loop safety (no blocking calls in coroutines)
- Multi-process file safety still works

The beauty is that many of your existing test scenarios (rotation, compression,
etc.) would be adapted to run in async context, so you're not starting from
scratch.

## The Async Dilemma

In async programming, the golden rule is "never block the event loop." But our
key features are about _selective blocking_ for reliability. This creates an
interesting design challenge.

## Graceful Degradation in Async Context

### The Problem

When the async queue is full, we have three options:

1. **Drop the message** (pure async way) - Never blocks but loses data
2. **Block the event loop** (our degradation) - Preserves data but violates
   async principles
3. **Use thread pool immediately** (hybrid) - Skip queue, go straight to
   executor

### The Reality

Sometimes blocking the event loop for critical logs is the lesser evil:

```python
# Pseudocode for async degradation
async def emit(self, record):
    if record.levelno >= self.sync_level:
        # Critical: block event loop to ensure written
        await self._force_sync_write(record)
    else:
        try:
            self.queue.put_nowait(record)
        except asyncio.QueueFull:
            if self.fallback_on_full:
                # Choice: block for reliability
                await self._force_sync_write(record)
            else:
                self.dropped_count += 1
```

## Configurable Sync Levels in Async

This maps surprisingly well, with nuanced implementation:

### Option 1: "Await-able Critical"

```python
# Critical logs return an awaitable future
future = logger.critical("Database corrupted")
await future  # Optional - wait for confirmation

# Info logs return None (fire and forget)
logger.info("User logged in")  # No await needed
```

### Option 2: "Priority Queue"

Critical messages skip to front of queue:

```python
# Use asyncio.PriorityQueue
await self.queue.put((priority, record))
# CRITICAL=10, ERROR=20, WARNING=30, etc.
```

### Option 3: "Dedicated Executor"

Critical messages get their own thread pool:

```python
if record.levelno >= self.sync_level:
    # Use high-priority executor
    await loop.run_in_executor(self.critical_executor, write_func)
else:
    # Use normal executor after queue
    await loop.run_in_executor(self.normal_executor, write_func)
```

## The Philosophical Question

Should we even offer sync fallback in async? Arguments both ways:

### Yes, Because

- **Data integrity**: Losing critical logs is worse than brief blocking
- **Real-world pragmatism**: A 50ms block for a critical error is often
  acceptable
- **Progressive degradation**: Better than crashing or losing data
- **User choice**: Let them decide the tradeoffs

### No, Because

- **Violates async principles**: Blocking the event loop can cascade
- **False security**: If the system is overloaded, blocking makes it worse
- **Alternative solutions**: Use monitoring/alerting instead of sync fallback

## My Recommendation

For `AsyncConcurrentHandler`, I'd suggest:

1. **Default to pure async** (no blocking)
2. **Make sync fallback opt-in** with clear warnings
3. **Provide alternatives**:

   ```python
   AsyncConcurrentHandler(
       handler,
       # Option 1: Pure async (default)
       fallback_mode='drop',  # Drops when full

       # Option 2: Block on critical (opt-in)
       fallback_mode='block',  # Blocks event loop
       block_warning=True,  # Logs warning when blocking

       # Option 3: Best effort
       fallback_mode='nowait',  # Try thread pool directly
   )
   ```

4. **Document the tradeoffs clearly**:
   - "If you need guaranteed delivery, consider using
     NonBlockingConcurrentHandler instead"
   - "Blocking mode may impact application responsiveness"
   - "Monitor dropped_count in production"

## The Pattern That Emerges

Interestingly, this might lead to a usage pattern where:

- **NonBlockingConcurrentHandler**: For apps that prioritize reliability
- **AsyncConcurrentHandler**: For apps that prioritize responsiveness

And users might even use both:

```python
# Critical logs: thread-based, guaranteed delivery
critical_handler = NonBlockingConcurrentHandler('critical.log')

# High-volume logs: async, best-effort
async_handler = AsyncConcurrentHandler('app.log', fallback_mode='drop')

# Route appropriately
logger.addHandler(critical_handler)  # Gets ERROR/CRITICAL
logger.addHandler(async_handler)     # Gets INFO/WARNING
```

The key insight is that the features are valuable but need careful
implementation to respect async constraints.

## The "nowait" Best Effort Mode

```python
async def emit(self, record):
    try:
        # Try the queue first
        self.queue.put_nowait(record)
    except asyncio.QueueFull:
        if self.fallback_mode == 'nowait':
            # Queue is full, but instead of dropping or blocking,
            # immediately submit to thread pool, bypassing queue
            task = asyncio.create_task(
                self.loop.run_in_executor(
                    self.executor,
                    self._write_directly,
                    record
                )
            )
            # Don't await - fire and forget to thread pool
            # This is "best effort" - we tried our best without blocking
```

This gives you a middle ground:

- Doesn't block the event loop (good for async)
- Doesn't drop the message (better than pure drop)
- Might overwhelm the thread pool if sustained (the tradeoff)

## The Documentation Evolution

You're absolutely right - the patterns document would evolve into something
like:

```
# Concurrent Log Handler: Patterns and Best Practices

## Quick Decision Tree
1. Is your app async (asyncio/FastAPI/aiohttp)?
   → Yes: See "Async Applications" section
   → No: Continue to #2

2. Do you need non-blocking logging?
   → Yes: See "Non-Blocking Patterns" section
   → No: Use standard ConcurrentRotatingFileHandler

3. Do you have mixed requirements?
   → See "Advanced Multi-Handler Patterns"

## Pattern Categories

### 1. Simple Synchronous (80% of use cases)
- Traditional applications
- Moderate log volume
- Examples: Django, Flask, CLI tools

### 2. Non-Blocking with Threads
- High log volume
- Thread-sensitive applications
- Examples: Web apps with slow disk I/O

### 3. Async-Native Applications
- Event loop based apps
- Must not block coroutines
- Examples: FastAPI, aiohttp, asyncio services

### 4. Hybrid Architectures
- Critical + Regular logs
- Mixed sync/async code
- Examples: Async app with sync background jobs

## For Each Pattern:
- When to use it
- When NOT to use it
- Complete example
- Performance characteristics
- Common pitfalls
- Monitoring approach
```

## The Modular Strength

What's elegant about this approach is it's not "one size fits all." Users can:

1. **Start simple**: Basic ConcurrentRotatingFileHandler
2. **Add non-blocking when needed**: Upgrade to NonBlockingConcurrentHandler
3. **Go full async**: Use AsyncConcurrentHandler for async apps
4. **Mix and match**: Different handlers for different requirements

Each class has a clear purpose:

- **ConcurrentRotatingFileHandler**: Reliable, simple, proven
- **NonBlockingConcurrentHandler**: Reliability + performance via threads
- **AsyncConcurrentHandler**: Native async integration

## Documentation Philosophy

The key is to make the "happy path" obvious while documenting advanced uses:

```python
# Chapter 1: Getting Started (90% of users stop here)
handler = ConcurrentRotatingFileHandler('app.log')
logger.addHandler(handler)

# Chapter 2: Performance Tuning
# "If you're seeing blocking on log writes..."
handler = NonBlockingConcurrentHandler('app.log')

# Chapter 3: Async Applications
# "If you're using asyncio/FastAPI/aiohttp..."
handler = AsyncConcurrentHandler('app.log')

# Chapter 4: Advanced Patterns
# "For complex requirements..."
```

This progressive disclosure helps users find their level without overwhelming
beginners.

Your instinct about careful documentation is spot-on. The features are powerful
but need clear guidance on when and how to use them. The existing patterns doc
is a great foundation to build on.

## Gemini critique

Gemini 2.5 had some thoughts on the above plan.

This is an exceptionally well-thought-out and comprehensive design document.
You've correctly identified the library's core strengths (reliable,
multi-process logging) and proposed a clear, phased approach to extend its
capabilities for modern, high-performance applications. My critique will focus
on reinforcing the excellent decisions made and offering minor refinements to
further solidify the plan.

### Overall Assessment

The plan is excellent. It correctly prioritizes a robust, thread-based solution
first (`NonBlockingConcurrentHandler`) before tackling the more nuanced
`AsyncConcurrentHandler`. The architecture, proposed features, and focus on
documentation and testing are all top-tier.

### Critique of `NonBlockingConcurrentHandler` (Thread-Based)

This design is solid and follows established best practices for non-blocking
logging in synchronous applications.

- **Architecture:** Using a wrapper class with composition (not inheritance)
  around the base CLH handlers is the right choice. It cleanly separates
  concerns. I recommend explicitly using the standard library's
  `logging.handlers.QueueListener` as the foundation for your worker
  implementation. It's robust, tested, and handles graceful shutdown logic
  correctly.
- **Feature Set:** The proposed features are perfect:
  - `sync_level`: A brilliant, pragmatic feature that allows users to trade
    performance for guaranteed delivery of critical logs. `logging.ERROR` is a
    sensible default.
  - `fallback_on_full`: Prioritizing log preservation by defaulting to a
    synchronous fallback aligns perfectly with CLH's philosophy. The plan to
    track and warn about this is crucial for diagnostics.
  - `get_stats()`: Essential for monitoring and production visibility.
- **Refinement Suggestion:**
  - In the documentation for multiprocessing, be explicit that while the
    _handler_ instance is created per-process, each process gets its own queue
    and listener thread, but all threads will still serialize through the single
    underlying file lock. This is the desired behavior, but it's a key concept
    to clarify.

### Critique of `AsyncConcurrentHandler` (Asyncio-Native)

This is the more complex part of the plan, and your analysis of the "async
dilemma" is spot-on. You've navigated the trade-offs between responsiveness and
reliability beautifully.

- **Architecture:** Using `asyncio.Queue` and `run_in_executor` is the correct
  pattern for integrating blocking I/O into an async application.
- **Fallback Modes:** This is the standout feature of the async design.
  Providing `drop`, `block`, and `nowait` modes gives users explicit control
  over the exact behavior they need.
  - The decision to default to `'drop'` and make `'block'` opt-in is
    philosophically correct for an async-native handler. It respects the "never
    block the event loop" principle.
  - The `'nowait'` mode is an innovative middle ground. The documentation must
    be very clear that while it avoids blocking the event loop and dropping the
    message, it can lead to out-of-order logs and potentially overwhelm the
    thread pool under sustained load.
- **Awaitable Interface:** Offering both a fire-and-forget `emit` and an
  optional `awaitable` version is an advanced and user-friendly pattern that
  will be highly appreciated.
- **Refinement Suggestion:**
  - Consider naming the awaitable method something explicit, like `emit_wait` or
    `emit_sync`, to make its purpose obvious in user code (e.g., `await
    handler.emit_wait(record)`).

### Documentation & Testing Strategy

Your plan here is as important as the code, and it's excellent.

- **Documentation:** Evolving the patterns document into a decision tree and
  cookbook is the right direction. The proposed structure, guiding users from
  simple to advanced use cases, will make the library much more approachable. I
  strongly endorse showcasing the advanced pattern of using _both_ a
  `NonBlockingConcurrentHandler` for critical logs and an
  `AsyncConcurrentHandler` for high-volume, best-effort logs within the same
  application.
- **Testing:** The requirements are comprehensive. The key will be rigorously
  testing the multi-process scenarios for both handlers to ensure the core
  promise of the library remains intact. The plan to use `pytest-asyncio` and
  test for event loop blocking is crucial for the async handler.

### Final Recommendation for Your Prompt

Your plan is already detailed enough to serve as an excellent foundation for a
coding prompt. To refine it further for that purpose, I would suggest
structuring the request to the AI as follows:

1. **Context:** Briefly state the goal: "Implement a
   `NonBlockingConcurrentHandler` for the `concurrent-log-handler` library based
   on the following architecture."
2. **Base Class:** Provide the existing `ConcurrentRotatingFileHandler` code as
   the foundation it will wrap.
3. **Requirements for `NonBlockingConcurrentHandler`:**
    - Clearly list the constructor parameters: `(handler, queue_size,
      sync_level, fallback_on_full)`.
    - Specify the use of `queue.Queue` and a
      `logging.handlers.QueueListener`-based implementation.
    - Detail the logic for `sync_level` (bypass queue) and `fallback_on_full`
      (sync emit when full).
    - Define the `get_stats()` method and its return value.
    - Specify the `start()` and `stop()` lifecycle methods.
4. **Requirements for Factory Function:**
    - Describe the `create_nonblocking_handler(...)` factory that takes CLH
      arguments (`filename`, `maxBytes`, etc.) and constructs the underlying
      handler and the non-blocking wrapper.
5. **Testing:** "Create a pytest test suite that verifies..." and list the key
   scenarios: basic queuing, sync fallback, queue full degradation, graceful
   shutdown, and a simple multi-process test.

By breaking down your existing plan into these concrete, actionable steps, you
will guide the AI to execute your vision precisely.
