from __future__ import annotations

from typing import overload

from loki_client.buffer import LogBuffer
from loki_client.models import LogEntry, LokiConfig
from loki_client.transport import LokiTransport


class Loki:
    @overload
    def __init__(self, config: LokiConfig) -> None: ...

    @overload
    def __init__(
        self,
        *,
        endpoint: str,
        app: str = "default",
        environment: str = "production",
        batch_size: int = 100,
        flush_interval: float = 5.0,
        max_buffer_size: int = 10_000,
        max_batch_bytes: int = 1_048_576,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        timeout: float = 10.0,
        gzip_enabled: bool = True,
        auth_header: str | None = None,
        extra_labels: dict[str, str] | None = None,
    ) -> None: ...

    def __init__(
        self,
        config: LokiConfig | None = None,
        **kwargs: object,
    ) -> None:
        if config is not None:
            if kwargs:
                raise TypeError(
                    "Cannot pass both config and keyword arguments",
                )
            self._config = config
        else:
            if kwargs.get("extra_labels") is None:
                kwargs["extra_labels"] = {}
            self._config = LokiConfig(**kwargs)  # type: ignore[arg-type]

        self._transport = LokiTransport(self._config)
        self._buffer = LogBuffer(self._transport, self._config)

    def debug(self, message: str, **metadata: str) -> None:
        self._log("debug", message, metadata)

    def info(self, message: str, **metadata: str) -> None:
        self._log("info", message, metadata)

    def warn(self, message: str, **metadata: str) -> None:
        self._log("warn", message, metadata)

    def error(self, message: str, **metadata: str) -> None:
        self._log("error", message, metadata)

    def flush(self) -> None:
        self._buffer.flush()

    def stop(self) -> None:
        self._buffer.stop()
        self._transport.close()

    @property
    def stats(self) -> dict[str, int]:
        """Aggregate stats (eventually consistent across subsystems)."""
        transport = self._transport.stats
        buf = self._buffer.stats
        return {
            "sent": transport["sent_count"],
            "errors": transport["error_count"],
            "dropped": transport["drop_count"] + buf["drop_count"],
            "pending": buf["buffered"],
            "retrying": buf["retry_queue"],
            "flushes": buf["flush_count"],
        }

    def _log(
        self, level: str, message: str, metadata: dict[str, str],
    ) -> None:
        labels = {
            **self._config.extra_labels,
            "app": self._config.app,
            "env": self._config.environment,
            "level": level,
        }
        entry = LogEntry(
            level=level,
            message=message,
            labels=labels,
            metadata=metadata,
        )
        self._buffer.append(entry)
