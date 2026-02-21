"""Unit tests for CloudWatch Logs Insights telemetry query functions.

Uses mocked boto3 clients so no real AWS calls are made.
"""

import pytest
from unittest.mock import MagicMock, patch

from glitch.telemetry import (
    query_cloudwatch_telemetry,
    get_cloudwatch_aggregates,
    _merge_aggregates,
)
from glitch.types import PeriodAggregates


class TestQueryCloudWatchTelemetry:
    """Tests for query_cloudwatch_telemetry with mocked boto3."""

    def test_returns_empty_when_no_client(self):
        with patch("glitch.telemetry._get_logs_client", return_value=None):
            result = query_cloudwatch_telemetry("day")
        assert result == []

    def test_returns_empty_when_no_log_group(self):
        with patch("glitch.telemetry._get_logs_client") as mock_client:
            with patch.dict("os.environ", {}, clear=True):
                mock_client.return_value = MagicMock()
                result = query_cloudwatch_telemetry("day", log_group=None)
        assert result == []

    def test_returns_entries_when_query_completes(self):
        mock_client = MagicMock()
        mock_client.start_query.return_value = {"queryId": "q1"}
        mock_client.get_query_results.side_effect = [
            {"status": "Running"},
            {
                "status": "Complete",
                "results": [
                    [
                        {"field": "@timestamp", "value": "1700000000000"},
                        {
                            "field": "@message",
                            "value": '{"event_type": "invocation_metrics", "timestamp": 1700000000.0, '
                            '"session_id": "s1", "token_usage": {"input_tokens": 10, "output_tokens": 20, '
                            '"total_tokens": 30, "cache_read_tokens": 0, "cache_write_tokens": 0}, '
                            '"duration_seconds": 1.5, "cycle_count": 1, "latency_ms": 100, "tools_used": []}',
                        },
                    ],
                ],
            },
        ]
        with patch("glitch.telemetry._get_logs_client", return_value=mock_client):
            with patch.dict("os.environ", {"GLITCH_TELEMETRY_LOG_GROUP": "/glitch/telemetry"}):
                result = query_cloudwatch_telemetry("day", log_group="/glitch/telemetry")
        assert len(result) == 1
        assert result[0]["timestamp"] == 1700000000.0
        assert result[0]["metrics"]["token_usage"]["input_tokens"] == 10
        assert result[0]["metrics"]["token_usage"]["output_tokens"] == 20


class TestGetCloudWatchAggregates:
    """Tests for get_cloudwatch_aggregates."""

    def test_returns_aggregates_from_query_results(self):
        with patch("glitch.telemetry.query_cloudwatch_telemetry") as mock_query:
            mock_query.return_value = [
                {"timestamp": 1700000000.0, "metrics": {"token_usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30, "cache_read_tokens": 0, "cache_write_tokens": 0}, "duration_seconds": 1.0, "cycle_count": 1, "latency_ms": 50, "stop_reason": "", "tool_usage": {}}},
                {"timestamp": 1700000100.0, "metrics": {"token_usage": {"input_tokens": 5, "output_tokens": 15, "total_tokens": 20, "cache_read_tokens": 0, "cache_write_tokens": 0}, "duration_seconds": 0.5, "cycle_count": 1, "latency_ms": 30, "stop_reason": "", "tool_usage": {}}},
            ]
            agg = get_cloudwatch_aggregates("day", log_group="/glitch/telemetry")
        assert agg["invocation_count"] == 2
        assert agg["input_tokens"] == 15
        assert agg["output_tokens"] == 35
        assert agg["total_tokens"] == 50
        assert agg["duration_seconds"] == 1.5


class TestMergeAggregates:
    """Tests for _merge_aggregates."""

    def test_sums_numeric_fields(self):
        a: PeriodAggregates = {
            "invocation_count": 2,
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "duration_seconds": 2.0,
            "latency_ms_total": 200,
            "latency_ms_avg": 100,
        }
        b: PeriodAggregates = {
            "invocation_count": 3,
            "input_tokens": 50,
            "output_tokens": 25,
            "total_tokens": 75,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "duration_seconds": 1.5,
            "latency_ms_total": 150,
            "latency_ms_avg": 50,
        }
        out = _merge_aggregates(a, b)
        assert out["invocation_count"] == 5
        assert out["input_tokens"] == 150
        assert out["output_tokens"] == 75
        assert out["duration_seconds"] == 3.5
        assert out["latency_ms_total"] == 350
        assert out["latency_ms_avg"] == 70
