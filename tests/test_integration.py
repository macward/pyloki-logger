from __future__ import annotations

import gzip
import json
from unittest.mock import MagicMock, patch

from loki_client import Loki, LokiConfig, LokiHandler


class TestEndToEnd:
    def test_log_flush_verify_payload(self) -> None:
        config = LokiConfig(
            endpoint="http://loki:3100",
            app="integration",
            environment="test",
            batch_size=100,
            flush_interval=60.0,
            gzip_enabled=True,
        )
        client = Loki(config)

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch.object(
            client._transport._client, "post", return_value=mock_resp
        ) as mock_post:
            client.info("user logged in", user_id="42")
            client.error("disk full", path="/var/log")
            client.flush()

        assert mock_post.called
        call = mock_post.call_args
        body = gzip.decompress(call.kwargs["content"])
        payload = json.loads(body)

        assert "streams" in payload
        streams = payload["streams"]
        assert len(streams) >= 1

        all_values = []
        for stream in streams:
            assert "app" in stream["stream"]
            assert stream["stream"]["app"] == "integration"
            all_values.extend(stream["values"])

        lines = [v[1] for v in all_values]
        assert any("user logged in" in line for line in lines)
        assert any("disk full" in line for line in lines)

        stats = client.stats
        assert stats["sent"] == 2
        assert stats["errors"] == 0
        client.stop()

    def test_handler_integration(self) -> None:
        import logging

        config = LokiConfig(
            endpoint="http://loki:3100",
            app="handlertest",
            environment="test",
            batch_size=100,
            flush_interval=60.0,
        )
        client = Loki(config)
        handler = LokiHandler.from_client(client)

        logger = logging.getLogger("test.integration")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._transport._client, "post", return_value=mock_resp):
            logger.info("integration test message")
            client.flush()

        assert client.stats["sent"] == 1
        logger.removeHandler(handler)
        client.stop()

    def test_stats_after_failure(self) -> None:
        config = LokiConfig(
            endpoint="http://loki:3100",
            app="failtest",
            environment="test",
            batch_size=100,
            flush_interval=60.0,
        )
        client = Loki(config)

        import httpx

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )

        with patch.object(client._transport._client, "post", return_value=mock_resp):
            client.info("will fail")
            client.flush()

        assert client.stats["errors"] == 1
        assert client.stats["sent"] == 0
        client.stop()
