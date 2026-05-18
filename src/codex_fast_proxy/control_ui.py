from __future__ import annotations

import http.client
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .control_ui_render import CONTROL_TOKEN_HEADER, render_page
from .models import paths_for
from .ports import find_available_port


RESERVED_PORTS = {8787}
PORT_SEARCH_ATTEMPTS = 100
CONTROL_UI_SERVER = "codex_fast_proxy_control_ui"
DELAYED_RMTREE_SCRIPT = """
import shutil
import sys
import time

path = sys.argv[1]
time.sleep(float(sys.argv[2]))
for _ in range(80):
    try:
        shutil.rmtree(path)
        break
    except FileNotFoundError:
        break
    except OSError:
        time.sleep(0.1)
"""
DELAYED_UI_RESTART_SCRIPT = """
import http.client
import subprocess
import sys
import time

host = sys.argv[1]
port = int(sys.argv[2])
delay = float(sys.argv[3])
command = sys.argv[4:]
time.sleep(delay)
deadline = time.monotonic() + 15
while time.monotonic() < deadline:
    try:
        connection = http.client.HTTPConnection(host, port, timeout=0.2)
        try:
            connection.request("GET", "/api/ping")
            response = connection.getresponse()
            response.read()
        finally:
            connection.close()
        time.sleep(0.1)
    except OSError:
        break
kwargs = {
    "stdin": subprocess.DEVNULL,
    "stdout": subprocess.DEVNULL,
    "stderr": subprocess.DEVNULL,
    "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
}
if sys.platform != "win32":
    kwargs["start_new_session"] = True
subprocess.Popen(command, **kwargs)
"""


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
        if self.path == "/api/ping":
            self.respond_json({
                "status": "ok",
                "server": CONTROL_UI_SERVER,
                **control_ui_identity(self.server.codex_home, self.server.provider),
            })
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
        action = self.path.rsplit("/", 1)[-1]
        try:
            result = self.run_action(action)
            self.respond_json({"status": "ok", **result})
            if result.get("shutdown_control_ui"):
                self.shutdown_soon()
        except Exception as exc:
            snapshot = collect_snapshot(self.server)
            snapshot["last_error"] = {"action": action, "message": str(exc)}
            self.respond_json({
                "status": "error",
                "error": user_error_message(action, snapshot),
                "snapshot": snapshot,
            }, status=400)

    def run_action(self, action: str) -> dict[str, Any]:
        from .actions import (
            run_first_run_enable,
            run_save_provider,
            run_set_speed_mode,
            run_switch_provider,
            run_uninstall,
            run_update,
        )

        body = self.read_body_json()
        shutdown_control_ui = False
        if action == "enable":
            action_provider = body.get("provider") if isinstance(body.get("provider"), str) else self.server.provider
            result = run_first_run_enable(self.server.codex_home, action_provider)
        elif action == "update":
            result = run_update(self.server.codex_home, self.server.provider)
            if result.get("control_ui_reload_required"):
                result["control_ui"] = self.restart_current_control_ui()
                shutdown_control_ui = result["control_ui"].get("status") == "scheduled"
        elif action == "save-provider":
            result = run_save_provider(
                self.server.codex_home,
                body.get("provider") if isinstance(body.get("provider"), str) else None,
                body.get("upstream_base") if isinstance(body.get("upstream_base"), str) else None,
                body.get("api_key") if isinstance(body.get("api_key"), str) else None,
            )
        elif action == "switch-provider":
            result = run_switch_provider(
                self.server.codex_home,
                body.get("provider") if isinstance(body.get("provider"), str) else None,
            )
        elif action == "set-speed-mode":
            result = run_set_speed_mode(
                self.server.codex_home,
                body.get("speed_mode") if isinstance(body.get("speed_mode"), str) else None,
            )
        elif action == "uninstall":
            result = run_uninstall(self.server.codex_home, bool(body.get("confirm")))
            cleanup = result.get("control_ui_cleanup") if isinstance(result.get("control_ui_cleanup"), dict) else None
            if cleanup and isinstance(cleanup.get("path"), str):
                result["control_ui_cleanup"] = schedule_path_cleanup(Path(cleanup["path"]))
                shutdown_control_ui = result["control_ui_cleanup"].get("status") == "scheduled"
        else:
            raise ValueError("Unknown action.")

        snapshot = result.get("final_status") if isinstance(result.get("final_status"), dict) else collect_snapshot(self.server)
        if isinstance(result.get("user_state"), dict):
            snapshot["user_state"] = result["user_state"]
        response = {"action": result, "snapshot": snapshot}
        if shutdown_control_ui:
            response["shutdown_control_ui"] = True
        return response

    def start_replacement_control_ui(self) -> dict[str, Any]:
        host, port = self.server.server_address[:2]
        result = open_control_ui(self.server.codex_home, self.server.provider, str(host), int(port), reuse_existing=False)
        if result.get("status") == "ready":
            result["replaces_current"] = True
        return result

    def restart_current_control_ui(self) -> dict[str, Any]:
        host, port = self.server.server_address[:2]
        return schedule_control_ui_restart(self.server.codex_home, self.server.provider, str(host), int(port))

    def shutdown_soon(self) -> None:
        timer = threading.Timer(0.2, self.server.shutdown)
        timer.daemon = True
        timer.start()

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
    finally:
        server.server_close()
    return 0


