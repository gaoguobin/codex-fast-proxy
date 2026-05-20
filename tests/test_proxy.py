from __future__ import annotations

import gzip
import json
import shutil
import sys
import threading
import unittest
import uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_fast_proxy.dashboard import (  # noqa: E402
    dashboard_diagnosis,
    read_benchmark_result,
    read_recent_events,
    render_dashboard,
    safe_url_display,
)
from codex_fast_proxy.proxy import (  # noqa: E402
    FastProxyHandler,
    copy_request_headers,
    dashboard_requested,
    parse_args,
    read_chunked_request_body,
    decompress_zstd,
    runtime_details,
    service_tier_patch,
    stream_response_body,
    upstream_request_path,
    zstandard,
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


class FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def request(self, _method: str, _path: str, body: bytes, headers: dict[str, str]) -> None:
        self.body = body
        self.headers = headers

    def getresponse(self) -> Any:
        return SimpleNamespace(
            status=200,
            getheader=lambda name, default=None: "text/event-stream"
            if name.lower() == "content-type"
            else default,
        )

    def close(self) -> None:
        self.closed = True


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
        raw_body = json.dumps(payload, indent=2).encode("utf-8")
        body, event = service_tier_patch(
            "POST",
            "/v1/responses",
            raw_body,
            "application/json",
            "priority",
        )

        self.assertEqual(body, raw_body)
        self.assertEqual(json.loads(body)["service_tier"], "auto")
        self.assertFalse(event["injected"])
        self.assertEqual(event["service_tier_before"], "auto")
        self.assertEqual(event["service_tier_after"], "auto")

    def test_preserve_policy_does_not_inject_missing_service_tier(self) -> None:
        payload = {"model": "gpt-5.4", "stream": True}
        raw_body = json.dumps(payload, indent=2).encode("utf-8")
        body, event = service_tier_patch(
            "POST",
            "/v1/responses",
            raw_body,
            "application/json",
            "priority",
            "preserve",
        )

        self.assertEqual(body, raw_body)
        self.assertNotIn("service_tier", json.loads(body))
        self.assertFalse(event["injected"])
        self.assertEqual(event["service_tier_before"], "<absent>")
        self.assertEqual(event["service_tier_after"], "<absent>")

    def test_injects_missing_service_tier_in_gzip_json_body(self) -> None:
        payload = {"model": "gpt-5.4", "stream": True}
        raw_body = gzip.compress(json.dumps(payload).encode("utf-8"))
        body, event = service_tier_patch(
            "POST",
            "/v1/responses",
            raw_body,
            "application/json",
            "priority",
            "inject_missing",
            "gzip",
        )

        patched = json.loads(gzip.decompress(body))
        self.assertEqual(patched["service_tier"], "priority")
        self.assertTrue(event["injected"])
        self.assertEqual(event["json_error"], None)

    @unittest.skipIf(zstandard is None, "zstandard package is not installed")
    def test_injects_missing_service_tier_in_zstd_json_body(self) -> None:
        payload = {"model": "gpt-5.4", "stream": True}
        raw_body = zstandard.ZstdCompressor().compress(json.dumps(payload).encode("utf-8"))
        body, event = service_tier_patch(
            "POST",
            "/v1/responses",
            raw_body,
            "application/json",
            "priority",
            "inject_missing",
            "zstd",
        )

        patched = json.loads(zstandard.ZstdDecompressor().decompress(body))
        self.assertEqual(patched["service_tier"], "priority")
        self.assertTrue(event["injected"])
        self.assertEqual(event["json_error"], None)

    @unittest.skipIf(zstandard is None, "zstandard package is not installed")
    def test_injects_missing_service_tier_in_zstd_body_without_content_size(self) -> None:
        payload = {"model": "gpt-5.4", "stream": True}
        raw_body = zstandard.ZstdCompressor(write_content_size=False).compress(json.dumps(payload).encode("utf-8"))
        body, event = service_tier_patch(
            "POST",
            "/v1/responses",
            raw_body,
            "application/json",
            "priority",
            "inject_missing",
            "zstd",
        )

        patched = json.loads(decompress_zstd(body))
        self.assertEqual(patched["service_tier"], "priority")
        self.assertTrue(event["injected"])
        self.assertEqual(event["json_error"], None)

    @unittest.skipIf(zstandard is None or shutil.which("zstd") is None, "zstd fallback is not available")
    def test_injects_missing_service_tier_when_python_zstd_stream_reader_fails(self) -> None:
        payload = {"model": "gpt-5.4", "stream": True}
        raw_body = zstandard.ZstdCompressor(write_content_size=False).compress(json.dumps(payload).encode("utf-8"))
        original = zstandard.ZstdDecompressor

        class BrokenDecompressor:
            def stream_reader(self, _body: bytes) -> Any:
                raise zstandard.ZstdError("forced stream failure")

        try:
            zstandard.ZstdDecompressor = BrokenDecompressor
            body, event = service_tier_patch(
                "POST",
                "/v1/responses",
                raw_body,
                "application/json",
                "priority",
                "inject_missing",
                "zstd",
            )
        finally:
            zstandard.ZstdDecompressor = original

        patched = json.loads(decompress_zstd(body))
        self.assertEqual(patched["service_tier"], "priority")
        self.assertTrue(event["injected"])
        self.assertEqual(event["json_error"], None)

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

    def test_runtime_details_exposes_source_without_secrets(self) -> None:
        details = runtime_details()

        self.assertEqual(details["python_executable"], sys.executable)
        self.assertIn("proxy.py", details["module_file"])
        self.assertIn(details["source_layout"], {"source_checkout", "installed_package"})

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

    def test_upstream_auth_override_replaces_auth_and_drops_cookie(self) -> None:
        headers = FakeHeaders(
            {
                "authorization": "Bearer chatgpt-token",
                "Authorization": "Bearer other-token",
                "Cookie": "session=secret",
                "Accept": "application/json",
            }
        )

        copied = copy_request_headers(headers, "api.example.test", None, "provider-key")

        self.assertEqual(copied["Authorization"], "Bearer provider-key")
        self.assertEqual(copied["Accept"], "application/json")
        self.assertEqual(copied["Host"], "api.example.test")
        self.assertNotIn("authorization", copied)
        self.assertNotIn("Cookie", copied)

    def test_health_hides_provider_auth_file_internal_env(self) -> None:
        handler = FastProxyHandler.__new__(FastProxyHandler)
        handler.wfile = BytesIO()
        handler.server = SimpleNamespace(
            proxy_base="/v1",
            upstream_base="https://api.example.test/v1",
            service_tier="priority",
            service_tier_policy="auto",
            service_tier_effective_policy="preserve",
            upstream_api_key_env="CODEX_FAST_PROXY_UPSTREAM_API_KEY",
            public_upstream_api_key_env=None,
            upstream_api_key_source="provider_auth_file",
        )
        handler.send_response = lambda _status: None
        handler.send_header = lambda _name, _value: None
        handler.end_headers = lambda: None

        FastProxyHandler.respond_health(handler)
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))

        self.assertEqual(payload["upstream_auth"], "override_configured")
        self.assertIsNone(payload["upstream_api_key_env"])
        self.assertTrue(payload["upstream_api_key_file"])
        self.assertEqual(payload["upstream_api_key_source"], "provider_auth_file")
        self.assertNotIn("CODEX_FAST_PROXY_UPSTREAM_API_KEY", json.dumps(payload))

    def test_sse_payload_bytes_are_forwarded_without_event_rewrite(self) -> None:
        response = FakeLineResponse([b"event: response.output_text.delta\n", b"data: {\"x\":1}\n", b"\n"])
        writer = BytesIO()

        stream_response_body(response, writer, chunked=False, line_buffered=True)

        self.assertEqual(writer.getvalue(), b"event: response.output_text.delta\ndata: {\"x\":1}\n\n")

    def test_chunked_request_body_is_dechunked_before_fast_injection(self) -> None:
        temp_root = ROOT / ".test_tmp"
        temp_root.mkdir(exist_ok=True)
        temp_dir = temp_root / f"chunked-inject-{uuid.uuid4().hex}"
        temp_dir.mkdir()
        try:
            log_path = temp_dir / "fast_proxy.jsonl"
            raw_body = json.dumps({"model": "gpt-test", "stream": True}).encode("utf-8")
            chunked_body = b"%X\r\n%s\r\n0\r\n\r\n" % (len(raw_body), raw_body)
            connection = FakeConnection()
            handler = FastProxyHandler.__new__(FastProxyHandler)
            handler.command = "POST"
            handler.path = "/v1/responses"
            handler.headers = {
                "Content-Type": "application/json",
                "Transfer-Encoding": "chunked",
            }
            handler.rfile = BytesIO(chunked_body)
            handler.server = SimpleNamespace(
                proxy_base="/v1",
                upstream_base_path="/v1",
                upstream_netloc="api.example.test",
                service_tier="priority",
                service_tier_policy="inject_missing",
                service_tier_effective_policy="inject_missing",
                log_path=log_path,
                log_lock=threading.Lock(),
                verbose=False,
                open_connection=lambda: connection,
            )
            handler.forward_response = lambda _response: None
            handler.respond_bad_gateway = lambda: None

            FastProxyHandler.proxy(handler)
            event = json.loads(log_path.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(temp_dir)

        forwarded = json.loads(connection.body)
        self.assertEqual(forwarded["service_tier"], "priority")
        self.assertEqual(connection.headers["Content-Length"], str(len(connection.body)))
        self.assertNotIn("Transfer-Encoding", connection.headers)
        self.assertTrue(event["service_tier_injected"])
        self.assertEqual(event["service_tier_before"], "<absent>")
        self.assertEqual(event["service_tier_after"], "priority")
        self.assertIsNone(event["json_error"])

    def test_read_chunked_request_body_handles_extensions_and_trailers(self) -> None:
        body = read_chunked_request_body(BytesIO(b"5;foo=bar\r\nhello\r\n0\r\nx-test: ok\r\n\r\n"))

        self.assertEqual(body, b"hello")

    def test_client_disconnect_during_stream_is_logged_without_bad_gateway(self) -> None:
        temp_root = ROOT / ".test_tmp"
        temp_root.mkdir(exist_ok=True)
        temp_dir = temp_root / f"client-disconnect-{uuid.uuid4().hex}"
        temp_dir.mkdir()
        try:
            log_path = temp_dir / "fast_proxy.jsonl"
            body = json.dumps({"model": "gpt-test", "stream": True}).encode("utf-8")
            connection = FakeConnection()
            handler = FastProxyHandler.__new__(FastProxyHandler)
            handler.command = "POST"
            handler.path = "/v1/responses"
            handler.headers = {
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            }
            handler.rfile = BytesIO(body)
            handler.server = SimpleNamespace(
                proxy_base="/v1",
                upstream_base_path="/v1",
                upstream_netloc="api.example.test",
                service_tier="priority",
                log_path=log_path,
                log_lock=threading.Lock(),
                verbose=False,
                open_connection=lambda: connection,
            )

            def raise_client_disconnect(_response: Any) -> None:
                raise ConnectionAbortedError("client closed SSE")

            def fail_bad_gateway() -> None:
                raise AssertionError("client disconnect should not be converted to a 502 response")

            handler.forward_response = raise_client_disconnect
            handler.respond_bad_gateway = fail_bad_gateway

            FastProxyHandler.proxy(handler)
            event = json.loads(log_path.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(temp_dir)

        self.assertTrue(connection.closed)
        self.assertEqual(event["status"], 200)
        self.assertEqual(event["error_type"], "client_disconnected")
        self.assertEqual(event["service_tier_before"], "<absent>")
        self.assertEqual(event["service_tier_after"], "priority")
        self.assertTrue(event["service_tier_injected"])

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

    def test_dashboard_diagnosis_prioritizes_response_streaming_state(self) -> None:
        self.assertEqual(dashboard_diagnosis(None)["title"], "Waiting for traffic")
        self.assertEqual(dashboard_diagnosis({"status": 502, "eligible": True})["title"], "Needs attention")
        self.assertEqual(
            dashboard_diagnosis({"status": 200, "eligible": True, "response_content_type": "text/event-stream"})["title"],
            "Ready",
        )

    def test_dashboard_uses_only_redacted_event_fields(self) -> None:
        log_path = ROOT / "tests" / "fixtures" / "fast_proxy_dashboard.jsonl"
        server = SimpleNamespace(
            log_path=log_path,
            server_address=("127.0.0.1", 8787),
            proxy_base="/v1",
            upstream_base="https://token@api.example.test/v1?secret=1",
            service_tier="priority",
            upstream_api_key_env="ACME_API_KEY",
        )

        html = render_dashboard(server)

        self.assertIn("Codex Fast Proxy", html)
        self.assertIn("https://api.example.test/v1", html)
        self.assertIn("Check streaming", html)
        self.assertIn("Provider env override: ACME_API_KEY", html)
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

    def test_dashboard_shows_preserved_provider_auth_without_secret(self) -> None:
        log_path = ROOT / "tests" / "fixtures" / "fast_proxy_dashboard.jsonl"
        server = SimpleNamespace(
            log_path=log_path,
            server_address=("127.0.0.1", 8787),
            proxy_base="/v1",
            upstream_base="https://api.example.test/v1",
            service_tier="priority",
        )

        html = render_dashboard(server)

        self.assertIn("Codex provider header", html)

    def test_dashboard_hides_provider_auth_file_internal_env(self) -> None:
        log_path = ROOT / "tests" / "fixtures" / "fast_proxy_dashboard.jsonl"
        server = SimpleNamespace(
            log_path=log_path,
            server_address=("127.0.0.1", 8787),
            proxy_base="/v1",
            upstream_base="https://api.example.test/v1",
            service_tier="priority",
            upstream_api_key_env="CODEX_FAST_PROXY_UPSTREAM_API_KEY",
            upstream_api_key_source="provider_auth_file",
        )

        html = render_dashboard(server)

        self.assertIn("Provider auth file override", html)
        self.assertNotIn("CODEX_FAST_PROXY_UPSTREAM_API_KEY", html)

    def test_dashboard_status_badge_exposes_redacted_event_detail(self) -> None:
        temp_root = ROOT / ".test_tmp"
        temp_root.mkdir(exist_ok=True)
        temp_dir = temp_root / f"dashboard-detail-{uuid.uuid4().hex}"
        temp_dir.mkdir()
        try:
            log_path = temp_dir / "fast_proxy.jsonl"
            log_path.write_text(
                json.dumps({
                    "ts": "2026-05-05T06:10:39.890+00:00",
                    "request_id": "req-demo",
                    "method": "POST",
                    "path": "/v1/responses",
                    "status": 502,
                    "duration_ms": 24501.2,
                    "eligible": True,
                    "service_tier_before": "<absent>",
                    "service_tier_after": "priority",
                    "service_tier_injected": True,
                    "stream": True,
                    "response_content_type": None,
                    "error_type": "client_disconnected",
                    "Authorization": "Bearer should-not-render",
                    "input": "prompt should-not-render",
                })
                + "\n",
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
        finally:
            shutil.rmtree(temp_dir)

        self.assertIn("Needs attention", html)
        self.assertIn("request_id: req-demo", html)
        self.assertIn("status: 502", html)
        self.assertIn("duration_ms: 24501.2", html)
        self.assertIn("error_type: client_disconnected", html)
        self.assertIn("service_tier_before: &lt;absent&gt;", html)
        self.assertNotIn("Bearer should-not-render", html)
        self.assertNotIn("prompt should-not-render", html)

    def test_dashboard_groups_models_as_provider_metadata(self) -> None:
        temp_root = ROOT / ".test_tmp"
        temp_root.mkdir(exist_ok=True)
        temp_dir = temp_root / f"dashboard-models-{uuid.uuid4().hex}"
        temp_dir.mkdir()
        try:
            log_path = temp_dir / "fast_proxy.jsonl"
            log_path.write_text(
                json.dumps({
                    "ts": "2026-05-05T06:10:39.890+00:00",
                    "method": "POST",
                    "path": "/v1/responses",
                    "status": 200,
                    "duration_ms": 1000,
                    "eligible": True,
                    "service_tier_before": "priority",
                    "service_tier_after": "priority",
                    "service_tier_injected": False,
                    "stream": True,
                    "response_content_type": "text/event-stream",
                })
                + "\n"
                + json.dumps({
                    "ts": "2026-05-05T06:10:41.000+00:00",
                    "method": "GET",
                    "path": "/v1/models",
                    "status": 503,
                    "duration_ms": 20,
                    "eligible": False,
                })
                + "\n",
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
        finally:
            shutil.rmtree(temp_dir)

        self.assertIn("<h2>Ready</h2>", html)
        self.assertIn("Recent Responses API traffic is streaming through the local proxy.", html)
        self.assertIn("Provider metadata", html)
        self.assertIn("GET /v1/models", html)
        self.assertIn("1/1", html)

    def test_dashboard_models_do_not_crowd_out_response_events(self) -> None:
        temp_root = ROOT / ".test_tmp"
        temp_root.mkdir(exist_ok=True)
        temp_dir = temp_root / f"dashboard-model-crowding-{uuid.uuid4().hex}"
        temp_dir.mkdir()
        try:
            log_path = temp_dir / "fast_proxy.jsonl"
            response = {
                "ts": "2026-05-05T06:10:00.000+00:00",
                "method": "POST",
                "path": "/v1/responses",
                "status": 200,
                "duration_ms": 1000,
                "eligible": True,
                "service_tier_before": "priority",
                "service_tier_after": "priority",
                "service_tier_injected": False,
                "stream": True,
                "response_content_type": "text/event-stream",
            }
            metadata = [
                {
                    "ts": f"2026-05-05T06:10:{index + 1:02d}.000+00:00",
                    "method": "GET",
                    "path": "/v1/models",
                    "status": 200,
                    "duration_ms": index,
                    "eligible": False,
                }
                for index in range(12)
            ]
            log_path.write_text(
                "\n".join(json.dumps(event) for event in [response, *metadata]) + "\n",
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
        finally:
            shutil.rmtree(temp_dir)

        self.assertIn("<h2>Ready</h2>", html)
        self.assertIn("POST /v1/responses", html)
        self.assertIn("Provider metadata", html)
        self.assertEqual(html.count('title="/v1/models">GET /v1/models'), 4)

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
                    "benchmark_mode": "codex-cli",
                    "profile": "full",
                    "pairs": 3,
                    "provider_confirmed_priority": True,
                    "priority_accepted": True,
                    "observed_priority_effective": True,
                    "observed_speedup_total": 1.53,
                    "observed_speedup_ttfb": 1.2,
                    "observed_speedup_first_output": 1.4,
                    "default": {"count": 3, "ok": 3, "median_total_ms": 1200.0, "median_first_output_ms": 500.0},
                    "priority": {"count": 3, "ok": 3, "median_total_ms": 784.3, "median_first_output_ms": 357.1},
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
        self.assertIn("provider acme / model gpt-test / mode codex-cli / profile full / pairs 3", html)
        self.assertIn("<div class=\"metric-value\">effective</div>", html)
        self.assertIn("<div class=\"metric-value\">1.53x</div>", html)
        self.assertIn("<div class=\"metric-value\">1.40x</div>", html)
        self.assertIn("<div class=\"metric-value\">784.3 ms</div>", html)
        self.assertIn("default total 1200.0 ms", html)
        self.assertIn("Last run <time class=\"local-time\"", html)
        self.assertNotIn("ACME_API_KEY", html)


if __name__ == "__main__":
    unittest.main()
