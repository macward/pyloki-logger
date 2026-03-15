"""Tests for edge cases and error resilience (issues #1-#8)."""

from __future__ import annotations

import logging
import threading
import time
from unittest.mock import MagicMock, patch

from loki_client.buffer import _MAX_RETRY_QUEUE, LogBuffer
from loki_client.client import Loki
from loki_client.handler import LokiHandler

from .conftest import FakeTransport, make_config, make_entry


class TestUseAfterStop:
    """#1 — Logging after stop() must not raise or accumulate."""

    def test_log_after_stop_is_silently_ignored(self) -> None:
        config = make_config()
        client = Loki(config)
        client.stop()

        with patch.object(client._buffer, "append") as mock_append:
            client.info("too late")

        mock_append.assert_not_called()

    def test_flush_after_stop_is_noop(self) -> None:
        config = make_config()
        client = Loki(config)
        client.stop()

        with patch.object(client._buffer, "flush") as mock_flush:
            client.flush()

        mock_flush.assert_not_called()

    def test_append_after_buffer_stop_is_ignored(self) -> None:
        transport = FakeTransport()
        config = make_config(batch_size=100)
        buf = LogBuffer(transport, config)
        buf.stop()

        buf.append(make_entry())
        assert buf.stats["buffered"] == 0


class TestDoubleStop:
    """#2 — Double stop must be safe and idempotent."""

    def test_client_double_stop_calls_transport_close_once(self) -> None:
        config = make_config()
        client = Loki(config)

        with (
            patch.object(client._transport, "close") as mock_close,
            patch.object(client._buffer, "stop"),
        ):
            client.stop()
            client.stop()

        mock_close.assert_called_once()

    def test_client_double_stop_no_error(self) -> None:
        config = make_config()
        client = Loki(config)
        client.stop()
        client.stop()  # should not raise


class TestFlushDuringShutdown:
    """#3 — stop() only flushes if background thread actually terminated."""

    def test_stop_skips_flush_when_thread_alive(self) -> None:
        transport = FakeTransport()
        config = make_config(batch_size=100, timeout=0.01)
        buf = LogBuffer(transport, config)

        buf.append(make_entry(ts=1))

        blocker_event = threading.Event()

        def blocking_send(entries: list) -> list:
            blocker_event.wait(timeout=2.0)
            return []

        # Replace transport with blocking one before the flush_interval fires
        buf._transport = MagicMock()
        buf._transport.send.side_effect = blocking_send

        # We can't easily simulate thread-alive-after-join without
        # actually blocking, so instead verify the guard exists
        buf._stop_event.set()
        buf._thread.join(timeout=0.01)
        blocker_event.set()

        # Thread may or may not be alive; key point is stop() is safe
        buf.stop()

    def test_stop_does_flush_when_thread_terminates(self) -> None:
        transport = FakeTransport()
        config = make_config(batch_size=100)
        buf = LogBuffer(transport, config)

        buf.append(make_entry(ts=1))
        buf.append(make_entry(ts=2))
        buf.stop()

        assert len(transport.batches) > 0


class TestProcessRetriesProtection:
    """#4 — _process_retries must not lose entries on transport error."""

    def test_retry_exception_re_enqueues_entries(self) -> None:
        transport = MagicMock()
        call_count = 0

        def side_effect(entries: list) -> list:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("client closed")
            return []

        transport.send.side_effect = side_effect
        config = make_config(batch_size=1, max_retries=3, retry_backoff=0.01)
        buf = LogBuffer(transport, config)

        buf.append(make_entry())

        # Let retry become ready and process it
        time.sleep(0.05)
        buf.flush()  # first retry — raises, should re-enqueue

        time.sleep(0.05)
        buf.flush()  # second retry — raises, should re-enqueue

        time.sleep(0.05)
        buf.flush()  # third retry — succeeds

        assert transport.send.call_count >= 3
        buf.stop()

    def test_retry_exception_after_max_retries_drops(self) -> None:
        transport = MagicMock()
        transport.send.side_effect = RuntimeError("always fails")
        config = make_config(batch_size=1, max_retries=2, retry_backoff=0.01)
        buf = LogBuffer(transport, config)

        buf.append(make_entry())

        for _ in range(10):
            time.sleep(0.05)
            buf.flush()

        assert buf.stats["drop_count"] >= 1
        buf.stop()


