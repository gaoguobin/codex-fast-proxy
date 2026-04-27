from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_fast_proxy.dashboard import (  # noqa: E402
    read_benchmark_result,
    read_recent_events,
    render_dashboard,
    safe_url_display,
)
from codex_fast_proxy.proxy import (  # noqa: E402
    copy_request_headers,
    dashboard_requested,
    parse_args,
    service_tier_patch,
    stream_response_body,
    upstream_request_path,
)


class FakeHeaders:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def items(self):
        return self.values.items()


class FakeLineResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def readline(self) -> bytes:
        if not self.lines:
            return b""
        return self.lines.pop(0)

    def read(self, _size: int) -> bytes:
        raise AssertionError("SSE should use line-buffered reads")


class ProxyPatchTests(unittest.TestCase):
    def test_injects_missing_service_tier_without_changing_payload_fields(self) -> None:
        payload = {
            "model": "gpt-5.4",
            "stream": True,
            "input": [{"role": "user", "content": "hello"}],
            "reasoning": {"effort": "high"},
            "tools": [{"type": "web_search"}],
        }
        body, event = service_tier_patch(
            "POST",
            "/v1/responses",
            json.dumps(payload).encode("utf-8"),
            "application/json",
            "priority",
        )

        patched = json.loads(body)
        self.assertEqual(patched["service_tier"], "priority")
        for key in ("model", "stream", "input", "reasoning", "tools"):
            self.assertEqual(patched[key], payload[key])
        self.assertTrue(event["eligible"])
        self.assertTrue(event["injected"])
        self.assertEqual(event["service_tier_before"], "<absent>")
        self.assertEqual(event["service_tier_after"], "priority")

    def test_preserves_existing_service_tier(self) -> None:
        payload = {"model": "gpt-5.4", "stream": True, "service_tier": "auto"}
        body, event = service_tier_patch(
            "POST",
            "/v1/responses",
            json.dumps(payload).encode("utf-8"),
            "application/json",
            "priority",
        )

        self.assertEqual(json.loads(body)["service_tier"], "auto")
        self.assertFalse(event["injected"])
        self.assertEqual(event["service_tier_before"], "auto")
        self.assertEqual(event["service_tier_after"], "auto")

    def test_leaves_non_responses_paths_untouched(self) -> None:
        body = b'{"model":"gpt-5.4"}'
        patched, event = service_tier_patch("POST", "/v1/chat/completions", body, "application/json", "priority")

        self.assertEqual(patched, body)
        self.assertFalse(event["eligible"])
        self.assertFalse(event["injected"])

    def test_leaves_non_json_responses_body_untouched(self) -> None:
        body = b"model=gpt-5.4"
        patched, event = service_tier_patch("POST", "/v1/responses", body, "text/plain", "priority")

        self.assertEqual(patched, body)
        self.assertTrue(event["eligible"])
        self.assertFalse(event["injected"])

    def test_maps_proxy_path_to_upstream_path(self) -> None:
        self.assertEqual(upstream_request_path("/v1/responses?stream=1", "/v1", "/v1"), "/v1/responses?stream=1")
        self.assertEqual(upstream_request_path("/local/responses", "/local", "/v1"), "/v1/responses")
        self.assertEqual(upstream_request_path("/v1/models", "/v1", "/v1"), "/v1/models")

    def test_request_headers_drop_hop_by_hop_and_update_length(self) -> None:
        headers = FakeHeaders(
            {
                "Authorization": "Bearer secret",
                "Connection": "keep-alive",
                "Content-Length": "1",
                "Host": "127.0.0.1:8787",
                "Accept": "text/event-stream",
            }
        )

        copied = copy_request_headers(headers, "www.packyapi.com", 42)

        self.assertEqual(copied["Authorization"], "Bearer secret")
        self.assertEqual(copied["Accept"], "text/event-stream")
        self.assertEqual(copied["Host"], "www.packyapi.com")
        self.assertEqual(copied["Content-Length"], "42")
        self.assertNotIn("Connection", copied)

    def test_sse_payload_bytes_are_forwarded_without_event_rewrite(self) -> None:
        response = FakeLineResponse([b"event: response.output_text.delta\n", b"data: {\"x\":1}\n", b"\n"])
        writer = BytesIO()

        stream_response_body(response, writer, chunked=False, line_buffered=True)

        self.assertEqual(writer.getvalue(), b"event: response.output_text.delta\ndata: {\"x\":1}\n\n")

    def test_foreground_proxy_default_log_dir_uses_runtime_state_dir(self) -> None:
        args = parse_args(["--upstream-base", "https://api.example.test/v1"])
        expected_suffixes = (
            ".codex\\codex-fast-proxy-state\\state",
            ".codex/codex-fast-proxy-state/state",
        )

        self.assertTrue(args.log_dir.endswith(expected_suffixes))


