from __future__ import annotations

import http.client
import json
import os
import shutil
import statistics
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    profile: str
    service_tier: str
    api_key_source: str
    api_key: str
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class BenchmarkProfile:
    name: str
    description: str
    prompt: str
    max_output_tokens: int | None


CODEX_BENCHMARK_INSTRUCTIONS = """You are Codex, a coding agent. You and the user share one workspace.
Answer with direct engineering judgment, concrete tradeoffs, and no tool calls."""


CODEX_BENCHMARK_INSTRUCTION_CONTEXT = """
Engineering operating rules:
- Read the relevant code before changing behavior.
- Prefer existing project patterns over new abstractions.
- Keep edits narrowly scoped to the requested behavior.
- Preserve user changes and unrelated worktree state.
- Avoid hidden magic and provider-specific branches.
- Use deterministic parsing for structured files.
- Keep logs redacted and actionable.
- Verify the change with focused tests.
- Explain residual risk without overstating certainty.

Proxy operating rules:
- Only mutate the Responses API request that needs the priority lane.
- Preserve existing service_tier values.
- Preserve stream semantics and hop-by-hop header handling.
- Preserve model, reasoning, tools, input, instructions, and store fields.
- Keep local dashboards read-only.
- Keep benchmark runs opt-in because they spend real quota.
- Prefer full response latency over first event latency when measuring speed.
- Treat accepted priority and effective acceleration as separate facts.
- Treat response metadata as optional because providers may not echo service_tier.

Lifecycle operating rules:
- Install files without changing provider config.
- Enable only after the proxy is healthy.
- Backup config before switching base_url.
- Restore direct upstream before stopping a proxy that a live process may still use.
- Preserve unrelated hooks during install, update, and uninstall.
- Restart stale runtime after update only when the provider still points to the proxy.
- Keep startup hooks quiet on normal no-op checks.
- Ask before destructive cleanup when config has drifted.
- Report exact next steps when Codex must be restarted.

Benchmark interpretation rules:
- A short OK response is a smoke test, not a speed test.
- A long output task is required to expose generation throughput.
- Interleave default and priority samples to reduce provider-load bias.
- Use the same synthetic prompt for both sides.
- Do not store response content.
- Do not print API keys.
- Report sample counts and failed samples.
- Do not promise a guaranteed speedup from a single run.
- Make the dashboard wording understandable to non-maintainers.
"""


def benchmark_instructions() -> str:
    # The full profile intentionally approximates the size of a real Codex request envelope.
    return CODEX_BENCHMARK_INSTRUCTIONS + "\n\n" + (CODEX_BENCHMARK_INSTRUCTION_CONTEXT.strip() + "\n\n") * 10


CODEX_BENCHMARK_DEVELOPER_CONTEXT = """<permissions instructions>
Filesystem sandboxing defines which files can be read or written. `sandbox_mode` is `read-only`.
Network access is available only for the benchmark request itself. Do not call tools.
</permissions instructions>

<benchmark context>
The request is a synthetic Codex-style workload used to compare default Responses API routing
against the provider's priority lane. Keep the task deterministic enough for latency comparison.
</benchmark context>"""


CODEX_BENCHMARK_USER_CONTEXT = """# AGENTS.md instructions for benchmark

<INSTRUCTIONS>
## Code taste
- Prefer removing special cases over adding branches.
- Check for avoidable nesting, unnecessary abstraction, duplicated logic, and brittle behavior.
- Communicate as a senior engineer: concise, factual, and focused on the user's goal.

## Delivery
- Start with the conclusion.
- Explain fix, why, and prevention when discussing implementation quality.
- Do not include secrets, raw request bodies, or private user data.
</INSTRUCTIONS>"""