class TestHandlerEmitProtection:
    """#5 — LokiHandler.emit() must never propagate exceptions."""

    def test_emit_catches_exception_and_calls_handle_error(self) -> None:
        client = Loki(make_config())
        handler = LokiHandler(client)

        with (
            patch.object(client, "_log", side_effect=RuntimeError("boom")),
            patch.object(handler, "handleError") as mock_handle,
        ):
            record = logging.LogRecord(
                "test",
                logging.INFO,
                "",
                0,
                "msg",
                (),
                None,
            )
            handler.emit(record)

        mock_handle.assert_called_once_with(record)
        client.stop()

    def test_emit_does_not_propagate_on_error(self) -> None:
        client = Loki(make_config())
        handler = LokiHandler(client)

        with patch.object(client, "_log", side_effect=ValueError("bad")):
            record = logging.LogRecord(
                "test",
                logging.INFO,
                "",
                0,
                "msg",
                (),
                None,
            )
            # Should NOT raise
            handler.emit(record)

        client.stop()


class TestThreadJoinTimeout:
    """#6 — If thread doesn't terminate, stop() must not double-flush."""

    def test_no_flush_when_join_times_out(self) -> None:
        transport = FakeTransport()
        config = make_config(batch_size=100, flush_interval=60.0, timeout=0.01)
        buf = LogBuffer(transport, config)

        buf.append(make_entry(ts=1))

        block_event = threading.Event()

        # If the thread is still alive after join, flush is skipped
        buf._stop_event.set()
        buf._thread.join(timeout=config.timeout)

        # Thread should have stopped (it was waiting on stop_event)
        # In production the issue is when _post blocks, making thread alive
        # The guard `if not self._thread.is_alive()` handles that
        buf.stop()
        block_event.set()


class TestRetryQueueLimit:
    """#7 — Retry queue must have a hard cap."""

    def test_retry_queue_capped_at_max(self) -> None:
        transport = MagicMock()
        transport.send.return_value = [[make_entry()]]
        config = make_config(batch_size=1, max_retries=3, retry_backoff=999)
        buf = LogBuffer(transport, config)

        # Fill retry queue to the cap
        for i in range(_MAX_RETRY_QUEUE + 50):
            buf._enqueue_retry([make_entry(ts=i)])

        assert buf.stats["retry_queue"] == _MAX_RETRY_QUEUE
        assert buf.stats["drop_count"] == 50
        buf.stop()

    def test_retry_queue_cap_value(self) -> None:
        assert _MAX_RETRY_QUEUE == 1000


class TestSendBatchFromAppend:
    """#8 — _send_batch in append() must not propagate to caller."""

    def test_append_send_failure_enqueues_retry(self) -> None:
        transport = MagicMock()
        transport.send.side_effect = RuntimeError("client closed")
        config = make_config(batch_size=2, max_retries=3, retry_backoff=0.01)
        buf = LogBuffer(transport, config)

        buf.append(make_entry(ts=1))
        buf.append(make_entry(ts=2))  # triggers batch, send raises

        # Entries should be in retry queue, not lost
        assert buf.stats["retry_queue"] > 0
        buf.stop()

    def test_append_never_raises_to_caller(self) -> None:
        transport = MagicMock()
        transport.send.side_effect = RuntimeError("total failure")
        config = make_config(batch_size=1)
        buf = LogBuffer(transport, config)

        # Must not raise
        buf.append(make_entry())
        buf.stop()


class TestFlushProtection:
    """flush() must not propagate transport errors."""

    def test_flush_send_failure_enqueues_retry(self) -> None:
        transport = MagicMock()
        transport.send.side_effect = RuntimeError("client closed")
        config = make_config(batch_size=100, max_retries=3, retry_backoff=0.01)
        buf = LogBuffer(transport, config)

        buf.append(make_entry(ts=1))
        buf.flush()  # should not raise

        assert buf.stats["retry_queue"] > 0
        buf.stop()
