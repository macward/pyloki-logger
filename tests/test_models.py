import warnings

import pytest

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

    @pytest.mark.parametrize(
        "field, value, match",
        [
            ("endpoint", "", "endpoint must not be empty"),
            ("batch_size", 0, "batch_size must be > 0"),
            ("batch_size", -1, "batch_size must be > 0"),
            ("flush_interval", 0, "flush_interval must be > 0"),
            ("flush_interval", -1.0, "flush_interval must be > 0"),
            ("max_buffer_size", 0, "max_buffer_size must be > 0"),
            ("max_batch_bytes", 0, "max_batch_bytes must be > 0"),
            ("max_retries", -1, "max_retries must be >= 0"),
            ("retry_backoff", -1.0, "retry_backoff must be >= 0"),
            ("timeout", 0, "timeout must be > 0"),
            ("timeout", -1.0, "timeout must be > 0"),
        ],
    )
    def test_validation_rejects_invalid(
        self, field: str, value: object, match: str,
    ) -> None:
        kwargs: dict[str, object] = {"endpoint": "http://localhost:3100"}
        kwargs[field] = value
        with pytest.raises(ValueError, match=match):
            LokiConfig(**kwargs)  # type: ignore[arg-type]

    def test_auth_header_hidden_from_repr(self) -> None:
        cfg = LokiConfig(
            endpoint="http://localhost:3100",
            auth_header="Bearer secret-token",
        )
        r = repr(cfg)
        assert "secret-token" not in r
        assert "auth_header" not in r

    def test_auth_header_hidden_from_str(self) -> None:
        cfg = LokiConfig(
            endpoint="http://localhost:3100",
            auth_header="Bearer secret-token",
        )
        assert "secret-token" not in str(cfg)

    def test_frozen_raises_on_mutation(self) -> None:
        cfg = LokiConfig(endpoint="http://localhost:3100")
        with pytest.raises(AttributeError):
            cfg.batch_size = 999  # type: ignore[misc]

    def test_max_retries_zero_is_valid(self) -> None:
        cfg = LokiConfig(endpoint="http://localhost:3100", max_retries=0)
        assert cfg.max_retries == 0

    def test_retry_backoff_zero_is_valid(self) -> None:
        cfg = LokiConfig(endpoint="http://localhost:3100", retry_backoff=0.0)
        assert cfg.retry_backoff == 0.0

    def test_max_message_bytes_none_is_default(self) -> None:
        cfg = LokiConfig(endpoint="http://localhost:3100")
        assert cfg.max_message_bytes is None

    def test_max_message_bytes_positive_is_valid(self) -> None:
        cfg = LokiConfig(
            endpoint="http://localhost:3100", max_message_bytes=1024,
        )
        assert cfg.max_message_bytes == 1024

    def test_max_message_bytes_zero_invalid(self) -> None:
        with pytest.raises(ValueError, match="max_message_bytes"):
            LokiConfig(
                endpoint="http://localhost:3100", max_message_bytes=0,
            )

    def test_max_message_bytes_negative_invalid(self) -> None:
        with pytest.raises(ValueError, match="max_message_bytes"):
            LokiConfig(
                endpoint="http://localhost:3100", max_message_bytes=-1,
            )

    def test_tls_warning_on_http_with_auth(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            LokiConfig(
                endpoint="http://localhost:3100",
                auth_header="Bearer token",
            )
        assert len(w) == 1
        assert "cleartext" in str(w[0].message)

    def test_no_tls_warning_on_https(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            LokiConfig(
                endpoint="https://localhost:3100",
                auth_header="Bearer token",
            )
        assert len(w) == 0

    def test_no_tls_warning_without_auth(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            LokiConfig(endpoint="http://localhost:3100")
        assert len(w) == 0


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

    def test_line_escapes_pipe_in_value(self) -> None:
        entry = LogEntry(
            level="info",
            message="msg",
            labels={"app": "test"},
            metadata={"data": "a | b"},
        )
        assert " | " not in entry.line.split(" | ", 1)[1].replace(
            '"a | b"', "",
        )
        assert 'data="a | b"' in entry.line

    def test_line_escapes_equals_in_value(self) -> None:
        entry = LogEntry(
            level="info",
            message="msg",
            labels={"app": "test"},
            metadata={"expr": "x=1"},
        )
        assert 'expr="x=1"' in entry.line

    def test_line_escapes_special_keys(self) -> None:
        entry = LogEntry(
            level="info",
            message="msg",
            labels={"app": "test"},
            metadata={"key with spaces": "val"},
        )
        assert '"key with spaces"=val' in entry.line

    def test_line_escapes_quotes_in_value(self) -> None:
        entry = LogEntry(
            level="info",
            message="msg",
            labels={"app": "test"},
            metadata={"q": 'say "hi"'},
        )
        assert r'q="say \"hi\""' in entry.line

    def test_line_empty_value_is_quoted(self) -> None:
        entry = LogEntry(
            level="info",
            message="msg",
            labels={"app": "test"},
            metadata={"empty": ""},
        )
        assert 'empty=""' in entry.line

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
