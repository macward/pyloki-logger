from __future__ import annotations

import gzip
import json
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import httpx
import pytest

from loki_client.models import LogEntry, LokiConfig
from loki_client.transport import LokiTransport


@pytest.fixture
def config() -> LokiConfig:
    return LokiConfig(endpoint="http://loki:3100", app="testapp")


@pytest.fixture
def config_no_gzip() -> LokiConfig:
    return LokiConfig(
        endpoint="http://loki:3100",
        app="testapp",
        gzip_enabled=False,
    )


@pytest.fixture
def config_with_auth() -> LokiConfig:
    return LokiConfig(
        endpoint="http://loki:3100",
        app="testapp",
        auth_header="Bearer tok123",
    )


@pytest.fixture
def transport(config: LokiConfig) -> Generator[LokiTransport, None, None]:
    t = LokiTransport(config)
    yield t
    t.close()


def _make_entry(
    msg: str = "hello",
    level: str = "info",
    labels: dict[str, str] | None = None,
    metadata: dict[str, str] | None = None,
    ts: int = 1_000_000_000,
) -> LogEntry:
    return LogEntry(
        level=level,
        message=msg,
        labels=labels or {"app": "testapp"},
        metadata=metadata or {},
        timestamp_ns=ts,
    )


def _mock_success() -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    return resp


class TestBuildStreams:
    def test_single_stream(self, transport: LokiTransport) -> None:
        entries = [_make_entry("a", ts=1), _make_entry("b", ts=2)]
        streams, entries_per_stream = transport._build_streams(entries)

        assert len(streams) == 1
        assert streams[0]["stream"] == {"app": "testapp"}
        assert streams[0]["values"] == [["1", "a"], ["2", "b"]]
        assert entries_per_stream[0] == entries

    def test_multiple_streams(self, transport: LokiTransport) -> None:
        entries = [
            _make_entry("a", labels={"app": "a"}),
            _make_entry("b", labels={"app": "b"}),
        ]
        streams, entries_per_stream = transport._build_streams(entries)

        assert len(streams) == 2
        labels = {json.dumps(s["stream"], sort_keys=True) for s in streams}
        assert labels == {'{"app": "a"}', '{"app": "b"}'}
        all_entries = [e for group in entries_per_stream for e in group]
        assert set(id(e) for e in all_entries) == set(id(e) for e in entries)

    def test_metadata_in_line(self, transport: LokiTransport) -> None:
        entries = [_make_entry("msg", metadata={"rid": "123"}, ts=1)]
        streams, _ = transport._build_streams(entries)

        assert streams[0]["values"] == [["1", "msg | rid=123"]]


class TestURLConstruction:
    def test_url_construction(self, config: LokiConfig) -> None:
        transport = LokiTransport(config)
        assert transport._url == "http://loki:3100/loki/api/v1/push"
        transport.close()

    def test_trailing_slash_stripped(self) -> None:
        cfg = LokiConfig(endpoint="http://loki:3100/")
        transport = LokiTransport(cfg)
        assert transport._url == "http://loki:3100/loki/api/v1/push"
        transport.close()


