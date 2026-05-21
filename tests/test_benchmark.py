from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import codex_fast_proxy.benchmark as benchmark  # noqa: E402
from codex_fast_proxy.benchmark import (  # noqa: E402
    BenchmarkTarget,
    benchmark_payload,
    discover_api_key,
    extract_response_service_tier,
    output_text_delta,
    priority_accepted,
    response_path,
    run_benchmark,
    sample_plan,
    summarize_samples,
    priority_confirmed,
)


class FakeResponse:
    def __init__(self, status: int, body: bytes, content_type: str = "text/event-stream") -> None:
        self.status = status
        self.lines = body.splitlines(keepends=True)
        self.content_type = content_type

    def read(self) -> bytes:
        body = b"".join(self.lines)
        self.lines = []
        return body

    def readline(self) -> bytes:
        if not self.lines:
            return b""
        return self.lines.pop(0)

    def getheader(self, name: str) -> str | None:
        return self.content_type if name.lower() == "content-type" else None


class FakeConnection:
    def __init__(self) -> None:
        self.body = b""

    def request(self, _method, _path, body=None, headers=None):
        self.body = body or b""
        self.headers = headers or {}

    def getresponse(self):
        payload = json.loads(self.body.decode("utf-8"))
        tier = payload.get("service_tier", "default")
        created = json.dumps({"type": "response.created", "service_tier": tier}).encode("utf-8")
        delta = json.dumps({"type": "response.output_text.delta", "delta": "review text"}).encode("utf-8")
        return FakeResponse(
            200,
            b"event: response.created\n"
            + b"data: "
            + created
            + b"\n\n"
            + b"event: response.output_text.delta\n"
            + b"data: "
            + delta
            + b"\n\n",
        )

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
            self.assertEqual(
                discover_api_key({"env_key": "ACME_API_KEY"}, None, ROOT / ".missing-codex-home"),
                ("env:ACME_API_KEY", "secret"),
            )
        finally:
            if original is None:
                os.environ.pop("ACME_API_KEY", None)
            else:
                os.environ["ACME_API_KEY"] = original

    def test_discover_api_key_falls_back_to_codex_auth(self) -> None:
        temp_root = ROOT / ".test_tmp"
        temp_root.mkdir(exist_ok=True)
        codex_home = temp_root / f"codex-home-{uuid.uuid4().hex}"
        codex_home.mkdir()
        try:
            (codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "secret"}), encoding="utf-8")
            self.assertEqual(discover_api_key({}, None, codex_home), ("auth.json:OPENAI_API_KEY", "secret"))
        finally:
            shutil.rmtree(codex_home)

    def test_sample_plan_balances_order(self) -> None:
        self.assertEqual(sample_plan(2), ["default", "priority", "priority", "default"])
        paired = benchmark.paired_sample_plan(4, randomize=False)
        self.assertEqual([item["pair_id"] for item in paired[:2]], [1, 1])
        self.assertEqual([item["order"] for item in paired[:2]], [1, 2])

    def test_extract_response_service_tier_ignores_non_json(self) -> None:
        self.assertIsNone(extract_response_service_tier(b"not json"))
        self.assertEqual(extract_response_service_tier(b'{"service_tier":"priority","output":"ignored"}'), "priority")
        self.assertEqual(
            extract_response_service_tier(b"event: response.created\ndata: {\"service_tier\":\"priority\"}\n\n"),
            "priority",
        )

    def test_output_text_delta_parses_responses_stream_events(self) -> None:
        self.assertEqual(output_text_delta({"type": "response.output_text.delta", "delta": "hello"}), "hello")
        self.assertEqual(output_text_delta({"type": "response.output_text.done", "text": "hello"}), "")

    def test_priority_confirmation_is_unknown_without_response_field(self) -> None:
        self.assertIsNone(priority_confirmed(summarize_samples([{"tier": "priority", "status": 200}], "priority")))

    def test_priority_accepted_uses_status_not_response_echo(self) -> None:
        self.assertTrue(priority_accepted(summarize_samples([{"tier": "priority", "status": 200}], "priority")))
        self.assertTrue(
            priority_accepted(
                summarize_samples(
                    [{"tier": "priority", "status": 200}, {"tier": "priority", "status": None}],
                    "priority",
                )
            )
        )
        self.assertFalse(priority_accepted(summarize_samples([{"tier": "priority", "status": 400}], "priority")))
        self.assertFalse(priority_accepted(summarize_samples([{"tier": "priority", "status": None}], "priority")))

    def test_full_payload_uses_codex_like_heavy_shape(self) -> None:
        profile = benchmark.profile_for_name("full")
        cache_key = "cfp-bench-test-01-priority"
        payload = json.loads(
            benchmark_payload("gpt-test", profile, "priority", reasoning_effort="xhigh", cache_key=cache_key).decode("utf-8")
        )

        self.assertEqual(payload["service_tier"], "priority")
        self.assertEqual(payload["reasoning"], {"effort": "xhigh"})
        self.assertEqual(payload["include"], ["reasoning.encrypted_content"])
        self.assertEqual(payload["store"], False)
        self.assertEqual(payload["prompt_cache_key"], cache_key)
        self.assertEqual(payload["text"], {"verbosity": "low"})
        self.assertGreater(len(payload["instructions"]), 20000)
        self.assertNotIn("max_output_tokens", payload)
        self.assertEqual([item["role"] for item in payload["input"]], ["developer", "user", "user"])
        self.assertGreater(len(payload["input"][0]["content"][1]["text"]), 7000)
        self.assertIn("4200-5000 Chinese characters", payload["input"][2]["content"][0]["text"])

    def test_smoke_payload_can_use_low_reasoning_without_heavy_include(self) -> None:
        profile = benchmark.profile_for_name("smoke")
        payload = json.loads(
            benchmark_payload("gpt-test", profile, "priority", reasoning_effort="low").decode("utf-8")
        )

        self.assertEqual(payload["reasoning"], {"effort": "low"})
        self.assertEqual(payload["max_output_tokens"], 16)
        self.assertEqual(payload["service_tier"], "priority")
        self.assertNotIn("include", payload)
        self.assertNotIn("instructions", payload)

    def test_run_benchmark_keeps_only_redacted_metrics(self) -> None:
        target = BenchmarkTarget(
            provider="acme",
            upstream_base="https://api.example.test/v1",
            model="gpt-test",
            profile="full",
            service_tier="priority",
            api_key_source="auth.json:OPENAI_API_KEY",
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
        self.assertIn("ts", result)
        self.assertEqual(result["profile"], "full")
        self.assertEqual(result["benchmark_mode"], "direct")
        self.assertEqual(result["api_key_source"], "auth.json:OPENAI_API_KEY")
        self.assertEqual(result["default"]["ok"], 1)
        self.assertEqual(result["priority"]["ok"], 1)
        self.assertEqual(result["priority"]["median_ttft_ms"], 6000.0)
        self.assertEqual(result["priority"]["median_first_output_ms"], 6000.0)
        self.assertEqual(result["observed_speedup_ttft"], result["observed_speedup_first_output"])
        self.assertEqual(result["priority"]["median_output_chars"], 11.0)
        self.assertEqual(result["default"]["request_service_tiers"], ["<absent>"])
        self.assertEqual(result["priority"]["request_service_tiers"], ["priority"])
        self.assertEqual(result["priority"]["response_service_tiers"], ["priority"])
        self.assertTrue(result["service_tier_control"]["valid"])
        self.assertEqual(result["cache_isolation"], ["per_sample_prompt_cache_key"])
        self.assertTrue(result["priority_accepted"])
        self.assertFalse(result["observed_priority_effective"])
        self.assertTrue(result["provider_confirmed_priority"])
        self.assertEqual(result["priority_support_assessment"]["conclusion"], "confirmed")
        self.assertFalse(result["priority_support_assessment"]["latency_is_proof"])
        self.assertTrue(result["latency_result_is_observational"])
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("cfp-bench-", json.dumps(result))
        self.assertNotIn("Codex App Responses API proxy", json.dumps(result))
        self.assertNotIn("review text", json.dumps(result))

    def test_benchmark_detects_invalid_service_tier_control(self) -> None:
        target = BenchmarkTarget(
            provider="acme",
            upstream_base="https://api.example.test/v1",
            model="gpt-test",
            profile="full",
            service_tier="priority",
            api_key_source="auth.json:OPENAI_API_KEY",
            api_key="secret",
        )
        result = benchmark.summarize_benchmark_result(
            target,
            pairs=1,
            samples=[
                {"tier": "default", "status": 200, "request_service_tier": "priority"},
                {"tier": "priority", "status": 200, "request_service_tier": "priority"},
            ],
            mode="direct",
        )

        self.assertFalse(result["service_tier_control"]["valid"])
        self.assertEqual(result["service_tier_control"]["default_request_service_tiers"], ["priority"])

    def test_strict_benchmark_reports_statistical_priority_speedup(self) -> None:
        target = BenchmarkTarget(
            provider="acme",
            upstream_base="https://api.example.test/v1",
            model="gpt-test",
            profile="full",
            service_tier="priority",
            api_key_source="auth.json:OPENAI_API_KEY",
            api_key="secret",
        )
        samples = []
        for pair_id in range(1, 11):
            samples.extend([
                {
                    "tier": "default",
                    "pair_id": pair_id,
                    "status": 200,
                    "request_service_tier": None,
                    "total_ms": 1000.0 + pair_id,
                    "ttft_ms": 400.0 + pair_id,
                    "response_service_tier": "auto",
                },
                {
                    "tier": "priority",
                    "pair_id": pair_id,
                    "status": 200,
                    "request_service_tier": "priority",
                    "total_ms": 700.0 + pair_id,
                    "ttft_ms": 300.0 + pair_id,
                    "response_service_tier": "auto",
                },
            ])

        result = benchmark.summarize_benchmark_result(
            target,
            pairs=10,
            samples=samples,
            mode="direct",
            benchmark_kind="strict",
            randomized_order=True,
        )

        self.assertEqual(result["benchmark_kind"], "strict")
        self.assertTrue(result["randomized_order"])
        self.assertEqual(result["statistical_test"]["conclusion"], "priority_faster")
        self.assertTrue(result["statistical_test"]["metrics"]["total_ms"]["significant_priority_faster"])
        self.assertEqual(result["priority_support_assessment"]["observed_latency"], "statistically_faster")
        self.assertEqual(result["priority_support_assessment"]["conclusion"], "accepted_different_tier")


if __name__ == "__main__":
    unittest.main()
