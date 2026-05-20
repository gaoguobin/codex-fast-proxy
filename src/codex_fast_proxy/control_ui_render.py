from __future__ import annotations

import html
import json
from typing import Any


CONTROL_TOKEN_HEADER = "X-Codex-Fast-Proxy-Token"


def speed_mode_from_snapshot(snapshot: dict[str, Any]) -> str:
    return "standard" if snapshot.get("service_tier_policy") == "preserve" else "fast"


def speed_mode_label(snapshot: dict[str, Any]) -> str:
    return "标准" if speed_mode_from_snapshot(snapshot) == "standard" else "快速"


def provider_status(snapshot: dict[str, Any]) -> tuple[str, str]:
    if snapshot.get("config_matches") and snapshot.get("healthy") and not snapshot.get("needs_restart"):
        return "运行中", "ok"
    if snapshot.get("config_matches") and snapshot.get("needs_restart"):
        return "待重启", "warn"
    if snapshot.get("config_matches"):
        return "需处理", "warn"
    if snapshot.get("base_url") and not snapshot.get("config_matches"):
        return "已恢复", "idle"
    if snapshot.get("base_url"):
        return "未接管", "idle"
    return "未启用", "idle"


def display_text(value: Any, fallback: str = "未配置") -> str:
    return str(value) if isinstance(value, str) and value else fallback


def boolean_label(value: Any) -> str:
    return "是" if value else "否"


def proxy_route_label(snapshot: dict[str, Any]) -> str:
    if snapshot.get("config_matches") and snapshot.get("healthy") and not snapshot.get("needs_restart"):
        return "正在通过本地代理"
    if snapshot.get("config_matches") and snapshot.get("needs_restart"):
        return "已指向本地代理，等待重启"
    if snapshot.get("base_url"):
        return "已停用或未接管"
    return "未启用"


def fast_behavior_label(snapshot: dict[str, Any]) -> str:
    behavior = snapshot.get("fast_behavior")
    if behavior == "app_controlled":
        return "由 Codex App 控制"
    if behavior == "inject_missing":
        return "快速模式"
    if behavior == "preserve":
        return "标准模式"
    return "未启用"


def provider_key_label(value: Any) -> str:
    if value == "saved":
        return "已保存"
    if isinstance(value, str) and value.startswith("process_env:"):
        return f"环境变量 {value.split(':', 1)[1]}"
    if isinstance(value, str) and value.startswith("windows_user_env:"):
        return f"环境变量 {value.split(':', 1)[1]}"
    if isinstance(value, str) and value.startswith("auth_json:"):
        return f"Codex 已保存 {value.split(':', 1)[1]}"
    return "未保存"


def providers_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("providers")
    providers = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    if providers:
        return providers
    provider = snapshot.get("provider")
    upstream = snapshot.get("upstream_base") or snapshot.get("config_base_url")
    if (isinstance(provider, str) and provider) or upstream or snapshot.get("base_url"):
        return [{
            "name": provider if isinstance(provider, str) and provider else "当前 Provider",
            "base_url": upstream,
            "current": True,
            "active": True,
            "proxy_enabled": bool(snapshot.get("config_matches")),
            "api_key": "saved" if snapshot.get("upstream_api_key_file") else "missing",
        }]
    return []


