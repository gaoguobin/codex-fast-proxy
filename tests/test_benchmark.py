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
        payload = json.loads(
            benchmark_payload("gpt-test", profile, "priority", reasoning_effort="xhigh").decode("utf-8")
        )

        self.assertEqual(payload["service_tier"], "priority")
        self.assertEqual(payload["reasoning"], {"effort": "xhigh"})
        self.assertEqual(payload["include"], ["reasoning.encrypted_content"])
        self.assertEqual(payload["store"], False)
        self.assertEqual(payload["prompt_cache_key"], "codex-fast-proxy-benchmark-full-v1")
        self.assertEqual(payload["text"], {"verbosity": "low"})
        self.assertGreater(len(payload["instructions"]), 20000)
        self.assertNotIn("max_output_tokens", payload)
        self.assertEqual([item["role"] for item in payload["input"]], ["developer", "user", "user"])
        self.assertGreater(len(payload["input"][0]["content"][1]["text"]), 7000)
        self.assertIn("4200-5000 Chinese characters", payload["input"][2]["content"][0]["text"])

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
        self.assertEqual(result["priority"]["median_first_output_ms"], 6000.0)
        self.assertEqual(result["priority"]["median_output_chars"], 11.0)
        self.assertEqual(result["priority"]["response_service_tiers"], ["priority"])
        self.assertTrue(result["priority_accepted"])
        self.assertFalse(result["observed_priority_effective"])
        self.assertTrue(result["provider_confirmed_priority"])
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("Codex App Responses API proxy", json.dumps(result))
        self.assertNotIn("review text", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
