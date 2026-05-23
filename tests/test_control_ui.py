from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_fast_proxy import manager  # noqa: E402
from codex_fast_proxy.lifecycle import record_codex_hook_event  # noqa: E402
from codex_fast_proxy.actions import (  # noqa: E402
    run_benchmark,
    run_check_update,
    run_configure_upstream,
    run_delete_provider,
    run_first_run_enable,
    run_save_provider,
    run_set_speed_mode,
    run_switch_provider,
    run_uninstall,
    run_update,
    run_verify_provider,
)
from codex_fast_proxy.control_ui import (  # noqa: E402
    ControlHandler,
    control_ui_identity,
    control_ui_runtime_paths,
    doctor_payload,
    find_existing_control_ui,
    ensure_control_ui_for_hook,
    is_loopback_host,
    open_control_ui,
    provider_key_payload,
    render_page,
    schedule_install_cleanup,
    schedule_control_ui_restart,
    schedule_path_cleanup,
    start_background_server,
    user_error_message,
)
from codex_fast_proxy.ports import find_available_port  # noqa: E402
from codex_fast_proxy.runtime_status import health_matches_settings  # noqa: E402
from codex_fast_proxy.state import collect_status, user_state  # noqa: E402


class ControlUiTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_root = ROOT / ".test_tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp_dir = temp_root / f"control-ui-{uuid.uuid4().hex}"
        self.temp_dir.mkdir()
        self.codex_home = self.temp_dir / ".codex"
        self.codex_home.mkdir()
        self.paths = manager.paths_for(self.codex_home)
        self.paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def test_status_snapshot_maps_unenabled_provider_to_chinese_enable_state(self) -> None:
        snapshot = collect_status(str(self.codex_home))

        self.assertEqual(snapshot["user_state"]["code"], "ready_to_enable")
        self.assertEqual(snapshot["user_state"]["title"], "准备启用")
        self.assertEqual(snapshot["user_state"]["primary_action"], "enable")
        self.assertEqual(snapshot["providers"][0]["name"], "acme")
        self.assertEqual(snapshot["providers"][0]["base_url"], "https://api.acme.test/v1")

    def test_status_snapshot_without_provider_uses_specific_missing_provider_state(self) -> None:
        self.paths.config_path.write_text("", encoding="utf-8")

        snapshot = collect_status(str(self.codex_home))

        self.assertEqual(snapshot["user_state"]["code"], "missing_provider")
        self.assertEqual(snapshot["user_state"]["title"], "需要先配置供应商")
        self.assertIn("没有检测到可接管的第三方模型服务入口", snapshot["user_state"]["message"])
        self.assertIn("还没有发起上游请求", snapshot["user_state"]["message"])
        self.assertEqual(snapshot["user_state"]["primary_action"], "diagnostics")
        self.assertEqual(snapshot["providers"], [])

        html = render_page(snapshot, "token")
        self.assertIn("还没有检测到 Codex config.toml 里的供应商入口。", html)
        self.assertIn("还没有可显示的供应商。请先在 Codex config.toml 配置 provider。", html)
        self.assertNotIn("还没有可管理的供应商。", html)

    def test_status_snapshot_lists_multiple_providers_without_proxy_url(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
        )
        manager.write_settings(self.paths, settings)
        self.paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            f'base_url = "{settings.base_url}"\n\n'
            "[model_providers.other]\n"
            'base_url = "https://api.other.test/v1"\n',
            encoding="utf-8",
        )

        snapshot = collect_status(str(self.codex_home))
        providers = {item["name"]: item for item in snapshot["providers"]}

        self.assertEqual(providers["acme"]["base_url"], "https://api.acme.test/v1")
        self.assertEqual(providers["other"]["base_url"], "https://api.other.test/v1")
        self.assertNotIn(settings.base_url, json.dumps(snapshot["providers"]))

    def test_status_snapshot_allows_proxy_managed_provider_switch_without_config_provider_change(self) -> None:
        settings = manager.ProxySettings(
            provider="other",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.other.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_entry(
            self.paths,
            "other",
            api_key="other-provider-secret",
            base_url="https://api.other.test/v1",
        )
        self.paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            f'base_url = "{settings.base_url}"\n',
            encoding="utf-8",
        )

        snapshot = collect_status(str(self.codex_home))
        providers = {item["name"]: item for item in snapshot["providers"]}

        self.assertTrue(snapshot["config_matches"])
        self.assertEqual(snapshot["provider"], "other")
        self.assertEqual(snapshot["config_provider"], "acme")
        self.assertEqual(snapshot["codex_model_provider"], "acme")
        self.assertEqual(snapshot["codex_proxy_provider"], "acme")
        self.assertEqual(snapshot["proxy_upstream_provider"], "other")
        self.assertEqual(snapshot["provider_route"]["codex_model_provider"], "acme")
        self.assertEqual(snapshot["provider_route"]["proxy_upstream_provider"], "other")
        self.assertEqual(providers["other"]["base_url"], "https://api.other.test/v1")
        self.assertTrue(providers["other"]["current"])
        self.assertNotIn("acme", providers)

        html = render_page(snapshot, "token")
        route = "acme -&gt; 127.0.0.1:18787/v1 -&gt; other -&gt; api.other.test/v1"
        overview_html = html[html.index('data-page="overview"'):html.index('data-page="providers"')]
        advanced_html = html[html.index('data-page="advanced"'):html.index('data-page="settings"')]
        self.assertNotIn(route, overview_html)
        self.assertIn(route, advanced_html)

    def test_status_snapshot_maps_restored_proxy_to_cleanup_state(self) -> None:
        manager.write_settings(
            self.paths,
            manager.ProxySettings(
                provider="acme",
                host="127.0.0.1",
                port=18787,
                proxy_base="/v1",
                upstream_base="https://api.acme.test/v1",
                service_tier="priority",
            ),
        )

        snapshot = collect_status(str(self.codex_home))

        self.assertEqual(snapshot["user_state"]["code"], "cleanup_pending")
        self.assertEqual(snapshot["user_state"]["title"], "已停用")
        self.assertEqual(snapshot["user_state"]["primary_action"], "enable")

    def test_status_snapshot_auto_applies_pending_restart_when_proxy_is_idle(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.new.test/v1",
            service_tier="priority",
        )
        manager.write_settings(self.paths, settings)
        manager.set_provider_base_url(self.paths.config_path, "acme", settings.base_url)
        probes = []

        def runtime_probe(_paths, _settings):
            probes.append("probe")
            health = {
                "ok": True,
                "pid": 9999,
                "proxy_base": "/v1",
                "upstream_base": "https://api.old.test/v1",
                "service_tier": "priority",
                "runtime_id": manager.RUNTIME_ID,
                "activity": {"active_requests": 0, "active_streams": 0, "idle": True},
            }
            if len(probes) > 1:
                health = {**health, "pid": 1234, "upstream_base": "https://api.new.test/v1"}
                return 1234, True, health, True, False, True
            return 9999, True, health, True, True, True

        with mock.patch("codex_fast_proxy.state.start_background", return_value={"status": "restarted", "pid": 1234}) as start:
            snapshot = collect_status(str(self.codex_home), runtime_probe=runtime_probe, apply_idle_pending=True)

        self.assertEqual(start.call_count, 1)
        self.assertEqual(len(probes), 2)
        self.assertEqual(snapshot["auto_apply_result"]["status"], "restarted")
        self.assertFalse(snapshot["needs_restart"])

    def test_status_snapshot_keeps_pending_restart_while_proxy_is_active(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.new.test/v1",
            service_tier="priority",
        )
        manager.write_settings(self.paths, settings)
        manager.set_provider_base_url(self.paths.config_path, "acme", settings.base_url)

        def runtime_probe(_paths, _settings):
            return 9999, True, {
                "ok": True,
                "pid": 9999,
                "proxy_base": "/v1",
                "upstream_base": "https://api.old.test/v1",
                "service_tier": "priority",
                "runtime_id": manager.RUNTIME_ID,
                "activity": {"active_requests": 1, "active_streams": 1, "idle": False},
            }, True, True, True

        with mock.patch("codex_fast_proxy.state.start_background", side_effect=AssertionError("should not restart")):
            snapshot = collect_status(str(self.codex_home), runtime_probe=runtime_probe, apply_idle_pending=True)

        self.assertTrue(snapshot["needs_restart"])
        self.assertEqual(snapshot["user_state"]["code"], "restart_deferred_active")
        self.assertEqual(snapshot["proxy_activity"]["active_streams"], 1)

    def test_status_snapshot_uses_clear_refresh_label_for_restart_state(self) -> None:
        snapshot = user_state({
            "config_matches": True,
            "healthy": True,
            "needs_restart": True,
            "provider": "acme",
            "config_base_url": "http://127.0.0.1:18787/v1",
        })

        self.assertEqual(snapshot["code"], "restart_required")
        self.assertEqual(snapshot["primary_action"], "refresh")
        self.assertEqual(snapshot["primary_label"], "刷新状态")

    def test_control_page_is_chinese_and_warns_about_codex_embedded_browser(self) -> None:
        html = render_page(
            {
                "provider": "acme",
                "config_base_url": "https://api.acme.test/v1",
                "user_state": {
                    "title": "准备启用",
                    "message": "点击启用后，会自动准备当前模型服务路径。",
                    "primary_action": "enable",
                    "primary_label": "启用",
                }
            },
            "token",
        )

        self.assertIn("Codex 控制面板", html)
        self.assertIn("Codex Model Gateway", html)
        self.assertNotIn("Codex Fast Proxy</strong>", html)
        self.assertIn("启用", html)
        self.assertIn("更新", html)
        self.assertNotIn('id="uninstall"', html)
        self.assertNotIn('id="languageSelect"', html)
        self.assertIn('name="languageChoice" value="zh"', html)
        self.assertIn('name="languageChoice" value="en"', html)
        self.assertIn('name="languageChoice" value="ja"', html)
        self.assertNotIn('id="themeSelect"', html)
        self.assertIn('name="themeChoice" value="system"', html)
        self.assertIn('name="themeChoice" value="light"', html)
        self.assertIn('name="themeChoice" value="dark"', html)
        self.assertIn("segmented-control", html)
        self.assertIn('const translations = ', html)
        self.assertIn('const stateTranslations = ', html)
        self.assertIn("codex-fast-proxy.locale", html)
        self.assertIn("codex-fast-proxy.theme", html)
        self.assertIn(':root[data-theme="dark"]', html)
        self.assertIn('id="codexConfigPanel"', html)
        self.assertNotIn('id="providerPanel"', html)
        self.assertIn("Codex 配置", html)
        self.assertIn("来自 config.toml · 只读", html)
        self.assertIn("供应商", html)
        self.assertIn('class="app-shell"', html)
        self.assertIn('class="sidebar"', html)
        self.assertIn('data-view="overview"', html)
        self.assertIn('data-view="providers"', html)
        self.assertIn('data-view="requests"', html)
        self.assertIn('data-view="advanced"', html)
        self.assertIn('data-view="settings"', html)
        self.assertIn('class="nav-item nav-settings"', html)
        self.assertIn('data-page="settings"', html)
        self.assertIn('id="updatePrimary"', html)
        self.assertIn('data-update-action="check-update"', html)
        self.assertNotIn('id="checkUpdate"', html)
        self.assertNotIn('id="update"', html)
        self.assertIn("检查更新", html)
        self.assertIn("语言和外观只影响这个本地控制面板", html)
        self.assertIn("模型服务地址", html)
        self.assertNotIn("providerProxy", html)
        self.assertNotIn("provider-tabs", html)
        self.assertNotIn("provider-tab", html)
        self.assertNotIn('id="newProvider"', html)
        self.assertNotIn('id="providerEditor"', html)
        self.assertNotIn("保存</button>", html)
        self.assertNotIn("添加供应商", html)
        self.assertNotIn("编辑供应商", html)
        self.assertNotIn('id="speedPanel"', html)
        self.assertNotIn('id="speedForm"', html)
        self.assertNotIn('id="statusPanel"', html)
        self.assertIn("请求记录", html)
        self.assertIn('data-page="providers"', html)
        self.assertNotIn("status-list", html)
        self.assertNotIn("status-row emphasized", html)
        self.assertIn("hero-summary", html)
        self.assertIn("api.acme.test/v1", html)
        self.assertIn('<span data-i18n="summary.speed">速度</span>', html)
        self.assertIn('<span data-i18n="summary.recentRequests">最近请求</span>', html)
        self.assertIn("status-metric", html)
        self.assertIn("request-table", html)
        self.assertIn("mobile-cell-label", html)
        self.assertIn("@media (max-width: 640px)", html)
        self.assertNotIn("Codex 当前入口", html)
        self.assertNotIn('name="speedMode" value="fast" checked', html)
        self.assertNotIn('name="speedMode" value="standard"', html)
        self.assertIn("这里汇总运行时、配置、登录、启动钩子和日志路径", html)
        self.assertIn('id="runDoctor"', html)
        self.assertIn('id="copyDiagnostics"', html)
        self.assertIn('id="downloadDiagnostics"', html)
        self.assertIn('id="refreshDiagnostics"', html)
        self.assertIn('id="diagnosticsFeedback"', html)
        self.assertIn("状态摘要", html)
        self.assertIn("日志路径", html)
        self.assertIn("自检结果", html)
        self.assertIn("诊断导出不包含密钥", html)
        self.assertIn("正在准备环境", html)
        self.assertIn("正在验证模型服务", html)
        self.assertIn("首次启用可能需要几十秒", html)
        self.assertIn("'save-provider'", html)
        self.assertIn("正在保存，并验证模型服务是否可用。", html)
        self.assertIn("'switch-provider'", html)
        self.assertIn("正在切换，并验证新的模型服务。", html)
        self.assertIn("'delete-provider'", html)
        self.assertIn("正在删除保存项", html)
        self.assertIn("'set-speed-mode'", html)
        self.assertIn("正在保存当前选择。", html)
        self.assertIn("如果验证失败，当前设置会保持不变。", html)
        self.assertIn("'check-update'", html)
        self.assertIn("正在读取远端分支和本地工作区状态", html)
        self.assertIn("'verify-provider'", html)
        self.assertIn("'run-benchmark'", html)
        self.assertIn("高级诊断", html)
        self.assertIn('id="diagnosticsPanel"', html)
        self.assertIn("/api/doctor", html)
        self.assertIn("copyDiagnostics", html)
        self.assertIn("downloadDiagnostics", html)
        self.assertIn("renderDoctorReport", html)
        self.assertIn('const token = "token";', html)
        self.assertNotIn("&quot;token&quot;", html)

    def test_control_page_recent_requests_are_compact_and_time_aware(self) -> None:
        html = render_page(
            {
                "base_url": "http://127.0.0.1:8787/v1",
                "config_matches": True,
                "healthy": True,
                "provider": "acme",
                "upstream_base": "https://api.acme.test/v1",
                "recent_response_events": [{
                    "ts": "2026-05-18T11:41:19.293+00:00",
                    "method": "POST",
                    "path": "/v1/responses",
                    "status": 200,
                    "ttfb_ms": 1234.5,
                    "ttft_ms": 2345.6,
                    "duration_ms": 32066.3,
                    "service_tier_before": "priority",
                    "service_tier_after": "priority",
                    "service_tier_injected": False,
                    "service_tier_effective_policy": "preserve",
                }],
                "user_state": {
                    "title": "运行正常",
                    "message": "Codex 已准备好继续使用当前模型服务。",
                    "primary_action": "uninstall",
                    "primary_label": "停用并恢复",
                },
            },
            "token",
        )

        self.assertIn("最近请求", html)
        self.assertIn('<th data-i18n="table.time">时间</th>', html)
        self.assertIn('title="首响应：收到上游第一个响应字节" data-i18n="table.firstResponse">首响应</span>', html)
        self.assertIn('title="首文本：收到第一个可见文本" data-i18n="table.firstText">首文本</span>', html)
        self.assertIn('title="完整耗时：请求从开始到结束的总耗时" data-i18n="table.totalDuration">完整耗时</span>', html)
        self.assertIn('<th data-i18n="table.speedMode">速度模式</th>', html)
        self.assertNotIn("<th>Tier</th>", html)
        self.assertNotIn("<th>首包</th>", html)
        self.assertNotIn("<th>首字</th>", html)
        self.assertIn('class="local-time" datetime="2026-05-18T11:41:19.293+00:00"', html)
        self.assertIn('title="post /v1/responses"', html)
        self.assertIn('<span class="mobile-cell-label" data-i18n="table.request">请求</span>', html)
        self.assertIn('<span class="cell-value">post /v1/responses</span>', html)
        self.assertIn('<span class="status-pill ok"', html)
        self.assertIn(">正常</span>", html)
        self.assertIn("首响应：收到上游第一个响应字节", html)
        self.assertIn("首文本：收到第一个可见文本", html)
        self.assertIn('<span class="cell-value">1.234s</span>', html)
        self.assertIn('<span class="cell-value">2.346s</span>', html)
        self.assertIn('<span class="cell-value">32.066s</span>', html)
        self.assertIn('<span class="cell-value">App 控制</span>', html)
        self.assertIn("运行细节", html)
        self.assertIn("性能基准", html)
        self.assertIn("Provider 检查", html)
        self.assertLess(html.index("Provider 检查"), html.index("性能基准"))
        self.assertIn("grid-template-columns: 1fr", html)
        self.assertIn("overflow-x: hidden", html)
        self.assertIn("date.getFullYear()", html)
        self.assertIn("renderLocalTimes();", html)

    def test_control_page_renders_migrated_dashboard_signals_without_secrets(self) -> None:
        html = render_page(
            {
                "base_url": "http://127.0.0.1:8787/v1",
                "config_matches": True,
                "healthy": True,
                "benchmark_result": {
                    "status": "completed",
                    "ts": "2026-04-27T06:00:00.000+00:00",
                    "provider": "acme",
                    "model": "gpt-test",
                    "benchmark_mode": "codex-cli",
                    "profile": "full",
                    "pairs": 3,
                    "priority_accepted": True,
                    "observed_priority_effective": True,
                    "observed_speedup_total": 1.53,
                    "observed_speedup_ttft": 1.4,
                    "default": {"count": 3, "ok": 3, "median_total_ms": 1200.0, "median_ttft_ms": 500.0},
                    "priority": {"count": 3, "ok": 3, "median_total_ms": 784.3, "median_ttft_ms": 357.1},
                },
                "recent_provider_metadata_events": [{
                    "ts": "2026-05-05T06:10:41.000+00:00",
                    "method": "GET",
                    "path": "/v1/models",
                    "status": 503,
                    "duration_ms": 20,
                }],
                "recent_response_events": [{
                    "ts": "2026-05-18T11:41:19.293+00:00",
                    "request_id": "req-demo",
                    "method": "POST",
                    "path": "/v1/responses",
                    "status": 502,
                    "duration_ms": 24501.2,
                    "ttfb_ms": 123.4,
                    "service_tier_before": "<absent>",
                    "service_tier_after": "priority",
                    "service_tier_injected": True,
                    "service_tier_effective_policy": "inject_missing",
                    "stream": True,
                    "error_type": "client_disconnected",
                }],
                "user_state": {
                    "title": "运行正常",
                    "message": "Codex 已准备好继续使用当前模型服务。",
                    "primary_action": "uninstall",
                    "primary_label": "停用并恢复",
                },
            },
            "token",
        )

        self.assertIn("运行细节", html)
        self.assertIn("总耗时收益", html)
        self.assertIn("1.53x", html)
        self.assertIn("已接受", html)
        self.assertIn("首文本收益", html)
        self.assertIn("1.40x", html)
        self.assertIn("优先耗时", html)
        self.assertIn("0.784s", html)
        self.assertIn("0.500s -&gt; 0.357s", html)
        self.assertIn("样本 default 3/3，priority 3/3", html)
        self.assertIn("延迟结果只代表本轮观测", html)
        self.assertIn("get /v1/models", html)
        self.assertIn(">异常</span>", html)
        self.assertIn("request_id: req-demo", html)
        self.assertIn("error_type: client_disconnected", html)
        self.assertNotIn("api_key_env", html)

    def test_status_snapshot_feeds_control_page_with_sanitized_telemetry(self) -> None:
        self.paths.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.log_path.write_text(
            json.dumps({
                "ts": "2026-05-18T11:41:19.293+00:00",
                "request_id": "req-demo",
                "method": "POST",
                "path": "/v1/responses",
                "status": 502,
                "duration_ms": 24501.2,
                "eligible": True,
                "service_tier_before": "<absent>",
                "service_tier_after": "priority",
                "service_tier_injected": True,
                "service_tier_effective_policy": "inject_missing",
                "stream": True,
                "error_type": "client_disconnected",
                "Authorization": "Bearer should-not-render",
                "input": "prompt should-not-render",
            })
            + "\n",
            encoding="utf-8",
        )
        self.paths.benchmark_path.write_text(
            json.dumps({
                "status": "completed",
                "provider": "acme",
                "model": "gpt-test",
                "observed_priority_effective": True,
                "api_key_env": "ACME_API_KEY",
                "priority": {"median_total_ms": 784.3},
            }),
            encoding="utf-8",
        )

        html = render_page(collect_status(str(self.codex_home)), "token")

        self.assertIn("request_id: req-demo", html)
        self.assertIn("client_disconnected", html)
        self.assertIn("0.784s", html)
        self.assertNotIn("Bearer should-not-render", html)
        self.assertNotIn("prompt should-not-render", html)
        self.assertNotIn("ACME_API_KEY", html)

    def test_control_page_marks_ttft_as_not_applicable_when_text_delta_is_absent(self) -> None:
        html = render_page(
            {
                "base_url": "http://127.0.0.1:8787/v1",
                "config_matches": True,
                "healthy": True,
                "recent_response_events": [{
                    "ts": "2026-05-18T11:41:19.293+00:00",
                    "method": "POST",
                    "path": "/v1/responses",
                    "status": 200,
                    "ttfb_ms": 1234.5,
                    "duration_ms": 32066.3,
                    "service_tier_effective_policy": "preserve",
                }],
                "user_state": {"title": "运行正常", "message": "", "primary_action": "uninstall", "primary_label": "停用并恢复"},
            },
            "token",
        )

        self.assertIn('<span class="cell-value">不适用</span>', html)

    def test_provider_management_is_collapsed_by_default(self) -> None:
        html = render_page(
            {
                "base_url": "http://127.0.0.1:8787/v1",
                "providers": [{
                    "name": "acme",
                    "base_url": "https://api.acme.test/v1",
                    "current": True,
                    "active": True,
                    "api_key": "saved",
                    "api_key_length": 27,
                }, {
                    "name": "other",
                    "base_url": "https://api.other.test/v1",
                    "current": False,
                    "active": False,
                    "deletable": True,
                    "api_key": "missing",
                }],
                "provider": "acme",
                "user_state": {
                    "title": "准备启用",
                    "message": "点击启用后，会自动准备当前模型服务路径。",
                    "primary_action": "enable",
                    "primary_label": "启用",
                },
            },
            "token",
        )

        self.assertIn('<section id="providerPanel" class="detail-panel provider-workspace">', html)
        self.assertIn('class="view-page" data-page="providers" hidden', html)
        self.assertIn('id="providerSummaryName">acme</h2>', html)
        self.assertIn('id="providerSummaryUrl">https://api.acme.test/v1</p>', html)
        self.assertIn('id="providerEditor" class="provider-editor" hidden', html)
        self.assertIn('id="providerFormFeedback"', html)
        self.assertIn('data-provider-check-feedback', html)
        self.assertIn("provider-row-feedback", html)
        self.assertIn("providerCheckResults", html)
        self.assertIn("setProviderCheckResult(provider", html)
        self.assertIn("renderSuccessSnapshot: false", html)
        self.assertIn("suppressGlobalProgress: true", html)
        self.assertIn("suppressGlobalError: true", html)
        self.assertIn("target.setAttribute('aria-label'", html)
        self.assertNotIn("providerCheckFeedback", html)
        self.assertIn("providerFormValidationError", html)
        self.assertIn("provider.form.invalidUrl", html)
        self.assertIn("renderErrorSnapshot: false", html)
        self.assertIn("feedbackElement: $('providerFormFeedback')", html)
        self.assertIn("if (result.ok && $('apiKey')) $('apiKey').value = '';", html)
        self.assertIn("添加", html)
        self.assertIn("编辑", html)
        self.assertIn("更新", html)
        self.assertIn("删除", html)
        self.assertIn('id="revealApiKey"', html)
        self.assertIn('aria-controls="apiKey"', html)
        self.assertIn('aria-pressed="false"', html)
        self.assertIn('data-eye-open', html)
        self.assertIn('data-eye-off', html)
        self.assertNotIn('class="icon-eye"', html)
        self.assertIn("syncRevealButton(true)", html)
        self.assertIn("maskSecret", html)
        self.assertIn('"api_key_length": 27', html)
        self.assertIn("Number(record.api_key_length)", html)
        self.assertIn("return '•'.repeat", html)
        self.assertIn(".eye-icon[hidden]", html)
        self.assertIn("open.toggleAttribute('hidden', revealed)", html)
        self.assertNotIn("••••••••••••••••", html)
        self.assertIn("apiKeyFormValue()", html)
        self.assertIn("/api/provider-key?provider=", html)
        self.assertIn('data-provider-action="verify"', html)
        self.assertIn('data-provider="other" data-i18n="button.checkProvider">检查</button>', html)
        self.assertIn('data-provider-action="switch"', html)
        self.assertIn('data-provider="other" data-i18n="button.switch">启用</button>', html)
        self.assertIn('data-provider="other" data-i18n="button.delete">删除</button>', html)
        self.assertIn('<span class="status-pill ok" data-i18n="value.inUse">使用中</span>', html)
        self.assertNotIn("已配置", html)
        self.assertIn("https://api.other.test/v1", html)
        self.assertNotIn("providerSelect", html)
        self.assertNotIn("provider-secret", html)
        self.assertNotIn("添加供应商", html)
        self.assertNotIn("编辑供应商", html)
        self.assertNotIn("更新供应商", html)

    def test_provider_management_is_hidden_before_proxy_enable(self) -> None:
        html = render_page(
            {
                "providers": [{
                    "name": "acme",
                    "base_url": "https://api.acme.test/v1",
                    "current": True,
                    "active": True,
                    "api_key": "saved",
                }],
                "provider": "acme",
                "user_state": {
                    "title": "准备启用",
                    "message": "点击启用后，会自动准备当前模型服务路径。",
                    "primary_action": "enable",
                    "primary_label": "启用",
                },
            },
            "token",
        )

        self.assertIn('id="codexConfigPanel"', html)
        self.assertIn("来自 config.toml · 只读", html)
        self.assertNotIn('id="providerPanel"', html)
        self.assertNotIn('id="providerForm"', html)
        self.assertNotIn('id="providerList"', html)
        self.assertNotIn('id="newProvider"', html)

    def test_provider_inventory_before_enable_is_config_read_only(self) -> None:
        manager.write_provider_auth_entry(
            self.paths,
            "other",
            api_key="other-secret",
            base_url="https://api.other.test/v1",
        )
        manager.write_provider_auth_entry(
            self.paths,
            "acme",
            api_key="acme-secret",
            base_url="https://api.saved.test/v1",
        )
        self.paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.config.test/v1"\n',
            encoding="utf-8",
        )

        providers = manager.provider_inventory(str(self.codex_home))["providers"]

        self.assertEqual([item["name"] for item in providers], ["acme"])
        self.assertEqual(providers[0]["base_url"], "https://api.config.test/v1")
        self.assertEqual(providers[0]["api_key"], "saved")
        self.assertEqual(providers[0]["api_key_length"], len("acme-secret"))
        self.assertFalse(providers[0]["deletable"])
        self.assertNotIn("acme-secret", json.dumps(providers, ensure_ascii=False))

    def test_provider_inventory_allows_deleting_inactive_config_provider_saved_entry(self) -> None:
        settings = manager.ProxySettings(
            provider="other",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.other.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_secret(self.paths, "acme", "acme-secret")
        manager.write_provider_auth_entry(self.paths, "other", api_key="other-secret", base_url="https://api.other.test/v1")
        self.paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            f'base_url = "{settings.base_url}"\n',
            encoding="utf-8",
        )

        providers = {item["name"]: item for item in manager.provider_inventory(str(self.codex_home))["providers"]}

        self.assertTrue(providers["acme"]["deletable"])
        self.assertEqual(providers["acme"]["api_key_length"], len("acme-secret"))
        self.assertFalse(providers["other"]["deletable"])
        self.assertEqual(providers["other"]["api_key_length"], len("other-secret"))

    def test_control_page_hides_maintenance_controls_before_enable(self) -> None:
        html = render_page(
            {
                "user_state": {
                    "title": "准备启用",
                    "message": "点击启用后，会自动准备当前模型服务路径。",
                    "primary_action": "enable",
                    "primary_label": "启用",
                }
            },
            "token",
        )

        self.assertNotIn('id="uninstall"', html)
        self.assertNotIn('id="speedPanel"', html)
        self.assertNotIn('id="speedForm"', html)

    def test_control_page_cleanup_state_offers_reenable_and_finish_cleanup(self) -> None:
        html = render_page(
            {
                "base_url": "http://127.0.0.1:8787/v1",
                "upstream_base": "https://api.acme.test/v1",
                "user_state": {
                    "code": "cleanup_pending",
                    "title": "已停用",
                    "message": "Codex 已恢复到原模型服务。",
                    "primary_action": "enable",
                    "primary_label": "重新启用",
                },
            },
            "token",
        )

        self.assertIn('data-action="enable"', html)
        self.assertIn("重新启用", html)
        self.assertIn('id="finishCleanup"', html)
        self.assertIn("完成清理", html)
        self.assertIn("else if (action === 'uninstall') await runButton", html)
        self.assertNotIn('id="uninstall"', html)

    def test_control_page_restores_maintenance_button_labels_after_action(self) -> None:
        html = render_page(
            {
                "base_url": "http://127.0.0.1:8787/v1",
                "upstream_base": "https://api.acme.test/v1",
                "api_key_auth": True,
                "user_state": {
                    "title": "运行正常",
                    "message": "Codex 已准备好继续使用当前模型服务。",
                    "primary_action": "diagnostics",
                }
            },
            "token",
        )

        self.assertIn('const labels = {"update": "更新"', html)
        self.assertIn('"uninstall": "停用并恢复"', html)
        self.assertIn('"confirmUninstall": "仍要停用"', html)
        self.assertIn('"cancelUninstall": "先不停用"', html)
        self.assertIn('"confirmDelete": "确认删除"', html)
        self.assertIn('"saveProvider": "保存"', html)
        self.assertIn("providerEditorActionLabel(saveProvider.dataset.providerMode)", html)
        self.assertIn('"saveSpeed": "保存"', html)
        self.assertIn('"checkUpdate": "检查更新"', html)
        self.assertIn("button.updateNow", html)
        self.assertIn("button.recheckUpdate", html)
        self.assertIn('"runBenchmark": "运行基准测试"', html)
        self.assertIn('"confirmBenchmark": "运行快速测试"', html)
        self.assertIn('"confirmStrictBenchmark": "运行严格测试"', html)
        self.assertIn("正在保存并验证...", html)
        self.assertIn("resetControls(userState, snapshot);", html)
        self.assertIn("resetSummary(snapshot);", html)
        self.assertIn("if (!renderedSnapshot) button.textContent = oldText;", html)
        self.assertNotIn("button.textContent = oldText;", html.replace("if (!renderedSnapshot) button.textContent = oldText;", ""))
        self.assertIn('value="https://api.acme.test/v1"', html)
        self.assertIn("providerSummaryName", html)
        self.assertIn("providerSummaryUrl", html)
        self.assertIn("button[aria-busy=\"true\"]", html)
        self.assertIn("button.setAttribute('aria-busy', 'true');", html)
        self.assertIn("button.removeAttribute('aria-busy');", html)
        self.assertIn("return { ok, error: caughtError, renderedSnapshot, data: responseData };", html)
        self.assertIn("startActionProgress(button, action, options)", html)
        self.assertIn("!options.suppressGlobalProgress", html)
        self.assertIn("cursor: not-allowed;", html)
        self.assertNotIn("button:disabled {\n      cursor: wait;", html)
        self.assertIn(".app-shell", html)
        self.assertIn(".sidebar", html)
        self.assertIn("position: sticky;", html)
        self.assertIn("height: 100vh;", html)
        self.assertIn("position: static;", html)
        self.assertIn(".detail-panel", html)
        self.assertIn(".provider-split", html)
        self.assertIn("showView('advanced')", html)
        self.assertIn("renderProviderList(snapshot);", html)
        self.assertIn("resetProviderForm(snapshot);", html)
        self.assertIn("resetSpeedForm(snapshot);", html)
        self.assertIn("syncPreferenceControls();", html)
        self.assertIn("updateRevealButtonState();", html)
        self.assertIn("reveal.disabled = !apiKey.value.trim();", html)
        self.assertIn("'set-speed-mode'", html)
        self.assertIn("reloadWhenControlUiReady", html)
        self.assertIn("new URL('/api/ping', url)", html)
        self.assertIn("window.location.href = url;", html)
        self.assertIn("wait_for_disconnect", html)
        self.assertIn("const delay = controlUi.reload_after_ms ?? 120;", html)
        self.assertIn("const replacementPid = Number(controlUi.pid);", html)
        self.assertIn("ping.pid === replacementPid", html)
        self.assertIn("let disconnected = !waitForDisconnect;", html)
        self.assertIn("controlUi.reload_after_ms", html)
        self.assertIn("async function refreshSnapshot", html)
        self.assertIn("cache: 'no-store'", html)
        self.assertIn("data: responseData", html)
        self.assertIn("shouldReloadForSnapshot(snapshot)", html)
        self.assertIn("const hasRuntimeControls = Boolean($('dangerZone') || $('uninstall'));", html)
        self.assertNotIn("Boolean($('update') || $('uninstall'))", html)
        self.assertIn("window.location.reload();", html)
        self.assertIn("showBenchmarkConfirm", html)
        self.assertIn("window.sessionStorage.setItem(viewStorageKey, currentActiveView());", html)
        self.assertIn("正在等待新版界面...", html)
        self.assertIn("查看诊断", html)
        self.assertIn('data-page="advanced"', html)
        self.assertIn("showView(item.dataset.view)", html)
        self.assertIn("action.dataset.updateAction = canUpdate ? 'update' : 'check-update';", html)
        self.assertIn("input[name=\"languageChoice\"]", html)
        self.assertIn("input[name=\"themeChoice\"]", html)
        self.assertNotIn("border-left: 3px solid var(--blue)", html)
        self.assertNotIn("border-left: 2px solid var(--border-strong)", html)
        self.assertNotIn("currentAction !== action", html)
        self.assertIn("render(result.data.snapshot);", html)
        self.assertIn("requestProviderDeleteConfirmation(provider, button);", html)
        self.assertNotIn("window.confirm", html)

    def test_control_page_maps_preserve_policy_to_standard_speed_mode(self) -> None:
        html = render_page(
            {
                "base_url": "http://127.0.0.1:8787/v1",
                "upstream_base": "https://api.acme.test/v1",
                "config_matches": True,
                "healthy": False,
                "service_tier_policy": "preserve",
                "api_key_auth": True,
                "user_state": {
                    "title": "运行正常",
                    "message": "Codex 已准备好继续使用当前模型服务。",
                    "primary_action": "diagnostics",
                },
            },
            "token",
        )

        self.assertNotIn('data-page="speed"', html)
        self.assertNotIn('id="speedPanel"', html)
        self.assertIn('id="overviewSpeedPreference"', html)
        self.assertNotIn('summary-speed-control', html)
        self.assertIn("快速会在请求未指定 service_tier 时使用 priority；标准保持原始请求。", html)
        self.assertIn('name="speedMode" value="standard" checked', html)
        self.assertIn('name="speedMode" value="fast"', html)
        self.assertIn("需处理", html)

    def test_control_page_hides_speed_mode_for_chatgpt_login(self) -> None:
        html = render_page(
            {
                "providers": [{
                    "name": "acme",
                    "base_url": "https://api.acme.test/v1",
                    "current": True,
                    "active": True,
                    "api_key": "saved",
                }],
                "login_mode": "chatgpt",
                "chatgpt_auth": True,
                "user_state": {
                    "title": "运行正常",
                    "message": "Codex 已准备好继续使用当前模型服务。",
                    "primary_action": "uninstall",
                    "primary_label": "停用并恢复",
                },
            },
            "token",
        )

        self.assertNotIn('id="speedPanel"', html)
        self.assertNotIn('id="speedForm"', html)
        self.assertNotIn('data-page="speed"', html)
        self.assertNotIn('data-view="speed"', html)
        self.assertIn("ChatGPT 账户登录", html)

    def test_control_page_maps_fast_behavior_names_to_summary_labels(self) -> None:
        html = render_page(
            {
                "base_url": "http://127.0.0.1:8787/v1",
                "provider": "acme",
                "fast_behavior": "auto_global_priority",
                "user_state": {
                    "title": "运行正常",
                    "message": "Codex 已准备好继续使用当前模型服务。",
                    "primary_action": "uninstall",
                    "primary_label": "停用并恢复",
                },
            },
            "token",
        )

        self.assertIn('<span data-i18n="summary.speed">速度</span>', html)
        self.assertIn("<strong>快速</strong>", html)
        self.assertIn("auto_global_priority", html)

    def test_configure_upstream_errors_are_user_facing(self) -> None:
        message = user_error_message(
            "configure-upstream",
            {"upstream_base": "https://api.acme.test/v1"},
        )

        self.assertEqual(message, "没有保存。新的模型服务没有通过验证，当前仍在使用：https://api.acme.test/v1")

    def test_provider_save_error_hides_internal_benchmark_detail(self) -> None:
        message = user_error_message(
            "save-provider",
            {"upstream_base": "https://api.acme.test/v1"},
            "Benchmark could not find an API key in provider config.",
        )

        self.assertIn("没有可用于验证的接口密钥", message)
        self.assertNotIn("Benchmark", message)

    def test_switch_provider_error_includes_specific_reason(self) -> None:
        message = user_error_message(
            "switch-provider",
            {},
            "Responses API side-path verification returned HTTP 403.",
        )

        self.assertIn("没有切换。请选择已保存且可验证的 Provider。", message)
        self.assertIn("HTTP 403", message)
        self.assertIn("key 权限", message)
        self.assertNotIn("HTTP 404", message)

    def test_provider_errors_map_common_upstream_failures(self) -> None:
        cases = [
            ("Responses API side-path verification returned HTTP 401.", "接口密钥无效"),
            ("Responses API side-path verification returned HTTP 402.", "额度或计费状态不可用"),
            ("Responses API side-path verification returned HTTP 404.", "/v1/responses"),
            ("Responses API side-path verification failed: timed out", "连接超时"),
            ("Responses API side-path verification failed: [Errno 61] Connection refused", "拒绝连接"),
            ("Responses API side-path verification failed: getaddrinfo ENOTFOUND", "无法解析"),
            ("Responses API side-path verification failed: remote disconnected", "模型服务验证失败"),
            ("Responses API side-path verification did not return SSE content: application/json.", "stream=true"),
        ]
        for detail, expected in cases:
            with self.subTest(detail=detail):
                message = user_error_message("verify-provider", {}, detail)
                self.assertIn(expected, message)
                self.assertNotIn("Responses API side-path", message)

    def test_update_action_reports_already_current_without_reload_prompt(self) -> None:
        with mock.patch("codex_fast_proxy.manager.update_installation", return_value={
            "status": "already_current",
            "code_update": {"status": "already_current"},
            "final_status": {"needs_restart": False},
        }):
            result = run_update(str(self.codex_home))

        self.assertEqual(result["user_state"]["code"], "already_current")
        self.assertEqual(result["user_state"]["title"], "已是最新")
        self.assertIn("最新版本", result["user_state"]["message"])
        self.assertNotIn("重新打开控制面板", result["user_state"]["message"])

    def test_update_action_blocked_local_changes_preserves_operational_context(self) -> None:
        with mock.patch("codex_fast_proxy.manager.update_installation", return_value={
            "status": "blocked",
            "code": "local_changes",
            "next_user_action": "请先处理本地改动，再从控制面板更新。",
        }):
            result = run_update(str(self.codex_home))

        self.assertEqual(result["user_state"]["code"], "update_blocked")
        self.assertEqual(result["user_state"]["title"], "更新被暂停")
        self.assertIn("当前代理状态不受影响", result["user_state"]["message"])
        self.assertIn("请先处理本地改动", result["user_state"]["message"])
        self.assertEqual(result["user_state"]["primary_action"], "diagnostics")

    def test_update_action_prompts_to_reopen_control_ui_after_code_update(self) -> None:
        with mock.patch("codex_fast_proxy.manager.update_installation", return_value={
            "status": "updated",
            "code_update": {"status": "updated"},
            "final_status": {"needs_restart": False},
        }):
            result = run_update(str(self.codex_home))

        self.assertEqual(result["user_state"]["title"], "更新完成")
        self.assertTrue(result["control_ui_reload_required"])
        self.assertIn("正在打开新版控制面板", result["user_state"]["message"])

    def test_update_action_reports_deferred_proxy_refresh_when_request_is_active(self) -> None:
        with mock.patch("codex_fast_proxy.manager.update_installation", return_value={
            "status": "updated",
            "code_update": {"status": "updated"},
            "refresh": {
                "status": "installed",
                "start_result": {
                    "status": "deferred",
                    "defer_reason": "active_requests",
                    "activity": {"active_requests": 1, "active_streams": 1},
                },
            },
            "final_status": {"needs_restart": True},
        }):
            result = run_update(str(self.codex_home))

        self.assertEqual(result["user_state"]["code"], "restart_deferred_active")
        self.assertEqual(result["user_state"]["title"], "更新完成，等待当前请求结束")
        self.assertIn("请求结束后自动应用", result["user_state"]["message"])

    def test_check_update_action_is_read_only_and_reports_local_changes(self) -> None:
        with mock.patch("codex_fast_proxy.manager.check_update", return_value={
            "status": "checked",
            "read_only": True,
            "local_changes": True,
            "update_available": True,
        }):
            result = run_check_update(str(self.codex_home))

        self.assertTrue(result["read_only"])
        self.assertEqual(result["user_state"]["code"], "update_checked_dirty")
        self.assertIn("未提交改动", result["user_state"]["message"])

    def test_verify_provider_action_checks_saved_inactive_provider_without_switching(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            service_tier_policy="auto",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_entry(
            self.paths,
            "other",
            api_key="other-secret",
            base_url="https://api.other.test/v1",
        )
        self.paths.config_path.write_text(
            'model_provider = "acme"\n'
            'model = "gpt-5.5"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n'
            "[model_providers.other]\n"
            'base_url = "https://api.other.test/v1"\n',
            encoding="utf-8",
        )

        with mock.patch("codex_fast_proxy.manager.verify_upstream_responses", return_value={
            "status": "verified",
            "total_ms": 1234.0,
        }) as verify:
            result = run_verify_provider(str(self.codex_home), "other")

        verified_settings = verify.call_args.args[2]
        self.assertEqual(result["status"], "provider_verified")
        self.assertEqual(result["provider"], "other")
        self.assertEqual(verified_settings.provider, "other")
        self.assertEqual(verified_settings.upstream_base, "https://api.other.test/v1")
        self.assertTrue(verified_settings.upstream_api_key_file)
        self.assertIn("1.23s", result["user_state"]["message"])

    def test_benchmark_action_uses_three_pairs_and_requires_confirmation(self) -> None:
        with self.assertRaises(ValueError):
            run_benchmark(str(self.codex_home), confirm=False)

        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_entry(
            self.paths,
            "acme",
            api_key="benchmark-secret",
            base_url="https://api.acme.test/v1",
        )
        self.paths.config_path.write_text(
            'model_provider = "acme"\n'
            'model = "gpt-5.5"\n'
            'model_reasoning_effort = "xhigh"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )

        def fake_benchmark(
            target: object,
            pairs: int,
            timeout: float,
            *,
            mode: str,
            benchmark_kind: str,
            randomized_order: bool,
        ) -> dict[str, object]:
            self.assertEqual(target.provider, "acme")
            self.assertEqual(target.model, "gpt-5.5")
            self.assertEqual(target.profile, "full")
            self.assertEqual(target.reasoning_effort, "xhigh")
            self.assertEqual(pairs, 3)
            self.assertEqual(timeout, 600.0)
            self.assertEqual(mode, "direct")
            self.assertEqual(benchmark_kind, "quick")
            self.assertFalse(randomized_order)
            return {"pairs": pairs, "profile": target.profile, "benchmark_kind": benchmark_kind}

        with mock.patch("codex_fast_proxy.benchmark.run_benchmark", side_effect=fake_benchmark):
            result = run_benchmark(str(self.codex_home), confirm=True)

        self.assertEqual(result["status"], "benchmark_saved")
        self.assertEqual(result["pairs"], 3)
        self.assertEqual(result["saved_to"], str(self.paths.benchmark_path))
        saved = manager.read_json(self.paths.benchmark_path)
        self.assertEqual(saved["pairs"], 3)
        self.assertTrue(result["reload_required"])
        self.assertIn("3 组", result["user_state"]["message"])

    def test_strict_benchmark_action_uses_twelve_pairs_and_randomized_order(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_entry(
            self.paths,
            "acme",
            api_key="benchmark-secret",
            base_url="https://api.acme.test/v1",
        )
        self.paths.config_path.write_text(
            'model_provider = "acme"\n'
            'model = "gpt-5.5"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )

        def fake_benchmark(
            _target: object,
            pairs: int,
            _timeout: float,
            *,
            mode: str,
            benchmark_kind: str,
            randomized_order: bool,
        ) -> dict[str, object]:
            self.assertEqual(pairs, 12)
            self.assertEqual(mode, "direct")
            self.assertEqual(benchmark_kind, "strict")
            self.assertTrue(randomized_order)
            return {"pairs": pairs, "benchmark_kind": benchmark_kind}

        with mock.patch("codex_fast_proxy.benchmark.run_benchmark", side_effect=fake_benchmark):
            result = run_benchmark(str(self.codex_home), confirm=True, benchmark_kind="strict")

        self.assertEqual(result["pairs"], 12)
        self.assertIn("12 组", result["user_state"]["message"])

    def test_update_control_action_restarts_current_ui_on_same_port(self) -> None:
        handler = object.__new__(ControlHandler)
        handler.server = mock.Mock(
            codex_home=str(self.codex_home),
            provider=None,
            server_address=("127.0.0.1", 8786),
        )
        handler.read_body_json = mock.Mock(return_value={})

        with (
            mock.patch("codex_fast_proxy.actions.run_update", return_value={
                "status": "updated",
                "control_ui_reload_required": True,
                "final_status": {"needs_restart": False},
                "user_state": {"title": "更新完成"},
            }),
            mock.patch.object(handler, "restart_current_control_ui", return_value={
                "status": "scheduled",
                "url": "http://127.0.0.1:8786/",
                "same_port": True,
                "pid": 4321,
                "wait_for_disconnect": True,
            }),
        ):
            response = handler.run_action("update")

        self.assertTrue(response["shutdown_control_ui"])
        self.assertEqual(response["action"]["control_ui"]["url"], "http://127.0.0.1:8786/")
        self.assertTrue(response["action"]["control_ui"]["same_port"])
        self.assertEqual(response["action"]["control_ui"]["pid"], 4321)
        self.assertTrue(response["action"]["control_ui"]["wait_for_disconnect"])

    def test_favicon_request_returns_empty_success(self) -> None:
        handler = object.__new__(ControlHandler)
        handler.path = "/favicon.ico"
        handler.respond_empty = mock.Mock()

        handler.do_GET()

        handler.respond_empty.assert_called_once_with()

    def test_scheduled_control_ui_restart_waits_for_old_port_to_close(self) -> None:
        with mock.patch("subprocess.Popen") as popen:
            popen.return_value.pid = 4321

            result = schedule_control_ui_restart(str(self.codex_home), None, "127.0.0.1", 8786)

        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["pid"], 4321)
        self.assertTrue(result["wait_for_disconnect"])
        self.assertEqual(result["reload_after_ms"], 0)
        self.assertEqual(result["reload_timeout_ms"], 8000)

    def test_provider_key_payload_returns_secret_only_on_explicit_request(self) -> None:
        manager.write_provider_auth_secret(self.paths, "acme", "provider-secret")

        payload = provider_key_payload(str(self.codex_home), "acme")

        self.assertEqual(payload, {
            "status": "ok",
            "provider": "acme",
            "api_key": "provider-secret",
        })

    def test_provider_key_payload_rejects_missing_secret(self) -> None:
        with self.assertRaises(ValueError):
            provider_key_payload(str(self.codex_home), "missing")

    def test_doctor_payload_returns_sanitized_control_ui_report(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
        )
        manager.write_settings(self.paths, settings)
        manager.set_provider_base_url(self.paths.config_path, "acme", settings.base_url)

        payload = doctor_payload(str(self.codex_home), None)

        self.assertEqual(payload["status"], "ok")
        self.assertIn("doctor", payload)
        self.assertIn("checks", payload["doctor"])
        names = [item["name"] for item in payload["doctor"]["checks"]]
        self.assertIn("python", names)
        self.assertIn("codex_config", names)
        self.assertIn("active_provider", names)
        self.assertIn("codex_model_provider", names)
        self.assertIn("codex_proxy_provider", names)
        self.assertIn("proxy_upstream_provider", names)
        self.assertIn("provider_route", names)
        self.assertNotIn("provider-secret", json.dumps(payload, ensure_ascii=False))

    def test_uninstall_control_action_schedules_state_cleanup(self) -> None:
        handler = object.__new__(ControlHandler)
        handler.server = mock.Mock(
            codex_home=str(self.codex_home),
            provider=None,
            server_address=("127.0.0.1", 8786),
        )
        handler.read_body_json = mock.Mock(return_value={})

        with (
            mock.patch("codex_fast_proxy.actions.run_uninstall", return_value={
                "status": "uninstalled",
                "control_ui_cleanup": {"path": str(self.paths.app_home)},
                "user_state": {"title": "已清理完成"},
            }),
            mock.patch("codex_fast_proxy.control_ui.schedule_path_cleanup", return_value={
                "status": "scheduled",
                "path": str(self.paths.app_home),
                "pid": 1234,
            }),
        ):
            response = handler.run_action("uninstall")

        self.assertTrue(response["shutdown_control_ui"])
        self.assertEqual(response["action"]["control_ui_cleanup"]["status"], "scheduled")

    def test_uninstall_control_action_schedules_deep_install_cleanup_last(self) -> None:
        handler = object.__new__(ControlHandler)
        handler.server = mock.Mock(
            codex_home=str(self.codex_home),
            provider=None,
            server_address=("127.0.0.1", 8786),
        )
        handler.read_body_json = mock.Mock(return_value={})

        cleanup = {
            "mode": "deep_install_removal",
            "app_home": str(self.paths.app_home),
            "repo_root": str(self.codex_home / "codex-fast-proxy"),
            "backup_dir": str(self.paths.backup_dir),
            "package": "codex-fast-proxy",
        }
        with (
            mock.patch("codex_fast_proxy.actions.run_uninstall", return_value={
                "status": "uninstalled",
                "control_ui_cleanup": cleanup,
                "user_state": {"title": "已清理完成"},
            }),
            mock.patch("codex_fast_proxy.control_ui.schedule_install_cleanup", return_value={
                "status": "scheduled",
                "mode": "deep_install_removal",
                "pid": 1234,
                "delay_seconds": 4.0,
            }) as schedule_cleanup,
        ):
            response = handler.run_action("uninstall")

        schedule_cleanup.assert_called_once_with(cleanup)
        self.assertTrue(response["shutdown_control_ui"])
        self.assertEqual(response["shutdown_after_seconds"], 2.5)
        self.assertEqual(response["action"]["shutdown_after_seconds"], 2.5)
        self.assertEqual(response["action"]["control_ui_cleanup"]["mode"], "deep_install_removal")

    def test_uninstall_confirmation_uses_safe_chinese_copy(self) -> None:
        with mock.patch("codex_fast_proxy.manager.enabled_installation", return_value=(True, "acme")):
            with mock.patch("codex_fast_proxy.manager.uninstall_result", return_value=({
                "status": "confirmation_required",
                "message": (
                    "ChatGPT login appears to be active. Uninstall would restore Codex config "
                    "to the direct third-party upstream before the proxy auth override is in the path, "
                    "so future model requests may fail with 401."
                ),
            }, 4)):
                result = run_uninstall(str(self.codex_home))

        self.assertEqual(result["user_state"]["title"], "停用前需要处理登录方式")
        self.assertIn("ChatGPT 账户登录", result["user_state"]["message"])
        self.assertIn("接口密钥", result["user_state"]["message"])
        self.assertNotIn("401", result["user_state"]["message"])

    def test_uninstall_cleanup_schedules_deep_install_removal_when_installed_repo_is_active(self) -> None:
        captured: dict[str, object] = {}

        def fake_uninstall(args: object) -> tuple[dict[str, object], int]:
            captured["args"] = args
            return {"status": "uninstalled", "stop_result": {"status": "stopped"}}, 0

        with (
            mock.patch("codex_fast_proxy.manager.enabled_installation", return_value=(False, "acme")),
            mock.patch("codex_fast_proxy.manager.uninstall_result", side_effect=fake_uninstall),
            mock.patch("codex_fast_proxy.manager.source_repo_root", return_value=self.codex_home / "codex-fast-proxy"),
        ):
            result = run_uninstall(str(self.codex_home))

        args = captured["args"]
        self.assertTrue(getattr(args, "keep_state"))
        self.assertFalse(getattr(args, "defer_stop"))
        self.assertEqual(result["user_state"]["title"], "已清理完成")
        self.assertEqual(result["control_ui_cleanup"]["mode"], "deep_install_removal")
        self.assertEqual(result["control_ui_cleanup"]["app_home"], str(self.paths.app_home))
        self.assertEqual(result["control_ui_cleanup"]["repo_root"], str(self.codex_home / "codex-fast-proxy"))
        self.assertEqual(result["control_ui_cleanup"]["backup_dir"], str(self.paths.backup_dir))

    def test_uninstall_cleanup_falls_back_to_runtime_state_for_dev_repo(self) -> None:
        with (
            mock.patch("codex_fast_proxy.manager.enabled_installation", return_value=(False, "acme")),
            mock.patch("codex_fast_proxy.manager.uninstall_result", return_value=({
                "status": "uninstalled",
                "stop_result": {"status": "stopped"},
            }, 0)),
            mock.patch("codex_fast_proxy.manager.source_repo_root", return_value=ROOT),
        ):
            result = run_uninstall(str(self.codex_home))

        self.assertEqual(result["control_ui_cleanup"]["mode"], "runtime_state")
        self.assertEqual(result["control_ui_cleanup"]["path"], str(self.paths.app_home))

    def test_confirmation_page_hides_normal_uninstall_and_shows_danger_zone(self) -> None:
        html = render_page(
            {
                "base_url": "http://127.0.0.1:8787/v1",
                "upstream_base": "https://api.acme.test/v1",
                "user_state": {
                    "code": "confirmation_required",
                    "title": "停用前需要处理登录方式",
                    "message": "你现在是 ChatGPT 账户登录。",
                },
            },
            "token",
        )

        self.assertIn('id="dangerZone"', html)
        self.assertIn("先确认登录路径", html)
        self.assertIn("登录路径示意", html)
        self.assertIn("仍要停用", html)
        self.assertIn("先不停用", html)
        self.assertIn("dangerZone.hidden = userState.code !== 'confirmation_required'", html)
        self.assertIn("uninstall.hidden = userState.code === 'confirmation_required'", html)

    def test_first_run_enable_prepares_provider_auth_and_installs_without_printing_secret(self) -> None:
        (self.codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "provider-secret"}), encoding="utf-8")
        original_verify = manager.verify_upstream_responses
        original_start = manager.start_background
        original_find_available_port = manager.find_available_port
        manager.verify_upstream_responses = lambda *_args, **_kwargs: {"status": "verified", "response_status": 200}
        manager.start_background = lambda *_args, **_kwargs: {"status": "started", "pid": 1234}
        manager.find_available_port = lambda _host, _preferred, attempts=100, reserved_ports=(): 8787
        try:
            result = run_first_run_enable(str(self.codex_home))
        finally:
            manager.verify_upstream_responses = original_verify
            manager.start_background = original_start
            manager.find_available_port = original_find_available_port

        result_text = json.dumps(result, ensure_ascii=False)
        config = manager.load_toml_config(self.paths.config_path)
        stored_auth = json.loads(self.paths.provider_auth_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "enabled")
        self.assertEqual(result["user_state"]["code"], "restart_required")
        self.assertEqual(result["user_state"]["title"], "已启用，重启后接管")
        self.assertIn("当前对话可以继续", result["user_state"]["message"])
        self.assertEqual(manager.provider_base_url(config, "acme"), "http://127.0.0.1:8787/v1")
        self.assertEqual(stored_auth["providers"]["acme"]["api_key"], "provider-secret")
        self.assertEqual(stored_auth["providers"]["acme"]["base_url"], "https://api.acme.test/v1")
        self.assertNotIn("provider-secret", result_text)

    def test_first_run_enable_fails_before_config_change_when_provider_key_is_missing(self) -> None:
        with self.assertRaises(manager.ConfigError):
            run_first_run_enable(str(self.codex_home))

        config = manager.load_toml_config(self.paths.config_path)
        self.assertEqual(manager.provider_base_url(config, "acme"), "https://api.acme.test/v1")
        self.assertFalse(self.paths.settings_path.exists())

    def test_configure_upstream_writes_provider_auth_without_printing_secret(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
        )
        manager.write_settings(self.paths, settings)
        manager.set_provider_base_url(self.paths.config_path, "acme", settings.base_url)
        original_verify = manager.verify_upstream_responses
        original_start = manager.start_background
        manager.verify_upstream_responses = lambda *_args, **_kwargs: {"status": "verified", "response_status": 200}
        manager.start_background = lambda *_args, **_kwargs: {"status": "started", "pid": 1234}
        try:
            result = run_configure_upstream(
                str(self.codex_home),
                "https://api.new.test/v1",
                "new-provider-secret",
            )
        finally:
            manager.verify_upstream_responses = original_verify
            manager.start_background = original_start

        result_text = json.dumps(result, ensure_ascii=False)
        stored_auth = json.loads(self.paths.provider_auth_path.read_text(encoding="utf-8"))
        saved_settings = manager.read_settings(self.paths)

        self.assertEqual(result["status"], "upstream_updated")
        self.assertEqual(result["user_state"]["code"], "configured")
        self.assertEqual(saved_settings.upstream_base, "https://api.new.test/v1")
        self.assertTrue(saved_settings.upstream_api_key_file)
        self.assertEqual(stored_auth["providers"]["acme"]["api_key"], "new-provider-secret")
        self.assertNotIn("new-provider-secret", result_text)

    def test_save_provider_adds_url_and_key_without_printing_secret(self) -> None:
        with mock.patch("codex_fast_proxy.manager.verify_upstream_responses", return_value={"status": "verified"}):
            result = run_save_provider(
                str(self.codex_home),
                "other",
                "https://api.other.test/v1",
                "other-provider-secret",
            )

        result_text = json.dumps(result, ensure_ascii=False)
        config = manager.load_toml_config(self.paths.config_path)
        stored_auth = json.loads(self.paths.provider_auth_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "provider_saved")
        self.assertIsNone(manager.provider_base_url(config, "other"))
        self.assertEqual(stored_auth["providers"]["other"]["api_key"], "other-provider-secret")
        self.assertEqual(stored_auth["providers"]["other"]["base_url"], "https://api.other.test/v1")
        self.assertNotIn("other-provider-secret", result_text)

    def test_save_current_provider_updates_proxy_state_without_mutating_user_config(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_entry(
            self.paths,
            "acme",
            api_key="old-provider-secret",
            base_url="https://api.acme.test/v1",
        )
        manager.set_provider_base_url(self.paths.config_path, "acme", settings.base_url)
        config_before = self.paths.config_path.read_bytes()

        with (
            mock.patch("codex_fast_proxy.manager.verify_upstream_responses", return_value={"status": "verified"}),
            mock.patch("codex_fast_proxy.manager.start_background", return_value={"status": "started", "pid": 1234}),
        ):
            result = run_save_provider(
                str(self.codex_home),
                "acme",
                "https://api.new.test/v1",
                "new-provider-secret",
            )

        stored_auth = json.loads(self.paths.provider_auth_path.read_text(encoding="utf-8"))
        saved_settings = manager.read_settings(self.paths)

        self.assertEqual(result["status"], "provider_saved")
        self.assertFalse(result["config_changed"])
        self.assertEqual(self.paths.config_path.read_bytes(), config_before)
        self.assertEqual(saved_settings.upstream_base, "https://api.new.test/v1")
        self.assertTrue(saved_settings.upstream_api_key_file)
        self.assertEqual(stored_auth["providers"]["acme"]["api_key"], "new-provider-secret")
        self.assertEqual(stored_auth["providers"]["acme"]["base_url"], "https://api.new.test/v1")

    def test_save_current_provider_restarts_running_proxy_when_only_key_changes(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_entry(self.paths, "acme", api_key="old-secret", base_url=settings.upstream_base)
        manager.set_provider_base_url(self.paths.config_path, "acme", settings.base_url)
        calls: list[tuple[str, object]] = []

        def fake_health(_settings):
            return {
                "ok": True,
                "pid": 9999,
                "proxy_base": settings.proxy_base,
                "upstream_base": settings.upstream_base,
                "service_tier": settings.service_tier,
                "service_tier_policy": settings.service_tier_policy,
                "service_tier_effective_policy": "preserve",
                "upstream_api_key_env": None,
                "upstream_api_key_file": True,
                "runtime_id": manager.RUNTIME_ID,
            }

        def fake_stop(_paths, force=False):
            calls.append(("stop", force))
            return {"status": "stopped", "pid": 9999}

        def fake_launch(_paths, launch_settings, _verbose_proxy, **_kwargs):
            calls.append(("launch", launch_settings.provider))
            return {"status": "started", "pid": 1234, "upstream_base": launch_settings.upstream_base}

        with (
            mock.patch("codex_fast_proxy.manager.verify_upstream_responses", return_value={"status": "verified"}),
            mock.patch("codex_fast_proxy.manager.current_process", return_value=(9999, True)),
            mock.patch("codex_fast_proxy.manager.proxy_health", side_effect=fake_health),
            mock.patch("codex_fast_proxy.manager.stop_process", side_effect=fake_stop),
            mock.patch("codex_fast_proxy.manager.wait_for_proxy_port_release"),
            mock.patch("codex_fast_proxy.manager.launch_background", side_effect=fake_launch),
        ):
            result = run_save_provider(
                str(self.codex_home),
                "acme",
                settings.upstream_base,
                "new-secret",
            )

        self.assertEqual(result["status"], "provider_saved")
        self.assertEqual(result["start_result"]["status"], "restarted")
        self.assertEqual(result["start_result"]["reason"], "provider_saved")
        self.assertEqual(calls, [("stop", True), ("launch", "acme")])

    def test_switch_provider_updates_proxy_settings_without_mutating_user_config(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_secret(self.paths, "acme", "acme-secret")
        manager.write_provider_auth_secret(self.paths, "other", "other-secret")
        self.paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            f'base_url = "{settings.base_url}"\n\n'
            "[model_providers.other]\n"
            'base_url = "https://api.other.test/v1"\n',
            encoding="utf-8",
        )
        with (
            mock.patch("codex_fast_proxy.manager.verify_upstream_responses", return_value={"status": "verified"}),
            mock.patch("codex_fast_proxy.manager.start_background", return_value={"status": "restarted", "pid": 1234}),
            mock.patch("codex_fast_proxy.manager.install_startup_hook", return_value={"status": "installed"}),
        ):
            result = run_switch_provider(str(self.codex_home), "other")

        config = manager.load_toml_config(self.paths.config_path)
        saved_settings = manager.read_settings(self.paths)

        self.assertEqual(result["status"], "provider_switched")
        self.assertFalse(result["config_changed"])
        self.assertEqual(saved_settings.provider, "other")
        self.assertEqual(saved_settings.upstream_base, "https://api.other.test/v1")
        self.assertEqual(config["model_provider"], "acme")
        self.assertEqual(manager.provider_base_url(config, "acme"), settings.base_url)
        self.assertEqual(manager.provider_base_url(config, "other"), "https://api.other.test/v1")

    def test_switch_provider_restarts_running_proxy_even_when_upstream_matches(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.shared.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_entry(self.paths, "acme", api_key="old-secret", base_url=settings.upstream_base)
        manager.write_provider_auth_entry(self.paths, "other", api_key="new-secret", base_url=settings.upstream_base)
        self.paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            f'base_url = "{settings.base_url}"\n\n'
            "[model_providers.other]\n"
            f'base_url = "{settings.upstream_base}"\n',
            encoding="utf-8",
        )
        calls: list[tuple[str, object]] = []

        def fake_health(_settings):
            return {
                "ok": True,
                "pid": 9999,
                "proxy_base": settings.proxy_base,
                "upstream_base": settings.upstream_base,
                "service_tier": settings.service_tier,
                "service_tier_policy": settings.service_tier_policy,
                "service_tier_effective_policy": "preserve",
                "upstream_api_key_env": None,
                "upstream_api_key_file": True,
                "runtime_id": manager.RUNTIME_ID,
            }

        def fake_stop(_paths, force=False):
            calls.append(("stop", force))
            return {"status": "stopped", "pid": 9999}

        def fake_launch(_paths, launch_settings, _verbose_proxy, **_kwargs):
            calls.append(("launch", launch_settings.provider))
            return {"status": "started", "pid": 1234, "upstream_base": launch_settings.upstream_base}

        with (
            mock.patch("codex_fast_proxy.manager.verify_upstream_responses", return_value={"status": "verified"}),
            mock.patch("codex_fast_proxy.manager.current_process", return_value=(9999, True)),
            mock.patch("codex_fast_proxy.manager.proxy_health", side_effect=fake_health),
            mock.patch("codex_fast_proxy.manager.stop_process", side_effect=fake_stop),
            mock.patch("codex_fast_proxy.manager.wait_for_proxy_port_release"),
            mock.patch("codex_fast_proxy.manager.launch_background", side_effect=fake_launch),
        ):
            result = run_switch_provider(str(self.codex_home), "other")

        self.assertEqual(result["status"], "provider_switched")
        self.assertEqual(result["start_result"]["status"], "restarted")
        self.assertEqual(result["start_result"]["reason"], "provider_switched")
        self.assertEqual(calls, [("stop", True), ("launch", "other")])

    def test_switch_provider_defers_restart_while_request_is_active(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_entry(self.paths, "acme", api_key="old-secret", base_url=settings.upstream_base)
        manager.write_provider_auth_entry(self.paths, "other", api_key="new-secret", base_url="https://api.other.test/v1")
        self.paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            f'base_url = "{settings.base_url}"\n\n'
            "[model_providers.other]\n"
            'base_url = "https://api.other.test/v1"\n',
            encoding="utf-8",
        )

        health = {
            "ok": True,
            "pid": 9999,
            "provider": "acme",
            "proxy_base": settings.proxy_base,
            "upstream_base": settings.upstream_base,
            "service_tier": settings.service_tier,
            "service_tier_policy": settings.service_tier_policy,
            "service_tier_effective_policy": "priority",
            "upstream_api_key_file": True,
            "runtime_id": manager.RUNTIME_ID,
            "activity": {"active_requests": 1, "active_streams": 1, "idle": False},
        }
        with (
            mock.patch("codex_fast_proxy.manager.verify_upstream_responses", return_value={"status": "verified"}),
            mock.patch("codex_fast_proxy.manager.current_process", return_value=(9999, True)),
            mock.patch("codex_fast_proxy.manager.proxy_health", return_value=health),
            mock.patch("codex_fast_proxy.manager.stop_process") as stop,
            mock.patch("codex_fast_proxy.manager.launch_background") as launch,
        ):
            result = run_switch_provider(str(self.codex_home), "other")

        saved_settings = manager.read_settings(self.paths)
        self.assertEqual(result["status"], "provider_switched")
        self.assertEqual(result["user_state"]["code"], "restart_deferred_active")
        self.assertEqual(result["user_state"]["title"], "切换已保存，等待当前请求结束")
        self.assertEqual(result["start_result"]["status"], "deferred")
        self.assertEqual(result["start_result"]["defer_reason"], "active_requests")
        self.assertEqual(saved_settings.provider, "other")
        stop.assert_not_called()
        launch.assert_not_called()

        snapshot = collect_status(str(self.codex_home), runtime_probe=lambda _paths, _settings: (
            9999,
            True,
            health,
            True,
            True,
            True,
        ))
        providers = {item["name"]: item for item in snapshot["providers"]}
        self.assertEqual(snapshot["runtime_upstream_provider"], "acme")
        self.assertEqual(snapshot["pending_upstream_provider"], "other")
        self.assertEqual(snapshot["current_provider"], "acme")
        self.assertTrue(providers["acme"]["current"])
        self.assertFalse(providers["other"]["current"])
        self.assertTrue(providers["other"]["pending"])
        html = render_page(snapshot, "token")
        self.assertIn("待应用", html)

    def test_switch_provider_waits_for_active_codex_turn_even_when_proxy_is_idle(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_entry(self.paths, "acme", api_key="old-secret", base_url=settings.upstream_base)
        manager.write_provider_auth_entry(self.paths, "other", api_key="new-secret", base_url="https://api.other.test/v1")
        self.paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            f'base_url = "{settings.base_url}"\n\n'
            "[model_providers.other]\n"
            'base_url = "https://api.other.test/v1"\n',
            encoding="utf-8",
        )
        record_codex_hook_event(self.paths, {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "cwd": str(self.temp_dir),
            "model": "gpt-5.5",
        })

        health = {
            "ok": True,
            "pid": 9999,
            "provider": "acme",
            "proxy_base": settings.proxy_base,
            "upstream_base": settings.upstream_base,
            "service_tier": settings.service_tier,
            "service_tier_policy": settings.service_tier_policy,
            "service_tier_effective_policy": "priority",
            "upstream_api_key_file": True,
            "runtime_id": manager.RUNTIME_ID,
            "activity": {"active_requests": 0, "active_streams": 0, "idle": True},
        }
        with (
            mock.patch("codex_fast_proxy.manager.verify_upstream_responses", return_value={"status": "verified"}),
            mock.patch("codex_fast_proxy.manager.current_process", return_value=(9999, True)),
            mock.patch("codex_fast_proxy.manager.proxy_health", return_value=health),
            mock.patch("codex_fast_proxy.manager.stop_process") as stop,
            mock.patch("codex_fast_proxy.manager.launch_background") as launch,
        ):
            result = run_switch_provider(str(self.codex_home), "other")

        self.assertEqual(result["start_result"]["status"], "deferred")
        self.assertEqual(result["start_result"]["defer_reason"], "active_codex_turns")
        self.assertEqual(result["start_result"]["codex_activity"]["active_turns"], 1)
        stop.assert_not_called()
        launch.assert_not_called()

        with mock.patch("codex_fast_proxy.state.start_background") as start:
            snapshot = collect_status(str(self.codex_home), apply_idle_pending=True, runtime_probe=lambda _paths, _settings: (
                9999,
                True,
                health,
                True,
                True,
                True,
            ))
        start.assert_not_called()
        self.assertTrue(snapshot["settings_pending"])
        self.assertEqual(snapshot["codex_activity"]["active_turns"], 1)
        html = render_page(snapshot, "token")
        self.assertIn("还有 1 个 Codex 请求未完成", html)

    def test_stop_hook_allows_idle_pending_settings_to_apply(self) -> None:
        settings = manager.ProxySettings(
            provider="other",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.other.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        record_codex_hook_event(self.paths, {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-1",
            "turn_id": "turn-1",
        })
        record_codex_hook_event(self.paths, {
            "hook_event_name": "Stop",
            "session_id": "session-1",
            "turn_id": "turn-1",
        })
        health = {
            "ok": True,
            "pid": 9999,
            "provider": "acme",
            "proxy_base": settings.proxy_base,
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": settings.service_tier,
            "service_tier_policy": settings.service_tier_policy,
            "service_tier_effective_policy": "priority",
            "upstream_api_key_file": True,
            "runtime_id": manager.RUNTIME_ID,
            "activity": {"active_requests": 0, "active_streams": 0, "idle": True},
        }

        with mock.patch("codex_fast_proxy.state.start_background", return_value={"status": "started"}) as start:
            snapshot = collect_status(str(self.codex_home), apply_idle_pending=True, runtime_probe=lambda _paths, _settings: (
                9999,
                True,
                health,
                True,
                True,
                True,
            ))

        start.assert_called_once()
        self.assertEqual(snapshot["codex_activity"]["active_turns"], 0)

    def test_save_current_provider_key_defers_as_pending_settings(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_entry(self.paths, "acme", api_key="old-secret", base_url=settings.upstream_base)
        self.paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            f'base_url = "{settings.base_url}"\n',
            encoding="utf-8",
        )
        old_revision = json.loads(self.paths.settings_path.read_text(encoding="utf-8"))["settings_revision"]
        health = {
            "ok": True,
            "pid": 9999,
            "provider": "acme",
            "settings_revision": old_revision,
            "proxy_base": settings.proxy_base,
            "upstream_base": settings.upstream_base,
            "service_tier": settings.service_tier,
            "service_tier_policy": settings.service_tier_policy,
            "service_tier_effective_policy": "preserve",
            "upstream_api_key_file": True,
            "runtime_id": manager.RUNTIME_ID,
            "activity": {"active_requests": 1, "active_streams": 1, "idle": False},
        }

        with (
            mock.patch("codex_fast_proxy.manager.verify_upstream_responses", return_value={"status": "verified"}),
            mock.patch("codex_fast_proxy.manager.current_process", return_value=(9999, True)),
            mock.patch("codex_fast_proxy.manager.proxy_health", return_value=health),
            mock.patch("codex_fast_proxy.manager.stop_process") as stop,
            mock.patch("codex_fast_proxy.manager.launch_background") as launch,
        ):
            result = run_save_provider(str(self.codex_home), "acme", settings.upstream_base, "new-secret")

        self.assertEqual(result["status"], "provider_saved")
        self.assertEqual(result["user_state"]["code"], "restart_deferred_active")
        self.assertEqual(result["start_result"]["status"], "deferred")
        stop.assert_not_called()
        launch.assert_not_called()

        snapshot = collect_status(str(self.codex_home), runtime_probe=lambda _paths, _settings: (
            9999,
            True,
            health,
            True,
            True,
            True,
        ))
        providers = {item["name"]: item for item in snapshot["providers"]}
        self.assertTrue(snapshot["settings_pending"])
        self.assertEqual(snapshot["pending_upstream_provider"], "acme")
        self.assertTrue(providers["acme"]["current"])
        self.assertTrue(providers["acme"]["pending"])
        html = render_page(snapshot, "token")
        self.assertIn("使用中", html)
        self.assertIn("待应用", html)

    def test_speed_mode_defer_shows_runtime_speed_with_pending_setting(self) -> None:
        (self.codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "provider-secret"}), encoding="utf-8")
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            service_tier_policy="preserve",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_entry(self.paths, "acme", api_key="old-secret", base_url=settings.upstream_base)
        manager.set_provider_base_url(self.paths.config_path, "acme", settings.base_url)
        old_revision = json.loads(self.paths.settings_path.read_text(encoding="utf-8"))["settings_revision"]
        health = {
            "ok": True,
            "pid": 9999,
            "provider": "acme",
            "settings_revision": old_revision,
            "proxy_base": settings.proxy_base,
            "upstream_base": settings.upstream_base,
            "service_tier": settings.service_tier,
            "service_tier_policy": "preserve",
            "service_tier_effective_policy": "preserve",
            "upstream_api_key_file": True,
            "runtime_id": manager.RUNTIME_ID,
            "activity": {"active_requests": 1, "active_streams": 1, "idle": False},
        }

        with (
            mock.patch("codex_fast_proxy.manager.verify_upstream_responses", return_value={"status": "verified"}),
            mock.patch("codex_fast_proxy.manager.current_process", return_value=(9999, True)),
            mock.patch("codex_fast_proxy.manager.proxy_health", return_value=health),
            mock.patch("codex_fast_proxy.manager.stop_process") as stop,
            mock.patch("codex_fast_proxy.manager.launch_background") as launch,
        ):
            result = run_set_speed_mode(str(self.codex_home), "fast")

        self.assertEqual(result["user_state"]["code"], "restart_deferred_active")
        stop.assert_not_called()
        launch.assert_not_called()

        snapshot = collect_status(str(self.codex_home), runtime_probe=lambda _paths, _settings: (
            9999,
            True,
            health,
            True,
            True,
            True,
        ))
        self.assertTrue(snapshot["settings_pending"])
        self.assertEqual(snapshot["runtime_fast_behavior"], "preserve_only")
        self.assertEqual(snapshot["fast_behavior"], "auto_global_priority")
        html = render_page(snapshot, "token")
        self.assertIn("标准 · 待应用快速", html)

    def test_runtime_mismatch_detects_provider_change_with_same_upstream_url(self) -> None:
        settings = manager.ProxySettings(
            provider="other",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.shared.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        health = {
            "ok": True,
            "pid": 9999,
            "provider": "acme",
            "proxy_base": "/v1",
            "upstream_base": "https://api.shared.test/v1",
            "service_tier": "priority",
            "service_tier_policy": settings.service_tier_policy,
            "service_tier_effective_policy": "priority",
            "upstream_api_key_file": True,
        }

        self.assertFalse(health_matches_settings(health, settings, "priority"))

    def test_write_settings_preserves_revision_for_noop_and_bumps_when_forced(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
        )
        manager.write_settings(self.paths, settings)
        first_revision = json.loads(self.paths.settings_path.read_text(encoding="utf-8"))["settings_revision"]

        manager.write_settings(self.paths, settings)
        second_revision = json.loads(self.paths.settings_path.read_text(encoding="utf-8"))["settings_revision"]
        manager.write_settings(self.paths, settings, bump_revision=True)
        third_revision = json.loads(self.paths.settings_path.read_text(encoding="utf-8"))["settings_revision"]

        self.assertEqual(second_revision, first_revision)
        self.assertNotEqual(third_revision, first_revision)

    def test_delete_provider_removes_saved_entry_without_mutating_user_config(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_secret(self.paths, "acme", "acme-secret")
        manager.write_provider_auth_entry(self.paths, "other", api_key="other-secret", base_url="https://api.other.test/v1")
        self.paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            f'base_url = "{settings.base_url}"\n\n'
            "[model_providers.other]\n"
            'base_url = "https://api.other.test/v1"\n',
            encoding="utf-8",
        )
        config_before = self.paths.config_path.read_bytes()

        result = run_delete_provider(str(self.codex_home), "other")

        stored_auth = json.loads(self.paths.provider_auth_path.read_text(encoding="utf-8"))
        config = manager.load_toml_config(self.paths.config_path)

        self.assertEqual(result["status"], "provider_deleted")
        self.assertFalse(result["config_changed"])
        self.assertEqual(self.paths.config_path.read_bytes(), config_before)
        self.assertNotIn("other", stored_auth["providers"])
        self.assertEqual(manager.provider_base_url(config, "other"), "https://api.other.test/v1")

    def test_delete_provider_rejects_current_provider(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_secret(self.paths, "acme", "acme-secret")

        with self.assertRaises(manager.ConfigError):
            run_delete_provider(str(self.codex_home), "acme")

    def test_delete_provider_allows_inactive_config_provider_saved_entry(self) -> None:
        settings = manager.ProxySettings(
            provider="other",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.other.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.write_provider_auth_entry(self.paths, "acme", api_key="acme-secret", base_url="https://api.acme.test/v1")
        manager.write_provider_auth_entry(self.paths, "other", api_key="other-secret", base_url="https://api.other.test/v1")
        self.paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            f'base_url = "{settings.base_url}"\n',
            encoding="utf-8",
        )

        result = run_delete_provider(str(self.codex_home), "acme")

        stored_auth = json.loads(self.paths.provider_auth_path.read_text(encoding="utf-8"))
        config = manager.load_toml_config(self.paths.config_path)
        self.assertEqual(result["status"], "provider_deleted")
        self.assertNotIn("acme", stored_auth["providers"])
        self.assertEqual(manager.provider_base_url(config, "acme"), settings.base_url)

    def test_set_speed_mode_saves_standard_without_provider_change(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
        )
        manager.write_settings(self.paths, settings)
        manager.set_provider_base_url(self.paths.config_path, "acme", settings.base_url)
        original_verify = manager.verify_upstream_responses
        original_start = manager.start_background
        manager.verify_upstream_responses = lambda *_args, **_kwargs: {"status": "verified", "response_status": 200}
        manager.start_background = lambda *_args, **_kwargs: {"status": "started", "pid": 1234}
        try:
            result = run_set_speed_mode(str(self.codex_home), "standard")
        finally:
            manager.verify_upstream_responses = original_verify
            manager.start_background = original_start

        saved_settings = manager.read_settings(self.paths)

        self.assertEqual(result["status"], "upstream_updated")
        self.assertEqual(result["user_state"]["code"], "speed_saved")
        self.assertEqual(saved_settings.upstream_base, "https://api.acme.test/v1")
        self.assertEqual(saved_settings.service_tier_policy, "preserve")

    def test_configure_upstream_restores_previous_provider_auth_when_verification_fails(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )
        manager.write_settings(self.paths, settings)
        manager.set_provider_base_url(self.paths.config_path, "acme", settings.base_url)
        manager.write_provider_auth_secret(self.paths, "acme", "old-provider-secret")
        original_verify = manager.verify_upstream_responses
        manager.verify_upstream_responses = mock.Mock(side_effect=manager.ConfigError("verification failed"))
        try:
            with self.assertRaises(manager.ConfigError):
                run_configure_upstream(
                    str(self.codex_home),
                    "https://api.new.test/v1",
                    "new-provider-secret",
                )
        finally:
            manager.verify_upstream_responses = original_verify

        stored_auth = json.loads(self.paths.provider_auth_path.read_text(encoding="utf-8"))
        saved_settings = manager.read_settings(self.paths)
        self.assertEqual(stored_auth["providers"]["acme"]["api_key"], "old-provider-secret")
        self.assertEqual(saved_settings.upstream_base, "https://api.acme.test/v1")

    def test_ui_command_can_be_parsed_without_opening_browser(self) -> None:
        args = manager.build_parser().parse_args(["ui"])

        self.assertEqual(args.command, "ui")
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8786)

    def test_ui_command_uses_control_ui_launcher(self) -> None:
        with mock.patch("codex_fast_proxy.control_ui.open_control_ui") as open_ui:
            open_ui.return_value = {"status": "ready", "url": "http://127.0.0.1:8786/"}
            exit_code = manager.command_ui(
                manager.build_parser().parse_args(["ui", "--codex-home", str(self.codex_home)])
            )

        self.assertEqual(exit_code, 0)
        open_ui.assert_called_once_with(str(self.codex_home), None, "127.0.0.1", 8786)

    def test_ui_command_returns_error_when_no_control_port_is_available(self) -> None:
        with mock.patch("codex_fast_proxy.control_ui.open_control_ui") as open_ui:
            open_ui.return_value = {"status": "error", "code": "control_ui_port_unavailable"}
            exit_code = manager.command_ui(
                manager.build_parser().parse_args(["ui", "--codex-home", str(self.codex_home)])
            )

        self.assertEqual(exit_code, 2)

    def test_open_control_ui_returns_external_browser_instruction_by_default(self) -> None:
        with (
            mock.patch("codex_fast_proxy.control_ui.find_existing_control_ui", return_value=None),
            mock.patch("codex_fast_proxy.control_ui.find_available_port", return_value=8786),
            mock.patch("codex_fast_proxy.control_ui.start_background_server", return_value={"status": "started"}),
            mock.patch("codex_fast_proxy.control_ui.wait_for_status", return_value=True),
        ):
            result = open_control_ui(str(self.codex_home), None, "127.0.0.1", 8786)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["url"], "http://127.0.0.1:8786/")
        self.assertEqual(result["open_instruction"], "请在外部浏览器中打开：http://127.0.0.1:8786/")
        self.assertTrue(result["background_process"])
        self.assertTrue(result["started_background_process"])
        self.assertFalse(result["reused_existing"])
        self.assertIn("approval", result["approval_reason"])

    def test_open_control_ui_reuses_existing_server(self) -> None:
        with (
            mock.patch("codex_fast_proxy.control_ui.find_existing_control_ui", return_value=8789) as find_existing,
            mock.patch("codex_fast_proxy.control_ui.find_available_port") as find_port,
            mock.patch("codex_fast_proxy.control_ui.start_background_server") as start_server,
        ):
            result = open_control_ui(str(self.codex_home), None, "127.0.0.1", 8786)

        find_port.assert_not_called()
        start_server.assert_not_called()
        find_existing.assert_called_once_with(
            "127.0.0.1",
            8786,
            identity=control_ui_identity(str(self.codex_home), None),
            attempts=100,
            probe_timeout=0.2,
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["url"], "http://127.0.0.1:8789/")
        self.assertFalse(result["started_background_process"])
        self.assertTrue(result["reused_existing"])

    def test_find_existing_control_ui_requires_matching_identity(self) -> None:
        identity = control_ui_identity(str(self.codex_home), "acme")

        def fake_probe(_host: str, port: int, **kwargs: object) -> bool:
            return port == 8788 and kwargs["identity"] == identity

        with mock.patch("codex_fast_proxy.control_ui.probe_control_ui", side_effect=fake_probe):
            port = find_existing_control_ui("127.0.0.1", 8786, identity=identity, attempts=4)

        self.assertEqual(port, 8788)

    def test_hook_control_ui_start_uses_short_best_effort_path(self) -> None:
        with (
            mock.patch("codex_fast_proxy.control_ui.find_existing_control_ui", return_value=None) as find_existing,
            mock.patch("codex_fast_proxy.control_ui.find_available_port", return_value=8786),
            mock.patch("codex_fast_proxy.control_ui.start_background_server", return_value={"status": "started", "pid": 1234}),
            mock.patch("codex_fast_proxy.control_ui.wait_for_status") as wait_for_status,
        ):
            result = ensure_control_ui_for_hook(str(self.codex_home), None, "127.0.0.1", 8786)

        find_existing.assert_called_once_with(
            "127.0.0.1",
            8786,
            identity=control_ui_identity(str(self.codex_home), None),
            attempts=8,
            probe_timeout=0.05,
        )
        wait_for_status.assert_not_called()
        self.assertEqual(result["status"], "starting")
        self.assertEqual(result["url"], "http://127.0.0.1:8786/")
        self.assertTrue(result["started_background_process"])
        self.assertFalse(result["ready_waited"])

    def test_loopback_host_parses_ipv6_bracket_host_header(self) -> None:
        self.assertTrue(is_loopback_host("[::1]:8786"))
        self.assertTrue(is_loopback_host("::1"))
        self.assertFalse(is_loopback_host("[2001:db8::1]:8786"))

    def test_open_control_ui_reports_when_ports_are_unavailable(self) -> None:
        with (
            mock.patch("codex_fast_proxy.control_ui.find_existing_control_ui", return_value=None),
            mock.patch("codex_fast_proxy.control_ui.find_available_port", return_value=None),
            mock.patch("codex_fast_proxy.control_ui.start_background_server") as start_server,
        ):
            result = open_control_ui(str(self.codex_home), None, "127.0.0.1", 8786)

        start_server.assert_not_called()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "control_ui_port_unavailable")
        self.assertIsNone(result["url"])
        self.assertIn("没有找到可用的本地控制台端口", result["error"])

    def test_open_control_ui_reports_when_background_server_does_not_start(self) -> None:
        with (
            mock.patch("codex_fast_proxy.control_ui.find_existing_control_ui", return_value=None),
            mock.patch("codex_fast_proxy.control_ui.find_available_port", return_value=8786),
            mock.patch("codex_fast_proxy.control_ui.start_background_server", return_value={"status": "started"}),
            mock.patch("codex_fast_proxy.control_ui.wait_for_status", return_value=False),
        ):
            result = open_control_ui(str(self.codex_home), None, "127.0.0.1", 8786)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "control_ui_start_failed")
        self.assertEqual(result["url"], "http://127.0.0.1:8786/")
        self.assertIsNone(result["open_instruction"])

    def test_background_server_detaches_standard_input_and_hides_windows_console(self) -> None:
        with (
            mock.patch("codex_fast_proxy.control_ui.is_windows_platform", return_value=True),
            mock.patch("codex_fast_proxy.control_ui.subprocess.Popen") as popen,
        ):
            popen.return_value.pid = 1234
            start_background_server(str(self.codex_home), None, "127.0.0.1", 8786)

        stdout_path, stderr_path, pid_path = control_ui_runtime_paths(str(self.codex_home))
        self.assertEqual(popen.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(Path(popen.call_args.kwargs["stdout"].name), stdout_path)
        self.assertEqual(Path(popen.call_args.kwargs["stderr"].name), stderr_path)
        self.assertTrue(popen.call_args.kwargs["stdout"].closed)
        self.assertTrue(popen.call_args.kwargs["stderr"].closed)
        self.assertEqual(popen.call_args.kwargs["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertFalse(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(pid_path.read_text(encoding="utf-8").strip(), "1234")

    def test_background_server_reports_launch_failure(self) -> None:
        with mock.patch("codex_fast_proxy.control_ui.subprocess.Popen", side_effect=OSError("boom")):
            result = start_background_server(str(self.codex_home), None, "127.0.0.1", 8786)

        stdout_path, stderr_path, pid_path = control_ui_runtime_paths(str(self.codex_home))
        self.assertEqual(result["status"], "error")
        self.assertIn("boom", result["error"])
        self.assertEqual(result["stdout"], str(stdout_path))
        self.assertEqual(result["stderr"], str(stderr_path))
        self.assertFalse(pid_path.exists())

    def test_schedule_path_cleanup_uses_detached_python_process(self) -> None:
        with mock.patch("codex_fast_proxy.control_ui.subprocess.Popen") as popen:
            popen.return_value.pid = 1234
            result = schedule_path_cleanup(self.paths.app_home, delay=0.1)

        command = popen.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1], "-c")
        self.assertIn("shutil.rmtree", command[2])
        self.assertEqual(command[3], str(self.paths.app_home))
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["pid"], 1234)

    def test_schedule_install_cleanup_unlinks_skill_uninstalls_package_and_delays_removal(self) -> None:
        cleanup = {
            "mode": "deep_install_removal",
            "app_home": str(self.paths.app_home),
            "repo_root": str(self.codex_home / "codex-fast-proxy"),
            "backup_dir": str(self.paths.backup_dir),
            "package": "codex-fast-proxy",
        }
        with mock.patch("codex_fast_proxy.control_ui.subprocess.Popen") as popen:
            popen.return_value.pid = 1234
            result = schedule_install_cleanup(cleanup, delay=0.1)

        command = popen.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1], "-c")
        self.assertIn("pip", command[2])
        self.assertIn("uninstall", command[2])
        self.assertEqual(command[3], "0.1")
        self.assertIn(str(self.paths.app_home), command)
        self.assertIn(str(self.codex_home / "codex-fast-proxy"), command)
        self.assertIn(str(self.paths.backup_dir), command)
        self.assertIn("codex-fast-proxy", command)
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["mode"], "deep_install_removal")
        self.assertEqual(result["delay_seconds"], 0.1)

    def test_schedule_control_ui_restart_reuses_current_port(self) -> None:
        with mock.patch("codex_fast_proxy.control_ui.subprocess.Popen") as popen:
            popen.return_value.pid = 1234
            result = schedule_control_ui_restart(str(self.codex_home), "acme", "127.0.0.1", 8786, delay=0.1)

        command = popen.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertIn("codex_fast_proxy", command)
        self.assertIn("8786", command)
        self.assertIn("--provider", command)
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["url"], "http://127.0.0.1:8786/")
        self.assertTrue(result["same_port"])
        self.assertEqual(result["reload_after_ms"], 0)
        self.assertEqual(result["reload_timeout_ms"], 8000)
        self.assertTrue(result["wait_for_disconnect"])

    def test_find_available_port_skips_reserved_proxy_port(self) -> None:
        bound_ports: list[int] = []

        class DummySocket:
            def settimeout(self, _timeout: float) -> None:
                return None

            def bind(self, address: tuple[str, int]) -> None:
                _, port = address
                bound_ports.append(port)
                if port in {8786, 8788}:
                    raise OSError("busy")

            def __enter__(self) -> "DummySocket":
                return self

            def __exit__(self, _exc_type, _exc, _tb) -> None:
                return None

        with mock.patch("codex_fast_proxy.ports.socket.socket", return_value=DummySocket()):
            port = find_available_port("127.0.0.1", 8786, reserved_ports={8787})

        self.assertEqual(port, 8789)
        self.assertNotIn(8787, bound_ports)


if __name__ == "__main__":
    unittest.main()