def status_code(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compact_url(value: Any, fallback: str = "未启用") -> str:
    if not isinstance(value, str) or not value:
        return fallback
    return value.replace("https://", "").replace("http://", "")


def short_login_label(snapshot: dict[str, Any]) -> str:
    if snapshot.get("chatgpt_auth"):
        return "ChatGPT"
    if snapshot.get("api_key_auth"):
        return "API Key"
    return "未知"


def short_proxy_label(snapshot: dict[str, Any]) -> str:
    if snapshot.get("config_matches") and snapshot.get("healthy") and not snapshot.get("needs_restart"):
        return "已接管"
    if snapshot.get("config_matches") and snapshot.get("needs_restart"):
        return "待重启"
    if snapshot.get("base_url"):
        return "未接管"
    return "未启用"


def short_speed_label(snapshot: dict[str, Any]) -> str:
    behavior = snapshot.get("fast_behavior")
    if behavior == "app_controlled":
        return "App 控制"
    if behavior == "inject_missing":
        return "快速"
    if behavior == "preserve":
        return "标准"
    return "未启用"


def format_duration(value: Any) -> str:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{duration / 1000:.3f}s"


def format_optional_duration(value: Any) -> str:
    rendered = format_duration(value)
    return "N/A" if rendered == "-" else rendered


def request_ttft_value(event: dict[str, Any]) -> Any:
    return event.get("ttft_ms", event.get("first_output_ms"))


def render_time_value(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "n/a"
    text = html.escape(value)
    return f'<time class="local-time" datetime="{text}" title="UTC {text}">{text}</time>'


def request_status_label(event: dict[str, Any] | None) -> tuple[str, str]:
    if not event:
        return "No events", "idle"
    code = status_code(event.get("status"))
    if code is None:
        return display_text(event.get("status"), "未知"), "warn"
    if code >= 400:
        return "Needs attention", "warn"
    return "Healthy", "ok"


def request_speed_label(event: dict[str, Any]) -> str:
    effective_policy = event.get("service_tier_effective_policy")
    if effective_policy == "preserve":
        return "App 控制"
    if effective_policy == "inject_missing":
        return "代理加速"
    return display_text(effective_policy, "未记录")


def render_status_metric(label: str, value: str, tone: str = "idle") -> str:
    return f"""
            <div class="status-metric">
              <span>{html.escape(label)}</span>
              <strong>{html.escape(value)}</strong>
              <i class="metric-mark {html.escape(tone)}" aria-hidden="true"></i>
            </div>
"""


def render_recent_events(snapshot: dict[str, Any]) -> str:
    raw = snapshot.get("recent_response_events")
    events = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    if not events:
        return '<p class="empty-state">还没有请求记录。</p>'
    rows: list[str] = []
    for event in reversed(events):
        status, tone = request_status_label(event)
        method = display_text(event.get("method"), "POST")
        path = display_text(event.get("path"), "n/a")
        rows.append(f"""
            <tr>
              <td class="time-cell">{render_time_value(event.get("ts"))}</td>
              <td class="request-route" title="{html.escape(method)} {html.escape(path)}">{html.escape(method)} {html.escape(path)}</td>
              <td><span class="status-pill {tone}">{html.escape(status)}</span></td>
              <td class="number-cell" title="Time to first byte: first response bytes or first SSE event.">{html.escape(format_duration(event.get("ttfb_ms", event.get("first_event_ms"))))}</td>
              <td class="number-cell" title="Time to first token: first visible output_text delta. N/A for requests without text output.">{html.escape(format_optional_duration(request_ttft_value(event)))}</td>
              <td class="number-cell">{html.escape(format_duration(event.get("duration_ms")))}</td>
              <td>{html.escape(request_speed_label(event))}</td>
            </tr>
""")
    return f"""
        <div class="request-table-wrap">
          <table class="request-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>请求</th>
                <th>状态</th>
                <th title="Time to first byte">TTFB</th>
                <th title="Time to first token">TTFT</th>
                <th title="End-to-end latency">E2E</th>
                <th>速度模式</th>
              </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>
"""


def render_status_panel(snapshot: dict[str, Any]) -> str:
    chatgpt_login = bool(snapshot.get("chatgpt_auth"))
    proxy_status = proxy_route_label(snapshot)
    auth_text = "ChatGPT 账户登录" if chatgpt_login else "API Key / 第三方登录"
    recent_events = snapshot.get("recent_response_events")
    last_event = recent_events[-1] if isinstance(recent_events, list) and recent_events else None
    last_status, last_status_tone = request_status_label(last_event if isinstance(last_event, dict) else None)
    provider = display_text(snapshot.get("provider"), "未选择")
    base_url = compact_url(snapshot.get("base_url"), "未启用")
    upstream = compact_url(snapshot.get("upstream_base"), "未配置")
    return f"""
      <details id="statusPanel" class="maintenance-panel">
        <summary>
          <span class="summary-copy">
            <span class="muted">状态</span>
            <strong>{html.escape(proxy_status)}</strong>
            <span>{html.escape(auth_text)}</span>
          </span>
          <span class="summary-action">查看</span>
        </summary>
        <div class="maintenance-body">
          <div class="status-dashboard">
            <div class="route-map" aria-label="请求链路">
              <div class="route-node">
                <span>Codex</span>
                <strong>{html.escape(short_login_label(snapshot))}</strong>
                <small>{html.escape(auth_text)}</small>
              </div>
              <div class="route-connector" aria-hidden="true"></div>
              <div class="route-node proxy-node">
                <span>本地代理</span>
                <strong>{html.escape(short_proxy_label(snapshot))}</strong>
                <small>{html.escape(base_url)}</small>
              </div>
              <div class="route-connector" aria-hidden="true"></div>
              <div class="route-node">
                <span>上游服务</span>
                <strong>{html.escape(provider)}</strong>
                <small>{html.escape(upstream)}</small>
              </div>
            </div>
            <div class="status-metrics">
              {render_status_metric("代理", short_proxy_label(snapshot), "ok" if snapshot.get("config_matches") else "idle")}
              {render_status_metric("登录", short_login_label(snapshot), "ok" if chatgpt_login else "idle")}
              {render_status_metric("速度", short_speed_label(snapshot))}
              {render_status_metric("最近请求", last_status, last_status_tone)}
            </div>
          </div>
          <h2 class="subsection-title">最近请求</h2>
          {render_recent_events(snapshot)}
        </div>
      </details>
"""


def render_provider_cards(providers: list[dict[str, Any]], selected_provider: str) -> str:
    cards: list[str] = []
    for item in providers:
        name = str(item.get("name") or "未命名")
        name_attr = html.escape(name, quote=True)
        is_current = bool(item.get("current")) or name == selected_provider
        card_class = "provider-card current" if is_current else "provider-card"
        status_label = "使用中" if is_current else "已配置"
        status_class = "ok" if is_current else "idle"
        enable_button = "" if is_current else (
            f'<button class="provider-enable" type="button" data-provider-action="switch" '
            f'data-provider="{name_attr}">启用</button>'
        )
        cards.append(f"""
            <article class="{card_class}" data-provider-name="{name_attr}">
              <div class="provider-main">
                <span class="provider-avatar">{html.escape((name[:1] or "?").upper())}</span>
                <div class="provider-info">
                  <strong>{html.escape(name)}</strong>
                  <span class="provider-url">{html.escape(display_text(item.get("base_url"), "未设置模型服务"))}</span>
                  <span class="provider-auth-state">密钥：{html.escape(provider_key_label(item.get("api_key")))}</span>
                </div>
              </div>
              <div class="provider-card-actions">
                <span class="status-pill {status_class}">{status_label}</span>
                {enable_button}
                <button class="provider-edit" type="button" data-provider-action="edit" data-provider="{name_attr}">编辑供应商</button>
              </div>
            </article>
""")
    return "".join(cards)


def render_page(snapshot: dict[str, Any], token: str) -> str:
    user_state = snapshot.get("user_state", {})
    state_code = str(user_state.get("code") or "")
    title = str(user_state.get("title") or "需要处理")
    message = str(user_state.get("message") or "请打开诊断，或让 Codex 根据诊断结果修复。")
    primary_action = user_state.get("primary_action")
    primary_label = str(user_state.get("primary_label") or "刷新")
    button = (
        f'<button id="primary" data-action="{html.escape(str(primary_action))}">{html.escape(primary_label)}</button>'
        if primary_action in {"enable", "refresh", "uninstall"}
        else '<button id="primary" class="secondary" data-action="diagnostics">打开诊断</button>'
    )
    labels: dict[str, str] = {}
    terminal_state = state_code in {"cleanup_pending", "uninstalled_deferred", "uninstalled"}
    show_runtime_controls = bool(snapshot.get("base_url")) and not terminal_state
    action_buttons = ""
    danger_zone = ""
    labels["update"] = "更新"
    if show_runtime_controls:
        labels.update({
            "uninstall": "停用并恢复",
            "confirmUninstall": "我知道可能导致模型请求失败，仍要停用",
        })
        if primary_action != "uninstall":
            action_buttons = '<button id="uninstall" class="warn" data-action="uninstall">停用并恢复</button>'
        danger_zone = """
      <div id="dangerZone" class="danger-zone" style="display:none">
        <p>仍要继续停用只适合你已经理解风险的情况。继续后，当前 ChatGPT 登录可能无法直接使用第三方模型服务。</p>
        <button id="confirmUninstall" class="warn" data-action="confirm-uninstall">我知道可能导致模型请求失败，仍要停用</button>
      </div>
"""
    elif state_code == "cleanup_pending":
        labels["finishCleanup"] = "完成清理"
        action_buttons = '<button id="finishCleanup" class="warn" data-action="uninstall">完成清理</button>'

    providers = providers_from_snapshot(snapshot)
    selected_provider = str(snapshot.get("current_provider") or snapshot.get("provider") or "")
    selected_record = next((item for item in providers if item.get("name") == selected_provider), providers[0] if providers else {})
    provider_name_value = html.escape(str(selected_record.get("name") or selected_provider), quote=True)
    provider_url_value = html.escape(str(selected_record.get("base_url") or ""), quote=True)
    provider_management = ""
    if providers and not terminal_state:
        summary_name = html.escape(str(selected_record.get("name") or selected_provider or "未选择"))
        summary_url = html.escape(display_text(selected_record.get("base_url"), "未设置模型服务"))
        labels.update({
            "saveProvider": "保存供应商",
        })
        selected_provider_name = str(selected_record.get("name") or selected_provider or "")
        provider_management = f"""
      <details id="providerPanel" class="maintenance-panel">
        <summary>
          <span class="summary-copy">
            <span class="muted">供应商管理</span>
            <strong id="providerSummaryName">{summary_name}</strong>
            <span id="providerSummaryUrl">{summary_url}</span>
          </span>
          <span class="summary-action">管理</span>
        </summary>
        <div class="maintenance-body">
          <div class="provider-panel-header">
            <div>
              <h2>供应商管理</h2>
              <div class="provider-tabs" aria-label="应用">
                <span class="provider-tab active">Codex</span>
              </div>
            </div>
            <button id="newProvider" type="button">添加供应商</button>
          </div>
          <div id="providerList" class="provider-list">
            {render_provider_cards(providers, selected_provider_name)}
          </div>
          <div id="providerEditor" class="provider-editor" hidden>
            <div class="provider-editor-title">
              <h3 id="providerEditorTitle">编辑供应商</h3>
              <button id="cancelProvider" class="provider-edit" type="button">取消</button>
            </div>
            <form id="providerForm" class="provider-form">
              <label>供应商名称
                <input id="providerNameInput" autocomplete="off" value="{provider_name_value}" placeholder="my-provider" required>
              </label>
              <label>模型服务地址
                <input id="upstreamBase" autocomplete="off" value="{provider_url_value}" placeholder="https://api.example.com/v1" required>
              </label>
              <label>API Key
                <input id="apiKey" type="password" autocomplete="off" placeholder="留空则不修改已保存的 key">
              </label>
              <div class="actions compact">
                <button id="saveProvider" type="submit">保存供应商</button>
              </div>
            </form>
          </div>
        </div>
      </details>
"""

    speed_controls = ""
    if providers and not terminal_state and not snapshot.get("chatgpt_auth"):
        status_label, status_class = provider_status(snapshot)
        speed_label = html.escape(speed_mode_label(snapshot))
        speed_mode = speed_mode_from_snapshot(snapshot)
        fast_checked = " checked" if speed_mode == "fast" else ""
        standard_checked = " checked" if speed_mode == "standard" else ""
        labels["saveSpeed"] = "保存速度模式"
        disabled_speed = "" if show_runtime_controls else " disabled"
        speed_controls = f"""
      <details id="speedPanel" class="maintenance-panel">
        <summary>
          <span class="summary-copy">
            <span class="muted">速度模式</span>
            <strong id="providerSpeed">{speed_label}</strong>
            <span>当前策略</span>
          </span>
          <span id="providerStatus" class="status-pill {status_class}">{html.escape(status_label)}</span>
        </summary>
        <div class="maintenance-body">
          <form id="speedForm" class="provider-form">
            <fieldset>
              <div class="segments">
                <label><input type="radio" name="speedMode" value="fast"{fast_checked}>快速</label>
                <label><input type="radio" name="speedMode" value="standard"{standard_checked}>标准</label>
              </div>
            </fieldset>
            <button id="saveSpeed" type="submit"{disabled_speed}>保存速度模式</button>
          </form>
        </div>
      </details>
"""
    snapshot_json = html.escape(json.dumps(snapshot, ensure_ascii=False))
    token_json = json.dumps(token)
    labels_json = json.dumps(labels, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex 控制面板</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f4;
      --surface: #ffffff;
      --surface-soft: #f2f2ee;
      --border: #deded7;
      --border-strong: #c9c9c1;
      --text: #111111;
      --muted: #5f5f58;
      --muted-strong: #3f3f3a;
      --green: #10a37f;
      --green-soft: #e7f6f1;
      --amber: #8a5a12;
      --amber-soft: #f6ead6;
      --red: #8f3a2e;
      --red-soft: #f5e7e3;
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-size: 15px;
    }}
    main {{
      margin: 0 auto;
      max-width: 880px;
      padding: 32px 22px 42px;
    }}
    .topbar {{
      align-items: center;
      display: flex;
      gap: 16px;
      justify-content: space-between;
      margin-bottom: 16px;
    }}
    .topbar h1 {{
      margin: 0;
    }}
    .topbar-actions {{
      display: flex;
      flex: 0 0 auto;
      gap: 8px;
    }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 28px;
    }}
    h1 {{
      color: var(--muted);
      font-size: 15px;
      font-weight: 600;
      margin: 0 0 18px;
    }}
    h2 {{
      border-top: 1px solid var(--border);
      font-size: 17px;
      font-weight: 600;
      margin: 28px 0 14px;
      padding-top: 24px;
    }}
    .state {{
      color: var(--text);
      font-size: 34px;
      font-weight: 560;
      line-height: 1.12;
      margin: 0 0 12px;
    }}
    .message, .note {{
      color: var(--muted-strong);
      line-height: 1.65;
      margin: 0;
    }}
    .note {{
      border-top: 1px solid var(--border);
      margin-top: 28px;
      padding-top: 18px;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 22px;
    }}
    button {{
      align-items: center;
      background: var(--text);
      border: 1px solid var(--text);
      border-radius: 999px;
      color: #ffffff;
      cursor: pointer;
      display: inline-flex;
      font-size: 14px;
      font-weight: 600;
      justify-content: center;
      line-height: 1.2;
      min-height: 40px;
      padding: 10px 16px;
      transition: background .16s ease, border-color .16s ease, color .16s ease, opacity .16s ease;
    }}
    button:hover:not(:disabled) {{ background: #2c2c2c; border-color: #2c2c2c; }}
    button.secondary, .provider-card-actions .provider-edit, #cancelProvider, #saveSpeed {{
      background: var(--surface);
      border-color: var(--border-strong);
      color: var(--text);
    }}
    button.secondary:hover:not(:disabled),
    .provider-card-actions .provider-edit:hover:not(:disabled),
    #cancelProvider:hover:not(:disabled),
    #saveSpeed:hover:not(:disabled) {{
      background: var(--surface-soft);
      border-color: var(--text);
      color: var(--text);
    }}
    button.warn {{
      background: var(--red);
      border-color: var(--red);
      color: #ffffff;
    }}
    button.warn:hover:not(:disabled) {{ background: #743126; border-color: #743126; }}
    button:disabled {{
      cursor: wait;
      opacity: .58;
    }}
    button:focus-visible, input:focus-visible, summary:focus-visible {{
      outline: 2px solid var(--green);
      outline-offset: 2px;
    }}
    .danger-zone {{
      background: var(--red-soft);
      border: 1px solid #e7c7bf;
      border-radius: 10px;
      margin-top: 18px;
      padding: 16px;
    }}
    .danger-zone p {{
      color: #5f2219;
      line-height: 1.6;
      margin: 0 0 12px;
    }}
    .maintenance-panel {{
      border-top: 1px solid var(--border);
      margin-top: 28px;
      padding-top: 2px;
    }}
    .maintenance-panel summary {{
      align-items: center;
      cursor: pointer;
      display: flex;
      gap: 14px;
      justify-content: space-between;
      list-style: none;
      padding: 17px 0;
    }}
    .maintenance-panel summary::-webkit-details-marker {{ display: none; }}
    .summary-copy {{
      display: grid;
      gap: 4px;
      min-width: 0;
    }}
    .summary-copy strong {{
      color: var(--text);
      font-size: 16px;
      font-weight: 600;
    }}
    .summary-copy span:last-child {{
      color: var(--muted);
      font-size: 14px;
      overflow-wrap: anywhere;
    }}
    .summary-action {{
      background: var(--surface);
      border: 1px solid var(--border-strong);
      border-radius: 999px;
      color: var(--text);
      flex: 0 0 auto;
      font-size: 13px;
      font-weight: 600;
      padding: 7px 12px;
    }}
    .maintenance-body {{
      border-top: 1px solid var(--border);
      padding-top: 18px;
    }}
    .provider-panel-header {{
      align-items: flex-start;
      display: flex;
      gap: 14px;
      justify-content: space-between;
      margin-bottom: 16px;
    }}
    .provider-panel-header h2 {{
      border: 0;
      margin: 0;
      padding: 0;
    }}
    .provider-tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 9px;
    }}
    .provider-tab {{
      background: var(--surface-soft);
      border: 1px solid transparent;
      border-radius: 999px;
      color: var(--muted-strong);
      font-size: 13px;
      font-weight: 600;
      padding: 6px 11px;
    }}
    .provider-tab.active {{
      background: var(--text);
      border-color: var(--text);
      color: #ffffff;
    }}
    .provider-list {{
      display: grid;
      gap: 10px;
    }}
    .provider-card {{
      align-items: flex-start;
      background: transparent;
      border: 1px solid var(--border);
      border-radius: 10px;
      display: flex;
      gap: 14px;
      justify-content: space-between;
      padding: 14px;
    }}
    .provider-card.current {{
      background: var(--green-soft);
      border-color: rgba(16, 163, 127, .28);
    }}
    .provider-main {{
      display: flex;
      gap: 12px;
      min-width: 0;
    }}
    .provider-avatar {{
      align-items: center;
      background: var(--text);
      border-radius: 50%;
      color: #ffffff;
      display: inline-flex;
      flex: 0 0 auto;
      font-size: 14px;
      font-weight: 600;
      height: 34px;
      justify-content: center;
      width: 34px;
    }}
    .provider-info {{
      display: grid;
      gap: 4px;
      min-width: 0;
    }}
    .provider-info strong {{
      font-size: 15px;
      font-weight: 600;
    }}
    .provider-url, .provider-auth-state {{
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
    }}
    .provider-card-actions {{
      align-items: center;
      display: flex;
      flex: 0 0 auto;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }}
    .provider-card-actions button {{
      min-height: 34px;
      padding: 7px 12px;
    }}
    .provider-editor {{
      border-top: 1px solid var(--border);
      margin-top: 18px;
      padding-top: 18px;
    }}
    .provider-editor-title {{
      align-items: center;
      display: flex;
      gap: 10px;
      justify-content: space-between;
      margin-bottom: 12px;
    }}
    .provider-editor-title h3 {{
      font-size: 15px;
      font-weight: 600;
      margin: 0;
    }}
    .muted {{
      color: var(--muted);
      font-size: 13px;
    }}
    .status-pill {{
      border: 1px solid transparent;
      border-radius: 999px;
      display: inline-flex;
      font-size: 13px;
      font-weight: 600;
      padding: 5px 10px;
      white-space: nowrap;
    }}
    .status-pill.ok {{
      background: var(--green-soft);
      border-color: rgba(16, 163, 127, .24);
      color: #08745d;
    }}
    .status-pill.warn {{
      background: var(--amber-soft);
      border-color: rgba(138, 90, 18, .2);
      color: var(--amber);
    }}
    .status-pill.idle {{
      background: var(--surface-soft);
      border-color: var(--border);
      color: var(--muted-strong);
    }}
    .status-dashboard {{
      display: grid;
      gap: 14px;
    }}
    .route-map {{
      display: grid;
      gap: 8px;
      grid-template-columns: minmax(0, 1fr) 32px minmax(0, 1fr) 32px minmax(0, 1fr);
    }}
    .route-node {{
      border: 1px solid var(--border);
      border-radius: 10px;
      display: grid;
      gap: 5px;
      min-width: 0;
      padding: 14px;
    }}
    .route-node span {{
      color: var(--muted);
      font-size: 13px;
    }}
    .route-node strong {{
      display: block;
      font-size: 16px;
      font-weight: 600;
      overflow-wrap: anywhere;
    }}
    .route-node small {{
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .proxy-node {{
      background: var(--green-soft);
      border-color: rgba(16, 163, 127, .26);
    }}
    .route-connector {{
      min-height: 84px;
      position: relative;
    }}
    .route-connector::before {{
      background: var(--border-strong);
      content: "";
      height: 1px;
      left: 0;
      position: absolute;
      right: 0;
      top: 50%;
    }}
    .route-connector::after {{
      border-right: 1px solid var(--border-strong);
      border-top: 1px solid var(--border-strong);
      content: "";
      height: 8px;
      position: absolute;
      right: 0;
      top: calc(50% - 4px);
      transform: rotate(45deg);
      width: 8px;
    }}
    .status-metrics {{
      display: grid;
      gap: 1px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--border);
    }}
    .status-metric {{
      background: var(--surface);
      display: grid;
      gap: 6px;
      min-width: 0;
      padding: 13px;
      position: relative;
    }}
    .status-metric span {{
      color: var(--muted);
      font-size: 13px;
    }}
    .status-metric strong {{
      color: var(--text);
      font-size: 16px;
      font-weight: 600;
      overflow-wrap: anywhere;
    }}
    .metric-mark {{
      background: var(--border-strong);
      border-radius: 999px;
      height: 7px;
      position: absolute;
      right: 13px;
      top: 15px;
      width: 7px;
    }}
    .metric-mark.ok {{ background: var(--green); }}
    .metric-mark.warn {{ background: var(--amber); }}
    form {{
      display: grid;
      gap: 12px;
      margin-top: 14px;
    }}
    form button {{
      justify-self: start;
    }}
    label {{
      color: var(--muted-strong);
      display: grid;
      font-size: 14px;
      gap: 7px;
    }}
    input, select {{
      background: var(--surface);
      border: 1px solid var(--border-strong);
      border-radius: 10px;
      color: var(--text);
      font-size: 15px;
      min-height: 42px;
      padding: 10px 12px;
    }}
    input[type="radio"] {{
      accent-color: var(--green);
      min-height: auto;
    }}
    fieldset {{
      border: 0;
      margin: 0;
      padding: 0;
    }}
    legend {{
      color: var(--muted-strong);
      font-size: 14px;
      margin-bottom: 6px;
    }}
    .actions.compact {{ margin-top: 4px; }}
    .segments {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .segments label {{
      align-items: center;
      border: 1px solid var(--border-strong);
      border-radius: 10px;
      cursor: pointer;
      display: flex;
      flex: 1 1 140px;
      gap: 9px;
      min-height: 42px;
      padding: 10px 12px;
    }}
    .segments label:has(input:checked) {{
      background: var(--green-soft);
      border-color: rgba(16, 163, 127, .36);
      color: #075f4d;
    }}
    .segments input {{
      margin: 0;
      padding: 0;
    }}
    .subsection-title {{
      border-top: 1px solid var(--border);
      font-size: 15px;
      margin: 18px 0 10px;
      padding-top: 16px;
    }}
    .empty-state {{
      color: var(--muted);
      line-height: 1.6;
      margin: 0;
    }}
    .request-table-wrap {{
      overflow-x: hidden;
    }}
    .request-table {{
      border-collapse: collapse;
      font-size: 13px;
      table-layout: fixed;
      width: 100%;
    }}
    .request-table th,
    .request-table td {{
      border-bottom: 1px solid var(--surface-soft);
      padding: 10px 6px;
      text-align: left;
      vertical-align: middle;
      white-space: nowrap;
    }}
    .request-table th {{
      color: var(--muted);
      font-weight: 600;
    }}
    .request-table tr:last-child td {{
      border-bottom: 0;
    }}
    .request-table th:nth-child(1), .request-table td:nth-child(1) {{ width: 148px; }}
    .request-table th:nth-child(2), .request-table td:nth-child(2) {{ width: 144px; }}
    .request-table th:nth-child(3), .request-table td:nth-child(3) {{ width: 100px; }}
    .request-table th:nth-child(4), .request-table td:nth-child(4),
    .request-table th:nth-child(5), .request-table td:nth-child(5),
    .request-table th:nth-child(6), .request-table td:nth-child(6) {{ width: 82px; }}
    .request-table th:nth-child(7), .request-table td:nth-child(7) {{ width: 76px; }}
    .request-route {{
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .number-cell {{ color: var(--text); }}
    .local-time {{
      color: var(--muted-strong);
      white-space: nowrap;
    }}
    details {{
      margin-top: 24px;
      border-top: 1px solid var(--border);
      padding-top: 18px;
    }}
    pre {{
      background: #171717;
      border-radius: 10px;
      color: #eeeeee;
      font-size: 13px;
      line-height: 1.5;
      overflow: auto;
      padding: 16px;
    }}
    @media (max-width: 640px) {{
      main {{ padding: 22px 14px 32px; }}
      .panel {{ border-radius: 10px; padding: 20px; }}
      .state {{ font-size: 28px; }}
      .provider-panel-header, .provider-card {{ flex-direction: column; }}
      .provider-card-actions {{ justify-content: flex-start; }}
      button {{ width: 100%; }}
      .topbar {{ align-items: stretch; flex-direction: column; }}
      .topbar-actions button, .provider-card-actions button, #newProvider, #cancelProvider {{ width: auto; }}
      .route-map {{ grid-template-columns: 1fr; }}
      .route-connector {{ min-height: 20px; }}
      .route-connector::before {{
        bottom: 0;
        height: auto;
        left: 18px;
        right: auto;
        top: 0;
        width: 1px;
      }}
      .route-connector::after {{
        bottom: 0;
        left: 14px;
        right: auto;
        top: auto;
        transform: rotate(135deg);
      }}
      .status-metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="topbar">
      <h1>Codex 控制面板</h1>
      <div class="topbar-actions">
        <button id="update" class="secondary" data-action="update">更新</button>
      </div>
    </div>
    <section class="panel">
      <p id="state" class="state">{html.escape(title)}</p>
      <p id="message" class="message">{html.escape(message)}</p>
      <div class="actions">
        {button}
        {action_buttons}
      </div>
      {danger_zone}
      {render_status_panel(snapshot)}
      {provider_management}
      {speed_controls}
      <p class="note">如果你是在 Codex 内置浏览器看到此页面，重启 Codex 前请用外部浏览器打开此页面，否则重启后页面会关闭。</p>
      <details>
        <summary>诊断</summary>
        <pre id="diagnostics">{snapshot_json}</pre>
      </details>
    </section>
  </main>
  <script>
    const token = {token_json};
    const headerName = {json.dumps(CONTROL_TOKEN_HEADER)};
    const $ = (id) => document.getElementById(id);
    const labels = {labels_json};
    const actionProgress = {{
      enable: [
        {{ delay: 0, label: '正在准备环境...', message: '正在读取当前 Provider 并准备环境。' }},
        {{ delay: 6000, label: '正在验证模型服务...', message: '正在连接当前模型服务，首次启用可能需要几十秒。' }},
        {{ delay: 18000, label: '模型服务响应较慢...', message: '仍在等待模型服务响应，完成后页面会自动更新。' }}
      ],
      update: [
        {{ delay: 0, label: '正在更新...', message: '正在拉取更新并刷新本地代理，页面会在完成后自动恢复。' }},
        {{ delay: 8000, label: '正在刷新运行时...', message: '正在重新安装并刷新代理进程，这一步可能需要十几秒。' }},
        {{ delay: 20000, label: '更新仍在继续...', message: '仍在等待本地更新完成，请保持控制面板打开。' }}
      ],
      uninstall: [
        {{ delay: 0, label: '正在恢复直连...', message: '正在恢复 Codex 原模型服务，并准备清理本地代理。' }},
        {{ delay: 1200, label: '正在清理...', message: '正在移除本地状态、安装文件和 skill 链接，控制面板会最后关闭。' }}
      ],
      default: [
        {{ delay: 0, label: '处理中...', message: null }}
      ]
    }};
    let providerRecords = {json.dumps(providers, ensure_ascii=False)};
    function escapeHtml(value) {{
      return String(value).replace(/[&<>"']/g, (char) => ({{
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }}[char]));
    }}
    function currentProviderName(snapshot) {{
      const records = Array.isArray(providerRecords) ? providerRecords : [];
      if (snapshot && typeof snapshot.current_provider === 'string' && snapshot.current_provider) return snapshot.current_provider;
      if (snapshot && typeof snapshot.provider === 'string' && snapshot.provider) return snapshot.provider;
      const current = records.find((item) => item && item.current && item.name);
      if (current && current.name) return current.name;
      return records[0] && records[0].name ? records[0].name : '';
    }}
    function renderProviderCard(record, currentName) {{
      const name = record && record.name ? String(record.name) : '未命名';
      const baseUrl = record && record.base_url ? String(record.base_url) : '未设置模型服务';
      const isCurrent = Boolean(record && record.current) || name === currentName;
      const statusLabel = isCurrent ? '使用中' : '已配置';
      const statusClass = isCurrent ? 'ok' : 'idle';
      const enableButton = isCurrent ? '' : `<button class="provider-enable" type="button" data-provider-action="switch" data-provider="${{escapeHtml(name)}}">启用</button>`;
      const avatar = (name.trim().charAt(0) || '?').toUpperCase();
      return `
            <article class="provider-card${{isCurrent ? ' current' : ''}}" data-provider-name="${{escapeHtml(name)}}">
              <div class="provider-main">
                <span class="provider-avatar">${{escapeHtml(avatar)}}</span>
                <div class="provider-info">
                  <strong>${{escapeHtml(name)}}</strong>
                  <span class="provider-url">${{escapeHtml(baseUrl)}}</span>
                  <span class="provider-auth-state">密钥：${{escapeHtml(keyLabel(record ? record.api_key : null))}}</span>
                </div>
              </div>
              <div class="provider-card-actions">
                <span class="status-pill ${{statusClass}}">${{statusLabel}}</span>
                ${{enableButton}}
                <button class="provider-edit" type="button" data-provider-action="edit" data-provider="${{escapeHtml(name)}}">编辑供应商</button>
              </div>
            </article>
`;
    }}
    function renderProviderList(snapshot) {{
      providerRecords = Array.isArray(snapshot.providers) ? snapshot.providers : providerRecords;
      const list = $('providerList');
      if (list) {{
        const currentName = currentProviderName(snapshot);
        list.innerHTML = providerRecords.map((item) => renderProviderCard(item, currentName)).join('');
      }}
    }}
    function resetControls(userState, snapshot) {{
      Object.entries(labels).forEach(([id, label]) => {{
        const item = $(id);
        if (item) {{
          item.disabled = false;
          item.textContent = label;
        }}
      }});
      $('primary').disabled = false;
      const confirmUninstall = $('confirmUninstall');
      const dangerZone = $('dangerZone');
      if (dangerZone) dangerZone.style.display = userState.code === 'confirmation_required' ? 'block' : 'none';
      const uninstall = $('uninstall');
      if (uninstall) uninstall.style.display = userState.code === 'confirmation_required' ? 'none' : 'inline-block';
      const saveSpeed = $('saveSpeed');
      if (saveSpeed) saveSpeed.disabled = !snapshot.base_url;
    }}
    function keyLabel(value) {{
      if (value === 'saved') return '已保存';
      if (typeof value === 'string' && value.includes(':')) {{
        const parts = value.split(':');
        if (parts[0] === 'auth_json') return `Codex 已保存 ${{parts[1]}}`;
        return `环境变量 ${{parts[1]}}`;
      }}
      return '未保存';
    }}
    function openProviderEditor(record, title) {{
      const editor = $('providerEditor');
      if (editor) editor.hidden = false;
      const editorTitle = $('providerEditorTitle');
      if (editorTitle && title) editorTitle.textContent = title;
      fillProviderForm(record);
      const nameInput = $('providerNameInput');
      if (nameInput) nameInput.focus();
    }}
    function closeProviderEditor() {{
      const editor = $('providerEditor');
      if (editor) editor.hidden = true;
      const editorTitle = $('providerEditorTitle');
      if (editorTitle) editorTitle.textContent = '编辑供应商';
    }}
    function providerByName(name) {{
      return providerRecords.find((item) => item.name === name) || null;
    }}
    function fillProviderForm(record) {{
      const nameInput = $('providerNameInput');
      if (nameInput) nameInput.value = record ? record.name || '' : '';
      const upstreamBase = $('upstreamBase');
      if (upstreamBase) upstreamBase.value = record ? record.base_url || '' : '';
      const apiKey = $('apiKey');
      if (apiKey) apiKey.value = '';
    }}
    function resetProviderForm(snapshot) {{
      renderProviderList(snapshot);
      closeProviderEditor();
      fillProviderForm(providerByName(currentProviderName(snapshot)));
    }}
    function resetSpeedForm(snapshot) {{
      const speedMode = snapshot.service_tier_policy === 'preserve' ? 'standard' : 'fast';
      const speedInput = document.querySelector(`input[name="speedMode"][value="${{speedMode}}"]`);
      if (speedInput) speedInput.checked = true;
    }}
    function displayValue(value, fallback) {{
      return typeof value === 'string' && value ? value : fallback;
    }}
    function speedLabel(snapshot) {{
      return snapshot.service_tier_policy === 'preserve' ? '标准' : '快速';
    }}
    function providerStatus(snapshot) {{
      if (snapshot.config_matches && snapshot.healthy && !snapshot.needs_restart) return ['运行中', 'ok'];
      if (snapshot.config_matches && snapshot.needs_restart) return ['待重启', 'warn'];
      if (snapshot.config_matches) return ['需处理', 'warn'];
      if (snapshot.base_url) return ['已恢复', 'idle'];
      return ['未启用', 'idle'];
    }}
    function formatLocalTime(date) {{
      const pad = (value) => String(value).padStart(2, '0');
      return [
        date.getFullYear(),
        '-',
        pad(date.getMonth() + 1),
        '-',
        pad(date.getDate()),
        ' ',
        pad(date.getHours()),
        ':',
        pad(date.getMinutes()),
        ':',
        pad(date.getSeconds())
      ].join('');
    }}
    function renderLocalTimes() {{
      document.querySelectorAll('time.local-time[datetime]').forEach((node) => {{
        const value = node.getAttribute('datetime');
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return;
        node.textContent = formatLocalTime(date);
        node.title = `UTC ${{value}}`;
      }});
    }}
    function resetSummary(snapshot) {{
      const providerSpeed = $('providerSpeed');
      if (providerSpeed) providerSpeed.textContent = speedLabel(snapshot);
      const [label, className] = providerStatus(snapshot);
      const status = $('providerStatus');
      if (status) {{
        status.textContent = label;
        status.className = `status-pill ${{className}}`;
      }}
      const summaryName = $('providerSummaryName');
      if (summaryName) summaryName.textContent = currentProviderName(snapshot) || '未选择';
      const summaryUrl = $('providerSummaryUrl');
      if (summaryUrl) summaryUrl.textContent = displayValue((providerByName(currentProviderName(snapshot)) || {{}}).base_url, '未设置模型服务');
    }}
    function selectedSpeedMode() {{
      const selected = document.querySelector('input[name="speedMode"]:checked');
      return selected ? selected.value : 'fast';
    }}
    function shouldReloadForSnapshot(snapshot) {{
      const userState = snapshot.user_state || {{}};
      const terminalState = ['cleanup_pending', 'uninstalled_deferred', 'uninstalled'].includes(userState.code);
      const hasRuntimeControls = Boolean($('update') || $('uninstall'));
      const shouldShowRuntimeControls = Boolean(snapshot.base_url) && !terminalState;
      const hasProviderPanel = Boolean($('providerPanel'));
      const shouldShowProviderPanel = Array.isArray(snapshot.providers) && snapshot.providers.length > 0 && !terminalState;
      const hasSpeedForm = Boolean($('speedForm'));
      const shouldShowSpeedForm = shouldShowProviderPanel && !snapshot.chatgpt_auth;
      return hasRuntimeControls !== shouldShowRuntimeControls ||
        hasProviderPanel !== shouldShowProviderPanel ||
        hasSpeedForm !== shouldShowSpeedForm;
    }}
    function render(snapshot) {{
      if (shouldReloadForSnapshot(snapshot)) {{
        window.location.reload();
        return;
      }}
      const userState = snapshot.user_state || {{}};
      $('state').textContent = userState.title || '需要处理';
      $('message').textContent = userState.message || '请打开诊断，或让 Codex 根据诊断结果修复。';
      $('diagnostics').textContent = JSON.stringify(snapshot, null, 2);
      renderLocalTimes();
      const button = $('primary');
      button.dataset.action = userState.primary_action || 'diagnostics';
      button.textContent = userState.primary_label || '打开诊断';
      resetControls(userState, snapshot);
      resetProviderForm(snapshot);
      resetSummary(snapshot);
      resetSpeedForm(snapshot);
    }}
    renderLocalTimes();
    async function requestAction(action, body) {{
      const response = await fetch('/api/actions/' + action, {{
        method: 'POST',
        headers: {{ [headerName]: token, 'Content-Type': 'application/json' }},
        body: body ? JSON.stringify(body) : undefined
      }});
      const data = await response.json();
      if (data.status !== 'ok') {{
        if (data.snapshot) render(data.snapshot);
        throw new Error(data.error || '操作没有完成。');
      }}
      render(data.snapshot);
      if (data.action && data.action.control_ui && data.action.control_ui.url) {{
        window.setTimeout(() => {{
          window.location.href = data.action.control_ui.url;
        }}, data.action.control_ui.reload_after_ms || 500);
      }}
    }}
    function startActionProgress(button, action) {{
      const timers = [];
      const steps = actionProgress[action] || actionProgress.default;
      const applyStep = (step) => {{
        button.textContent = step.label;
        if (step.message) $('message').textContent = step.message;
      }};
      steps.forEach((step) => {{
        if (step.delay > 0) timers.push(window.setTimeout(() => applyStep(step), step.delay));
        else applyStep(step);
      }});
      return () => timers.forEach((timer) => window.clearTimeout(timer));
    }}
    async function runButton(button, action, body) {{
      button.disabled = true;
      const oldText = button.textContent;
      const stopProgress = startActionProgress(button, action);
      try {{
        await requestAction(action, body);
      }} catch (error) {{
        $('state').textContent = '需要处理';
        $('message').textContent = (error && error.message) ? error.message : String(error);
        button.disabled = false;
        button.textContent = oldText;
      }} finally {{
        stopProgress();
      }}
    }}
    $('primary').addEventListener('click', async (event) => {{
      const action = event.currentTarget.dataset.action;
      if (action === 'enable') await runButton(event.currentTarget, 'enable', {{ provider: currentProviderName() || null }});
      else if (action === 'refresh') window.location.reload();
      else if (action === 'uninstall') await runButton(event.currentTarget, 'uninstall');
      else document.querySelector('details').open = true;
    }});
    if ($('update')) $('update').addEventListener('click', (event) => runButton(event.currentTarget, 'update'));
    if ($('uninstall')) $('uninstall').addEventListener('click', (event) => runButton(event.currentTarget, 'uninstall'));
    if ($('finishCleanup')) $('finishCleanup').addEventListener('click', (event) => runButton(event.currentTarget, 'uninstall'));
    if ($('confirmUninstall')) $('confirmUninstall').addEventListener('click', (event) => runButton(event.currentTarget, 'uninstall', {{ confirm: true }}));
    if ($('newProvider')) $('newProvider').addEventListener('click', () => {{
      openProviderEditor(null, '添加供应商');
    }});
    if ($('cancelProvider')) $('cancelProvider').addEventListener('click', () => closeProviderEditor());
    if ($('providerList')) $('providerList').addEventListener('click', async (event) => {{
      const button = event.target.closest('button[data-provider-action]');
      if (!button) return;
      const provider = button.dataset.provider || '';
      if (button.dataset.providerAction === 'edit') {{
        openProviderEditor(providerByName(provider), '编辑供应商');
        return;
      }}
      if (button.dataset.providerAction === 'switch') {{
        await runButton(button, 'switch-provider', {{ provider }});
      }}
    }});
    if ($('providerForm')) $('providerForm').addEventListener('submit', async (event) => {{
      event.preventDefault();
      await runButton($('saveProvider'), 'save-provider', {{
        provider: $('providerNameInput').value.trim() || null,
        upstream_base: $('upstreamBase').value.trim() || null,
        api_key: $('apiKey').value.trim() || null
      }});
      $('apiKey').value = '';
    }});
    if ($('speedForm')) $('speedForm').addEventListener('submit', async (event) => {{
      event.preventDefault();
      await runButton($('saveSpeed'), 'set-speed-mode', {{ speed_mode: selectedSpeedMode() }});
    }});
  </script>
</body>
</html>"""
