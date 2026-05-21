from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any


EVENT_SCAN_LIMIT = 64
RESPONSE_EVENT_LIMIT = 5
PROVIDER_METADATA_LIMIT = 4
BENCHMARK_FILENAME = "fast_proxy.benchmark.json"
EVENT_DETAIL_FIELDS = (
    "ts",
    "request_id",
    "method",
    "path",
    "status",
    "ttfb_ms",
    "first_event_ms",
    "ttft_ms",
    "first_output_ms",
    "duration_ms",
    "eligible",
    "service_tier_before",
    "service_tier_after",
    "service_tier_injected",
    "service_tier_policy",
    "service_tier_effective_policy",
    "stream",
    "json_error",
    "response_content_type",
    "error_type",
)
RESPONSE_EVENT_FIELDS = EVENT_DETAIL_FIELDS
PROVIDER_METADATA_FIELDS = (
    "ts",
    "request_id",
    "method",
    "path",
    "status",
    "duration_ms",
    "response_content_type",
    "error_type",
)
BENCHMARK_FIELDS = (
    "status",
    "ts",
    "provider",
    "model",
    "benchmark_mode",
    "benchmark_kind",
    "randomized_order",
    "profile",
    "pairs",
    "provider_confirmed_priority",
    "priority_accepted",
    "priority_support_assessment",
    "statistical_test",
    "cache_isolation",
    "latency_result_is_observational",
    "observed_priority_effective",
    "observed_speedup_total",
    "observed_speedup_ttfb",
    "observed_speedup_ttft",
    "observed_speedup_first_output",
)
BENCHMARK_SUMMARY_FIELDS = (
    "count",
    "ok",
    "median_total_ms",
    "median_ttfb_ms",
    "median_first_event_ms",
    "median_ttft_ms",
    "median_first_output_ms",
)


def read_recent_events(log_path: Path, limit: int = EVENT_SCAN_LIMIT) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    events: deque[dict[str, Any]] = deque(maxlen=limit)
    try:
        with log_path.open("r", encoding="utf-8") as log_file:
            for line in log_file:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
    except OSError:
        return []
    return list(events)


def sanitized_event(event: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: event.get(key) for key in fields if key in event}


def is_response_event(event: dict[str, Any]) -> bool:
    return event.get("eligible") is True


def is_provider_metadata_event(event: dict[str, Any]) -> bool:
    return event.get("method") == "GET" and event.get("path") == "/v1/models"


def status_code(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def recent_response_events(log_path: Path) -> list[dict[str, Any]]:
    events = [event for event in read_recent_events(log_path) if is_response_event(event)]
    return [sanitized_event(event, RESPONSE_EVENT_FIELDS) for event in events[-RESPONSE_EVENT_LIMIT:]]


def recent_provider_metadata_events(log_path: Path) -> list[dict[str, Any]]:
    events = [event for event in read_recent_events(log_path) if is_provider_metadata_event(event)]
    return [sanitized_event(event, PROVIDER_METADATA_FIELDS) for event in events[-PROVIDER_METADATA_LIMIT:]]


def read_benchmark_result(log_path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads((log_path.parent / BENCHMARK_FILENAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    result = sanitized_event(value, BENCHMARK_FIELDS)
    for tier in ("default", "priority"):
        summary = value.get(tier)
        if isinstance(summary, dict):
            result[tier] = sanitized_event(summary, BENCHMARK_SUMMARY_FIELDS)
    return result