def user_error_message(action: str, snapshot: dict[str, Any]) -> str:
    if action in {"save-provider", "configure-upstream"}:
        upstream = snapshot.get("upstream_base")
        if isinstance(upstream, str) and upstream:
            return f"没有保存。新的模型服务没有通过验证，当前仍在使用：{upstream}"
        return "没有保存。新的模型服务没有通过验证，当前设置保持不变。"
    if action == "switch-provider":
        return "没有切换。请选择已保存且可验证的 Provider。"
    if action == "set-speed-mode":
        return "速度模式没有保存，当前设置保持不变。"
    if action == "enable":
        return "启用没有完成，当前设置保持不变。请打开诊断，或让 Codex 检查原因。"
    if action == "update":
        return "更新没有完成。请打开诊断，或让 Codex 检查原因。"
    if action == "uninstall":
        return "停用没有完成，当前设置保持不变。请打开诊断，或让 Codex 检查原因。"
    return "操作没有完成，当前设置保持不变。请打开诊断，或让 Codex 检查原因。"


def open_control_ui(
    codex_home: str | None,
    provider: str | None,
    host: str,
    port: int,
    *,
    reuse_existing: bool = True,
) -> dict[str, Any]:
    identity = control_ui_identity(codex_home, provider)
    existing_port = find_existing_control_ui(host, port, identity=identity) if reuse_existing else None
    if existing_port is not None:
        url = f"http://{host}:{existing_port}/"
        return ready_control_ui_result(url, started_background_process=False, reused_existing=True)

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
    start_result = start_background_server(codex_home, provider, host, selected_port)
    if start_result.get("status") == "error":
        return {
            "status": "error",
            "code": "control_ui_start_failed",
            "url": url,
            "error": f"控制面板未能在 {url} 启动，请让 Codex 查看诊断后重试。",
            "open_instruction": None,
            "start": start_result,
        }
    if not wait_for_status(host, selected_port, identity=identity):
        return {
            "status": "error",
            "code": "control_ui_start_failed",
            "url": url,
            "error": f"控制面板未能在 {url} 启动，请让 Codex 查看诊断后重试。",
            "open_instruction": None,
            "start": start_result,
        }

    return ready_control_ui_result(url, started_background_process=True, reused_existing=False)


def ready_control_ui_result(url: str, *, started_background_process: bool, reused_existing: bool) -> dict[str, Any]:
    return {
        "status": "ready",
        "url": url,
        "open_instruction": f"请在外部浏览器中打开：{url}",
        "background_process": True,
        "started_background_process": started_background_process,
        "reused_existing": reused_existing,
        "approval_reason": (
            "Starts a local background Control UI server. In sandboxed Codex environments, "
            "run this command with approval so the server can stay alive after the launcher exits."
        ),
    }


def start_background_server(codex_home: str | None, provider: str | None, host: str, port: int) -> dict[str, Any]:
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

    stdout_path, stderr_path, pid_path = control_ui_runtime_paths(codex_home)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout = stdout_path.open("ab")
    stderr = stderr_path.open("ab")
    kwargs: dict[str, Any] = {
        "cwd": str(Path.cwd()),
        "stdout": stdout,
        "stderr": stderr,
        "stdin": subprocess.DEVNULL,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "start_new_session": os.name != "nt",
    }
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        }
    finally:
        stdout.close()
        stderr.close()
    pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    return {
        "status": "started",
        "pid": process.pid,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }


