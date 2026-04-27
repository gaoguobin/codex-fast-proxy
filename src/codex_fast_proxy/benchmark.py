from __future__ import annotations

import http.client
import json
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .proxy import compact_json, join_paths


ConnectionFactory = Callable[[str, str, int | None, float], http.client.HTTPConnection]


@dataclass(frozen=True)
class BenchmarkTarget:
    provider: str
    upstream_base: str
    model: str
    service_tier: str
    api_key_env: str
    api_key: str


def resolve_api_key_env(provider_config: dict[str, Any], requested: str | None) -> str:
    if requested:
        return requested
    for key in ("api_key_env_var", "env_key", "api_key_env"):
        value = provider_config.get(key)
        if isinstance(value, str) and value:
            return value
    raise ValueError("Provider has no api key environment field; rerun with --api-key-env.")


def resolve_api_key(provider_config: dict[str, Any], requested: str | None) -> tuple[str, str]:
    env_name = resolve_api_key_env(provider_config, requested)
    api_key = os.environ.get(env_name)
    if not api_key:
        raise ValueError(f"Environment variable {env_name!r} is not set.")
    return env_name, api_key


def response_path(upstream_base: str) -> str:
    parsed = urlsplit(upstream_base)
    base_path = parsed.path.rstrip("/") or "/"
    return join_paths(base_path, "/responses")


def default_connection_factory(scheme: str, host: str, port: int | None, timeout: float) -> http.client.HTTPConnection:
    connection_class = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    return connection_class(host, port, timeout=timeout)


def benchmark_payload(model: str, service_tier: str | None) -> bytes:
    payload: dict[str, Any] = {
        "model": model,
        "input": "Reply with the single word OK.",
        "max_output_tokens": 16,
        "stream": False,
    }
    if service_tier:
        payload["service_tier"] = service_tier
    return compact_json(payload).encode("utf-8")


def extract_response_service_tier(body: bytes) -> str | None:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("service_tier")
    return value if isinstance(value, str) and value else None


def run_sample(
    target: BenchmarkTarget,
    label: str,
    timeout: float,
    connection_factory: ConnectionFactory = default_connection_factory,
) -> dict[str, Any]:
    parsed = urlsplit(target.upstream_base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid upstream base URL: {target.upstream_base}")

    body = benchmark_payload(target.model, target.service_tier if label == "priority" else None)
    headers = {
        "Authorization": f"Bearer {target.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Content-Length": str(len(body)),
    }

    started = time.perf_counter()
    connection = connection_factory(parsed.scheme, parsed.hostname or parsed.netloc, parsed.port, timeout)
    try:
        connection.request("POST", response_path(target.upstream_base), body=body, headers=headers)
        response = connection.getresponse()
        headers_at = time.perf_counter()
        response_body = response.read()
        finished = time.perf_counter()
    finally:
        connection.close()

    return {
        "tier": label,
        "status": response.status,
        "ttfb_ms": round((headers_at - started) * 1000, 1),
        "total_ms": round((finished - started) * 1000, 1),
        "response_service_tier": extract_response_service_tier(response_body),
    }


def sample_plan(pairs: int) -> list[str]:
    plan: list[str] = []
    for index in range(pairs):
        plan.extend(("default", "priority") if index % 2 == 0 else ("priority", "default"))
    return plan


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def summarize_samples(samples: list[dict[str, Any]], label: str) -> dict[str, Any]:
    matching = [sample for sample in samples if sample.get("tier") == label]
    ok_samples = [sample for sample in matching if int(sample.get("status") or 0) < 400]
    total_values = [float(sample["total_ms"]) for sample in ok_samples if sample.get("total_ms") is not None]
    ttfb_values = [float(sample["ttfb_ms"]) for sample in ok_samples if sample.get("ttfb_ms") is not None]
    tiers = sorted({sample["response_service_tier"] for sample in ok_samples if sample.get("response_service_tier")})
    return {
        "count": len(matching),
        "ok": len(ok_samples),
        "median_total_ms": median(total_values),
        "median_ttfb_ms": median(ttfb_values),
        "response_service_tiers": tiers,
    }


def speedup(default_ms: float | None, priority_ms: float | None) -> float | None:
    if not default_ms or not priority_ms:
        return None
    return round(default_ms / priority_ms, 2)


def priority_confirmed(priority_summary: dict[str, Any]) -> bool | None:
    tiers = priority_summary["response_service_tiers"]
    if not tiers:
        return None
    return "priority" in tiers


def run_benchmark(
    target: BenchmarkTarget,
    pairs: int,
    timeout: float,
    connection_factory: ConnectionFactory = default_connection_factory,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for label in sample_plan(pairs):
        try:
            samples.append(run_sample(target, label, timeout, connection_factory))
        except Exception as exc:
            samples.append({"tier": label, "status": None, "error_type": type(exc).__name__})

    default_summary = summarize_samples(samples, "default")
    priority_summary = summarize_samples(samples, "priority")
    return {
        "status": "completed",
        "provider": target.provider,
        "upstream_base": target.upstream_base,
        "model": target.model,
        "pairs": pairs,
        "samples": samples,
        "default": default_summary,
        "priority": priority_summary,
        "observed_speedup_total": speedup(default_summary["median_total_ms"], priority_summary["median_total_ms"]),
        "observed_speedup_ttfb": speedup(default_summary["median_ttfb_ms"], priority_summary["median_ttfb_ms"]),
        "provider_confirmed_priority": priority_confirmed(priority_summary),
        "privacy": "Synthetic prompt only; response content and API key are not stored.",
    }


def save_benchmark_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
