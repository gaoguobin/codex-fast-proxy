from __future__ import annotations

import html
import http.client
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = 8786
CONTROL_TOKEN_HEADER = "X-Codex-Fast-Proxy-Token"
MAX_JSON_BODY_BYTES = 64 * 1024
RESERVED_PORTS = {8787}


class ControlServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], *, codex_home: str | None, provider: str | None, token: str) -> None:
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
        if self.path != "/api/actions/enable":
            self.respond_json({"status": "error", "error": "not_found"}, status=404)
            return
        try:
            self.read_json_body()
            from .actions import run_first_run_enable

            result = run_first_run_enable(self.server.codex_home, self.server.provider)
            self.respond_json({"status": "ok", "action": result, "snapshot": collect_snapshot(self.server)})
        except Exception as exc:
            self.respond_json({
                "status": "error",
                "error": str(exc),
                "snapshot": collect_snapshot(self.server),
            }, status=400)

    def write_allowed(self) -> bool:
        if self.headers.get(CONTROL_TOKEN_HEADER) != self.server.token:
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            return False
        return is_loopback_host(self.headers.get("Host", ""))

    def read_json_body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > MAX_JSON_BODY_BYTES:
            raise ValueError("Request body is too large.")
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

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


def render_page(snapshot: dict[str, Any], token: str) -> str:
    user_state = snapshot.get("user_state", {})
    title = str(user_state.get("title") or "需要处理")
    message = str(user_state.get("message") or "请打开诊断，或让 Codex 根据诊断结果修复。")
    primary_action = user_state.get("primary_action")
    primary_label = str(user_state.get("primary_label") or "刷新")
    button = (
        f'<button id="primary" data-action="{html.escape(str(primary_action))}">{html.escape(primary_label)}</button>'
        if primary_action in {"enable", "refresh"}
        else '<button id="primary" data-action="diagnostics">打开诊断</button>'
    )
    snapshot_json = html.escape(json.dumps(snapshot, ensure_ascii=False))
    token_json = json.dumps(token)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex 控制面板</title>
  <style>
    :root {{ color-scheme: light; font-family: "Segoe UI", system-ui, sans-serif; }}
    body {{ margin: 0; background: #f6f7f9; color: #17202a; }}
    main {{ max-width: 760px; margin: 0 auto; padding: 40px 20px; }}
    h1 {{ font-size: 28px; margin: 0 0 18px; }}
    .panel {{ background: white; border: 1px solid #d9dee7; border-radius: 8px; padding: 24px; }}
    .state {{ font-size: 34px; font-weight: 700; margin: 0 0 10px; }}
    .message {{ font-size: 16px; line-height: 1.6; color: #344054; margin: 0 0 24px; }}
    button {{ border: 0; border-radius: 8px; background: #1769aa; color: white; cursor: pointer; font-size: 16px; font-weight: 650; padding: 12px 22px; }}
    button:disabled {{ cursor: wait; opacity: .65; }}
    .note {{ margin-top: 18px; color: #5b6472; line-height: 1.55; }}
    details {{ margin-top: 24px; border-top: 1px solid #e5e8ef; padding-top: 18px; }}
    pre {{ background: #111827; border-radius: 8px; color: #e5e7eb; overflow: auto; padding: 16px; }}
  </style>
</head>
<body>
  <main>
    <h1>Codex 控制面板</h1>
    <section class="panel">
      <p id="state" class="state">{html.escape(title)}</p>
      <p id="message" class="message">{html.escape(message)}</p>
      {button}
      <p class="note">如果你是在 Codex 内置浏览器看到此页面，重启 Codex 前请用外部浏览器打开此页面，否则重启后页面会关闭。</p>
      <details>
        <summary>诊断</summary>
        <pre id="diagnostics">{snapshot_json}</pre>
      </details>
    </section>
  </main>
  <script>
    const token = {token_json};
    async function refresh() {{
      try {{
        const response = await fetch('/api/status');
        const data = await response.json();
        render(data.snapshot);
      }} catch (error) {{
        document.getElementById('state').textContent = '需要处理';
        document.getElementById('message').textContent = '刷新失败：' + (error && error.message ? error.message : error);
      }}
    }}
    function render(snapshot) {{
      const userState = snapshot.user_state || {{}};
      document.getElementById('state').textContent = userState.title || '需要处理';
      document.getElementById('message').textContent = userState.message || '请打开诊断，或让 Codex 根据诊断结果修复。';
      document.getElementById('diagnostics').textContent = JSON.stringify(snapshot, null, 2);
      const button = document.getElementById('primary');
      button.dataset.action = userState.primary_action || 'diagnostics';
      button.textContent = userState.primary_label || '打开诊断';
      button.disabled = false;
    }}
    async function enable(button) {{
      button.disabled = true;
      button.textContent = '正在准备环境...';
      try {{
        const response = await fetch('/api/actions/enable', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json', '{CONTROL_TOKEN_HEADER}': token }},
          body: '{{}}'
        }});
        const data = await response.json();
        if (data.status !== 'ok') {{
          document.getElementById('state').textContent = '需要处理';
          document.getElementById('message').textContent = data.error || '启用失败，请打开诊断。';
          button.disabled = false;
          button.textContent = '启用';
          return;
        }}
        render(data.snapshot);
      }} catch (error) {{
        document.getElementById('state').textContent = '需要处理';
        document.getElementById('message').textContent = '启用失败：' + (error && error.message ? error.message : error);
        button.disabled = false;
        button.textContent = '启用';
      }}
    }}
    document.getElementById('primary').addEventListener('click', async (event) => {{
      const action = event.currentTarget.dataset.action;
      if (action === 'enable') await enable(event.currentTarget);
      else if (action === 'refresh') await refresh();
      else document.querySelector('details').open = true;
    }});
  </script>
</body>
</html>"""


def serve_control_ui(codex_home: str | None, provider: str | None, host: str, port: int) -> int:
    server = ControlServer((host, port), ControlHandler, codex_home=codex_home, provider=provider, token=secrets.token_urlsafe(24))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    return 0


def open_control_ui(codex_home: str | None, provider: str | None, host: str, port: int, open_browser: bool) -> dict[str, Any]:
    selected_port = find_available_port(host, port)
    if selected_port is None:
        selected_port = port
        started = False
    else:
        started = start_background_server(codex_home, provider, host, selected_port)
        wait_for_status(host, selected_port)

    url = f"http://{host}:{selected_port}/"
    opened = bool(open_browser and webbrowser.open(url, new=2))
    return {
        "status": "opened" if opened else "ready",
        "url": url,
        "server_started": started,
        "opened_external_browser": opened,
        "open_instruction": None if opened else f"请在外部浏览器中打开：{url}",
        "fallback_message": None if opened else f"请在外部浏览器中打开：{url}",
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

    from .manager import paths_for

    paths = paths_for(codex_home)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = paths.state_dir / "control-ui.out"
    stderr_path = paths.state_dir / "control-ui.err"
    stdout = stdout_path.open("ab")
    stderr = stderr_path.open("ab")
    try:
        kwargs: dict[str, Any] = {"stdout": stdout, "stderr": stderr}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(command, **kwargs)
    finally:
        stdout.close()
        stderr.close()
    return True


def find_available_port(host: str, preferred: int) -> int | None:
    for port in range(preferred, preferred + 10):
        if port in RESERVED_PORTS:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    return None


def wait_for_status(host: str, port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            connection = http.client.HTTPConnection(host, port, timeout=0.5)
            try:
                connection.request("GET", "/api/status")
                response = connection.getresponse()
                response.read()
                if response.status == 200:
                    return
            finally:
                connection.close()
        except OSError:
            time.sleep(0.05)


def is_loopback_host(value: str) -> bool:
    host = value.split(":", 1)[0].strip("[]").lower()
    return host in {"127.0.0.1", "localhost", "::1"}
