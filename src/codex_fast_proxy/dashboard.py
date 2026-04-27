from __future__ import annotations

import json
import os
from collections import deque
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


DASHBOARD_PATH = "/__codex_fast_proxy/dashboard"
DASHBOARD_EVENT_LIMIT = 8


def safe_url_display(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return url

    netloc = parsed.netloc.rsplit("@", 1)[-1]
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme, netloc, path, "", ""))


def read_recent_events(log_path: Path, limit: int = DASHBOARD_EVENT_LIMIT) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    events: deque[dict[str, Any]] = deque(maxlen=limit)
    try:
        with log_path.open("r", encoding="utf-8") as log_file:
            for line in log_file:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
    except OSError:
        return []
    return list(events)


def html_value(value: Any, default: str = "n/a") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "true" if value else "false"
    return escape(str(value), quote=True)


def render_dashboard(server: Any) -> str:
    events = read_recent_events(server.log_path)
    last_response = next((event for event in reversed(events) if event.get("eligible")), None)
    latest_event = events[-1] if events else None
    success_count = sum(1 for event in events if int(event.get("status") or 0) < 400)
    injected_count = sum(1 for event in events if event.get("service_tier_injected"))

    local_base = f"http://{server.server_address[0]}:{server.server_address[1]}{server.proxy_base}"
    upstream_base = safe_url_display(server.upstream_base)
    last_injection = render_injection_state(last_response)
    last_status = latest_event.get("status") if latest_event else None
    last_duration = latest_event.get("duration_ms") if latest_event else None

    event_rows = "\n".join(render_event_row(event) for event in reversed(events))
    if not event_rows:
        event_rows = '<tr><td class="empty" colspan="7">No request events yet.</td></tr>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <link rel="icon" href="data:,">
  <title>Codex Fast Proxy</title>
  <style>
    :root {{
      --bg: #f7f7f4;
      --panel: #ffffff;
      --text: #111111;
      --muted: #686864;
      --line: #deded9;
      --soft: #f0f0ed;
      --soft-2: #fafaf8;
      --ok: #10a37f;
      --warn: #c77700;
      --bad: #c33b32;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }}
    a {{ color: inherit; text-decoration: none; }}
    main {{
      width: min(1120px, 100%);
      margin: 0 auto;
      padding: 28px 24px 48px;
    }}
    .topbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 44px;
      margin-bottom: 22px;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 11px;
      min-width: 0;
    }}
    .mark {{
      display: grid;
      place-items: center;
      width: 32px;
      height: 32px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      font-weight: 650;
    }}
    h1, h2, p {{ margin: 0; }}
    h1 {{
      font-size: 15px;
      line-height: 1.2;
      font-weight: 600;
      letter-spacing: 0;
    }}
    .subtle {{
      color: var(--muted);
      font-size: 13px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .actions {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 7px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--text);
      font-size: 13px;
      font-weight: 500;
    }}
    .button:hover {{ background: var(--soft-2); }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(280px, .85fr);
      gap: 12px;
      margin-bottom: 12px;
    }}
    .panel {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .status-panel {{
      padding: 22px;
      min-height: 220px;
    }}
    .headline {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 24px;
    }}
    .headline h2 {{
      font-size: 30px;
      line-height: 1.08;
      font-weight: 600;
      letter-spacing: 0;
    }}
    .status-chip, .badge {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 28px;
      padding: 4px 9px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--soft-2);
      color: var(--text);
      font-size: 12px;
      font-weight: 500;
      white-space: nowrap;
    }}
    .dot {{
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--ok);
    }}
    .dot.warn {{ background: var(--warn); }}
    .dot.bad {{ background: var(--bad); }}
    .badge.muted {{ color: var(--muted); }}
    .route {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 40px minmax(0, 1fr) 40px minmax(0, 1fr);
      align-items: stretch;
      gap: 8px;
    }}
    .node {{
      min-height: 104px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--soft-2);
    }}
    .node-label {{
      color: var(--muted);
      font-size: 12px;
    }}
    .node-value {{
      margin-top: 9px;
      font-size: 14px;
      font-weight: 560;
      overflow-wrap: anywhere;
    }}
    .connector {{
      position: relative;
      min-height: 104px;
    }}
    .connector::before {{
      content: "";
      position: absolute;
      top: 50%;
      left: 0;
      right: 0;
      height: 1px;
      background: var(--line);
    }}
    .connector::after {{
      content: "";
      position: absolute;
      top: calc(50% - 4px);
      right: 0;
      width: 8px;
      height: 8px;
      border-top: 1px solid var(--line);
      border-right: 1px solid var(--line);
      transform: rotate(45deg);
      background: var(--bg);
    }}
    .side-panel {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1px;
      overflow: hidden;
      background: var(--line);
    }}
    .metric {{
      min-height: 109px;
      padding: 16px;
      background: var(--panel);
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 12px;
    }}
    .metric-value {{
      margin-top: 10px;
      font-size: 22px;
      line-height: 1.15;
      font-weight: 600;
      letter-spacing: 0;
      overflow-wrap: anywhere;
    }}
    .section {{
      margin-top: 12px;
    }}
    .section-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 15px 16px 0;
    }}
    .section-head h2 {{
      font-size: 15px;
      line-height: 1.3;
      font-weight: 600;
      letter-spacing: 0;
    }}
    .section-head p {{
      color: var(--muted);
      font-size: 12px;
    }}
    .table-wrap {{
      overflow-x: auto;
      padding: 8px 16px 16px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }}
    th, td {{
      padding: 10px 8px;
      border-bottom: 1px solid var(--soft);
      text-align: left;
      vertical-align: middle;
      white-space: nowrap;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 500;
      letter-spacing: 0;
    }}
    td.path {{
      max-width: 240px;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    tr:hover td {{ background: var(--soft-2); }}
    tr:last-child td {{ border-bottom: 0; }}
    .empty {{
      color: var(--muted);
      text-align: center;
      white-space: normal;
    }}
    .details-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 12px;
    }}
    details {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    summary {{
      cursor: pointer;
      list-style: none;
      padding: 14px 16px;
      font-weight: 600;
    }}
    summary::-webkit-details-marker {{ display: none; }}
    summary::after {{
      content: "+";
      float: right;
      color: var(--muted);
      font-weight: 400;
    }}
    details[open] summary::after {{ content: "-"; }}
    .detail-body {{
      display: grid;
      gap: 8px;
      padding: 0 16px 16px;
      color: var(--muted);
      font-size: 13px;
    }}
    code {{
      display: block;
      min-height: 38px;
      padding: 9px 11px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--soft);
      color: var(--text);
      font-family: "Cascadia Mono", "SFMono-Regular", Consolas, monospace;
      font-size: 13px;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }}
    .local-time {{
      font-variant-numeric: tabular-nums;
    }}
    @media (max-width: 860px) {{
      main {{ padding: 20px 14px 36px; }}
      .topbar, .headline {{ display: block; }}
      .actions {{ justify-content: flex-start; margin-top: 14px; }}
      .hero, .details-grid {{ grid-template-columns: 1fr; }}
      .headline h2 {{ font-size: 26px; }}
      .status-chip {{ margin-top: 14px; }}
      .route {{ grid-template-columns: 1fr; }}
      .connector {{ min-height: 22px; }}
      .connector::before {{
        top: 0;
        bottom: 0;
        left: 18px;
        right: auto;
        width: 1px;
        height: auto;
      }}
      .connector::after {{
        top: auto;
        bottom: 0;
        left: 14px;
        right: auto;
        transform: rotate(135deg);
      }}
    }}
  </style>
