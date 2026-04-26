from __future__ import annotations

import json
import sys
import unittest
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_fast_proxy.proxy import (  # noqa: E402
    copy_request_headers,
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


if __name__ == "__main__":
    unittest.main()
