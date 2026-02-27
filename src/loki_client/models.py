from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class LokiConfig:
    endpoint: str
    app: str = "default"
    environment: str = "production"
    batch_size: int = 100
    flush_interval: float = 5.0
    max_buffer_size: int = 10_000
    max_batch_bytes: int = 1_048_576  # 1 MB
    max_retries: int = 3
    retry_backoff: float = 1.0
    timeout: float = 10.0
    gzip_enabled: bool = True
    auth_header: str | None = field(default=None, repr=False)
    extra_labels: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.endpoint:
            raise ValueError("endpoint must not be empty")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be > 0")
        if self.flush_interval <= 0:
            raise ValueError("flush_interval must be > 0")
        if self.max_buffer_size <= 0:
            raise ValueError("max_buffer_size must be > 0")
        if self.max_batch_bytes <= 0:
            raise ValueError("max_batch_bytes must be > 0")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.retry_backoff < 0:
            raise ValueError("retry_backoff must be >= 0")
        if self.timeout <= 0:
            raise ValueError("timeout must be > 0")


class TransportProtocol(Protocol):
    @property
    def stats(self) -> dict[str, int]: ...
    @property
    def sent_count(self) -> int: ...
    @property
    def error_count(self) -> int: ...
    @property
    def drop_count(self) -> int: ...
    def send(self, entries: list[LogEntry]) -> list[list[LogEntry]]: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class LogEntry:
    level: str
    message: str
    labels: dict[str, str]
    metadata: dict[str, str] = field(default_factory=dict)
    timestamp_ns: int = field(default_factory=lambda: time.time_ns())

    @property
    def line(self) -> str:
        if not self.metadata:
            return self.message
        pairs = " ".join(
            f"{_escape_meta(k)}={_escape_meta(v)}"
            for k, v in self.metadata.items()
        )
        return f"{self.message} | {pairs}"


_META_NEEDS_QUOTING = frozenset('|=" ')


def _escape_meta(value: str) -> str:
    if not value or _META_NEEDS_QUOTING & set(value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
