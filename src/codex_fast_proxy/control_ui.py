from __future__ import annotations

import http.client
import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .control_ui_render import CONTROL_TOKEN_HEADER, render_page
from .defaults import (
    CONTROL_UI_PORT_RANGES,
    DEFAULT_CONTROL_UI_PORT,
    DEFAULT_PORT,
    LEGACY_CONTROL_UI_PORT,
    LEGACY_DEFAULT_PORT,
)
from .models import paths_for, settings_from_dict
from .ports import iter_port_candidates
from .skill_link import skill_namespace_path, skill_target_path
from .storage import ensure_private_dir, open_private_append, read_json, write_json, write_private_text


RESERVED_PORTS = {DEFAULT_PORT, LEGACY_DEFAULT_PORT}
PORT_SEARCH_ATTEMPTS = 100
CONTROL_UI_SERVER = "codex_fast_proxy_control_ui"
CONTROL_UI_REVISION_FILES = (
    "control_ui.py",
    "control_ui_render.py",
    "actions.py",
    "auth_store.py",
    "manager.py",
    "runtime_process.py",
    "state.py",
)
CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)


@dataclass(frozen=True)
class ControlUiOpenPolicy:
    existing_attempts: int
    existing_probe_timeout: float
    port_search_attempts: int
    ready_timeout: float
    return_starting_on_timeout: bool = False


