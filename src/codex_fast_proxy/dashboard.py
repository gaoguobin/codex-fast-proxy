from __future__ import annotations

import json
import os
from collections import deque
from html import escape
from pathlib import Path
from typing import Any

from .core import safe_url_display

DASHBOARD_PATH = "/__codex_fast_proxy/dashboard"
DASHBOARD_EVENT_LIMIT = 8
DASHBOARD_EVENT_SCAN_LIMIT = 64
DASHBOARD_METADATA_LIMIT = 4
BENCHMARK_FILENAME = "fast_proxy.benchmark.json"
EVENT_DETAIL_FIELDS = (
    "ts",
    "request_id",
    "method",
    "path",
    "status",
    "ttfb_ms",
    "first_event_ms",
    "first_output_ms",
    "duration_ms",
    "eligible",
    "service_tier_before",
    "service_tier_after",
    "service_tier_injected",
    "service_tier_policy",
    "service_tier_effective_policy",
    "stream",
    "json_error",
    "response_content_type",
    "error_type",
)

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


def read_benchmark_result(log_path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads((log_path.parent / BENCHMARK_FILENAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def html_value(value: Any, default: str = "n/a") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "true" if value else "false"
    return escape(str(value), quote=True)


def status_code(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_response_event(event: dict[str, Any]) -> bool:
    return event.get("eligible") is True


def is_provider_metadata_event(event: dict[str, Any]) -> bool:
    return event.get("method") == "GET" and event.get("path") == "/v1/models"


def dashboard_diagnosis(last_response: dict[str, Any] | None) -> dict[str, str]:
    if not last_response:
        return {
            "level": "attention",
            "title": "Waiting for traffic",
            "message": "Send a Codex message to verify Responses API streaming.",
            "dot": "warn",
            "chip": "No responses",
        }

    status = status_code(last_response.get("status"))
    if status is not None and status >= 400:
        return {
            "level": "attention",
            "title": "Needs attention",
            "message": "Latest Responses API request returned an upstream or proxy error.",
            "dot": "warn",
            "chip": "Check recent event",
        }

    if last_response.get("stream") is True or last_response.get("response_content_type") == "text/event-stream":
        return {
            "level": "ready",
            "title": "Ready",
            "message": "Recent Responses API traffic is streaming through the local proxy.",
            "dot": "",
            "chip": "SSE passthrough",
        }

    return {
        "level": "attention",
        "title": "Check streaming",
        "message": "Recent Responses API traffic succeeded, but streaming metadata is unclear.",
        "dot": "warn",
        "chip": "Stream unclear",
    }


def render_dashboard(server: Any) -> str:
    events = read_recent_events(server.log_path, limit=DASHBOARD_EVENT_SCAN_LIMIT)
    benchmark = read_benchmark_result(server.log_path)
    response_events = [event for event in events if is_response_event(event)][-DASHBOARD_EVENT_LIMIT:]
    metadata_events = [event for event in events if is_provider_metadata_event(event)][-DASHBOARD_METADATA_LIMIT:]
    last_response = response_events[-1] if response_events else None
    success_count = sum(
        1
        for event in response_events
        if (code := status_code(event.get("status"))) is not None and code < 400
    )
    injected_count = sum(1 for event in response_events if event.get("service_tier_injected"))

    local_base = f"http://{server.server_address[0]}:{server.server_address[1]}{server.proxy_base}"
    upstream_base = safe_url_display(server.upstream_base)
    service_tier_policy = getattr(server, "service_tier_policy", "preserve")
    service_tier_effective_policy = getattr(server, "service_tier_effective_policy", service_tier_policy)
    service_tier = getattr(server, "service_tier", "priority")
    if service_tier_policy == "auto":
        policy_label = "App controlled" if service_tier_effective_policy == "preserve" else f"Auto {service_tier}"
    elif service_tier_policy == "preserve":
        policy_label = "Preserve only"
    else:
        policy_label = f"Global {service_tier}"
    last_injection = render_injection_state(last_response)
    last_status = last_response.get("status") if last_response else None
    last_duration = last_response.get("duration_ms") if last_response else None
    diagnosis = dashboard_diagnosis(last_response)

    event_rows = "\n".join(render_event_row(event) for event in reversed(response_events))
    if not event_rows:
        event_rows = '<tr><td class="empty" colspan="7">No response events yet.</td></tr>'

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
    .node-note {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
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
    .benchmark-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 1px;
      overflow: hidden;
      margin: 12px 16px 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--line);
    }}
    .benchmark-note {{
      padding: 0 16px 16px;
      color: var(--muted);
      font-size: 12px;
    }}
    .benchmark-empty {{
      padding: 18px 16px 16px;
      color: var(--muted);
      font-size: 13px;
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
      .hero, .details-grid, .benchmark-grid {{ grid-template-columns: 1fr; }}
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
            <p class="subtle">{html_value(diagnosis["message"])}</p>
            <h2>{html_value(diagnosis["title"])}</h2>
          </div>
          <div class="status-chip"><span class="dot {html_value(diagnosis["dot"])}" aria-hidden="true"></span>{html_value(diagnosis["chip"])}</div>
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
            <div class="node-note">{html_value(auth_label(server))}</div>
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
          <div class="metric-label">Fast policy</div>
          <div class="metric-value">{html_value(policy_label)}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Last inject</div>
          <div class="metric-value">{last_injection}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Recent ok</div>
          <div class="metric-value">{success_count}/{len(response_events)}</div>
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
        {render_status_badge(last_status, event_detail(last_response))}
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

    {render_metadata_section(metadata_events)}

    {render_benchmark_section(benchmark)}

    <section class="details-grid" aria-label="More information">
      <details open>
        <summary>Commands</summary>
        <div class="detail-body">
          <code>python -m codex_fast_proxy status</code>
          <code>python -m codex_fast_proxy start</code>
          <code>python -m codex_fast_proxy verify-upstream --upstream-base &lt;url&gt;</code>
          <code>python -m codex_fast_proxy set-upstream --clear-upstream-auth</code>
          <code>python -m codex_fast_proxy benchmark</code>
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


def auth_label(server: Any) -> str:
    if getattr(server, "upstream_api_key_source", None) == "provider_auth_file":
        return "Provider auth file override"
    env_name = getattr(server, "upstream_api_key_env", None)
    if isinstance(env_name, str) and env_name:
        return f"Provider env override: {env_name}"
    return "Codex provider header"


def event_detail(event: dict[str, Any] | None) -> str | None:
    if not event:
        return None

    lines = []
    for field in EVENT_DETAIL_FIELDS:
        value = event.get(field)
        if value is not None:
            lines.append(f"{field}: {value}")
    return "\n".join(lines) if lines else None


def render_status_badge(status: Any, detail: str | None = None) -> str:
    title = f' title="{html_value(detail, "")}"' if detail else ""
    if status is None:
        return f'<span class="badge"{title}><span class="dot warn" aria-hidden="true"></span>No events</span>'
    code = status_code(status)
    if code is None:
        return f'<span class="badge"{title}><span class="dot warn" aria-hidden="true"></span>{html_value(status)}</span>'

    dot_class = "bad" if code >= 400 else ""
    label = "Needs attention" if code >= 400 else "Healthy"
    return f'<span class="badge"{title}><span class="dot {dot_class}" aria-hidden="true"></span>{label}</span>'


def benchmark_fast_label(benchmark: dict[str, Any]) -> str:
    if benchmark.get("observed_priority_effective") is True:
        return "effective"
    if benchmark.get("priority_accepted") is True:
        return "accepted"
    if benchmark.get("provider_confirmed_priority") is True:
        return "confirmed"
    if benchmark.get("priority_accepted") is False:
        return "not accepted"
    return "unknown"


def render_benchmark_fast_badge(benchmark: dict[str, Any]) -> str:
    label = benchmark_fast_label(benchmark)
    if label in {"effective", "accepted", "confirmed"}:
        return f'<span class="badge"><span class="dot" aria-hidden="true"></span>{label}</span>'
    if label == "not accepted":
        return '<span class="badge"><span class="dot bad" aria-hidden="true"></span>not accepted</span>'
    return '<span class="badge muted"><span class="dot warn" aria-hidden="true"></span>unknown</span>'


def format_speedup(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return f"{float(value):.2f}x"
    except (TypeError, ValueError):
        return None


def benchmark_summary_value(benchmark: dict[str, Any], tier: str, key: str) -> Any:
    summary = benchmark.get(tier)
    if not isinstance(summary, dict):
        return None
    return summary.get(key)


def render_benchmark_section(benchmark: dict[str, Any] | None) -> str:
    if not benchmark:
        return """
    <section class="panel section" aria-label="Benchmark">
      <div class="section-head">
        <div>
          <h2>Benchmark</h2>
          <p>Provider Fast check</p>
        </div>
        <span class="badge muted">Not run</span>
      </div>
      <div class="benchmark-empty">
        <p>Run <code>python -m codex_fast_proxy benchmark</code> from Codex or a terminal to compare default vs priority latency with the full coding workload.</p>
      </div>
    </section>
"""

    provider = benchmark.get("provider")
    model = benchmark.get("model")
    profile = benchmark.get("profile", "full")
    mode = benchmark.get("benchmark_mode", "direct")
    pairs = benchmark.get("pairs")
    default_total = benchmark_summary_value(benchmark, "default", "median_total_ms")
    priority_total = benchmark_summary_value(benchmark, "priority", "median_total_ms")
    default_first_output = benchmark_summary_value(benchmark, "default", "median_first_output_ms")
    priority_first_output = benchmark_summary_value(benchmark, "priority", "median_first_output_ms")
    default_ok = benchmark_summary_value(benchmark, "default", "ok")
    priority_ok = benchmark_summary_value(benchmark, "priority", "ok")
    default_count = benchmark_summary_value(benchmark, "default", "count")
    priority_count = benchmark_summary_value(benchmark, "priority", "count")
    speedup = format_speedup(benchmark.get("observed_speedup_total"))
    ttfb_speedup = format_speedup(benchmark.get("observed_speedup_ttfb"))
    first_output_speedup = format_speedup(benchmark.get("observed_speedup_first_output"))
    sample_text = f"default {html_value(default_ok)}/{html_value(default_count)} / priority {html_value(priority_ok)}/{html_value(priority_count)}"
    return f"""
    <section class="panel section" aria-label="Benchmark">
      <div class="section-head">
        <div>
          <h2>Benchmark</h2>
          <p>provider {html_value(provider)} / model {html_value(model)} / mode {html_value(mode)} / profile {html_value(profile)} / pairs {html_value(pairs)}</p>
        </div>
        {render_benchmark_fast_badge(benchmark)}
      </div>
      <div class="benchmark-grid">
        <div class="metric">
          <div class="metric-label">Fast result</div>
          <div class="metric-value">{html_value(benchmark_fast_label(benchmark))}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Observed speedup</div>
          <div class="metric-value">{html_value(speedup)}</div>
        </div>
        <div class="metric">
          <div class="metric-label">First output</div>
          <div class="metric-value">{html_value(first_output_speedup)}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Priority total</div>
          <div class="metric-value">{html_value(format_duration(priority_total))}</div>
        </div>
      </div>
      <p class="benchmark-note">
        Last run {render_time_value(benchmark.get("ts"))} / samples {sample_text} / default total {html_value(format_duration(default_total))} / first output {html_value(format_duration(default_first_output))} -> {html_value(format_duration(priority_first_output))} / TTFB speedup {html_value(ttfb_speedup)}. Synthetic workload; not a guarantee.
      </p>
    </section>
"""


def render_metadata_section(events: list[dict[str, Any]]) -> str:
    if not events:
        return ""
    last_event = events[-1]
    rows = "\n".join(render_metadata_row(event) for event in reversed(events))
    return f"""
    <section class="panel section" aria-label="Provider metadata checks">
      <div class="section-head">
        <div>
          <h2>Provider metadata</h2>
          <p>GET /v1/models checks; no prompt or response input.</p>
        </div>
        {render_status_badge(last_event.get("status"), event_detail(last_event))}
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Route</th>
              <th>Status</th>
              <th>Latency</th>
            </tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
      </div>
    </section>
"""


def render_metadata_row(event: dict[str, Any]) -> str:
    status = event.get("status")
    return (
        "<tr>"
        f"<td>{render_time_value(event.get('ts'))}</td>"
        f"<td class=\"path\" title=\"{html_value(event.get('path'), '')}\">{html_value(event.get('method'))} {html_value(event.get('path'))}</td>"
        f"<td>{render_status_badge(status, event_detail(event))}</td>"
        f"<td>{html_value(format_duration(event.get('duration_ms')))}</td>"
        "</tr>"
    )


def render_event_row(event: dict[str, Any]) -> str:
    status = event.get("status")
    injected = event.get("service_tier_injected")
    stream = event.get("stream")
    return (
        "<tr>"
        f"<td>{render_time_value(event.get('ts'))}</td>"
        f"<td class=\"path\" title=\"{html_value(event.get('path'), '')}\">{html_value(event.get('method'))} {html_value(event.get('path'))}</td>"
        f"<td>{render_status_badge(status, event_detail(event))}</td>"
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
