from __future__ import annotations

from loki_client.models import LogEntry


class FakeTransport:
    """In-memory transport that records batches for test assertions."""

    def __init__(
        self, *, fail_until: int = 0,
    ) -> None:
        self.batches: list[list[LogEntry]] = []
        self.closed: bool = False
        self._fail_count = 0
        self._fail_until = fail_until

    def send(
        self, entries: list[LogEntry],
    ) -> list[list[LogEntry]]:
        if self._fail_count < self._fail_until:
            self._fail_count += 1
            return [entries]
        self.batches.append(entries)
        return []

    def close(self) -> None:
        self.closed = True