INTERACTIVE_CONTROL_UI_POLICY = ControlUiOpenPolicy(
    existing_attempts=PORT_SEARCH_ATTEMPTS,
    existing_probe_timeout=0.2,
    port_search_attempts=PORT_SEARCH_ATTEMPTS,
    ready_timeout=5.0,
)
AUTOSTART_CONTROL_UI_POLICY = ControlUiOpenPolicy(
    existing_attempts=8,
    existing_probe_timeout=0.05,
    port_search_attempts=8,
    ready_timeout=0.5,
    return_starting_on_timeout=True,
)
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
DELAYED_INSTALL_CLEANUP_SCRIPT = """
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path


def remove_tree(path):
    for _ in range(80):
        try:
            shutil.rmtree(path)
            break
        except FileNotFoundError:
            break
        except OSError:
            time.sleep(0.1)


def path_is_junction(path):
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def path_exists_or_link(path):
    return path.exists() or path.is_symlink() or path_is_junction(path)


def comparable_path(path):
    try:
        resolved = str(path.resolve(strict=True))
    except OSError:
        if not path_is_junction(path):
            return None
        try:
            resolved = str(path.readlink())
        except OSError:
            return None
    if resolved.startswith("\\\\?\\UNC\\"):
        resolved = "\\\\" + resolved[8:]
    elif resolved.startswith("\\\\?\\"):
        resolved = resolved[4:]
    return os.path.normcase(os.path.normpath(resolved))


def remove_skill_link(path, target):
    try:
        if not path_exists_or_link(path):
            return
        source_path = comparable_path(path)
        target_path = comparable_path(target)
        if source_path is None or source_path != target_path:
            return
        if path.is_symlink():
            path.unlink()
        else:
            path.rmdir()
    except OSError:
        return


def stop_control_ui_processes(codex_home):
    if sys.platform == "win32":
        script = r'''
$CodexHome = [System.IO.Path]::GetFullPath($args[0]).TrimEnd('\\').ToLowerInvariant()
$SelfPid = [int]$args[1]
$ModuleNeedle = ('-m ' + 'codex_fast_proxy ' + 'ui')
$CodexHomeNeedle = ('--' + 'codex-home')
Get-CimInstance Win32_Process | Where-Object {
    if (-not $_.CommandLine) { return $false }
    $Command = $_.CommandLine.ToLowerInvariant()
    $_.ProcessId -ne $SelfPid -and
        $Command.Contains($ModuleNeedle) -and
        $Command.Contains($CodexHomeNeedle) -and
        $Command.Contains($CodexHome)
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
'''
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script, str(codex_home), str(os.getpid())],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        return

    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return

    home = str(codex_home)
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        command = parts[1]
        if pid == os.getpid():
            continue
        if "-m codex_fast_proxy ui" not in command or "--codex-home" not in command or home not in command:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue


delay = float(sys.argv[1])
app_home = Path(sys.argv[2])
repo_root = Path(sys.argv[3])
backup_dir = Path(sys.argv[4])
package = sys.argv[5]
skill_link = Path(sys.argv[6])
skill_target = Path(sys.argv[7])

time.sleep(delay)
stop_control_ui_processes(app_home.parent)
remove_skill_link(skill_link, skill_target)
subprocess.run(
    [sys.executable, "-m", "pip", "uninstall", "-y", package],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    check=False,
    timeout=120,
)
remove_tree(backup_dir)
remove_tree(app_home)
remove_tree(repo_root)
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
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self.respond_html(render_page(collect_snapshot(self.server), self.server.token))
            return
        if parsed.path == "/favicon.ico":
            self.respond_empty()
            return
        if parsed.path == "/api/ping":
            self.respond_json({
                "status": "ok",
                "server": CONTROL_UI_SERVER,
                "pid": os.getpid(),
                **control_ui_identity(self.server.codex_home, self.server.provider),
            })
            return
        if parsed.path == "/api/status":
            self.respond_json({"status": "ok", "snapshot": collect_snapshot(self.server)})
            return
        if parsed.path == "/api/doctor":
            if not self.write_allowed():
                self.respond_json({"status": "error", "error": "forbidden"}, status=403)
                return
            try:
                self.respond_json(doctor_payload(self.server.codex_home, self.server.provider))
            except Exception as exc:
                self.respond_json({"status": "error", "error": str(exc)}, status=400)
            return
        if parsed.path == "/api/provider-key":
            if not self.write_allowed():
                self.respond_json({"status": "error", "error": "forbidden"}, status=403)
                return
            query = parse_qs(parsed.query)
            provider = query.get("provider", [None])[0]
            try:
                self.respond_json(provider_key_payload(self.server.codex_home, provider))
            except ValueError as exc:
                self.respond_json({"status": "error", "error": str(exc)}, status=404)
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
        except Exception as exc:
            try:
                self.respond_json(action_error_payload(action, self.server, str(exc)), status=400)
            except CLIENT_DISCONNECT_ERRORS:
                return
            return

        try:
            self.respond_json({"status": "ok", **result})
        except CLIENT_DISCONNECT_ERRORS:
            pass
        finally:
            if result.get("shutdown_control_ui"):
                self.shutdown_soon(float(result.get("shutdown_after_seconds") or 0.2))

    def run_action(self, action: str) -> dict[str, Any]:
        from .actions import (
            run_apply_pending_now,
            run_benchmark,
            run_check_update,
            run_delete_provider,
            run_first_run_enable,
            run_save_provider,
            run_set_speed_mode,
            run_switch_provider,
            run_uninstall,
            run_update,
            run_verify_provider,
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
        elif action == "check-update":
            result = run_check_update(self.server.codex_home)
        elif action == "apply-pending-now":
            result = run_apply_pending_now(self.server.codex_home)
        elif action == "save-provider":
            result = run_save_provider(
                self.server.codex_home,
                body.get("provider") if isinstance(body.get("provider"), str) else None,
                body.get("upstream_base") if isinstance(body.get("upstream_base"), str) else None,
                body.get("api_key") if isinstance(body.get("api_key"), str) else None,
            )
        elif action == "verify-provider":
            result = run_verify_provider(
                self.server.codex_home,
                body.get("provider") if isinstance(body.get("provider"), str) else None,
            )
        elif action == "switch-provider":
            result = run_switch_provider(
                self.server.codex_home,
                body.get("provider") if isinstance(body.get("provider"), str) else None,
            )
        elif action == "delete-provider":
            result = run_delete_provider(
                self.server.codex_home,
                body.get("provider") if isinstance(body.get("provider"), str) else None,
            )
        elif action == "set-speed-mode":
            result = run_set_speed_mode(
                self.server.codex_home,
                body.get("speed_mode") if isinstance(body.get("speed_mode"), str) else None,
            )
        elif action == "run-benchmark":
            result = run_benchmark(
                self.server.codex_home,
                bool(body.get("confirm")),
                body.get("benchmark_kind") if isinstance(body.get("benchmark_kind"), str) else "quick",
            )
        elif action == "uninstall":
            result = run_uninstall(self.server.codex_home, bool(body.get("confirm")))
            cleanup = result.get("control_ui_cleanup") if isinstance(result.get("control_ui_cleanup"), dict) else None
            if cleanup and cleanup.get("mode") == "deep_install_removal":
                result["control_ui_cleanup"] = schedule_install_cleanup(cleanup)
                shutdown_control_ui = result["control_ui_cleanup"].get("status") == "scheduled"
                if shutdown_control_ui:
                    result["shutdown_after_seconds"] = 2.5
            elif cleanup and isinstance(cleanup.get("path"), str):
                result["control_ui_cleanup"] = schedule_path_cleanup(Path(cleanup["path"]), delay=3.0)
                shutdown_control_ui = result["control_ui_cleanup"].get("status") == "scheduled"
                if shutdown_control_ui:
                    result["shutdown_after_seconds"] = 2.5
        else:
            raise ValueError("Unknown action.")

        if not shutdown_control_ui and not control_ui_restart_scheduled(result) and control_ui_source_changed():
            result["control_ui_reload_required"] = True
            result["control_ui"] = self.restart_current_control_ui()
            shutdown_control_ui = result["control_ui"].get("status") == "scheduled"

        snapshot = result.get("final_status") if isinstance(result.get("final_status"), dict) else collect_snapshot(self.server)
        if isinstance(result.get("user_state"), dict):
            snapshot["user_state"] = result["user_state"]
        response = {"action": result, "snapshot": snapshot}
        if shutdown_control_ui:
            response["shutdown_control_ui"] = True
            response["shutdown_after_seconds"] = result.get("shutdown_after_seconds", 0.2)
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

    def shutdown_soon(self, delay: float = 0.2) -> None:
        timer = threading.Timer(delay, self.server.shutdown)
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

    def respond_empty(self, status: int = 204) -> None:
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

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

    return collect_status(server.codex_home, server.provider, apply_idle_pending=True)


def action_error_payload(action: str, server: ControlServer, detail: str) -> dict[str, Any]:
    snapshot = collect_snapshot(server)
    message = user_error_message(action, snapshot, detail)
    snapshot["last_error"] = {"action": action, "message": detail}
    snapshot["user_state"] = {
        "code": "action_failed",
        "title": "需要处理",
        "message": message,
        "primary_action": "diagnostics",
        "primary_label": "打开高级诊断",
    }
    return {
        "status": "error",
        "action": {"status": "error", "error": message},
        "error": message,
        "snapshot": snapshot,
    }


def doctor_payload(codex_home: str | None, provider: str | None) -> dict[str, Any]:
    from .manager import doctor_report

    return {"status": "ok", "doctor": doctor_report(paths_for(codex_home), provider)}


def provider_key_payload(codex_home: str | None, provider: str | None) -> dict[str, str]:
    from .auth_store import provider_auth_secret

    name = provider.strip() if isinstance(provider, str) else ""
    if not name:
        raise ValueError("Provider 不能为空。")
    api_key = provider_auth_secret(paths_for(codex_home), name)
    if not api_key:
        raise ValueError("这个 Provider 没有保存接口密钥。")
    return {"status": "ok", "provider": name, "api_key": api_key}


def serve_control_ui(codex_home: str | None, provider: str | None, host: str, port: int) -> int:
    try:
        server = ControlServer((host, port), ControlHandler, codex_home=codex_home, provider=provider, token=secrets.token_urlsafe(24))
    except OSError as exc:
        print(f"control-ui bind failed on {host}:{port}: {exc}", file=sys.stderr, flush=True)
        return 2
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


def user_error_detail(detail: str | None) -> str | None:
    if not detail:
        return None
    lowered = detail.lower()
    if "could not find an api key" in lowered or "does not contain an api key" in lowered:
        return "没有可用于验证的接口密钥；请填写接口密钥，或确认该 Provider 已保存 key。"
    if "http 401" in lowered or "unauthorized" in lowered or "invalid api key" in lowered:
        return "HTTP 401：接口密钥无效或未被该模型服务接受，请检查这个 Provider 的 key。"
    if "http 402" in lowered or "insufficient_quota" in lowered or "quota" in lowered or "billing" in lowered:
        return "额度或计费状态不可用；请检查供应商账户余额、套餐或计费状态。"
    if "http 403" in lowered or "forbidden" in lowered:
        return "HTTP 403：供应商拒绝了验证请求，请检查 key 权限、模型权限或账户状态。"
    if "http 404" in lowered or "not found" in lowered:
        return "HTTP 404：模型服务地址可能不支持 /v1/responses，请确认 base_url 指向兼容的 API 入口。"
    if "timed out" in lowered or "timeout" in lowered:
        return "连接超时；请检查模型服务地址、网络连通性，或稍后重试。"
    if "connection refused" in lowered or "errno 61" in lowered or "errno 10061" in lowered:
        return "模型服务地址拒绝连接；请确认 base_url 正确，且供应商服务当前可访问。"
    if "getaddrinfo" in lowered or "name or service not known" in lowered or "nodename nor servname" in lowered:
        return "模型服务地址无法解析；请检查 base_url 的域名或网络 DNS 设置。"
    if "did not return sse" in lowered:
        return "模型服务没有返回流式 SSE 响应；请确认该供应商支持 Responses API 的 stream=true。"
    if "responses api side-path verification failed" in lowered:
        return "模型服务验证失败；请检查 base_url、接口密钥和网络连通性。"
    return detail


def user_error_message(action: str, snapshot: dict[str, Any], detail: str | None = None) -> str:
    friendly_detail = user_error_detail(detail)
    suffix = f" 原因：{friendly_detail}" if friendly_detail else ""
    if action in {"save-provider", "configure-upstream"}:
        upstream = snapshot.get("upstream_base")
        if isinstance(upstream, str) and upstream:
            return f"没有保存。新的模型服务没有通过验证，当前仍在使用：{upstream}{suffix}"
        return f"没有保存。新的模型服务没有通过验证，当前设置保持不变。{suffix}"
    if action == "switch-provider":
        return f"没有切换。请选择已保存且可验证的 Provider。{suffix}"
    if action == "delete-provider":
        return f"没有删除。当前正在使用的 Provider 不能删除。{suffix}"
    if action == "set-speed-mode":
        return f"速度模式没有保存，当前设置保持不变。{suffix}"
    if action == "enable":
        return f"启用没有完成，当前设置保持不变。{suffix}" if suffix else "启用没有完成，当前设置保持不变。请打开高级诊断，或让 Codex 检查原因。"
    if action == "update":
        return "更新没有完成。请打开高级诊断，或让 Codex 检查原因。"
    if action == "check-update":
        return f"检查更新没有完成。{suffix}"
    if action == "apply-pending-now":
        return f"当前还不能立即应用，等待状态保持不变。{suffix}"
    if action == "verify-provider":
        return f"Provider 检查没有完成，当前设置保持不变。{suffix}"
    if action == "run-benchmark":
        return f"基准测试没有完成，未保存新结果。{suffix}"
    if action == "uninstall":
        return "停用没有完成，当前设置保持不变。请打开高级诊断，或让 Codex 检查原因。"
    return "操作没有完成，当前设置保持不变。请打开高级诊断，或让 Codex 检查原因。"


def control_ui_state_path(codex_home: str | None) -> Path:
    return paths_for(codex_home).app_home / "control-ui.json"


def current_proxy_port(codex_home: str | None) -> int | None:
    settings_data = read_json(paths_for(codex_home).settings_path)
    if not settings_data:
        return None
    try:
        return settings_from_dict(settings_data).port
    except Exception:
        return None


def default_control_ui_port(codex_home: str | None) -> int:
    return LEGACY_CONTROL_UI_PORT if current_proxy_port(codex_home) == LEGACY_DEFAULT_PORT else DEFAULT_CONTROL_UI_PORT


def saved_control_ui_port(codex_home: str | None, host: str) -> int | None:
    state = read_json(control_ui_state_path(codex_home))
    if not isinstance(state, dict) or state.get("host") != host:
        return None
    try:
        return int(state["port"])
    except (KeyError, TypeError, ValueError):
        return None


def preferred_control_ui_port(codex_home: str | None, host: str, requested_port: int | None) -> int:
    if requested_port is not None:
        return requested_port
    return saved_control_ui_port(codex_home, host) or default_control_ui_port(codex_home)


def reserved_control_ui_ports(codex_home: str | None) -> set[int]:
    reserved = set(RESERVED_PORTS)
    proxy_port = current_proxy_port(codex_home)
    if proxy_port is not None:
        reserved.add(proxy_port)
    return reserved


def save_control_ui_port(codex_home: str | None, host: str, port: int) -> None:
    path = control_ui_state_path(codex_home)
    ensure_private_dir(path.parent)
    write_json(path, {"host": host, "port": port, "updated_at": time.time()})


def control_ui_bind_failed(start_result: dict[str, Any]) -> bool:
    stderr = start_result.get("stderr")
    offset = start_result.get("stderr_offset")
    if not isinstance(stderr, str) or not isinstance(offset, int):
        return False
    text = read_text_since(Path(stderr), offset)
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "bind failed",
            "address already in use",
            "permissionerror",
            "winerror 10013",
            "errno 98",
            "errno 48",
        )
    )


def read_text_since(path: Path, offset: int, *, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as file:
        file.seek(offset)
        data = file.read()
    if len(data) > limit:
        data = data[-limit:]
    return data.decode("utf-8", errors="replace")


def wait_for_control_ui_start(
    host: str,
    port: int,
    start_result: dict[str, Any],
    *,
    timeout: float,
    identity: dict[str, str | None],
) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe_control_ui(host, port, timeout=0.2, fallback_status=True, identity=identity):
            return "ready"
        if control_ui_bind_failed(start_result):
            return "bind_failed"
        time.sleep(0.05)
    return "timeout"


def open_control_ui(
    codex_home: str | None,
    provider: str | None,
    host: str,
    port: int | None,
    *,
    reuse_existing: bool = True,
    policy: ControlUiOpenPolicy = INTERACTIVE_CONTROL_UI_POLICY,
) -> dict[str, Any]:
    identity = control_ui_identity(codex_home, provider)
    preferred_port = preferred_control_ui_port(codex_home, host, port)
    existing_port = (
        find_existing_control_ui(
            host,
            preferred_port,
            identity=identity,
            attempts=policy.existing_attempts,
            probe_timeout=policy.existing_probe_timeout,
        )
        if reuse_existing
        else None
    )
    if existing_port is not None:
        url = f"http://{host}:{existing_port}/"
        save_control_ui_port(codex_home, host, existing_port)
        return ready_control_ui_result(url, started_background_process=False, reused_existing=True)

    failed_ports: list[int] = []
    reserved_ports = reserved_control_ui_ports(codex_home)
    candidates = iter_port_candidates(preferred_port, CONTROL_UI_PORT_RANGES, reserved_ports=reserved_ports)
    for index, selected_port in enumerate(candidates):
        if index >= policy.port_search_attempts:
            break
        url = f"http://{host}:{selected_port}/"
        start_result = start_background_server(codex_home, provider, host, selected_port)
        if start_result.get("status") == "error":
            return {
                "status": "error",
                "code": "control_ui_start_failed",
                "url": url,
                "error": f"控制面板未能在 {url} 启动，请让 Codex 查看高级诊断后重试。",
                "open_instruction": None,
                "start": start_result,
            }
        start_state = wait_for_control_ui_start(
            host,
            selected_port,
            start_result,
            timeout=policy.ready_timeout,
            identity=identity,
        )
        if start_state == "ready":
            save_control_ui_port(codex_home, host, selected_port)
            result = ready_control_ui_result(url, started_background_process=True, reused_existing=False)
            if selected_port != preferred_port:
                result["port_selection"] = {
                    "preferred": preferred_port,
                    "selected": selected_port,
                    "auto_selected": True,
                    "reason": "bind_failed",
                    "failed_ports": failed_ports,
                }
            return result
        if start_state == "bind_failed":
            failed_ports.append(selected_port)
            continue
        if policy.return_starting_on_timeout:
            save_control_ui_port(codex_home, host, selected_port)
            return starting_control_ui_result(url, start_result)
        return {
            "status": "error",
            "code": "control_ui_start_failed",
            "url": url,
            "error": f"控制面板未能在 {url} 启动，请让 Codex 查看高级诊断后重试。",
            "open_instruction": None,
            "start": start_result,
        }

    return {
        "status": "error",
        "code": "control_ui_port_unavailable",
        "url": None,
        "error": "没有找到可用的本地控制台端口，请关闭占用本地端口的旧进程后重试。",
        "open_instruction": None,
    }


def ensure_control_ui_for_hook(codex_home: str | None, provider: str | None, host: str, port: int | None) -> dict[str, Any]:
    return open_control_ui(
        codex_home,
        provider,
        host,
        port,
        policy=AUTOSTART_CONTROL_UI_POLICY,
    )


def ready_control_ui_result(url: str, *, started_background_process: bool, reused_existing: bool) -> dict[str, Any]:
    return {
        "status": "ready",
        "url": url,
        "open_instruction": f"请在外部浏览器中打开：{url}",
        "background_process": True,
        "started_background_process": started_background_process,
        "reused_existing": reused_existing,
        "ready_waited": True,
        "approval_reason": (
            "Starts a local background Control UI server. In sandboxed Codex environments, "
            "run this command with approval so the server can stay alive after the launcher exits."
        ),
    }


def starting_control_ui_result(url: str, start_result: dict[str, Any]) -> dict[str, Any]:
    result = ready_control_ui_result(url, started_background_process=True, reused_existing=False)
    result.update({
        "status": "starting",
        "ready_waited": False,
        "start": start_result,
    })
    return result


def is_windows_platform() -> bool:
    return os.name == "nt"


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
    ensure_private_dir(stdout_path.parent.parent)
    ensure_private_dir(stdout_path.parent)
    stderr_offset = stderr_path.stat().st_size if stderr_path.exists() else 0
    stdout = open_private_append(stdout_path, binary=True)
    stderr = open_private_append(stderr_path, binary=True)
    kwargs: dict[str, Any] = {
        "cwd": str(Path.cwd()),
        "stdout": stdout,
        "stderr": stderr,
        "stdin": subprocess.DEVNULL,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "start_new_session": not is_windows_platform(),
    }
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
            "stderr_offset": stderr_offset,
        }
    finally:
        stdout.close()
        stderr.close()
    write_private_text(pid_path, f"{process.pid}\n")
    return {
        "status": "started",
        "pid": process.pid,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "stderr_offset": stderr_offset,
    }


def control_ui_runtime_paths(codex_home: str | None) -> tuple[Path, Path, Path]:
    paths = paths_for(codex_home)
    return (
        paths.state_dir / "control_ui.stdout.log",
        paths.state_dir / "control_ui.stderr.log",
        paths.state_dir / "control_ui.pid",
    )


def compute_control_ui_revision() -> str:
    digest = hashlib.sha256()
    source_dir = Path(__file__).resolve().parent
    for filename in CONTROL_UI_REVISION_FILES:
        path = source_dir / filename
        digest.update(filename.encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(str(path).encode("utf-8", errors="replace"))
    return digest.hexdigest()[:16]


CONTROL_UI_REVISION = compute_control_ui_revision()


def control_ui_source_changed() -> bool:
    return compute_control_ui_revision() != CONTROL_UI_REVISION


def control_ui_restart_scheduled(result: dict[str, Any]) -> bool:
    control_ui = result.get("control_ui")
    return isinstance(control_ui, dict) and control_ui.get("status") == "scheduled"


def control_ui_identity(codex_home: str | None, provider: str | None) -> dict[str, str | None]:
    return {
        "codex_home": normalized_control_path(paths_for(codex_home).codex_home),
        "provider": provider or None,
        "control_ui_revision": CONTROL_UI_REVISION,
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
        "start_new_session": not is_windows_platform(),
    }
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        return {"status": "error", "path": str(path), "error": str(exc)}
    return {"status": "scheduled", "path": str(path), "pid": process.pid}


def schedule_install_cleanup(cleanup: dict[str, Any], delay: float = 4.0) -> dict[str, Any]:
    app_home = Path(str(cleanup["app_home"]))
    repo_root = Path(str(cleanup["repo_root"]))
    log_path = app_home / "state" / "install_cleanup.stderr.log"
    command = [
        sys.executable,
        "-c",
        DELAYED_INSTALL_CLEANUP_SCRIPT,
        str(delay),
        str(app_home),
        str(repo_root),
        str(cleanup["backup_dir"]),
        str(cleanup["package"]),
        str(skill_namespace_path()),
        str(skill_target_path(repo_root)),
    ]
    ensure_private_dir(log_path.parent)
    log_file = open_private_append(log_path, binary=True)
    kwargs: dict[str, Any] = {
        "cwd": str(Path.home()),
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": log_file,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "start_new_session": not is_windows_platform(),
    }
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        return {"status": "error", "mode": cleanup.get("mode"), "error": str(exc)}
    finally:
        log_file.close()
    return {
        "status": "scheduled",
        "mode": cleanup.get("mode"),
        "app_home": str(app_home),
        "repo_root": str(repo_root),
        "backup_dir": str(cleanup["backup_dir"]),
        "package": str(cleanup["package"]),
        "log": str(log_path),
        "pid": process.pid,
        "delay_seconds": delay,
    }


def schedule_control_ui_restart(
    codex_home: str | None,
    provider: str | None,
    host: str,
    port: int,
    delay: float = 0.1,
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
        "start_new_session": not is_windows_platform(),
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
        "reload_after_ms": 0,
        "reload_timeout_ms": 8000,
        "wait_for_disconnect": True,
    }


def restart_saved_control_ui(codex_home: str | None, provider: str | None, host: str = "127.0.0.1") -> dict[str, Any]:
    port = saved_control_ui_port(codex_home, host)
    if port is None:
        return {"status": "not_running", "reason": "no_saved_port"}
    ping = fetch_control_ui_ping(host, port)
    if not ping:
        return {"status": "not_running", "reason": "not_responding", "port": port}
    expected_owner = {
        "codex_home": normalized_control_path(paths_for(codex_home).codex_home),
        "provider": provider or None,
    }
    if not control_ui_identity_matches(ping, expected_owner):
        return {"status": "not_running", "reason": "identity_mismatch", "port": port}
    pid = ping.get("pid")
    if not isinstance(pid, int):
        return {"status": "not_running", "reason": "missing_pid", "port": port}

    restart = schedule_control_ui_restart(codex_home, provider, host, port)
    if restart.get("status") != "scheduled":
        return restart

    from .runtime_process import terminate_process

    restart["old_pid"] = pid
    try:
        terminate_process(pid)
        restart["terminated_old"] = True
    except OSError as exc:
        restart["terminated_old"] = False
        restart["terminate_error"] = str(exc)
    return restart


def find_existing_control_ui(
    host: str,
    port: int,
    *,
    identity: dict[str, str | None],
    attempts: int = PORT_SEARCH_ATTEMPTS,
    probe_timeout: float = 0.2,
) -> int | None:
    for candidate in range(port, port + attempts):
        if probe_control_ui(host, candidate, timeout=probe_timeout, fallback_status=False, identity=identity):
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
    data = fetch_control_ui_json(host, port, path, timeout)
    if data is None:
        return False
    if require_server_marker:
        return data.get("server") == CONTROL_UI_SERVER and control_ui_identity_matches(data, identity)
    return True


def fetch_control_ui_ping(host: str, port: int, timeout: float = 0.2) -> dict[str, Any] | None:
    data = fetch_control_ui_json(host, port, "/api/ping", timeout)
    if not data or data.get("server") != CONTROL_UI_SERVER:
        return None
    return data


def fetch_control_ui_json(host: str, port: int, path: str, timeout: float) -> dict[str, Any] | None:
    try:
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read()
            if response.status != 200:
                return None
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, dict) or data.get("status") != "ok":
                return None
            return data
        finally:
            connection.close()
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def control_ui_identity_matches(data: dict[str, Any], identity: dict[str, str | None] | None) -> bool:
    if identity is None:
        return True
    return all(data.get(key) == value for key, value in identity.items())


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
