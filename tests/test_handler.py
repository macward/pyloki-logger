from __future__ import annotations

import logging
from unittest.mock import patch

from loki_client.client import Loki
from loki_client.handler import LokiHandler
from loki_client.models import LokiConfig


def _make_config(**overrides: object) -> LokiConfig:
    defaults: dict[str, object] = {
        "endpoint": "http://loki:3100",
        "app": "testapp",
        "environment": "test",
        "batch_size": 100,
        "flush_interval": 60.0,
    }
    defaults.update(overrides)
    return LokiConfig(**defaults)  # type: ignore[arg-type]


class TestLevelMapping:
    def test_debug_maps(self) -> None:
        client = Loki(_make_config())
        handler = LokiHandler(client)

        with patch.object(client._buffer, "append") as mock:
            record = logging.LogRecord("test", logging.DEBUG, "", 0, "msg", (), None)
            handler.emit(record)

        assert mock.call_args[0][0].level == "debug"
        client.stop()

    def test_info_maps(self) -> None:
        client = Loki(_make_config())
        handler = LokiHandler(client)

        with patch.object(client._buffer, "append") as mock:
            record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
            handler.emit(record)

        assert mock.call_args[0][0].level == "info"
        client.stop()

    def test_warning_maps_to_warn(self) -> None:
        client = Loki(_make_config())
        handler = LokiHandler(client)

        with patch.object(client._buffer, "append") as mock:
            record = logging.LogRecord("test", logging.WARNING, "", 0, "msg", (), None)
            handler.emit(record)

        assert mock.call_args[0][0].level == "warn"
        client.stop()

    def test_error_maps(self) -> None:
        client = Loki(_make_config())
        handler = LokiHandler(client)

        with patch.object(client._buffer, "append") as mock:
            record = logging.LogRecord("test", logging.ERROR, "", 0, "msg", (), None)
            handler.emit(record)

        assert mock.call_args[0][0].level == "error"
        client.stop()

    def test_critical_maps_to_error(self) -> None:
        client = Loki(_make_config())
        handler = LokiHandler(client)

        with patch.object(client._buffer, "append") as mock:
            record = logging.LogRecord("test", logging.CRITICAL, "", 0, "msg", (), None)
            handler.emit(record)

        assert mock.call_args[0][0].level == "error"
        client.stop()


class TestLoopPrevention:
    def test_ignores_loki_client_loggers(self) -> None:
        client = Loki(_make_config())
        handler = LokiHandler(client)

        with patch.object(client._buffer, "append") as mock:
            record = logging.LogRecord(
                "loki_client.transport", logging.INFO, "", 0, "msg", (), None
            )
            handler.emit(record)

        mock.assert_not_called()
        client.stop()

    def test_allows_other_loggers(self) -> None:
        client = Loki(_make_config())
        handler = LokiHandler(client)

        with patch.object(client._buffer, "append") as mock:
            record = logging.LogRecord(
                "myapp.service", logging.INFO, "", 0, "msg", (), None
            )
            handler.emit(record)

        mock.assert_called_once()
        client.stop()


class TestMetadataExtraction:
    def test_extracts_logger_module_func(self) -> None:
        client = Loki(_make_config())
        handler = LokiHandler(client)

        with patch.object(client._buffer, "append") as mock:
            record = logging.LogRecord(
                "myapp", logging.INFO, "mod.py", 42, "msg", (), None
            )
            record.module = "mymodule"
            record.funcName = "myfunc"
            handler.emit(record)

        entry = mock.call_args[0][0]
        assert entry.metadata["logger"] == "myapp"
        assert entry.metadata["module"] == "mymodule"
        assert entry.metadata["func"] == "myfunc"
        client.stop()

    def test_includes_traceback_on_exception(self) -> None:
        client = Loki(_make_config())
        handler = LokiHandler(client)

        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        with patch.object(client._buffer, "append") as mock:
            record = logging.LogRecord(
                "test", logging.ERROR, "", 0, "fail", (), exc_info
            )
            handler.emit(record)

        entry = mock.call_args[0][0]
        assert "traceback" in entry.metadata
        assert "ValueError" in entry.metadata["traceback"]
        client.stop()


class TestFromClient:
    def test_shares_buffer(self) -> None:
        client = Loki(_make_config())
        handler = LokiHandler.from_client(client)

        assert handler._client is client
        assert not handler._owns_client
        client.stop()


class TestStandalone:
    def test_creates_internal_client(self) -> None:
        handler = LokiHandler.standalone(endpoint="http://loki:3100", app="standalone")
        assert handler._owns_client
        assert handler._client._config.app == "standalone"
        handler.close()

    def test_close_stops_owned_client(self) -> None:
        handler = LokiHandler.standalone(endpoint="http://loki:3100", app="standalone")
        with patch.object(handler._client, "stop") as mock_stop:
            handler.close()
        mock_stop.assert_called_once()