class TestSend:
    def test_post_json_gzipped(self, transport: LokiTransport) -> None:
        with patch.object(
            transport._client,
            "post",
            return_value=_mock_success(),
        ) as mock_post:
            failed = transport.send([_make_entry()])

        assert failed == []
        call = mock_post.call_args
        assert call.kwargs["headers"]["Content-Encoding"] == "gzip"
        assert call.kwargs["headers"]["Content-Type"] == "application/json"

        body = gzip.decompress(call.kwargs["content"])
        payload = json.loads(body)
        assert "streams" in payload
        assert transport.sent_count == 1

    def test_post_without_gzip(self, config_no_gzip: LokiConfig) -> None:
        transport = LokiTransport(config_no_gzip)
        with patch.object(
            transport._client,
            "post",
            return_value=_mock_success(),
        ) as mock_post:
            transport.send([_make_entry()])

        call = mock_post.call_args
        assert "Content-Encoding" not in call.kwargs["headers"]
        payload = json.loads(call.kwargs["content"])
        assert "streams" in payload
        transport.close()

    def test_auth_header(self, config_with_auth: LokiConfig) -> None:
        transport = LokiTransport(config_with_auth)
        with patch.object(
            transport._client,
            "post",
            return_value=_mock_success(),
        ) as mock_post:
            transport.send([_make_entry()])

        call = mock_post.call_args
        assert call.kwargs["headers"]["Authorization"] == "Bearer tok123"
        transport.close()

    def test_empty_batch_noop(self, transport: LokiTransport) -> None:
        with patch.object(transport._client, "post") as mock_post:
            failed = transport.send([])
        mock_post.assert_not_called()
        assert failed == []

    def test_send_returns_failed_batches(self, transport: LokiTransport) -> None:
        entry = _make_entry()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        with patch.object(transport._client, "post", return_value=mock_resp):
            failed = transport.send([entry])

        assert len(failed) == 1
        assert failed[0] == [entry]

    def test_multi_batch_partial_failure(self) -> None:
        cfg = LokiConfig(
            endpoint="http://loki:3100",
            app="testapp",
            max_batch_bytes=200,
        )
        transport = LokiTransport(cfg)

        e1 = _make_entry("a" * 80, labels={"s": "1"}, ts=1)
        e2 = _make_entry("b" * 80, labels={"s": "2"}, ts=2)
        e3 = _make_entry("c" * 80, labels={"s": "3"}, ts=3)

        ok_resp = _mock_success()
        fail_resp = MagicMock()
        fail_resp.raise_for_status.side_effect = (
            httpx.HTTPStatusError(
                "500", request=MagicMock(), response=MagicMock(),
            )
        )

        streams, _ = transport._build_streams([e1, e2, e3])
        batches = transport._split_batches(streams)
        assert len(batches) > 1

        responses = []
        for i in range(len(batches)):
            responses.append(fail_resp if i == 0 else ok_resp)

        with patch.object(
            transport._client, "post", side_effect=responses,
        ):
            failed = transport.send([e1, e2, e3])

        assert len(failed) == 1
        for entry in failed[0]:
            assert entry in [e1, e2, e3]
        transport.close()

    def test_sent_count_tracks_entries_not_batches(
        self, transport: LokiTransport
    ) -> None:
        entries = [_make_entry(ts=1), _make_entry(ts=2), _make_entry(ts=3)]
        with patch.object(
            transport._client,
            "post",
            return_value=_mock_success(),
        ):
            transport.send(entries)

        assert transport.sent_count == 3


class TestSubBatchSplitting:
    def test_splits_when_exceeding_max_bytes(self) -> None:
        cfg = LokiConfig(
            endpoint="http://loki:3100",
            app="testapp",
            max_batch_bytes=200,
        )
        transport = LokiTransport(cfg)

        entries = [
            _make_entry("a" * 80, labels={"s": "1"}, ts=1),
            _make_entry("b" * 80, labels={"s": "2"}, ts=2),
            _make_entry("c" * 80, labels={"s": "3"}, ts=3),
        ]

        streams, _ = transport._build_streams(entries)
        batches = transport._split_batches(streams)

        assert len(batches) > 1
        for batch in batches:
            assert "streams" in batch
        transport.close()

    def test_batch_size_accounts_for_wrapper_overhead(self) -> None:
        cfg = LokiConfig(
            endpoint="http://loki:3100",
            app="testapp",
            max_batch_bytes=500,
        )
        transport = LokiTransport(cfg)

        entries = [_make_entry("x" * 100, labels={"s": str(i)}, ts=i) for i in range(5)]

        streams, _ = transport._build_streams(entries)
        batches = transport._split_batches(streams)

        for batch in batches:
            serialized = json.dumps(batch).encode()
            assert len(serialized) <= cfg.max_batch_bytes + 200
        transport.close()


class TestErrorCounting:
    def test_http_status_error_increments_error_count(
        self, transport: LokiTransport
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )

        with patch.object(transport._client, "post", return_value=mock_resp):
            transport.send([_make_entry()])

        assert transport.error_count == 1
        assert transport.sent_count == 0

    def test_connection_error_increments_drop_count(
        self, transport: LokiTransport
    ) -> None:
        with patch.object(
            transport._client,
            "post",
            side_effect=httpx.ConnectError("fail"),
        ):
            transport.send([_make_entry()])

        assert transport.drop_count == 1
        assert transport.sent_count == 0


class TestClose:
    def test_close_delegates_to_httpx_client(self, config: LokiConfig) -> None:
        transport = LokiTransport(config)
        with patch.object(transport._client, "close") as mock_close:
            transport.close()
        mock_close.assert_called_once()
