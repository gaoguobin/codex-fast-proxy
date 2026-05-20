from __future__ import annotations

import argparse
import gzip
import hashlib
import http.client
import json
import os
import signal
import shutil
import ssl
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

try:
    import zstandard
except ImportError:  # pragma: no cover - optional local dependency
    zstandard = None

from . import __version__
from .auth import resolve_env
from .dashboard import DASHBOARD_PATH, render_dashboard


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

BODY_METHODS = {"POST", "PUT", "PATCH"}
RESPONSES_PATH = "/v1/responses"
HEALTH_PATH = "/__codex_fast_proxy/health"
CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)
SERVICE_TIER_POLICIES = {"auto", "inject_missing", "preserve"}
EFFECTIVE_SERVICE_TIER_POLICIES = {"inject_missing", "preserve"}


def source_fingerprint(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(str(path).encode("utf-8"))
    return digest.hexdigest()[:16]


RUNTIME_ID = source_fingerprint([Path(__file__), Path(render_dashboard.__code__.co_filename)])


def runtime_details() -> dict[str, str]:
    module_file = Path(__file__).resolve()
    source_layout = (
        "source_checkout"
        if len(module_file.parents) > 1 and module_file.parents[1].name == "src"
        else "installed_package"
    )
    source_root = module_file.parents[2] if source_layout == "source_checkout" else module_file.parent
    return {
        "runtime_id": RUNTIME_ID,
        "python_executable": sys.executable,
        "module_file": str(module_file),
        "source_root": str(source_root),
        "source_layout": source_layout,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def normalized_path(raw_path: str) -> str:
    parsed = urlsplit(raw_path)
    return parsed.path.rstrip("/") or "/"


def join_paths(left: str, right: str) -> str:
    return f"{left.rstrip('/')}/{right.lstrip('/')}".rstrip("/") or "/"


def upstream_request_path(raw_path: str, proxy_base: str, upstream_base_path: str) -> str:
    parsed = urlsplit(raw_path)
    request_path = parsed.path
    proxy_prefix = proxy_base.rstrip("/") or "/"

    if request_path == proxy_prefix:
        suffix = ""
    elif proxy_prefix != "/" and request_path.startswith(f"{proxy_prefix}/"):
        suffix = request_path[len(proxy_prefix) :]
    else:
        suffix = request_path

    upstream_path = join_paths(upstream_base_path or "/", suffix)
    return f"{upstream_path}?{parsed.query}" if parsed.query else upstream_path


def accepts_html(accept_header: str) -> bool:
    for entry in accept_header.lower().split(","):
        media_type = entry.split(";", 1)[0].strip()
        if media_type in {"text/html", "application/xhtml+xml"}:
            return True
    return False


def dashboard_requested(method: str, raw_path: str, accept_header: str, proxy_base: str) -> bool:
    if method.upper() != "GET" or not accepts_html(accept_header):
        return False

    path = normalized_path(raw_path)
    return path in {"/", normalized_path(proxy_base), DASHBOARD_PATH}


def copy_request_headers(
    headers: Any,
    upstream_host: str,
    body_length: int | None,
    upstream_api_key: str | None = None,
) -> dict[str, str]:
    copied = {
        name: value
        for name, value in headers.items()
        if name.lower() not in HOP_BY_HOP_HEADERS | {"host", "content-length"}
    }
    if upstream_api_key is not None:
        copied = {
            name: value
            for name, value in copied.items()
            if name.lower() not in {"authorization", "cookie"}
        }
        copied["Authorization"] = f"Bearer {upstream_api_key}"
    copied["Host"] = upstream_host
    if body_length is not None:
        copied["Content-Length"] = str(body_length)
    return copied


def copy_response_headers(headers: Iterable[tuple[str, str]], chunked: bool) -> list[tuple[str, str]]:
    copied: list[tuple[str, str]] = []
    for name, value in headers:
        lower_name = name.lower()
        if lower_name in HOP_BY_HOP_HEADERS:
            continue
        if chunked and lower_name == "content-length":
            continue
        copied.append((name, value))
    return copied


def decompress_zstd(body: bytes) -> bytes:
    python_error: Exception | None = None

    if zstandard is not None:
        try:
            with zstandard.ZstdDecompressor().stream_reader(body) as reader:
                return reader.read()
        except Exception as exc:
            python_error = exc

    zstd_bin = shutil.which("zstd")
    if zstd_bin:
        try:
            result = subprocess.run(
                [zstd_bin, "-dc"],
                input=body,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return result.stdout
        except Exception as exc:
            if python_error is not None:
                raise python_error from exc
            raise

    if python_error is not None:
        raise python_error
    return body


def compress_zstd(body: bytes) -> bytes:
    if zstandard is None:
        return body

    return zstandard.ZstdCompressor().compress(body)


def service_tier_patch(
    method: str,
    raw_path: str,
    body: bytes,
    content_type: str,
    service_tier: str,
    service_tier_policy: str = "inject_missing",
    content_encoding: str = "",
) -> tuple[bytes, dict[str, Any]]:
    event = {
        "eligible": False,
        "injected": False,
        "service_tier_before": None,
        "service_tier_after": None,
        "stream": None,
        "json_error": None,
        "request_body_len": len(body),
        "request_body_magic": body[:4].hex() if body else "",
        "request_content_encoding": content_encoding,
    }

    if method.upper() != "POST" or normalized_path(raw_path) != RESPONSES_PATH:
        return body, event

    event["eligible"] = True
    if "json" not in content_type.lower():
        return body, event

    try:
        normalized_encoding = content_encoding.lower().strip()
        if normalized_encoding == "gzip":
            decoded_body = gzip.decompress(body)
        elif normalized_encoding == "zstd" and zstandard is not None:
            decoded_body = decompress_zstd(body)
        else:
            decoded_body = body
        payload = json.loads(decoded_body.decode("utf-8"))
    except Exception as exc:
        event["json_error"] = type(exc).__name__
        return body, event

    if not isinstance(payload, dict):
        event["json_error"] = f"top_level_{type(payload).__name__}"
        return body, event

    event["stream"] = payload.get("stream")
    event["service_tier_before"] = payload.get("service_tier", "<absent>")

    if service_tier_policy == "inject_missing" and "service_tier" not in payload:
        payload["service_tier"] = service_tier
        event["injected"] = True

    event["service_tier_after"] = payload.get("service_tier", "<absent>")
    if not event["injected"]:
        return body, event

    patched_body = compact_json(payload).encode("utf-8")
    if normalized_encoding == "gzip":
        return gzip.compress(patched_body), event
    if normalized_encoding == "zstd" and zstandard is not None:
        return compress_zstd(patched_body), event
    return patched_body, event


def write_chunk(writer: Any, data: bytes) -> None:
    if not data:
        return
    writer.write(f"{len(data):X}\r\n".encode("ascii"))
    writer.write(data)
    writer.write(b"\r\n")
    writer.flush()


def stream_response_body(
    response: http.client.HTTPResponse,
    writer: Any,
    chunked: bool,
    line_buffered: bool,
) -> None:
    read: Callable[[int], bytes]
    if line_buffered:
        read = lambda _size: response.readline()
    else:
        read = response.read

    while True:
        data = read(64 * 1024)
        if not data:
            break
        if chunked:
            write_chunk(writer, data)
        else:
            writer.write(data)
            if line_buffered:
                writer.flush()

    if chunked:
        writer.write(b"0\r\n\r\n")
    writer.flush()


def read_chunked_request_body(reader: Any) -> bytes:
    chunks: list[bytes] = []
    while True:
        size_line = reader.readline()
        if not size_line:
            raise ValueError("incomplete_chunked_request_body")

        size_text = size_line.split(b";", 1)[0].strip()
        try:
            size = int(size_text, 16)
        except ValueError as exc:
            raise ValueError("invalid_chunked_request_body") from exc

        if size == 0:
            while True:
                trailer_line = reader.readline()
                if trailer_line in {b"", b"\n", b"\r\n"}:
                    return b"".join(chunks)

        chunk = reader.read(size)
        if len(chunk) != size:
            raise ValueError("incomplete_chunked_request_body")
        chunks.append(chunk)

        line_end = reader.readline()
        if line_end not in {b"\n", b"\r\n"}:
            raise ValueError("invalid_chunked_request_body")


class FastProxyHandler(BaseHTTPRequestHandler):
    server_version = "CodexFastProxy/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *args: Any) -> None:
        return

    def do_DELETE(self) -> None:
        self.proxy()

    def do_GET(self) -> None:
        if normalized_path(self.path) == HEALTH_PATH:
            self.respond_health()
            return
        if dashboard_requested(self.command, self.path, self.headers.get("Accept", ""), self.server.proxy_base):
            self.respond_dashboard()
            return
        self.proxy()

    def do_HEAD(self) -> None:
        self.proxy()

    def do_OPTIONS(self) -> None:
        self.proxy()

    def do_PATCH(self) -> None:
        self.proxy()

    def do_POST(self) -> None:
        self.proxy()

    def do_PUT(self) -> None:
        self.proxy()

    def proxy(self) -> None:
        started_at = time.perf_counter()
        request_id = uuid.uuid4().hex
        request_body = self.read_request_body()
        request_body, patch_event = service_tier_patch(
            self.command,
            self.path,
            request_body,
            self.headers.get("Content-Type", ""),
            self.server.service_tier,
            getattr(self.server, "service_tier_effective_policy", "inject_missing"),
            self.headers.get("Content-Encoding", ""),
        )

        upstream_path = upstream_request_path(
            self.path,
            self.server.proxy_base,
            self.server.upstream_base_path,
        )
        request_headers = copy_request_headers(
            self.headers,
            self.server.upstream_netloc,
            len(request_body) if request_body or self.command.upper() in BODY_METHODS else None,
            getattr(self.server, "upstream_api_key", None),
        )

        status = 502
        response_content_type = None
        error_type = None
        try:
            connection = self.server.open_connection()
            try:
                connection.request(self.command, upstream_path, body=request_body, headers=request_headers)
                response = connection.getresponse()
                status = response.status
                response_content_type = response.getheader("Content-Type")
                self.forward_response(response)
            finally:
                connection.close()
        except CLIENT_DISCONNECT_ERRORS:
            error_type = "client_disconnected"
        except Exception as exc:
            error_type = type(exc).__name__
            self.respond_bad_gateway()
        finally:
            self.write_event(request_id, started_at, status, patch_event, response_content_type, error_type)

    def respond_health(self) -> None:
        payload = {
            "ok": True,
            "pid": os.getpid(),
            "proxy_base": self.server.proxy_base,
            "upstream_base": self.server.upstream_base,
            "service_tier": self.server.service_tier,
            "service_tier_policy": getattr(self.server, "service_tier_policy", "inject_missing"),
            "service_tier_effective_policy": getattr(self.server, "service_tier_effective_policy", "inject_missing"),
            "upstream_auth": "override_configured" if getattr(self.server, "upstream_api_key_env", None) else "preserved",
            "upstream_api_key_env": getattr(self.server, "public_upstream_api_key_env", None),
            "upstream_api_key_file": getattr(self.server, "upstream_api_key_source", None) == "provider_auth_file",
            "upstream_api_key_source": getattr(self.server, "upstream_api_key_source", None),
            "version": __version__,
            "runtime_id": RUNTIME_ID,
            "runtime": runtime_details(),
        }
        encoded = compact_json(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
        self.wfile.flush()

    def respond_dashboard(self) -> None:
        encoded = render_dashboard(self.server).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)
        self.wfile.flush()

    def read_request_body(self) -> bytes:
        transfer_encoding = self.headers.get("Transfer-Encoding", "")
        if "chunked" in transfer_encoding.lower():
            return read_chunked_request_body(self.rfile)

        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length > 0 else b""

    def forward_response(self, response: http.client.HTTPResponse) -> None:
        response_headers = response.getheaders()
        has_content_length = response.getheader("Content-Length") is not None
        no_body = self.command.upper() == "HEAD" or response.status in {204, 304}
        chunked = not no_body and not has_content_length

        self.send_response(response.status, response.reason)
        for name, value in copy_response_headers(response_headers, chunked):
            self.send_header(name, value)
        if chunked:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        if no_body:
            return

        content_type = response.getheader("Content-Type", "") or ""
        stream_response_body(
            response,
            self.wfile,
            chunked,
            line_buffered="text/event-stream" in content_type.lower(),
        )

    def respond_bad_gateway(self) -> None:
        payload = {
            "error": {
                "message": "codex-fast-proxy failed to reach upstream",
                "type": "fast_proxy_upstream_error",
                "code": "fast_proxy_upstream_error",
            }
        }
        encoded = compact_json(payload).encode("utf-8")
        self.send_response(502)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
        self.wfile.flush()

    def write_event(
        self,
        request_id: str,
        started_at: float,
        status: int,
        patch_event: dict[str, Any],
        response_content_type: str | None,
        error_type: str | None,
    ) -> None:
        event = {
            "ts": utc_now(),
            "request_id": request_id,
            "method": self.command,
            "path": normalized_path(self.path),
            "status": status,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 1),
            "eligible": patch_event["eligible"],
            "service_tier_before": patch_event["service_tier_before"],
            "service_tier_after": patch_event["service_tier_after"],
            "service_tier_injected": patch_event["injected"],
            "service_tier_policy": getattr(self.server, "service_tier_policy", "inject_missing"),
            "service_tier_effective_policy": getattr(self.server, "service_tier_effective_policy", "inject_missing"),
            "stream": patch_event["stream"],
            "json_error": patch_event["json_error"],
            "request_body_len": patch_event.get("request_body_len"),
            "request_body_magic": patch_event.get("request_body_magic"),
            "request_content_encoding": patch_event.get("request_content_encoding"),
            "response_content_type": response_content_type,
            "error_type": error_type,
        }

        with self.server.log_lock:
            with self.server.log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(compact_json(event) + "\n")

        if self.server.verbose:
            print(
                f"{event['ts']} {event['method']} {event['path']} "
                f"status={status} tier={event['service_tier_before']}->{event['service_tier_after']} "
                f"injected={event['service_tier_injected']} duration_ms={event['duration_ms']}",
                flush=True,
            )


class FastProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        log_path: Path,
        upstream_base: str,
        proxy_base: str,
        service_tier: str,
        service_tier_policy: str,
        service_tier_effective_policy: str | None,
        upstream_api_key_env: str | None,
        upstream_api_key_source: str | None,
        verbose: bool,
    ) -> None:
        parsed = urlsplit(upstream_base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Invalid upstream base URL: {upstream_base}")
        if service_tier_policy not in SERVICE_TIER_POLICIES:
            raise ValueError(f"Invalid service tier policy: {service_tier_policy}")
        effective_policy = service_tier_effective_policy or (
            "preserve" if service_tier_policy == "auto" else service_tier_policy
        )
        if effective_policy not in EFFECTIVE_SERVICE_TIER_POLICIES:
            raise ValueError(f"Invalid effective service tier policy: {effective_policy}")
        upstream_api_key = resolve_env(upstream_api_key_env) if upstream_api_key_env else None
        if upstream_api_key_env and not upstream_api_key:
            raise ValueError(f"Upstream API key environment variable is not available: {upstream_api_key_env}")
        upstream_api_key_source = upstream_api_key_source or ("env" if upstream_api_key_env else None)

        super().__init__(address, FastProxyHandler)
        self.log_path = log_path
        self.log_lock = threading.Lock()
        self.upstream_base = upstream_base
        self.upstream_scheme = parsed.scheme
        self.upstream_netloc = parsed.netloc
        self.upstream_host = parsed.hostname or parsed.netloc
        self.upstream_port = parsed.port
        self.upstream_base_path = parsed.path.rstrip("/") or "/"
        self.proxy_base = normalized_path(proxy_base)
        self.service_tier = service_tier
        self.service_tier_policy = service_tier_policy
        self.service_tier_effective_policy = effective_policy
        self.upstream_api_key_env = upstream_api_key_env
        self.public_upstream_api_key_env = None if upstream_api_key_source == "provider_auth_file" else upstream_api_key_env
        self.upstream_api_key_source = upstream_api_key_source
        self.upstream_api_key = upstream_api_key
        self.verbose = verbose

    def open_connection(self) -> http.client.HTTPConnection:
        if self.upstream_scheme == "https":
            return http.client.HTTPSConnection(
                self.upstream_host,
                self.upstream_port,
                timeout=3600,
                context=ssl.create_default_context(),
            )
        return http.client.HTTPConnection(self.upstream_host, self.upstream_port, timeout=3600)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transparent local proxy that enables Codex Fast mode for compatible providers."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--proxy-base", default="/v1")
    parser.add_argument("--upstream-base", required=True)
    parser.add_argument("--service-tier", default="priority")
    parser.add_argument("--service-tier-policy", choices=sorted(SERVICE_TIER_POLICIES), default="auto")
    parser.add_argument("--service-tier-effective-policy", choices=sorted(EFFECTIVE_SERVICE_TIER_POLICIES))
    parser.add_argument("--upstream-api-key-env")
    parser.add_argument("--upstream-api-key-source", choices=("env", "provider_auth_file"))
    parser.add_argument("--log-dir", default=str(Path.home() / ".codex" / "codex-fast-proxy-state" / "state"))
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "fast_proxy.jsonl"
    pid_path = log_dir / "fast_proxy.pid"

    server = FastProxyServer(
        (args.host, args.port),
        log_path,
        args.upstream_base,
        args.proxy_base,
        args.service_tier,
        args.service_tier_policy,
        args.service_tier_effective_policy,
        args.upstream_api_key_env,
        args.upstream_api_key_source,
        args.verbose,
    )
    pid_path.write_text(str(os.getpid()), encoding="utf-8")

    print(f"codex-fast-proxy listening on http://{args.host}:{args.port}{server.proxy_base}", flush=True)
    print(f"upstream: {args.upstream_base}", flush=True)
    print(f"log file: {log_path}", flush=True)

    stopping = False

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        server.shutdown()

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, stop)

    try:
        server.serve_forever()
    finally:
        server.server_close()
        try:
            pid_path.unlink()
        except FileNotFoundError:
            pass

    return 0
