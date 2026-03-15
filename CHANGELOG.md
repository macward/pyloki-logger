# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Catch `RuntimeError` in transport when httpx client is already closed (#20)
- Prevent use-after-stop: logging and flushing silently ignored after `stop()`
- Make `Loki.stop()` idempotent — `transport.close()` called only once
- Guard `LogBuffer.append()` against writes after stop
- Wrap `_send_batch()` in try/except in both `append()` and `flush()` paths
- Only flush on `stop()` if background thread actually terminated (prevent double-flush race)
- Protect `_process_retries()` against transport exceptions (entries re-enqueued instead of lost)
- Cap retry queue at 1000 entries to prevent unbounded memory growth
- Wrap `LokiHandler.emit()` with `handleError()` per `logging.Handler` contract

### Added

- Edge case and error resilience test suite (17 tests)

## [0.1.0] - 2026-03-15

### Added

- `Loki` client facade with `.debug()`, `.info()`, `.warn()`, `.error()` log methods
- `LokiHandler` for stdlib `logging` integration via `from_client()` and `standalone()`
- `LogBuffer` with background daemon thread for non-blocking flush
- `LokiTransport` with batch serialization, gzip compression, and HTTP POST to Loki push API
- `LokiConfig` frozen dataclass with validation, auth redaction, and TLS warning
- `LogEntry` frozen dataclass with metadata line formatting and separator escaping
- `TransportProtocol` for dependency injection
- Retry queue with exponential backoff and configurable `max_retries`
- Batch splitting by `max_batch_bytes` with oversized stream handling
- `max_message_bytes` support to drop oversized messages
- Context manager support (`with Loki(...) as client:`)
- `@overload` constructor for type-safe kwargs
- Thread-safe counters for transport and buffer stats
- `atexit` hook for graceful shutdown
- Concurrency test suite for buffer and transport thread safety
- Integration tests and shared `conftest.py` test helpers
