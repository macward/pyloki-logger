from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
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
    auth_header: str | None = None
    extra_labels: dict[str, str] = field(default_factory=dict)


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
        pairs = " ".join(f"{k}={v}" for k, v in self.metadata.items())
        return f"{self.message} | {pairs}"
