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
from codex_fast_proxy.actions import run_configure_upstream, run_first_run_enable  # noqa: E402
from codex_fast_proxy.control_ui import open_control_ui, render_page, start_background_server  # noqa: E402
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
        self.assertIn("保存并验证", html)
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
            mock.patch("codex_fast_proxy.control_ui.find_available_port", return_value=8786),
            mock.patch("codex_fast_proxy.control_ui.start_background_server", return_value=True),
            mock.patch("codex_fast_proxy.control_ui.wait_for_status", return_value=True),
        ):
            result = open_control_ui(str(self.codex_home), None, "127.0.0.1", 8786)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["url"], "http://127.0.0.1:8786/")
        self.assertEqual(result["open_instruction"], "请在外部浏览器中打开：http://127.0.0.1:8786/")

    def test_open_control_ui_reports_when_ports_are_unavailable(self) -> None:
        with (
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
            mock.patch("codex_fast_proxy.control_ui.find_available_port", return_value=8786),
            mock.patch("codex_fast_proxy.control_ui.start_background_server", return_value=True),
            mock.patch("codex_fast_proxy.control_ui.wait_for_status", return_value=False),
        ):
            result = open_control_ui(str(self.codex_home), None, "127.0.0.1", 8786)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "control_ui_start_failed")
        self.assertEqual(result["url"], "http://127.0.0.1:8786/")
        self.assertIsNone(result["open_instruction"])

    def test_background_server_uses_detached_windows_process_flags(self) -> None:
        with (
            mock.patch("codex_fast_proxy.control_ui.os.name", "nt"),
            mock.patch("codex_fast_proxy.control_ui.subprocess.Popen") as popen,
        ):
            start_background_server(str(self.codex_home), None, "127.0.0.1", 8786)

        flags = popen.call_args.kwargs["creationflags"]
        self.assertTrue(flags & subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(flags & subprocess.DETACHED_PROCESS)

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
