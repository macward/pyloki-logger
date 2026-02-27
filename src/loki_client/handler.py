from __future__ import annotations

import logging
import traceback
from typing import ClassVar

from loki_client.client import Loki
from loki_client.models import LokiConfig

_LEVEL_MAP: dict[int, str] = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warn",
    logging.ERROR: "error",
    logging.CRITICAL: "error",
}


class LokiHandler(logging.Handler):
    _IGNORE_PREFIX: ClassVar[str] = "loki_client"

    def __init__(self, client: Loki) -> None:
        super().__init__()
        self._client = client
        self._owns_client = False

    @classmethod
    def from_client(cls, client: Loki) -> LokiHandler:
        return cls(client)

    @classmethod
    def standalone(
        cls,
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
        max_message_bytes: int | None = None,
    ) -> LokiHandler:
        config = LokiConfig(
            endpoint=endpoint,
            app=app,
            environment=environment,
            batch_size=batch_size,
            flush_interval=flush_interval,
            max_buffer_size=max_buffer_size,
            max_batch_bytes=max_batch_bytes,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            timeout=timeout,
            gzip_enabled=gzip_enabled,
            auth_header=auth_header,
            extra_labels=extra_labels or {},
            max_message_bytes=max_message_bytes,
        )
        client = Loki(config)
        handler = cls(client)
        handler._owns_client = True
        return handler

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(self._IGNORE_PREFIX):
            return

        level = _LEVEL_MAP.get(record.levelno, "info")
        message = self.format(record)

        metadata: dict[str, str] = {
            "logger": record.name,
            "module": record.module,
            "func": record.funcName,
        }

        if record.exc_info and record.exc_info[1] is not None:
            metadata["traceback"] = "".join(
                traceback.format_exception(*record.exc_info)
            )

        self._client._log(level, message, metadata)

    def close(self) -> None:
        if self._owns_client:
            self._client.stop()
        super().close()
