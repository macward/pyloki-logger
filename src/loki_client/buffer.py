from __future__ import annotations

import atexit
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loki_client.models import LogEntry, LokiConfig, TransportProtocol


class _RetryItem:
    __slots__ = ("entries", "attempts", "next_retry")

    def __init__(self, entries: list[LogEntry], backoff: float) -> None:
        self.entries = entries
        self.attempts = 0
        self.next_retry = time.monotonic() + backoff


class LogBuffer:
    def __init__(self, transport: TransportProtocol, config: LokiConfig) -> None:
        self._transport = transport
        self._config = config
        self._buffer: list[LogEntry] = []
        self._retry_queue: list[_RetryItem] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._flush_count: int = 0
        self._drop_count: int = 0

        self._thread = threading.Thread(
            target=self._run, daemon=True, name="loki-buffer"
        )
        self._thread.start()
        atexit.register(self.stop)

    def append(self, entry: LogEntry) -> None:
        batch: list[LogEntry] | None = None
        with self._lock:
            if len(self._buffer) >= self._config.max_buffer_size:
                self._drop_count += 1
                return
            self._buffer.append(entry)

            if len(self._buffer) >= self._config.batch_size:
                batch = list(self._buffer)
                self._buffer.clear()

        if batch is not None:
            self._send_batch(batch)

    def flush(self) -> None:
        with self._lock:
            batch = list(self._buffer)
            self._buffer.clear()
        if batch:
            self._send_batch(batch)
        self._process_retries()

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        self._thread.join(timeout=self._config.timeout)
        self.flush()

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "buffered": len(self._buffer),
                "retry_queue": len(self._retry_queue),
                "flush_count": self._flush_count,
                "drop_count": self._drop_count,
            }

    def _run(self) -> None:
        while not self._stop_event.wait(self._config.flush_interval):
            self.flush()

    def _send_batch(self, entries: list[LogEntry]) -> None:
        failed = self._transport.send(entries)
        with self._lock:
            self._flush_count += 1
        for batch in failed:
            self._enqueue_retry(batch)

    def _enqueue_retry(self, entries: list[LogEntry]) -> None:
        if self._config.max_retries <= 0:
            with self._lock:
                self._drop_count += len(entries)
            return
        with self._lock:
            self._retry_queue.append(
                _RetryItem(entries, self._config.retry_backoff),
            )

    def _process_retries(self) -> None:
        now = time.monotonic()
        with self._lock:
            ready = [r for r in self._retry_queue if r.next_retry <= now]
            self._retry_queue = [r for r in self._retry_queue if r.next_retry > now]

        for item in ready:
            item.attempts += 1
            failed = self._transport.send(item.entries)
            if failed:
                if item.attempts < self._config.max_retries:
                    backoff = self._config.retry_backoff * (
                        2 ** item.attempts
                    )
                    item.next_retry = time.monotonic() + backoff
                    with self._lock:
                        self._retry_queue.append(item)
                else:
                    with self._lock:
                        self._drop_count += len(item.entries)