</head>
<body>
  <main>
    <nav class="topbar" aria-label="Dashboard">
      <div class="brand">
        <div class="mark" aria-hidden="true">F</div>
        <div>
          <h1>Codex Fast Proxy</h1>
          <p class="subtle">{html_value(local_base)}</p>
        </div>
      </div>
      <div class="actions">
        <a class="button" href="{html_value(server.proxy_base)}">Refresh</a>
      </div>
    </nav>

    <section class="hero" aria-label="Proxy status">
      <div class="panel status-panel">
        <div class="headline">
          <div>
            <p class="subtle">Read-only local status</p>
            <h2>Proxy is running</h2>
          </div>
          <div class="status-chip"><span class="dot" aria-hidden="true"></span>SSE passthrough</div>
        </div>
        <div class="route" aria-label="Request route">
          <div class="node">
            <div class="node-label">Client</div>
            <div class="node-value">Codex App / CLI</div>
          </div>
          <div class="connector" aria-hidden="true"></div>
          <div class="node">
            <div class="node-label">Local proxy</div>
            <div class="node-value">{html_value(local_base)}</div>
          </div>
          <div class="connector" aria-hidden="true"></div>
          <div class="node">
            <div class="node-label">Upstream</div>
            <div class="node-value">{html_value(upstream_base)}</div>
          </div>
        </div>
      </div>

      <div class="panel side-panel" aria-label="Summary metrics">
        <div class="metric">
          <div class="metric-label">Tier</div>
          <div class="metric-value">{html_value(server.service_tier)}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Last inject</div>
          <div class="metric-value">{last_injection}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Recent ok</div>
          <div class="metric-value">{success_count}/{len(events)}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Last latency</div>
          <div class="metric-value">{html_value(format_duration(last_duration))}</div>
        </div>
      </div>
    </section>

    <section class="panel section" aria-label="Recent requests">
      <div class="section-head">
        <div>
          <h2>Recent requests</h2>
          <p>pid {html_value(os.getpid())} / injected {injected_count}</p>
        </div>
        {render_status_badge(last_status)}
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Route</th>
              <th>Status</th>
              <th>Latency</th>
              <th>Tier</th>
              <th>Inject</th>
              <th>Stream</th>
            </tr>
          </thead>
          <tbody>
            {event_rows}
          </tbody>
        </table>
      </div>
    </section>

    <section class="details-grid" aria-label="More information">
      <details open>
        <summary>Commands</summary>
        <div class="detail-body">
          <code>python -m codex_fast_proxy status</code>
          <code>python -m codex_fast_proxy install --start</code>
          <code>python -m codex_fast_proxy uninstall --defer-stop</code>
        </div>
      </details>
      <details open>
        <summary>Privacy</summary>
        <div class="detail-body">
          <p>No request bodies, prompts, headers, API keys, tokens, tool arguments, or response contents are displayed.</p>
          <p>The table is built from the existing redacted event log.</p>
        </div>
      </details>
    </section>
  </main>
  <script>
    (() => {{
      const pad = (value) => String(value).padStart(2, "0");
      const formatLocalTime = (date) => [
        date.getFullYear(),
        "-",
        pad(date.getMonth() + 1),
        "-",
        pad(date.getDate()),
        " ",
        pad(date.getHours()),
        ":",
        pad(date.getMinutes()),
        ":",
        pad(date.getSeconds()),
      ].join("");

      document.querySelectorAll("time.local-time[datetime]").forEach((node) => {{
        const value = node.getAttribute("datetime");
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {{
          return;
        }}
        node.textContent = formatLocalTime(date);
        node.title = `UTC ${{value}}`;
      }});
    }})();
  </script>
