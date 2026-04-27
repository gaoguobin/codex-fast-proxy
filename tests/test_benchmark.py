from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import codex_fast_proxy.benchmark as benchmark  # noqa: E402
from codex_fast_proxy.benchmark import (  # noqa: E402
    BenchmarkTarget,
    extract_response_service_tier,
    resolve_api_key,
    response_path,
    run_benchmark,
    sample_plan,
    summarize_samples,
    priority_confirmed,
)


class FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body

    def read(self) -> bytes:
        return self.body


class FakeConnection:
    def __init__(self) -> None:
        self.body = b""

    def request(self, _method, _path, body=None, headers=None):
        self.body = body or b""
        self.headers = headers or {}

    def getresponse(self):
        payload = json.loads(self.body.decode("utf-8"))
        tier = payload.get("service_tier", "default")
        return FakeResponse(200, json.dumps({"service_tier": tier}).encode("utf-8"))

    def close(self):
        return None


class BenchmarkTests(unittest.TestCase):
    def test_response_path_appends_responses_under_base_path(self) -> None:
        self.assertEqual(response_path("https://api.example.test/v1"), "/v1/responses")
        self.assertEqual(response_path("https://api.example.test"), "/responses")

    def test_resolve_api_key_uses_provider_env_field(self) -> None:
        original = os.environ.get("ACME_API_KEY")
        os.environ["ACME_API_KEY"] = "secret"
        try:
            self.assertEqual(resolve_api_key({"env_key": "ACME_API_KEY"}, None), ("ACME_API_KEY", "secret"))
        finally:
            if original is None:
                os.environ.pop("ACME_API_KEY", None)
            else:
                os.environ["ACME_API_KEY"] = original

    def test_sample_plan_balances_order(self) -> None:
        self.assertEqual(sample_plan(2), ["default", "priority", "priority", "default"])

    def test_extract_response_service_tier_ignores_non_json(self) -> None:
        self.assertIsNone(extract_response_service_tier(b"not json"))
        self.assertEqual(extract_response_service_tier(b'{"service_tier":"priority","output":"ignored"}'), "priority")

    def test_priority_confirmation_is_unknown_without_response_field(self) -> None:
        self.assertIsNone(priority_confirmed(summarize_samples([{"tier": "priority", "status": 200}], "priority")))

    def test_run_benchmark_keeps_only_redacted_metrics(self) -> None:
        target = BenchmarkTarget(
            provider="acme",
            upstream_base="https://api.example.test/v1",
            model="gpt-test",
            service_tier="priority",
            api_key_env="ACME_API_KEY",
            api_key="secret",
        )
        original_clock = benchmark.time.perf_counter
        ticks = iter(range(1, 100))

        benchmark.time.perf_counter = lambda: float(next(ticks))
        try:
            result = run_benchmark(target, pairs=1, timeout=30.0, connection_factory=lambda *_args: FakeConnection())
        finally:
            benchmark.time.perf_counter = original_clock

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["default"]["ok"], 1)
        self.assertEqual(result["priority"]["ok"], 1)
        self.assertEqual(result["priority"]["response_service_tiers"], ["priority"])
        self.assertTrue(result["provider_confirmed_priority"])
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("OK", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
