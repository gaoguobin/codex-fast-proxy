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
    if snapshot.get("base_url") and snapshot.get("config_base_url") == snapshot.get("upstream_base"):
        return "已恢复", "idle"
    if snapshot.get("base_url"):
        return "未接管", "idle"
    return "未启用", "idle"


def upstream_auth_label(snapshot: dict[str, Any]) -> str:
    if snapshot.get("upstream_api_key_file"):
        return "已保存"
    if snapshot.get("upstream_api_key_env"):
        return f"环境变量 {snapshot['upstream_api_key_env']}"
    if snapshot.get("upstream_auth") == "preserved":
        return "使用 Codex 当前登录"
    return "未配置"


def display_text(value: Any, fallback: str = "未配置") -> str:
    return str(value) if isinstance(value, str) and value else fallback


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
        else '<button id="primary" data-action="diagnostics">打开诊断</button>'
    )
    labels: dict[str, str] = {}
    terminal_state = state_code in {"cleanup_pending", "uninstalled_deferred", "uninstalled"}
    show_runtime_controls = bool(snapshot.get("base_url")) and not terminal_state
    action_buttons = ""
    danger_zone = ""
    if show_runtime_controls:
        labels.update({
            "update": "更新",
            "uninstall": "停用并恢复",
            "confirmUninstall": "我知道可能导致模型请求失败，仍要停用",
        })
        action_buttons = """
        <button id="update" class="secondary" data-action="update">更新</button>
        <button id="uninstall" class="warn" data-action="uninstall">停用并恢复</button>
"""
        danger_zone = """
      <div id="dangerZone" class="danger-zone" style="display:none">
        <p>仍要继续停用只适合你已经理解风险的情况。继续后，当前 ChatGPT 登录可能无法直接使用第三方模型服务。</p>
        <button id="confirmUninstall" class="warn" data-action="confirm-uninstall">我知道可能导致模型请求失败，仍要停用</button>
      </div>
"""

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
            <span class="muted">Provider 管理</span>
            <strong id="providerSummaryName">{summary_name}</strong>
            <span id="providerSummaryUrl">{summary_url}</span>
          </span>
          <span class="summary-action">管理</span>
        </summary>
        <div class="maintenance-body">
          <div class="provider-panel-header">
            <div>
              <h2>Provider 管理</h2>
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
    if providers and not terminal_state:
        status_label, status_class = provider_status(snapshot)
        speed_label = html.escape(speed_mode_label(snapshot))
        speed_mode = speed_mode_from_snapshot(snapshot)
        fast_checked = " checked" if speed_mode == "fast" else ""
        standard_checked = " checked" if speed_mode == "standard" else ""
        labels["saveSpeed"] = "保存速度模式"
        disabled_speed = "" if show_runtime_controls else " disabled"
        speed_controls = f"""
      <h2>速度模式</h2>
      <div class="provider-summary">
        <div class="provider-title">
          <div>
            <span class="muted">当前策略</span>
            <strong id="providerSpeed">{speed_label}</strong>
          </div>
          <span id="providerStatus" class="status-pill {status_class}">{html.escape(status_label)}</span>
        </div>
      </div>
      <form id="speedForm" class="provider-form">
        <fieldset>
          <div class="segments">
            <label><input type="radio" name="speedMode" value="fast"{fast_checked}>快速</label>
            <label><input type="radio" name="speedMode" value="standard"{standard_checked}>标准</label>
          </div>
        </fieldset>
        <button id="saveSpeed" type="submit"{disabled_speed}>保存速度模式</button>
      </form>
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
    :root {{ color-scheme: light; font-family: "Segoe UI", system-ui, sans-serif; }}
    body {{ margin: 0; background: #f6f7f9; color: #17202a; }}
    main {{ max-width: 820px; margin: 0 auto; padding: 40px 20px; }}
    .panel {{ background: white; border: 1px solid #d9dee7; border-radius: 8px; padding: 24px; }}
    h1, .state {{ margin: 0 0 16px; }}
    h1 {{ font-size: 28px; }}
    h2 {{ font-size: 18px; margin: 28px 0 12px; }}
    .state {{ font-size: 32px; font-weight: 650; }}
    .message, .note {{ line-height: 1.6; color: #344054; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
    button {{ border: 0; border-radius: 8px; background: #1769aa; color: white; cursor: pointer; font-size: 15px; font-weight: 600; padding: 11px 18px; }}
    button.secondary {{ background: #344054; }}
    button.warn {{ background: #9a3412; }}
    button:disabled {{ cursor: wait; opacity: .65; }}
    .danger-zone {{ border-top: 1px solid #e5e8ef; margin-top: 18px; padding-top: 18px; }}
    .danger-zone p {{ color: #7c2d12; line-height: 1.6; margin: 0 0 12px; }}
    .maintenance-panel {{ border-top: 1px solid #e5e8ef; margin-top: 28px; padding-top: 4px; }}
    .maintenance-panel summary {{ align-items: center; cursor: pointer; display: flex; gap: 14px; justify-content: space-between; list-style: none; padding: 14px 0; }}
    .maintenance-panel summary::-webkit-details-marker {{ display: none; }}
    .summary-copy {{ display: grid; gap: 3px; min-width: 0; }}
    .summary-copy strong {{ font-size: 17px; font-weight: 600; }}
    .summary-copy span:last-child {{ color: #344054; font-size: 14px; overflow-wrap: anywhere; }}
    .summary-action {{ border: 1px solid #cbd5e1; border-radius: 999px; color: #344054; flex: 0 0 auto; font-size: 13px; font-weight: 650; padding: 5px 10px; }}
    .maintenance-body {{ border-top: 1px solid #e5e8ef; padding-top: 14px; }}
    .provider-panel-header {{ align-items: start; display: flex; gap: 14px; justify-content: space-between; margin-bottom: 14px; }}
    .provider-panel-header h2 {{ margin: 0; }}
    .provider-tabs {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }}
    .provider-tab {{ border: 1px solid #cbd5e1; border-radius: 999px; color: #344054; font-size: 13px; font-weight: 650; padding: 5px 10px; }}
    .provider-tab.active {{ background: #111827; border-color: #111827; color: white; }}
    .provider-list {{ display: grid; gap: 12px; }}
    .provider-card {{ background: #f8fafc; border: 1px solid #d9dee7; border-radius: 8px; display: flex; gap: 14px; justify-content: space-between; padding: 14px; }}
    .provider-card.current {{ background: white; border-color: #c7d2fe; box-shadow: inset 0 0 0 1px #e0e7ff; }}
    .provider-main {{ display: flex; gap: 12px; min-width: 0; }}
    .provider-avatar {{ align-items: center; background: #dbeafe; border-radius: 999px; color: #1d4ed8; display: inline-flex; flex: 0 0 auto; font-size: 16px; font-weight: 700; height: 36px; justify-content: center; width: 36px; }}
    .provider-info {{ display: grid; gap: 4px; min-width: 0; }}
    .provider-info strong {{ font-size: 16px; }}
    .provider-url, .provider-auth-state {{ color: #344054; font-size: 13px; overflow-wrap: anywhere; }}
    .provider-card-actions {{ align-items: center; display: flex; flex: 0 0 auto; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }}
    .provider-card-actions button {{ padding: 8px 12px; }}
    .provider-card-actions .provider-edit {{ background: #344054; }}
    .provider-editor {{ border-top: 1px solid #e5e8ef; margin-top: 16px; padding-top: 16px; }}
    .provider-editor-title {{ align-items: center; display: flex; gap: 10px; justify-content: space-between; margin-bottom: 10px; }}
    .provider-editor-title h3 {{ font-size: 16px; margin: 0; }}
    .provider-summary {{ border-top: 1px solid #e5e8ef; border-bottom: 1px solid #e5e8ef; padding: 14px 0; }}
    .provider-title {{ align-items: center; display: flex; gap: 12px; justify-content: space-between; }}
    .provider-title strong {{ display: block; font-size: 18px; margin-top: 3px; }}
    .muted {{ color: #667085; font-size: 13px; }}
    .status-pill {{ border-radius: 999px; display: inline-flex; font-size: 13px; font-weight: 650; padding: 5px 10px; white-space: nowrap; }}
    .status-pill.ok {{ background: #dcfce7; color: #166534; }}
    .status-pill.warn {{ background: #fef3c7; color: #92400e; }}
    .status-pill.idle {{ background: #e5e7eb; color: #344054; }}
    dl {{ display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 14px 0 0; }}
    dt {{ color: #667085; font-size: 13px; }}
    dd {{ color: #17202a; font-size: 14px; margin: 3px 0 0; overflow-wrap: anywhere; }}
    form {{ display: grid; gap: 10px; margin-top: 14px; }}
    label {{ display: grid; gap: 6px; color: #344054; font-size: 14px; }}
    input, select {{ border: 1px solid #cbd5e1; border-radius: 8px; font-size: 15px; padding: 10px 12px; }}
    fieldset {{ border: 0; margin: 0; padding: 0; }}
    legend {{ color: #344054; font-size: 14px; margin-bottom: 6px; }}
    .actions.compact {{ margin-top: 4px; }}
    .segments {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .segments label {{ align-items: center; border: 1px solid #cbd5e1; border-radius: 8px; cursor: pointer; display: flex; flex: 1 1 120px; gap: 8px; padding: 10px 12px; }}
    .segments input {{ margin: 0; padding: 0; }}
    details {{ margin-top: 24px; border-top: 1px solid #e5e8ef; padding-top: 18px; }}
    pre {{ background: #111827; border-radius: 8px; color: #e5e7eb; overflow: auto; padding: 16px; }}
    @media (max-width: 640px) {{ .provider-panel-header, .provider-card {{ flex-direction: column; }} .provider-card-actions {{ justify-content: flex-start; }} }}
  </style>
</head>
<body>
  <main>
    <h1>Codex 控制面板</h1>
    <section class="panel">
      <p id="state" class="state">{html.escape(title)}</p>
      <p id="message" class="message">{html.escape(message)}</p>
      <div class="actions">
        {button}
        {action_buttons}
      </div>
      {danger_zone}
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
    function authLabel(snapshot) {{
      if (snapshot.upstream_api_key_file) return '已保存';
      if (snapshot.upstream_api_key_env) return `环境变量 ${{snapshot.upstream_api_key_env}}`;
      if (snapshot.upstream_auth === 'preserved') return '使用 Codex 当前登录';
      return '未配置';
    }}
    function providerStatus(snapshot) {{
      if (snapshot.config_matches && snapshot.healthy && !snapshot.needs_restart) return ['运行中', 'ok'];
      if (snapshot.config_matches && snapshot.needs_restart) return ['待重启', 'warn'];
      if (snapshot.config_matches) return ['需处理', 'warn'];
      if (snapshot.base_url && snapshot.config_base_url === snapshot.upstream_base) return ['已恢复', 'idle'];
      if (snapshot.base_url) return ['未接管', 'idle'];
      return ['未启用', 'idle'];
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
      return hasRuntimeControls !== shouldShowRuntimeControls ||
        hasProviderPanel !== shouldShowProviderPanel;
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
      const button = $('primary');
      button.dataset.action = userState.primary_action || 'diagnostics';
      button.textContent = userState.primary_label || '打开诊断';
      resetControls(userState, snapshot);
      resetProviderForm(snapshot);
      resetSummary(snapshot);
      resetSpeedForm(snapshot);
    }}
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
