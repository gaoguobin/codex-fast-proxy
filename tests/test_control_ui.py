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
from codex_fast_proxy.actions import (  # noqa: E402
    run_configure_upstream,
    run_first_run_enable,
    run_uninstall,
    run_update,
)
from codex_fast_proxy.control_ui import (  # noqa: E402
    ControlHandler,
    control_ui_identity,
    control_ui_runtime_paths,
    find_existing_control_ui,
    is_loopback_host,
    open_control_ui,
    render_page,
    schedule_path_cleanup,
    start_background_server,
    user_error_message,
)
from codex_fast_proxy.ports import find_available_port  # noqa: E402
from codex_fast_proxy.state import collect_status  # noqa: E402


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
        self.assertEqual(snapshot["user_state"]["title"], "已停用，完成清理")
        self.assertEqual(snapshot["user_state"]["primary_action"], "uninstall")

    def test_control_page_is_chinese_and_warns_about_codex_embedded_browser(self) -> None:
        html = render_page(
            {
                "base_url": "http://127.0.0.1:8787/v1",
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
        self.assertIn("启用", html)
        self.assertIn("更新", html)
        self.assertIn("停用并恢复", html)
        self.assertIn("当前模型服务", html)
        self.assertIn("模型服务地址", html)
        self.assertNotIn("本地入口", html)
        self.assertNotIn("providerProxy", html)
        self.assertIn("保存并验证", html)
        self.assertIn("速度模式", html)
        self.assertIn('name="speedMode" value="fast" checked', html)
        self.assertIn('name="speedMode" value="standard"', html)
        self.assertIn("重启 Codex 前请用外部浏览器打开此页面", html)
        self.assertIn("正在准备环境", html)
        self.assertIn('const token = "token";', html)
        self.assertNotIn("&quot;token&quot;", html)

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

        self.assertNotIn("停用并恢复", html)
        self.assertNotIn("保存并验证", html)
        self.assertNotIn("速度模式", html)

    def test_control_page_cleanup_state_uses_single_primary_button(self) -> None:
        html = render_page(
            {
                "base_url": "http://127.0.0.1:8787/v1",
                "upstream_base": "https://api.acme.test/v1",
                "user_state": {
                    "code": "cleanup_pending",
                    "title": "已停用，完成清理",
                    "message": "Codex 已恢复到原模型服务。",
                    "primary_action": "uninstall",
                    "primary_label": "完成清理",
                },
            },
            "token",
        )

        self.assertIn('data-action="uninstall"', html)
        self.assertIn("完成清理", html)
        self.assertIn("else if (action === 'uninstall') await runButton", html)
        self.assertNotIn("保存并验证", html)
        self.assertNotIn("停用并恢复", html)

    def test_control_page_restores_maintenance_button_labels_after_action(self) -> None:
        html = render_page(
            {
                "base_url": "http://127.0.0.1:8787/v1",
                "upstream_base": "https://api.acme.test/v1",
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
        self.assertIn('"confirmUninstall": "我知道可能导致模型请求失败，仍要停用"', html)
        self.assertIn('"saveConfig": "保存并验证"', html)
        self.assertIn("resetControls(userState);", html)
        self.assertIn("resetSummary(snapshot);", html)
        self.assertIn('value="https://api.acme.test/v1"', html)
        self.assertIn("resetForm(snapshot);", html)
        self.assertIn("speed_mode: selectedSpeedMode()", html)
        self.assertIn("window.location.href = data.action.control_ui.url;", html)

    def test_control_page_maps_preserve_policy_to_standard_speed_mode(self) -> None:
        html = render_page(
            {
                "base_url": "http://127.0.0.1:8787/v1",
                "upstream_base": "https://api.acme.test/v1",
                "config_matches": True,
                "healthy": False,
                "service_tier_policy": "preserve",
                "user_state": {
                    "title": "运行正常",
                    "message": "Codex 已准备好继续使用当前模型服务。",
                    "primary_action": "diagnostics",
                },
            },
            "token",
        )

        self.assertIn('name="speedMode" value="standard" checked', html)
        self.assertIn('name="speedMode" value="fast"', html)
        self.assertIn("需处理", html)

    def test_configure_upstream_errors_are_user_facing(self) -> None:
        message = user_error_message(
            "configure-upstream",
            {"upstream_base": "https://api.acme.test/v1"},
        )

        self.assertEqual(message, "没有保存。新的模型服务没有通过验证，当前仍在使用：https://api.acme.test/v1")
        self.assertNotIn("HTTP 404", message)

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

    def test_update_control_action_starts_replacement_ui(self) -> None:
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
            mock.patch.object(handler, "start_replacement_control_ui", return_value={
                "status": "ready",
                "url": "http://127.0.0.1:8788/",
            }),
        ):
            response = handler.run_action("update")

        self.assertTrue(response["shutdown_control_ui"])
        self.assertEqual(response["action"]["control_ui"]["url"], "http://127.0.0.1:8788/")

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
        self.assertIn("API Key", result["user_state"]["message"])
        self.assertNotIn("401", result["user_state"]["message"])

    def test_uninstall_cleanup_keeps_state_until_control_ui_shutdown(self) -> None:
        captured: dict[str, object] = {}

        def fake_uninstall(args: object) -> tuple[dict[str, object], int]:
            captured["args"] = args
            return {"status": "uninstalled", "stop_result": {"status": "stopped"}}, 0

        with (
            mock.patch("codex_fast_proxy.manager.enabled_installation", return_value=(False, "acme")),
            mock.patch("codex_fast_proxy.manager.uninstall_result", side_effect=fake_uninstall),
        ):
            result = run_uninstall(str(self.codex_home))

        args = captured["args"]
        self.assertTrue(getattr(args, "keep_state"))
        self.assertFalse(getattr(args, "defer_stop"))
        self.assertEqual(result["user_state"]["title"], "已清理完成")
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
        self.assertIn("我知道可能导致模型请求失败，仍要停用", html)
        self.assertIn("uninstall.style.display = userState.code === 'confirmation_required' ? 'none'", html)

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

    def test_configure_upstream_can_save_standard_speed_mode_only(self) -> None:
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
            result = run_configure_upstream(str(self.codex_home), None, None, "standard")
        finally:
            manager.verify_upstream_responses = original_verify
            manager.start_background = original_start

        saved_settings = manager.read_settings(self.paths)

        self.assertEqual(result["status"], "upstream_updated")
        self.assertEqual(result["user_state"]["code"], "configured")
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
            mock.patch("codex_fast_proxy.control_ui.os.name", "nt"),
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