def control_ui_runtime_paths(codex_home: str | None) -> tuple[Path, Path, Path]:
    paths = paths_for(codex_home)
    return (
        paths.state_dir / "control_ui.stdout.log",
        paths.state_dir / "control_ui.stderr.log",
        paths.state_dir / "control_ui.pid",
    )


def control_ui_identity(codex_home: str | None, provider: str | None) -> dict[str, str | None]:
    return {
        "codex_home": normalized_control_path(paths_for(codex_home).codex_home),
        "provider": provider or None,
    }


def normalized_control_path(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve()))


def schedule_path_cleanup(path: Path, delay: float = 1.0) -> dict[str, Any]:
    command = [sys.executable, "-c", DELAYED_RMTREE_SCRIPT, str(path), str(delay)]
    kwargs: dict[str, Any] = {
        "cwd": str(Path.cwd()),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "start_new_session": os.name != "nt",
    }
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        return {"status": "error", "path": str(path), "error": str(exc)}
    return {"status": "scheduled", "path": str(path), "pid": process.pid}


def schedule_control_ui_restart(
    codex_home: str | None,
    provider: str | None,
    host: str,
    port: int,
    delay: float = 0.5,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "codex_fast_proxy",
        "ui",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if codex_home:
        command.extend(["--codex-home", codex_home])
    if provider:
        command.extend(["--provider", provider])
    launcher = [sys.executable, "-c", DELAYED_UI_RESTART_SCRIPT, host, str(port), str(delay), *command]
    kwargs: dict[str, Any] = {
        "cwd": str(Path.cwd()),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "start_new_session": os.name != "nt",
    }
    try:
        process = subprocess.Popen(launcher, **kwargs)
    except OSError as exc:
        return {
            "status": "error",
            "url": f"http://{host}:{port}/",
            "error": str(exc),
        }
    return {
        "status": "scheduled",
        "url": f"http://{host}:{port}/",
        "same_port": True,
        "pid": process.pid,
        "reload_after_ms": 1200,
    }


def find_existing_control_ui(
    host: str,
    port: int,
    *,
    identity: dict[str, str | None],
    attempts: int = PORT_SEARCH_ATTEMPTS,
) -> int | None:
    for candidate in range(port, port + attempts):
        if probe_control_ui(host, candidate, timeout=0.2, fallback_status=False, identity=identity):
            return candidate
    return None


def wait_for_status(
    host: str,
    port: int,
    timeout: float = 5.0,
    *,
    identity: dict[str, str | None] | None = None,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe_control_ui(host, port, timeout=0.5, fallback_status=True, identity=identity):
            return True
        time.sleep(0.05)
    return False


def probe_control_ui(
    host: str,
    port: int,
    *,
    timeout: float,
    fallback_status: bool,
    identity: dict[str, str | None] | None = None,
) -> bool:
    if probe_control_ui_path(host, port, "/api/ping", timeout, require_server_marker=True, identity=identity):
        return True
    return identity is None and fallback_status and probe_control_ui_path(
        host,
        port,
        "/api/status",
        timeout,
        require_server_marker=False,
    )


def probe_control_ui_path(
    host: str,
    port: int,
    path: str,
    timeout: float,
    *,
    require_server_marker: bool,
    identity: dict[str, str | None] | None = None,
) -> bool:
    try:
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read()
            if response.status != 200:
                return False
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, dict) or data.get("status") != "ok":
                return False
            if require_server_marker:
                return data.get("server") == CONTROL_UI_SERVER and control_ui_identity_matches(data, identity)
            return True
        finally:
            connection.close()
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def control_ui_identity_matches(data: dict[str, Any], identity: dict[str, str | None] | None) -> bool:
    if identity is None:
        return True
    return data.get("codex_home") == identity["codex_home"] and data.get("provider") == identity["provider"]


def is_loopback_host(value: str) -> bool:
    host = host_without_port(value).lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def host_without_port(value: str) -> str:
    host = value.strip()
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end != -1 else host.strip("[]")
    if host.count(":") == 1:
        return host.rsplit(":", 1)[0]
    return host
