from __future__ import annotations

from unittest.mock import patch

import pytest

from loki_client.client import Loki
from loki_client.models import LokiConfig


def _make_config(**overrides: object) -> LokiConfig:
    defaults: dict[str, object] = {
        "endpoint": "http://loki:3100",
        "app": "myapp",
        "environment": "test",
        "batch_size": 100,
        "flush_interval": 60.0,
    }
    defaults.update(overrides)
    return LokiConfig(**defaults)  # type: ignore[arg-type]


class TestLogMethods:
    def test_info_creates_correct_entry(self) -> None:
        config = _make_config()
        client = Loki(config)

        with patch.object(client._buffer, "append") as mock_append:
            client.info("hello world", request_id="abc")

        entry = mock_append.call_args[0][0]
        assert entry.level == "info"
        assert entry.message == "hello world"
        assert entry.labels == {"app": "myapp", "env": "test", "level": "info"}
        assert entry.metadata == {"request_id": "abc"}
        client.stop()

    def test_debug_level(self) -> None:
        config = _make_config()
        client = Loki(config)

        with patch.object(client._buffer, "append") as mock_append:
            client.debug("dbg msg")

        assert mock_append.call_args[0][0].level == "debug"
        client.stop()

    def test_warn_level(self) -> None:
        config = _make_config()
        client = Loki(config)

        with patch.object(client._buffer, "append") as mock_append:
            client.warn("warning")

        assert mock_append.call_args[0][0].level == "warn"
        client.stop()

    def test_error_level(self) -> None:
        config = _make_config()
        client = Loki(config)

        with patch.object(client._buffer, "append") as mock_append:
            client.error("oops")

        assert mock_append.call_args[0][0].level == "error"
        client.stop()

    def test_extra_labels_included(self) -> None:
        config = _make_config(extra_labels={"region": "us-east"})
        client = Loki(config)

        with patch.object(client._buffer, "append") as mock_append:
            client.info("test")

        entry = mock_append.call_args[0][0]
        assert entry.labels["region"] == "us-east"
        client.stop()


class TestKwargsConstructor:
    def test_kwargs_creates_config(self) -> None:
        client = Loki(endpoint="http://loki:3100", app="fromkw")
        assert client._config.app == "fromkw"
        assert client._config.endpoint == "http://loki:3100"
        client.stop()

    def test_rejects_both_config_and_kwargs(self) -> None:
        config = _make_config()
        with pytest.raises(TypeError, match="Cannot pass both"):
            Loki(config, endpoint="http://loki:3100")

    def test_kwargs_with_extra_labels_none(self) -> None:
        client = Loki(
            endpoint="http://loki:3100", extra_labels=None,
        )
        assert client._config.extra_labels == {}
        client.stop()


class TestStats:
    def test_stats_keys(self) -> None:
        config = _make_config()
        client = Loki(config)

        stats = client.stats
        assert set(stats.keys()) == {
            "sent",
            "errors",
            "dropped",
            "pending",
            "retrying",
            "flushes",
        }
        client.stop()

    def test_stats_aggregates_transport_and_buffer(self) -> None:
        config = _make_config()
        client = Loki(config)

        client._transport._sent_count = 10
        client._transport._error_count = 2
        client._transport._drop_count = 1

        stats = client.stats
        assert stats["sent"] == 10
        assert stats["errors"] == 2
        assert stats["dropped"] >= 1
        client.stop()


class TestLifecycle:
    def test_stop_delegates(self) -> None:
        config = _make_config()
        client = Loki(config)

        with (
            patch.object(client._buffer, "stop") as mock_buf_stop,
            patch.object(client._transport, "close") as mock_transport_close,
        ):
            client.stop()

        mock_buf_stop.assert_called_once()
        mock_transport_close.assert_called_once()

    def test_flush_delegates(self) -> None:
        config = _make_config()
        client = Loki(config)

        with patch.object(client._buffer, "flush") as mock_flush:
            client.flush()

        mock_flush.assert_called_once()
        client.stop()
