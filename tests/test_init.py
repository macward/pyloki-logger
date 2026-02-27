from __future__ import annotations

import loki_client


class TestPublicExports:
    def test_all_names_importable(self) -> None:
        for name in ["Loki", "LokiHandler", "LokiConfig", "LogEntry"]:
            assert hasattr(loki_client, name)

    def test_all_list_matches(self) -> None:
        assert set(loki_client.__all__) == {
            "Loki",
            "LokiHandler",
            "LokiConfig",
            "LogEntry",
        }

    def test_from_import(self) -> None:
        from loki_client import LogEntry, Loki, LokiConfig, LokiHandler

        assert Loki is not None
        assert LokiHandler is not None
        assert LokiConfig is not None
        assert LogEntry is not None
