from __future__ import annotations

import gzip
import json
import threading
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
        self._lock = threading.Lock()
        self._sent_count: int = 0
        self._drop_count: int = 0
        self._error_count: int = 0

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "sent_count": self._sent_count,
                "error_count": self._error_count,
                "drop_count": self._drop_count,
            }

    @property
    def sent_count(self) -> int:
        with self._lock:
            return self._sent_count

    @property
    def error_count(self) -> int:
        with self._lock:
            return self._error_count

    @property
    def drop_count(self) -> int:
        with self._lock:
            return self._drop_count

    def send(self, entries: list[LogEntry]) -> list[list[LogEntry]]:
        """Send entries to Loki. Returns list of failed entry batches."""
        if not entries:
            return []

        streams, entries_per_stream = self._build_streams(entries)
        streams, entries_per_stream = self._split_oversized_streams(
            streams, entries_per_stream,
        )
        batches = self._split_batches(streams)
        failed: list[list[LogEntry]] = []

        stream_offset = 0
        for batch in batches:
            batch_size = len(batch["streams"])
            ok = self._post(batch)
            if not ok:
                batch_entries: list[LogEntry] = []
                for i in range(
                    stream_offset, stream_offset + batch_size,
                ):
                    batch_entries.extend(entries_per_stream[i])
                failed.append(batch_entries)
            stream_offset += batch_size

        return failed

    def close(self) -> None:
        self._client.close()

    def _build_streams(
        self, entries: list[LogEntry],
    ) -> tuple[list[dict[str, object]], list[list[LogEntry]]]:
        grouped: dict[str, tuple[dict[str, str], list[LogEntry]]] = {}
        for entry in entries:
            key = json.dumps(entry.labels, sort_keys=True)
            if key not in grouped:
                grouped[key] = (entry.labels, [])
            grouped[key][1].append(entry)

        streams: list[dict[str, object]] = []
        entries_per_stream: list[list[LogEntry]] = []
        for _, (labels, group) in grouped.items():
            values = [[str(e.timestamp_ns), e.line] for e in group]
            streams.append({"stream": labels, "values": values})
            entries_per_stream.append(group)
        return streams, entries_per_stream

    def _split_oversized_streams(
        self,
        streams: list[dict[str, object]],
        entries_per_stream: list[list[LogEntry]],
    ) -> tuple[
        list[dict[str, object]], list[list[LogEntry]],
    ]:
        max_bytes = self._config.max_batch_bytes
        out_streams: list[dict[str, object]] = []
        out_entries: list[list[LogEntry]] = []

        for stream, group in zip(streams, entries_per_stream, strict=True):
            stream_size = len(json.dumps(stream).encode())
            if stream_size <= max_bytes:
                out_streams.append(stream)
                out_entries.append(group)
                continue

            labels = stream["stream"]
            values = stream["values"]
            # overhead: {"stream":<labels>,"values":[]}
            label_json = json.dumps(labels)
            base = len(
                f'{{"stream":{label_json},"values":[]}}'.encode(),
            )
            base += _WRAPPER_OVERHEAD

            chunk_vals: list[list[str]] = []
            chunk_entries: list[LogEntry] = []
            chunk_size = base

            for val, entry in zip(values, group, strict=True):  # type: ignore[arg-type]
                val_size = len(json.dumps(val).encode())
                comma = _COMMA_OVERHEAD if chunk_vals else 0
                if chunk_vals and chunk_size + comma + val_size > max_bytes:
                    out_streams.append(
                        {"stream": labels, "values": chunk_vals},
                    )
                    out_entries.append(chunk_entries)
                    chunk_vals = []
                    chunk_entries = []
                    chunk_size = base

                chunk_vals.append(val)
                chunk_entries.append(entry)
                chunk_size += (
                    _COMMA_OVERHEAD if len(chunk_vals) > 1 else 0
                ) + val_size

            if chunk_vals:
                out_streams.append(
                    {"stream": labels, "values": chunk_vals},
                )
                out_entries.append(chunk_entries)

        return out_streams, out_entries

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
            with self._lock:
                self._sent_count += entry_count
            return True
        except httpx.HTTPStatusError:
            with self._lock:
                self._error_count += 1
            return False
        except httpx.HTTPError:
            with self._lock:
                self._drop_count += 1
            return False