</body>
</html>
"""


def format_duration(value: Any) -> str | None:
    if value is None:
        return None
    return f"{value} ms"


def render_injection_state(event: dict[str, Any] | None) -> str:
    if not event:
        return "none"
    return "yes" if event.get("service_tier_injected") else "no"


def render_status_badge(status: Any) -> str:
    if status is None:
        return '<span class="badge"><span class="dot warn" aria-hidden="true"></span>No events</span>'
    try:
        status_code = int(status)
    except (TypeError, ValueError):
        return f'<span class="badge"><span class="dot warn" aria-hidden="true"></span>{html_value(status)}</span>'

    dot_class = "bad" if status_code >= 400 else ""
    label = "Needs attention" if status_code >= 400 else "Healthy"
    return f'<span class="badge"><span class="dot {dot_class}" aria-hidden="true"></span>{label}</span>'


def render_event_row(event: dict[str, Any]) -> str:
    status = event.get("status")
    injected = event.get("service_tier_injected")
    stream = event.get("stream")
    return (
        "<tr>"
        f"<td>{render_time_value(event.get('ts'))}</td>"
        f"<td class=\"path\" title=\"{html_value(event.get('path'), '')}\">{html_value(event.get('method'))} {html_value(event.get('path'))}</td>"
        f"<td>{render_status_badge(status)}</td>"
        f"<td>{html_value(format_duration(event.get('duration_ms')))}</td>"
        f"<td>{render_tier_change(event)}</td>"
        f"<td>{render_boolean_badge(injected)}</td>"
        f"<td>{render_boolean_badge(stream)}</td>"
        "</tr>"
    )


def render_time_value(value: Any) -> str:
    if value is None:
        return "n/a"
    text = html_value(value)
    return f'<time class="local-time" datetime="{text}" title="UTC {text}">{text}</time>'


def render_tier_change(event: dict[str, Any]) -> str:
    before = event.get("service_tier_before")
    after = event.get("service_tier_after")
    if before is None and after is None:
        return '<span class="badge muted">n/a</span>'
    return f"{html_value(before)} -> {html_value(after)}"


def render_boolean_badge(value: Any) -> str:
    if value is True:
        return '<span class="badge"><span class="dot" aria-hidden="true"></span>yes</span>'
    if value is False:
        return '<span class="badge muted">no</span>'
    return '<span class="badge muted">n/a</span>'
