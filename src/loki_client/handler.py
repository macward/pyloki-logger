from __future__ import annotations

import logging
import traceback
from typing import ClassVar

from loki_client.client import Loki
from loki_client.models import LogEntry

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
    def standalone(cls, **kwargs: object) -> LokiHandler:
        client = Loki(**kwargs)  # type: ignore[arg-type]
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

        labels = {
            "app": self._client._config.app,
            "env": self._client._config.environment,
            "level": level,
            **self._client._config.extra_labels,
        }

        entry = LogEntry(
            level=level,
            message=message,
            labels=labels,
            metadata=metadata,
        )
        self._client._buffer.append(entry)

    def close(self) -> None:
        if self._owns_client:
            self._client.stop()
        super().close()