CODEX_BENCHMARK_RUNTIME_CONTEXT = """
<codex runtime context>
The following synthetic context intentionally resembles the amount and structure of a normal Codex
session. It is not copied from user data. It gives the benchmark enough stable input to measure the
same kind of workload that Codex App and Codex CLI send through the Responses API.

General behavior:
- Codex reads the repository before editing and lets the existing code shape the change.
- Codex prefers local helper APIs and project conventions over new abstractions.
- Codex keeps edits scoped to the requested behavioral surface.
- Codex avoids changing unrelated files, metadata, or user worktree changes.
- Codex adds comments only when they explain a non-obvious block.
- Codex verifies meaningful changes with focused tests.
- Codex reports what changed, why it changed, and what was verified.

Tool discipline:
- Use fast file search for codebase discovery.
- Keep command output concise and avoid printing secrets.
- Treat API keys, auth files, request bodies, prompts, and histories as sensitive.
- Prefer structured parsers over ad hoc string manipulation when the platform provides them.
- Avoid destructive file operations unless the user explicitly requested them.
- Preserve unrelated hooks, config fields, provider entries, and user-managed files.
- When sandbox approval is needed, request it for the intended action instead of inventing a bypass.

Proxy design constraints:
- Only POST /v1/responses is eligible for mutation.
- Requests that already contain service_tier must be preserved exactly.
- The proxy must not change model, reasoning, tools, input, instructions, or stream settings.
- Server-sent events must be passed through without buffering the stream into a different protocol.
- Logs must contain redacted metadata only, never Authorization, input text, or response content.
- Health checks and dashboards are local-only operational surfaces.
- Install must back up Codex config before switching a provider base_url.
- Uninstall must preserve unrelated config changes and unrelated hooks.

Lifecycle constraints:
- A file-only install must not switch Codex to the proxy.
- Enabling starts the proxy before changing provider config.
- Startup hooks should be quiet during no-op checks.
- A stale running proxy should be refreshed after update when the provider still points to the proxy.
- Running Codex processes do not hot-switch provider config.
- Disabling should restore direct upstream first and defer stopping the proxy when needed.
- Cleanup should remove only the package, state, hook, and skill junction owned by this tool.

Benchmark constraints:
- The benchmark is opt-in because it consumes real provider quota.
- It compares default routing against the same request with service_tier set to priority.
- It should use interleaved ordering so provider load and prompt cache effects are shared.
- It should measure full response latency and first output latency, not just first event time.
- It should report accepted priority requests separately from observed acceleration.
- A provider may accept priority but not echo service_tier in the response.
- Small OK prompts are connectivity checks, not speed benchmarks.
- A heavy final-answer task is needed to make generation throughput visible.

Review rubric:
- Identify whether the proxy changes only the intended request path.
- Identify whether rollback can lose user config changes.
- Identify whether hooks are installed in a provider-gated way.
- Identify whether update restarts stale runtime only when necessary.
- Identify whether status can distinguish config intent from live traffic.
- Identify whether dashboard content avoids private prompt or response data.
- Identify whether benchmark output can be explained to a user without overclaiming.
- Identify whether docs match the real install, update, benchmark, and uninstall flows.

Operational examples:
- A user installs the package from GitHub and restarts Codex so the skill is scanned.
- The user asks Codex to enable Fast proxy; the manager starts the local server and switches base_url.
- The current Codex process may keep its old provider config until restart.
- A future session fires SessionStart and the hook quietly confirms the proxy is already healthy.
- If the user updates the repo, manager commands use the new code and stale runtime is restarted.
- If the user uninstalls, config is restored before the proxy is stopped to avoid breaking a live session.
- If the user manually edits config, uninstall should ask or preserve changes instead of restoring an old backup blindly.

Dashboard examples:
- Recent traffic shows method, path, status, duration, service_tier before and after, injection state, and stream state.
- The benchmark card shows default total latency, priority total latency, observed speedup, first output speedup, and sample counts.
- If benchmark has not run, the dashboard shows an empty state and does not start quota-consuming work.
- If priority requests return 200 but speedup is not material, the result should say accepted but not effective.
- If priority requests fail, the result should say not accepted and include redacted error metadata.

Implementation checklist:
- Parse TOML with a real parser so comments and unrelated provider blocks are preserved where possible.
- Keep state files under a dedicated codex-fast-proxy-state directory.
- Keep installed source under a dedicated codex-fast-proxy directory.
- Store benchmark JSON beside proxy logs so the dashboard can read it without scanning user history.
- Use explicit service_tier defaults and make the injected value configurable only through manager settings.
- Treat local port conflicts as a startup error that should restore config before returning.
- Treat unhealthy runtime, mismatched runtime id, and mismatched upstream as different status states.
- Make status useful when the proxy is not installed, installed but stopped, running but stale, or running and healthy.
- Avoid special branches for one provider; provider-specific behavior should come from config and measured results.
- Keep the dashboard read-only so browsing the local URL cannot spend provider quota.

User communication checklist:
- Tell the user that install and update may require a Codex restart because skills are scanned at startup.
- Tell the user that enabling the proxy may require a new Codex process because provider config is loaded by the running process.
- Tell the user that disabling should be two-phase if the current process might still be using the proxy.
- Tell the user when benchmark consumed real requests and that results are observations, not guarantees.
- Explain that priority_accepted means the upstream accepted the parameter.
- Explain that observed_priority_effective means this benchmark workload got materially faster.
- Explain that provider_confirmed_priority is optional metadata and may be absent even when priority is effective.
- Avoid claiming official speed guarantees for a third-party provider.
- Prefer one concise JSON result plus a short human summary.
</codex runtime context>"""


