from __future__ import annotations

from loki_client.models import LogEntry, LokiConfig


def make_config(**overrides: object) -> LokiConfig:
    """Shared config factory with sensible test defaults."""
    defaults: dict[str, object] = {
        "endpoint": "http://loki:3100",
        "app": "testapp",
        "environment": "test",
        "batch_size": 100,
        "flush_interval": 60.0,
        "max_buffer_size": 10_000,
        "max_retries": 3,
        "retry_backoff": 0.01,
    }
    defaults.update(overrides)
    return LokiConfig(**defaults)  # type: ignore[arg-type]


def make_entry(
    msg: str = "hello",
    level: str = "info",
    labels: dict[str, str] | None = None,
    metadata: dict[str, str] | None = None,
    ts: int = 1,
) -> LogEntry:
    """Shared LogEntry factory."""
    return LogEntry(
        level=level,
        message=msg,
        labels=labels or {"app": "testapp"},
        metadata=metadata or {},
        timestamp_ns=ts,
    )


class FakeTransport:
    """In-memory transport that records batches for test assertions."""

    def __init__(
        self, *, fail_until: int = 0,
    ) -> None:
        self.batches: list[list[LogEntry]] = []
        self.closed: bool = False
        self._fail_count = 0
        self._fail_until = fail_until
        self._sent_count = 0
        self._error_count = 0
        self._drop_count = 0

    @property
    def stats(self) -> dict[str, int]:
        return {
            "sent_count": self._sent_count,
            "error_count": self._error_count,
            "drop_count": self._drop_count,
        }

    @property
    def sent_count(self) -> int:
        return self._sent_count

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def drop_count(self) -> int:
        return self._drop_count

    def send(
        self, entries: list[LogEntry],
    ) -> list[list[LogEntry]]:
        if self._fail_count < self._fail_until:
            self._fail_count += 1
            self._error_count += 1
            return [entries]
        self.batches.append(entries)
        self._sent_count += len(entries)
        return []

    def close(self) -> None:
        self.closed = True
