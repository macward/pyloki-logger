from loki_client.models import LogEntry, LokiConfig


class TestLokiConfig:
    def test_defaults(self) -> None:
        cfg = LokiConfig(endpoint="http://localhost:3100/loki/api/v1/push")
        assert cfg.app == "default"
        assert cfg.environment == "production"
        assert cfg.batch_size == 100
        assert cfg.flush_interval == 5.0
        assert cfg.max_buffer_size == 10_000
        assert cfg.max_retries == 3
        assert cfg.gzip_enabled is True
        assert cfg.auth_header is None
        assert cfg.extra_labels == {}


class TestLogEntry:
    def test_line_plain_message(self) -> None:
        entry = LogEntry(level="info", message="hello", labels={"app": "test"})
        assert entry.line == "hello"

    def test_line_with_metadata(self) -> None:
        entry = LogEntry(
            level="error",
            message="request failed",
            labels={"app": "test"},
            metadata={"request_id": "abc123", "status": "500"},
        )
        assert entry.line == "request failed | request_id=abc123 status=500"

    def test_immutability(self) -> None:
        entry = LogEntry(level="info", message="hello", labels={"app": "test"})
        try:
            entry.level = "error"  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass

    def test_timestamp_ns_is_nanoseconds(self) -> None:
        entry = LogEntry(level="info", message="hello", labels={"app": "test"})
        # Nanosecond timestamps are at least 19 digits (since ~2001)
        assert entry.timestamp_ns > 1_000_000_000_000_000_000