FULL_BENCHMARK_PROMPT = """Do not call tools. Return only the final answer text.

Write a detailed Chinese technical analysis for engineers evaluating a local Codex App Responses API proxy.
Cover: problem background, request-path boundaries, why only POST /v1/responses should be changed,
SSE passthrough risks, provider compatibility, install/uninstall safety, autostart behavior,
benchmark methodology, provider compatibility diagnostics, dashboard interpretation,
install/update/uninstall lifecycle, hook behavior, failure modes, rollback safety, privacy boundaries,
and operational caveats. Use clear sections and concrete tradeoffs.
Target about 4200-5000 Chinese characters. Do not include code blocks."""


SMOKE_BENCHMARK_PROMPT = "Reply with the single word OK."


BENCHMARK_PROFILES: dict[str, BenchmarkProfile] = {
    "full": BenchmarkProfile(
        name="full",
        description="Codex-like heavy synthetic engineering workload",
        prompt=FULL_BENCHMARK_PROMPT,
        max_output_tokens=None,
    ),
    "smoke": BenchmarkProfile(
        name="smoke",
        description="small connectivity check",
        prompt=SMOKE_BENCHMARK_PROMPT,
        max_output_tokens=16,
    ),
}


def profile_for_name(name: str) -> BenchmarkProfile:
    try:
        return BENCHMARK_PROFILES[name]
    except KeyError as exc:
        names = ", ".join(sorted(BENCHMARK_PROFILES))
        raise ValueError(f"Unknown benchmark profile {name!r}. Available: {names}") from exc


CANDIDATE_API_KEY_ENV_NAMES = ("OPENAI_API_KEY",)