class DashboardTests(unittest.TestCase):
    def test_dashboard_only_handles_browser_visits_to_root_or_proxy_base(self) -> None:
        browser_accept = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

        self.assertTrue(dashboard_requested("GET", "/", browser_accept, "/v1"))
        self.assertTrue(dashboard_requested("GET", "/v1", browser_accept, "/v1"))
        self.assertFalse(dashboard_requested("GET", "/v1", "application/json", "/v1"))
        self.assertFalse(dashboard_requested("GET", "/v1/models", browser_accept, "/v1"))
        self.assertFalse(dashboard_requested("POST", "/v1/responses", browser_accept, "/v1"))

    def test_safe_url_display_removes_userinfo_query_and_fragment(self) -> None:
        self.assertEqual(
            safe_url_display("https://token:secret@api.example.test:8443/v1?api_key=hidden#frag"),
            "https://api.example.test:8443/v1",
        )

    def test_recent_events_ignores_invalid_lines_and_keeps_tail(self) -> None:
        log_path = ROOT / "tests" / "fixtures" / "fast_proxy_dashboard.jsonl"

        self.assertEqual(
            [event["path"] for event in read_recent_events(log_path, limit=1)],
            ["/v1/responses"],
        )

    def test_dashboard_uses_only_redacted_event_fields(self) -> None:
        log_path = ROOT / "tests" / "fixtures" / "fast_proxy_dashboard.jsonl"
        server = SimpleNamespace(
            log_path=log_path,
            server_address=("127.0.0.1", 8787),
            proxy_base="/v1",
            upstream_base="https://token@api.example.test/v1?secret=1",
            service_tier="priority",
        )

        html = render_dashboard(server)

        self.assertIn("Codex Fast Proxy", html)
        self.assertIn("https://api.example.test/v1", html)
        self.assertIn("/v1/responses", html)
        self.assertIn("<details open>", html)
        self.assertIn("<summary>Commands</summary>", html)
        self.assertIn("<summary>Privacy</summary>", html)
        self.assertIn("Benchmark", html)
        self.assertIn("Not run", html)
        self.assertNotIn("<summary>Health</summary>", html)
        self.assertNotIn("Health JSON", html)
        self.assertIn('<time class="local-time" datetime="2026-04-27T00:00:00.000+00:00"', html)
        self.assertIn("formatLocalTime", html)
        self.assertIn("&lt;absent&gt; -> priority", html)
        self.assertIn('class="badge muted">n/a</span>', html)
        self.assertNotIn("<span class=\"badge\">-</span>", html)
        self.assertNotIn("token@", html)
        self.assertNotIn("secret=1", html)
        self.assertNotIn("Bearer should-not-render", html)
        self.assertNotIn("prompt should-not-render", html)

    def test_dashboard_renders_saved_benchmark_result(self) -> None:
        temp_root = ROOT / ".test_tmp"
        temp_root.mkdir(exist_ok=True)
        temp_dir = temp_root / f"dashboard-benchmark-{uuid.uuid4().hex}"
        temp_dir.mkdir()
        try:
            log_path = temp_dir / "fast_proxy.jsonl"
            log_path.write_text("", encoding="utf-8")
            benchmark_path = temp_dir / "fast_proxy.benchmark.json"
            benchmark_path.write_text(
                json.dumps({
                    "status": "completed",
                    "ts": "2026-04-27T06:00:00.000+00:00",
                    "provider": "acme",
                    "model": "gpt-test",
                    "pairs": 3,
                    "provider_confirmed_priority": True,
                    "observed_speedup_total": 1.53,
                    "observed_speedup_ttfb": 1.2,
                    "default": {"count": 3, "ok": 3, "median_total_ms": 1200.0},
                    "priority": {"count": 3, "ok": 3, "median_total_ms": 784.3},
                    "api_key_env": "ACME_API_KEY",
                }),
                encoding="utf-8",
            )
            server = SimpleNamespace(
                log_path=log_path,
                server_address=("127.0.0.1", 8787),
                proxy_base="/v1",
                upstream_base="https://api.example.test/v1",
                service_tier="priority",
            )

            html = render_dashboard(server)
            benchmark = read_benchmark_result(log_path)
        finally:
            shutil.rmtree(temp_dir)

        self.assertEqual(benchmark["provider"], "acme")
        self.assertIn("provider acme / model gpt-test / pairs 3", html)
        self.assertIn("<div class=\"metric-value\">1.53x</div>", html)
        self.assertIn("<div class=\"metric-value\">1200.0 ms</div>", html)
        self.assertIn("<div class=\"metric-value\">784.3 ms</div>", html)
        self.assertIn("Last run <time class=\"local-time\"", html)
        self.assertNotIn("ACME_API_KEY", html)


if __name__ == "__main__":
    unittest.main()
