from __future__ import annotations

import gzip
import json
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from loki_client.models import LogEntry, LokiConfig

_WRAPPER_OVERHEAD = len(b'{"streams":[]}')
_COMMA_OVERHEAD = 1


class LokiTransport:
    """HTTP transport that serializes log batches and POSTs to Loki.

    Counter semantics:
        sent_count   — number of log entries successfully delivered.
        error_count  — server responded with 4xx/5xx (may be retryable).
        drop_count   — network failure, request never reached server.
    """

    def __init__(self, config: LokiConfig) -> None:
        self._config = config
        self._client = httpx.Client(timeout=config.timeout)
        self._url = f"{config.endpoint.rstrip('/')}/loki/api/v1/push"
        self.sent_count: int = 0
        self.drop_count: int = 0
        self.error_count: int = 0

    def send(self, entries: list[LogEntry]) -> list[list[LogEntry]]:
        """Send entries to Loki. Returns list of failed entry batches."""
        if not entries:
            return []

        streams = self._build_streams(entries)
        batches = self._split_batches(streams)
        failed: list[list[LogEntry]] = []

        for batch in batches:
            ok = self._post(batch)
            if not ok:
                batch_entries = [
                    e
                    for e in entries
                    if any(
                        [str(e.timestamp_ns), e.line] in s["values"]
                        for s in batch["streams"]
                    )
                ]
                failed.append(batch_entries)

        return failed

    def close(self) -> None:
        self._client.close()

    def _build_streams(self, entries: list[LogEntry]) -> list[dict[str, object]]:
        grouped: dict[str, tuple[dict[str, str], list[LogEntry]]] = {}
        for entry in entries:
            key = json.dumps(entry.labels, sort_keys=True)
            if key not in grouped:
                grouped[key] = (entry.labels, [])
            grouped[key][1].append(entry)

        streams: list[dict[str, object]] = []
        for _, (labels, group) in grouped.items():
            values = [[str(e.timestamp_ns), e.line] for e in group]
            streams.append({"stream": labels, "values": values})
        return streams

    def _split_batches(
        self, streams: list[dict[str, object]]
    ) -> list[dict[str, list[dict[str, object]]]]:
        max_bytes = self._config.max_batch_bytes
        batches: list[dict[str, list[dict[str, object]]]] = []
        current: list[dict[str, object]] = []
        current_size = _WRAPPER_OVERHEAD

        for stream in streams:
            stream_size = len(json.dumps(stream).encode())
            comma = _COMMA_OVERHEAD if current else 0
            projected = current_size + comma + stream_size

            if current and projected > max_bytes:
                batches.append({"streams": current})
                current = []
                current_size = _WRAPPER_OVERHEAD

            current.append(stream)
            current_size += (_COMMA_OVERHEAD if len(current) > 1 else 0) + stream_size

        if current:
            batches.append({"streams": current})
        return batches

    def _post(self, payload: dict[str, list[dict[str, object]]]) -> bool:
        """POST a payload to Loki. Returns True on success."""
        body = json.dumps(payload).encode()
        headers: dict[str, str] = {"Content-Type": "application/json"}

        if self._config.auth_header:
            headers["Authorization"] = self._config.auth_header

        if self._config.gzip_enabled:
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"

        try:
            resp = self._client.post(self._url, content=body, headers=headers)
            resp.raise_for_status()
            entry_count = sum(len(s["values"]) for s in payload["streams"])
            self.sent_count += entry_count
            return True
        except httpx.HTTPStatusError:
            self.error_count += 1
            return False
        except httpx.HTTPError:
            self.drop_count += 1
            return False