def read_codex_auth(codex_home: Path) -> dict[str, str]:
    try:
        payload = json.loads((codex_home / "auth.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {key: value for key, value in payload.items() if isinstance(key, str) and isinstance(value, str) and value}


def api_key_env_candidates(provider_config: dict[str, Any], requested: str | None) -> list[str]:
    candidates: list[str] = []
    if requested:
        candidates.append(requested)
    for key in ("api_key_env_var", "env_key", "api_key_env"):
        value = provider_config.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    candidates.extend(CANDIDATE_API_KEY_ENV_NAMES)
    return list(dict.fromkeys(candidates))


def discover_api_key(provider_config: dict[str, Any], requested: str | None, codex_home: Path) -> tuple[str, str]:
    candidates = api_key_env_candidates(provider_config, requested)
    for env_name in candidates:
        api_key = os.environ.get(env_name)
        if api_key:
            return f"env:{env_name}", api_key

    codex_auth = read_codex_auth(codex_home)
    for env_name in candidates:
        api_key = codex_auth.get(env_name)
        if api_key:
            return f"auth.json:{env_name}", api_key

    if requested:
        raise ValueError(
            f"API key {requested!r} was not found in the environment or ~/.codex/auth.json. "
            "Proxy 200 logs only prove the injected request succeeded."
        )
    raise ValueError(
        "Benchmark could not find an API key in provider config, common environment variables, or ~/.codex/auth.json. "
        "Proxy 200 logs only prove the injected request succeeded; rerun with --api-key-env NAME if your provider uses another key name."
    )


def response_path(upstream_base: str) -> str:
    parsed = urlsplit(upstream_base)
    base_path = parsed.path.rstrip("/") or "/"
    return join_paths(base_path, "/responses")


def default_connection_factory(scheme: str, host: str, port: int | None, timeout: float) -> http.client.HTTPConnection:
    connection_class = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    return connection_class(host, port, timeout=timeout)


HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def forward_path(upstream_base: str, incoming_path: str) -> str:
    parsed = urlsplit(upstream_base)
    base = parsed.path.rstrip("/")
    suffix = incoming_path
    if suffix.startswith("/v1/"):
        suffix = suffix[3:]
    elif suffix == "/v1":
        suffix = ""
    return f"{base}{suffix}" or "/"


class CodexCliCaptureServer(ThreadingHTTPServer):
    def __init__(self, upstream_base: str, timeout: float) -> None:
        super().__init__(("127.0.0.1", 0), CodexCliCaptureHandler)
        self.upstream_base = upstream_base
        self.timeout = timeout
        self.records: list[dict[str, Any]] = []
        self.records_lock = threading.Lock()


class CodexCliCaptureHandler(BaseHTTPRequestHandler):
    server_version = "CodexFastProxyBenchmark/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:
        started = time.perf_counter()
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(length)
        request_json = json_from_bytes(raw_body)

        upstream_base = self.server.upstream_base  # type: ignore[attr-defined]
        parsed = urlsplit(upstream_base)
        connection = default_connection_factory(
            parsed.scheme,
            parsed.hostname or parsed.netloc,
            parsed.port,
            self.server.timeout,  # type: ignore[attr-defined]
        )
        upstream_headers = {key: value for key, value in self.headers.items() if key.lower() not in HOP_BY_HOP_HEADERS}
        upstream_headers["Host"] = parsed.netloc
        upstream_headers["Content-Length"] = str(len(raw_body))

        response_status = 502
        response_reason = "Bad Gateway"
        response_headers: list[tuple[str, str]] = [("Content-Type", "application/json")]
        response_body = b""
        response_service_tier = None
        first_event_at = None
        first_output_at = None
        output_chars = 0
        error_type = None
        try:
            connection.request(
                "POST",
                forward_path(upstream_base, self.path),
                body=raw_body,
                headers=upstream_headers,
            )
            response = connection.getresponse()
            response_status = response.status
            response_reason = response.reason
            response_headers = response.getheaders()
            chunks: list[bytes] = []
            while True:
                line = response.readline()
                if not line:
                    break
                now = time.perf_counter()
                chunks.append(line)
                if line.strip() and first_event_at is None:
                    first_event_at = now
                payload = json_from_sse_line(line)
                delta = output_text_delta(payload)
                if delta:
                    output_chars += len(delta)
                    if first_output_at is None:
                        first_output_at = now
            response_body = b"".join(chunks)
            response_service_tier = extract_response_service_tier(response_body)
        except Exception as exc:
            error_type = type(exc).__name__
            response_body = compact_json({"error": error_type}).encode("utf-8")
        finally:
            connection.close()

        finished = time.perf_counter()
        request_service_tier = None
        if isinstance(request_json, dict):
            value = request_json.get("service_tier")
            request_service_tier = value if isinstance(value, str) else None
        record = {
            "path": self.path,
            "status": response_status,
            "total_ms": round((finished - started) * 1000, 1),
            "ttfb_ms": round(((first_event_at or finished) - started) * 1000, 1),
            "first_event_ms": round(((first_event_at or finished) - started) * 1000, 1),
            "first_output_ms": round((first_output_at - started) * 1000, 1) if first_output_at else None,
            "output_chars": output_chars,
            "response_content_type": next(
                (value for key, value in response_headers if key.lower() == "content-type"),
                None,
            ),
            "request_service_tier": request_service_tier,
            "response_service_tier": response_service_tier,
            "error_type": error_type,
        }
        with self.server.records_lock:  # type: ignore[attr-defined]
            self.server.records.append(record)  # type: ignore[attr-defined]

        self.send_response(response_status, response_reason)
        skipped = HOP_BY_HOP_HEADERS | {"content-encoding"}
        sent_type = False
        for key, value in response_headers:
            lower = key.lower()
            if lower in skipped:
                continue
            if lower == "content-type":
                sent_type = True
            self.send_header(key, value)
        if not sent_type:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(response_body)


def benchmark_input(profile: BenchmarkProfile) -> list[dict[str, Any]]:
    if profile.name == "smoke":
        return [{"role": "user", "content": profile.prompt}]
    return [
        {
            "type": "message",
            "role": "developer",
            "content": [
                {"type": "input_text", "text": CODEX_BENCHMARK_DEVELOPER_CONTEXT},
                {"type": "input_text", "text": CODEX_BENCHMARK_RUNTIME_CONTEXT},
            ],
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": CODEX_BENCHMARK_USER_CONTEXT}],
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": profile.prompt}],
        },
    ]


def benchmark_payload(
    model: str,
    profile: BenchmarkProfile,
    service_tier: str | None,
    reasoning_effort: str | None = None,
) -> bytes:
    payload: dict[str, Any] = {
        "model": model,
        "input": benchmark_input(profile),
        "stream": True,
        "store": False,
    }
    if profile.name != "smoke":
        payload["instructions"] = benchmark_instructions()
        payload["prompt_cache_key"] = "codex-fast-proxy-benchmark-full-v1"
        payload["text"] = {"verbosity": "low"}
    if profile.max_output_tokens is not None:
        payload["max_output_tokens"] = profile.max_output_tokens
    if reasoning_effort and profile.name != "smoke":
        payload["reasoning"] = {"effort": reasoning_effort}
        payload["include"] = ["reasoning.encrypted_content"]
    if service_tier:
        payload["service_tier"] = service_tier
    return compact_json(payload).encode("utf-8")


def json_from_bytes(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def json_from_sse_line(line: bytes) -> Any:
    stripped = line.strip()
    if not stripped.startswith(b"data:"):
        return None
    data = stripped[5:].strip()
    if not data or data == b"[DONE]":
        return None
    return json_from_bytes(data)


def first_string_field(value: Any, field: str) -> str | None:
    if isinstance(value, dict):
        field_value = value.get(field)
        if isinstance(field_value, str) and field_value:
            return field_value
        for child in value.values():
            found = first_string_field(child, field)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = first_string_field(child, field)
            if found:
                return found
    return None


def extract_response_service_tier(body: bytes) -> str | None:
    for raw_line in body.splitlines():
        value = first_string_field(json_from_sse_line(raw_line), "service_tier")
        if value:
            return value
    return first_string_field(json_from_bytes(body), "service_tier")


def output_text_delta(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    event_type = payload.get("type")
    if event_type == "response.output_text.delta":
        delta = payload.get("delta")
        return delta if isinstance(delta, str) else ""
    if event_type == "response.output_text.done":
        return ""

    choices = payload.get("choices")
    if isinstance(choices, list):
        parts: list[str] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str):
                    parts.append(content)
            elif isinstance(delta, str):
                parts.append(delta)
        return "".join(parts)

    return ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def run_sample(
    target: BenchmarkTarget,
    label: str,
    timeout: float,
    connection_factory: ConnectionFactory = default_connection_factory,
) -> dict[str, Any]:
    parsed = urlsplit(target.upstream_base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid upstream base URL: {target.upstream_base}")

    profile = profile_for_name(target.profile)
    body = benchmark_payload(
        target.model,
        profile,
        target.service_tier if label == "priority" else None,
        target.reasoning_effort,
    )
    headers = {
        "Authorization": f"Bearer {target.api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Content-Length": str(len(body)),
    }

    started = time.perf_counter()
    connection = connection_factory(parsed.scheme, parsed.hostname or parsed.netloc, parsed.port, timeout)
    try:
        connection.request("POST", response_path(target.upstream_base), body=body, headers=headers)
        response = connection.getresponse()
        headers_at = time.perf_counter()
        response_chunks: list[bytes] = []
        first_event_at: float | None = None
        first_output_at: float | None = None
        output_chars = 0

        while True:
            line = response.readline()
            if not line:
                break
            now = time.perf_counter()
            response_chunks.append(line)
            if line.strip() and first_event_at is None:
                first_event_at = now
            delta = output_text_delta(json_from_sse_line(line))
            if delta:
                output_chars += len(delta)
                if first_output_at is None:
                    first_output_at = now

        response_body = b"".join(response_chunks)
        finished = time.perf_counter()
    finally:
        connection.close()

    first_event_ms = round(((first_event_at or headers_at) - started) * 1000, 1)
    first_output_ms = round((first_output_at - started) * 1000, 1) if first_output_at is not None else None
    return {
        "tier": label,
        "status": response.status,
        "ttfb_ms": first_event_ms,
        "first_event_ms": first_event_ms,
        "first_output_ms": first_output_ms,
        "total_ms": round((finished - started) * 1000, 1),
        "output_chars": output_chars,
        "response_content_type": response.getheader("Content-Type"),
        "response_service_tier": extract_response_service_tier(response_body),
    }


def sample_plan(pairs: int) -> list[str]:
    plan: list[str] = []
    for index in range(pairs):
        plan.extend(("default", "priority") if index % 2 == 0 else ("priority", "default"))
    return plan


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def is_success_status(value: Any) -> bool:
    try:
        status = int(value)
    except (TypeError, ValueError):
        return False
    return 200 <= status < 400


def summarize_samples(samples: list[dict[str, Any]], label: str) -> dict[str, Any]:
    matching = [sample for sample in samples if sample.get("tier") == label]
    ok_samples = [sample for sample in matching if is_success_status(sample.get("status"))]
    total_values = [float(sample["total_ms"]) for sample in ok_samples if sample.get("total_ms") is not None]
    ttfb_values = [float(sample["ttfb_ms"]) for sample in ok_samples if sample.get("ttfb_ms") is not None]
    first_output_values = [
        float(sample["first_output_ms"]) for sample in ok_samples if sample.get("first_output_ms") is not None
    ]
    output_char_values = [
        float(sample["output_chars"]) for sample in ok_samples if sample.get("output_chars") is not None
    ]
    tiers = sorted({sample["response_service_tier"] for sample in ok_samples if sample.get("response_service_tier")})
    return {
        "count": len(matching),
        "ok": len(ok_samples),
        "median_total_ms": median(total_values),
        "median_ttfb_ms": median(ttfb_values),
        "median_first_output_ms": median(first_output_values),
        "median_output_chars": median(output_char_values),
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


def priority_accepted(priority_summary: dict[str, Any]) -> bool | None:
    count = priority_summary["count"]
    if count == 0:
        return None
    return priority_summary["ok"] > 0


def observed_priority_effective(priority_summary: dict[str, Any], total_speedup: float | None) -> bool | None:
    accepted = priority_accepted(priority_summary)
    if accepted is not True or total_speedup is None:
        return None if accepted is not False else False
    return total_speedup >= 1.15


def codex_command() -> list[str]:
    override = os.environ.get("CODEX_FAST_PROXY_CODEX_CMD")
    if override:
        return [override]
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        node = shutil.which("node")
        if appdata and node:
            script = Path(appdata) / "npm" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            if script.exists():
                return [node, str(script)]
    executable = shutil.which("codex")
    if executable:
        return [executable]
    raise RuntimeError("Codex CLI was not found. Install Codex CLI or rerun benchmark with --mode direct.")


def toml_string(value: str) -> str:
    return json.dumps(value)


def run_codex_cli_sample(
    target: BenchmarkTarget,
    label: str,
    profile: BenchmarkProfile,
    server: CodexCliCaptureServer,
    timeout: float,
) -> dict[str, Any]:
    before = len(server.records)
    port = server.server_address[1]
    with tempfile.TemporaryDirectory(prefix="codex-fast-proxy-benchmark-") as workdir:
        provider_config = (
            'model_providers.capture={name="capture",'
            f'base_url="http://127.0.0.1:{port}/v1",'
            'env_key="OPENAI_API_KEY",wire_api="responses"}'
        )
        args = [
            *codex_command(),
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "--json",
            "-C",
            workdir,
            "-s",
            "read-only",
            "-c",
            'model_provider="capture"',
            "-c",
            f"model={toml_string(target.model)}",
            "-c",
            provider_config,
            "-c",
            "features.fast_mode=false",
        ]
        if target.reasoning_effort:
            args.extend(["-c", f"model_reasoning_effort={toml_string(target.reasoning_effort)}"])
        if label == "priority":
            args.extend(["-c", 'service_tier="fast"', "-c", "features.fast_mode=true"])
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = target.api_key
        completed = subprocess.run(
            args + [profile.prompt],
            cwd=workdir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 60,
            check=False,
        )

    with server.records_lock:
        records = server.records[before:]
    record = next((item for item in reversed(records) if item.get("path") == "/v1/responses"), None)
    if record:
        return {"tier": label, **record, "codex_exit_code": completed.returncode}
    return {
        "tier": label,
        "status": None,
        "error_type": "CodexCliNoCapture",
        "codex_exit_code": completed.returncode,
    }


def run_codex_cli_benchmark(target: BenchmarkTarget, pairs: int, timeout: float) -> dict[str, Any]:
    profile = profile_for_name(target.profile)
    server = CodexCliCaptureServer(target.upstream_base, timeout)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    samples: list[dict[str, Any]] = []
    try:
        for label in sample_plan(pairs):
            try:
                samples.append(run_codex_cli_sample(target, label, profile, server, timeout))
            except Exception as exc:
                samples.append({"tier": label, "status": None, "error_type": type(exc).__name__})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return summarize_benchmark_result(target, pairs, samples, mode="codex-cli")


def summarize_benchmark_result(
    target: BenchmarkTarget,
    pairs: int,
    samples: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    profile = profile_for_name(target.profile)
    default_summary = summarize_samples(samples, "default")
    priority_summary = summarize_samples(samples, "priority")
    total_speedup = speedup(default_summary["median_total_ms"], priority_summary["median_total_ms"])
    ttfb_speedup = speedup(default_summary["median_ttfb_ms"], priority_summary["median_ttfb_ms"])
    first_output_speedup = speedup(default_summary["median_first_output_ms"], priority_summary["median_first_output_ms"])
    return {
        "status": "completed",
        "ts": utc_now(),
        "provider": target.provider,
        "upstream_base": target.upstream_base,
        "model": target.model,
        "reasoning_effort": target.reasoning_effort,
        "profile": target.profile,
        "profile_description": profile.description,
        "benchmark_mode": mode,
        "max_output_tokens": profile.max_output_tokens,
        "api_key_source": target.api_key_source,
        "pairs": pairs,
        "samples": samples,
        "default": default_summary,
        "priority": priority_summary,
        "observed_speedup_total": total_speedup,
        "observed_speedup_ttfb": ttfb_speedup,
        "observed_speedup_first_output": first_output_speedup,
        "priority_accepted": priority_accepted(priority_summary),
        "observed_priority_effective": observed_priority_effective(priority_summary, total_speedup),
        "provider_confirmed_priority": priority_confirmed(priority_summary),
        "privacy": "Synthetic prompt only; response content and API key are not stored.",
    }


def run_benchmark(
    target: BenchmarkTarget,
    pairs: int,
    timeout: float,
    connection_factory: ConnectionFactory = default_connection_factory,
    mode: str = "direct",
) -> dict[str, Any]:
    if mode == "codex-cli":
        return run_codex_cli_benchmark(target, pairs, timeout)
    if mode != "direct":
        raise ValueError(f"Unknown benchmark mode {mode!r}. Available: codex-cli, direct")
    samples: list[dict[str, Any]] = []
    for label in sample_plan(pairs):
        try:
            samples.append(run_sample(target, label, timeout, connection_factory))
        except Exception as exc:
            samples.append({"tier": label, "status": None, "error_type": type(exc).__name__})
    return summarize_benchmark_result(target, pairs, samples, mode=mode)


def save_benchmark_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
