# Glitch Telemetry Maintainer

You are working on the Glitch agent's telemetry system. This skill provides expert guidance for maintaining, extending, and debugging the telemetry infrastructure.

## Architecture Overview

The telemetry system has three tiers:

1. **In-Memory History** (`telemetry.py`)
   - `_telemetry_history: List[TelemetryHistoryEntry]` - bounded to 10K entries, 31 days
   - Rolling periods: hour, day, week, month
   - Calendar periods: this_hour, today, this_week, this_month

2. **CloudWatch Logs** (detailed per-invocation)
   - Enabled via `GLITCH_TELEMETRY_LOG_GROUP` env var
   - Daily log streams (`YYYY/MM/DD`)
   - JSON events with full `InvocationMetrics`

3. **CloudWatch Metrics** (long-term aggregates)
   - Namespace: `Glitch/Agent`
   - 1-hour resolution for 15-month retention

## Key Types

```python
class InvocationMetrics(TypedDict):
    duration_seconds: float
    token_usage: TokenUsage
    cycle_count: int
    latency_ms: int
    stop_reason: str
    tool_usage: Dict[str, ToolUsageStats]

class TelemetryThreshold(TypedDict):
    metric: str   # input_tokens, output_tokens, total_tokens, invocation_count, duration_seconds
    period: str   # hour, day, week, month, this_hour, today, this_week, this_month
    limit: float
```

## Key Files

- `agent/src/glitch/telemetry.py` - Core telemetry module
- `agent/src/glitch/tools/telemetry_tools.py` - Agent-callable tools
- `agent/src/glitch/types.py` - Type definitions

## Guidelines

### Adding New Metrics

1. Define the metric type in `types.py` if needed
2. Add extraction logic in `extract_metrics_from_result()`
3. Add aggregation logic in `aggregate_metrics()`
4. Expose via tool in `telemetry_tools.py`

### Threshold Management

- Thresholds are stored in-memory (`_telemetry_thresholds`)
- Use `set_telemetry_threshold()` for single thresholds
- Use `set_telemetry_thresholds()` for bulk updates (replaces all)
- Alerts are checked in `check_thresholds()` and returned with telemetry

### CloudWatch Integration

- Logs require `GLITCH_TELEMETRY_LOG_GROUP` env var
- Metrics require `GLITCH_TELEMETRY_NAMESPACE` env var (default: `Glitch/Agent`)
- Use `create_cloudwatch_metric()` tool for ad-hoc metrics

## Common Tasks

### Add a custom metric
```python
# 1. Register the metric
add_telemetry_metric(name="my_metric", unit="Count")

# 2. Record values per invocation
record_telemetry_metric(name="my_metric", value=42)

# 3. View in telemetry output
telemetry(period="hour")
```

### Set up alerts
```python
set_telemetry_thresholds([
    {"metric": "total_tokens", "period": "hour", "limit": 100000},
    {"metric": "invocation_count", "period": "day", "limit": 1000},
])
```

## Testing Changes

1. Run unit tests: `pytest agent/tests/`
2. Check telemetry output: Use `telemetry()` tool
3. Verify CloudWatch: Check log group and metrics in AWS Console
