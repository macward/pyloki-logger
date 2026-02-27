from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from loki_client.buffer import LogBuffer
from loki_client.transport import LokiTransport

from .conftest import FakeTransport, make_config, make_entry


class TestBufferConcurrency:
    def test_concurrent_append_stress(self) -> None:
        """10 threads x 1000 entries; sent + dropped + buffered == 10000."""
        transport = FakeTransport()
        config = make_config(
            batch_size=50, max_buffer_size=10_000,
        )
        buf = LogBuffer(transport, config)

        num_threads = 10
        per_thread = 1000
        barrier = threading.Barrier(num_threads)

        def worker() -> None:
            barrier.wait()
            for i in range(per_thread):
                buf.append(make_entry(ts=i))

        threads = [
            threading.Thread(target=worker) for _ in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        buf.stop()

        total_sent = sum(len(b) for b in transport.batches)
        stats = buf.stats
        total = total_sent + stats["drop_count"] + stats["buffered"]
        assert total == num_threads * per_thread

    def test_flush_racing_with_append(self) -> None:
        """Concurrent flush and append from different threads."""
        transport = FakeTransport()
        config = make_config(batch_size=100)
        buf = LogBuffer(transport, config)

        barrier = threading.Barrier(2)

        def appender() -> None:
            barrier.wait()
            for i in range(500):
                buf.append(make_entry(ts=i))

        def flusher() -> None:
            barrier.wait()
            for _ in range(50):
                buf.flush()

        t1 = threading.Thread(target=appender)
        t2 = threading.Thread(target=flusher)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        buf.stop()

        total_sent = sum(len(b) for b in transport.batches)
        stats = buf.stats
        total = total_sent + stats["drop_count"] + stats["buffered"]
        assert total == 500

    def test_stop_while_background_flush_active(self) -> None:
        """stop() called while background flush thread is running."""
        transport = FakeTransport()
        config = make_config(
            batch_size=100, flush_interval=0.01,
        )
        buf = LogBuffer(transport, config)

        for i in range(50):
            buf.append(make_entry(ts=i))

        # Stop should join the thread cleanly
        buf.stop()
        assert buf._stop_event.is_set()

    def test_double_stop_from_two_threads(self) -> None:
        """Double stop() from two threads simultaneously."""
        transport = FakeTransport()
        config = make_config()
        buf = LogBuffer(transport, config)

        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def stopper() -> None:
            barrier.wait()
            try:
                buf.stop()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=stopper)
        t2 = threading.Thread(target=stopper)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) == 0


class TestTransportConcurrency:
    def test_concurrent_send_aggregate_counters(self) -> None:
        """Concurrent send() calls produce correct aggregate counters."""
        config = make_config()
        transport = LokiTransport(config)

        num_threads = 5
        per_thread = 20
        barrier = threading.Barrier(num_threads)

        with patch.object(
            transport._client, "post",
        ) as mock_post:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            mock_post.return_value = resp

            def worker() -> None:
                barrier.wait()
                for _ in range(per_thread):
                    transport.send([make_entry()])

            threads = [
                threading.Thread(target=worker)
                for _ in range(num_threads)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert transport.sent_count == num_threads * per_thread
        assert transport.error_count == 0
        transport.close()
