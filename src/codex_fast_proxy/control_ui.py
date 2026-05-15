from __future__ import annotations

import http.client
import json
import os
import secrets
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .control_ui_render import CONTROL_TOKEN_HEADER, render_page
from .ports import find_available_port


RESERVED_PORTS = {8787}
PORT_SEARCH_ATTEMPTS = 100


class ControlServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        codex_home: str | None,
        provider: str | None,
        token: str,
    ) -> None:
        super().__init__(address, handler)
        self.codex_home = codex_home
        self.provider = provider
        self.token = token


class ControlHandler(BaseHTTPRequestHandler):
    server: ControlServer
    server_version = "CodexFastProxyControl/0.1"

    def log_message(self, _format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self.respond_html(render_page(collect_snapshot(self.server), self.server.token))
            return
        if self.path == "/api/status":
            self.respond_json({"status": "ok", "snapshot": collect_snapshot(self.server)})
            return
        self.respond_json({"status": "error", "error": "not_found"}, status=404)

    def do_POST(self) -> None:
        if not self.write_allowed():
            self.respond_json({"status": "error", "error": "forbidden"}, status=403)
            return
        if not self.path.startswith("/api/actions/"):
            self.respond_json({"status": "error", "error": "not_found"}, status=404)
            return
        try:
            result = self.run_action(self.path.rsplit("/", 1)[-1])
            self.respond_json({"status": "ok", **result})
        except Exception as exc:
            self.respond_json({
                "status": "error",
                "error": str(exc),
                "snapshot": collect_snapshot(self.server),
            }, status=400)

    def run_action(self, action: str) -> dict[str, Any]:
        from .actions import run_configure_upstream, run_first_run_enable, run_uninstall, run_update

        body = self.read_body_json()
        if action == "enable":
            result = run_first_run_enable(self.server.codex_home, self.server.provider)
        elif action == "update":
            result = run_update(self.server.codex_home, self.server.provider)
        elif action == "configure-upstream":
            result = run_configure_upstream(
                self.server.codex_home,
                body.get("upstream_base") if isinstance(body.get("upstream_base"), str) else None,
                body.get("api_key") if isinstance(body.get("api_key"), str) else None,
            )
        elif action == "uninstall":
            result = run_uninstall(self.server.codex_home, bool(body.get("confirm")))
        else:
            raise ValueError("Unknown action.")

        snapshot = result.get("final_status") if isinstance(result.get("final_status"), dict) else collect_snapshot(self.server)
        if isinstance(result.get("user_state"), dict):
            snapshot["user_state"] = result["user_state"]
        return {"action": result, "snapshot": snapshot}

    def read_body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        if length > 65536:
            raise ValueError("Request body is too large.")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    def write_allowed(self) -> bool:
        if self.headers.get(CONTROL_TOKEN_HEADER) != self.server.token:
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            return False
        return is_loopback_host(self.headers.get("Host", ""))

    def respond_html(self, text: str) -> None:
        encoded = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def respond_json(self, value: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def collect_snapshot(server: ControlServer) -> dict[str, Any]:
    from .state import collect_status

    return collect_status(server.codex_home, server.provider)


def serve_control_ui(codex_home: str | None, provider: str | None, host: str, port: int) -> int:
    server = ControlServer((host, port), ControlHandler, codex_home=codex_home, provider=provider, token=secrets.token_urlsafe(24))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    return 0


def open_control_ui(codex_home: str | None, provider: str | None, host: str, port: int) -> dict[str, Any]:
    selected_port = find_available_port(host, port, attempts=PORT_SEARCH_ATTEMPTS, reserved_ports=RESERVED_PORTS)
    if selected_port is None:
        port_range = f"{host}:{port}-{port + PORT_SEARCH_ATTEMPTS - 1}"
        return {
            "status": "error",
            "code": "control_ui_port_unavailable",
            "url": None,
            "error": f"没有找到可用的本地控制台端口，请关闭占用 {port_range} 的旧进程后重试。",
            "open_instruction": None,
        }
    url = f"http://{host}:{selected_port}/"
    start_background_server(codex_home, provider, host, selected_port)
    if not wait_for_status(host, selected_port):
        return {
            "status": "error",
            "code": "control_ui_start_failed",
            "url": url,
            "error": f"控制面板未能在 {url} 启动，请让 Codex 查看诊断后重试。",
            "open_instruction": None,
        }

    return {
        "status": "ready",
        "url": url,
        "open_instruction": f"请在外部浏览器中打开：{url}",
    }


def start_background_server(codex_home: str | None, provider: str | None, host: str, port: int) -> bool:
    command = [
        sys.executable,
        "-m",
        "codex_fast_proxy",
        "ui",
        "--foreground",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if codex_home:
        command.extend(["--codex-home", codex_home])
    if provider:
        command.extend(["--provider", provider])

    kwargs: dict[str, Any] = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        flags |= getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(command, **kwargs)
    except OSError:
        if os.name != "nt" or "creationflags" not in kwargs:
            raise
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        subprocess.Popen(command, **kwargs)
    return True


def wait_for_status(host: str, port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            connection = http.client.HTTPConnection(host, port, timeout=0.5)
            try:
                connection.request("GET", "/api/status")
                response = connection.getresponse()
                response.read()
                if response.status == 200:
                    return True
            finally:
                connection.close()
        except OSError:
            time.sleep(0.05)
    return False


def is_loopback_host(value: str) -> bool:
    host = value.split(":", 1)[0].strip("[]").lower()
    return host in {"127.0.0.1", "localhost", "::1"}
