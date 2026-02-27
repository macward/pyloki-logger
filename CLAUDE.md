# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`pyloki-logger` — A non-blocking Python client for sending logs to Grafana Loki with batching, gzip compression, and retry. Single dependency: `httpx`. Python 3.11+.

**Import name:** `loki_client`
**Package name:** `pyloki-logger`

## Build & Dev Commands

```bash
# Install (editable)
uv pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_buffer.py

# Run a single test
pytest tests/test_buffer.py::test_flush_on_batch_size -v

# Lint & format
ruff check src/ tests/
ruff format src/ tests/

# Type check
mypy src/
```

## Architecture

```
src/loki_client/
├── models.py      # LogEntry (frozen dataclass) — the unit that flows through the system
├── transport.py   # LokiTransport — serializes batches to Loki push API format, POSTs with httpx/gzip
├── buffer.py      # LogBuffer — thread-safe accumulator, background daemon thread for periodic flush, retry queue
├── client.py      # Loki — public facade: .info(), .error(), .flush(), .stop(), .stats
├── handler.py     # LokiHandler(logging.Handler) — bridges stdlib logging to the client
└── __init__.py    # Public exports: Loki, LokiHandler, LokiConfig
```

**Data flow:** `Loki.info()` / `LokiHandler.emit()` → `LogEntry` → `LogBuffer` (accumulates) → `LokiTransport.send(batch)` → Loki HTTP API

**Labels strategy:** Only low-cardinality labels (`app`, `env`, `level`) go in the Loki stream. Everything else (request_id, traceback, custom kv) goes in the log message line as `message | key=val`.

## Design Principles

- **No singletons.** Each `Loki` instance owns its own buffer and transport. No global state, no module-level registries.
- **No antipatterns.** Explicit instantiation, explicit lifecycle (`stop()`), no magic. Dependencies are injected through constructors, not looked up globally.
- **Non-blocking.** Log calls append to an in-memory buffer and return immediately. A background daemon thread handles flushing.
- **Composition over inheritance.** `LokiHandler.from_client(loki)` shares the buffer by reference, not through class hierarchy tricks.

## Key Behaviors

- `flush()` is triggered by: batch_size reached, flush_interval timer, manual call, or `atexit`
- Failed batches go to a retry queue with exponential backoff (1s, 2s, 4s), then drop after max_retries
- Buffer has a hard cap (`max_buffer_size`); excess logs are silently dropped
- `LokiHandler` ignores logs from `loki_client.*` loggers to prevent infinite loops

## base branch

main
