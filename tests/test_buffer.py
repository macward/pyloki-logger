from __future__ import annotations

import time
from unittest.mock import MagicMock

from loki_client.buffer import LogBuffer
from loki_client.models import LogEntry, LokiConfig


def _make_entry(msg: str = "hello", ts: int = 1) -> LogEntry:
    return LogEntry(
        level="info",
        message=msg,
        labels={"app": "test"},
        timestamp_ns=ts,
    )


def _make_config(**overrides: object) -> LokiConfig:
    defaults: dict[str, object] = {
        "endpoint": "http://loki:3100",
        "app": "test",
        "batch_size": 5,
        "flush_interval": 60.0,
        "max_buffer_size": 100,
        "max_retries": 3,
        "retry_backoff": 0.01,
    }
    defaults.update(overrides)
    return LokiConfig(**defaults)  # type: ignore[arg-type]


class TestAppend:
    def test_batch_size_triggers_send(self) -> None:
        transport = MagicMock()
        transport.send.return_value = []
        config = _make_config(batch_size=3)
        buf = LogBuffer(transport, config)

        for i in range(3):
            buf.append(_make_entry(ts=i))

        buf.stop()
        transport.send.assert_called()
        batch = transport.send.call_args_list[0][0][0]
        assert len(batch) == 3

    def test_below_batch_size_stays_buffered(self) -> None:
        transport = MagicMock()
        transport.send.return_value = []
        config = _make_config(batch_size=10)
        buf = LogBuffer(transport, config)

        buf.append(_make_entry())
        buf.append(_make_entry())

        assert buf.stats["buffered"] == 2
        transport.send.assert_not_called()
        buf.stop()

    def test_max_buffer_size_drops_silently(self) -> None:
        transport = MagicMock()
        transport.send.return_value = []
        config = _make_config(batch_size=100, max_buffer_size=3)
        buf = LogBuffer(transport, config)

        for i in range(5):
            buf.append(_make_entry(ts=i))

        assert buf.stats["buffered"] == 3
        assert buf.stats["drop_count"] == 2
        buf.stop()


class TestFlush:
    def test_flush_sends_buffered_entries(self) -> None:
        transport = MagicMock()
        transport.send.return_value = []
        config = _make_config(batch_size=100)
        buf = LogBuffer(transport, config)

        buf.append(_make_entry(ts=1))
        buf.append(_make_entry(ts=2))
        buf.flush()

        transport.send.assert_called_once()
        assert len(transport.send.call_args[0][0]) == 2
        buf.stop()

    def test_flush_empty_buffer_noop(self) -> None:
        transport = MagicMock()
        transport.send.return_value = []
        config = _make_config()
        buf = LogBuffer(transport, config)

        buf.flush()
        transport.send.assert_not_called()
        buf.stop()

    def test_flush_interval_triggers_flush(self) -> None:
        transport = MagicMock()
        transport.send.return_value = []
        config = _make_config(batch_size=100, flush_interval=0.05)
        buf = LogBuffer(transport, config)

        buf.append(_make_entry())
        time.sleep(0.15)

        transport.send.assert_called()
        buf.stop()


class TestRetry:
    def test_failed_batch_is_retried(self) -> None:
        transport = MagicMock()
        transport.send.side_effect = [
            [[_make_entry()]],  # first: fail
            [],  # retry: success
        ]
        config = _make_config(batch_size=1, retry_backoff=0.01)
        buf = LogBuffer(transport, config)

        buf.append(_make_entry())
        time.sleep(0.05)
        buf.flush()

        assert transport.send.call_count == 2
        buf.stop()

    def test_dropped_after_max_retries(self) -> None:
        transport = MagicMock()
        entry = _make_entry()
        transport.send.return_value = [[entry]]
        config = _make_config(
            batch_size=1, max_retries=2, retry_backoff=0.01,
        )
        buf = LogBuffer(transport, config)

        buf.append(entry)
        for _ in range(5):
            time.sleep(0.05)
            buf.flush()

        assert buf.stats["drop_count"] == 1
        buf.stop()

    def test_max_retries_zero_drops_immediately(self) -> None:
        transport = MagicMock()
        entry = _make_entry()
        transport.send.return_value = [[entry]]
        config = _make_config(
            batch_size=1, max_retries=0, retry_backoff=0.01,
        )
        buf = LogBuffer(transport, config)

        buf.append(entry)
        time.sleep(0.05)
        buf.flush()

        assert transport.send.call_count == 1
        assert buf.stats["drop_count"] == 1
        assert buf.stats["retry_queue"] == 0
        buf.stop()

    def test_exact_retry_count(self) -> None:
        transport = MagicMock()
        entry = _make_entry()
        transport.send.return_value = [[entry]]
        config = _make_config(
            batch_size=1, max_retries=3, retry_backoff=0.01,
        )
        buf = LogBuffer(transport, config)

        buf.append(entry)
        for _ in range(10):
            time.sleep(0.05)
            buf.flush()

        # 1 initial send + 3 retries = 4 total calls
        assert transport.send.call_count == 4
        assert buf.stats["drop_count"] == 1
        buf.stop()


class TestStop:
    def test_stop_flushes_remaining(self) -> None:
        transport = MagicMock()
        transport.send.return_value = []
        config = _make_config(batch_size=100)
        buf = LogBuffer(transport, config)

        buf.append(_make_entry(ts=1))
        buf.append(_make_entry(ts=2))
        buf.stop()

        transport.send.assert_called()

    def test_double_stop_is_safe(self) -> None:
        transport = MagicMock()
        transport.send.return_value = []
        config = _make_config()
        buf = LogBuffer(transport, config)

        buf.stop()
        buf.stop()


class TestMaxMessageBytes:
    def test_oversized_message_dropped(self) -> None:
        transport = MagicMock()
        transport.send.return_value = []
        config = _make_config(batch_size=100, max_message_bytes=10)
        buf = LogBuffer(transport, config)

        buf.append(_make_entry(msg="short"))
        buf.append(_make_entry(msg="this message is way too long"))

        assert buf.stats["buffered"] == 1
        assert buf.stats["drop_count"] == 1
        buf.stop()

    def test_none_max_message_bytes_allows_all(self) -> None:
        transport = MagicMock()
        transport.send.return_value = []
        config = _make_config(batch_size=100, max_message_bytes=None)
        buf = LogBuffer(transport, config)

        buf.append(_make_entry(msg="a" * 10_000))

        assert buf.stats["buffered"] == 1
        assert buf.stats["drop_count"] == 0
        buf.stop()


class TestBackgroundThreadResilience:
    def test_flush_exception_does_not_kill_thread(self) -> None:
        transport = MagicMock()
        call_count = 0

        def side_effect(entries: list) -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("network error")
            return []

        transport.send.side_effect = side_effect
        config = _make_config(
            batch_size=100, flush_interval=0.05,
        )
        buf = LogBuffer(transport, config)

        buf.append(_make_entry(ts=1))
        time.sleep(0.15)  # let background thread flush (and fail)
        buf.append(_make_entry(ts=2))
        time.sleep(0.15)  # let it flush again (should succeed)

        assert transport.send.call_count >= 2
        buf.stop()


class TestStats:
    def test_stats_keys(self) -> None:
        transport = MagicMock()
        transport.send.return_value = []
        config = _make_config()
        buf = LogBuffer(transport, config)

        stats = buf.stats
        assert set(stats.keys()) == {
            "buffered",
            "retry_queue",
            "flush_count",
            "drop_count",
        }
        buf.stop()
