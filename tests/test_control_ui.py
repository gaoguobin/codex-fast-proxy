from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_fast_proxy import manager  # noqa: E402
from codex_fast_proxy.actions import run_first_run_enable  # noqa: E402
from codex_fast_proxy.control_ui import open_control_ui, render_page  # noqa: E402
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
        self.assertIn("重启 Codex 前请用外部浏览器打开此页面", html)
        self.assertIn("正在准备环境", html)
        self.assertIn('const token = "token";', html)
        self.assertNotIn("&quot;token&quot;", html)

    def test_first_run_enable_prepares_provider_auth_and_installs_without_printing_secret(self) -> None:
        (self.codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "provider-secret"}), encoding="utf-8")
        original_verify = manager.verify_upstream_responses
        original_start = manager.start_background
        manager.verify_upstream_responses = lambda *_args, **_kwargs: {"status": "verified", "response_status": 200}
        manager.start_background = lambda *_args, **_kwargs: {"status": "started", "pid": 1234}
        try:
            result = run_first_run_enable(str(self.codex_home))
        finally:
            manager.verify_upstream_responses = original_verify
            manager.start_background = original_start

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

    def test_ui_command_can_be_parsed_without_opening_browser(self) -> None:
        args = manager.build_parser().parse_args(["ui"])

        self.assertEqual(args.command, "ui")
        self.assertFalse(args.open_browser)
        self.assertFalse(args.no_open)
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8786)

    def test_ui_command_uses_control_ui_launcher(self) -> None:
        with mock.patch("codex_fast_proxy.control_ui.open_control_ui") as open_ui:
            open_ui.return_value = {"status": "ready", "url": "http://127.0.0.1:8786/"}
            exit_code = manager.command_ui(
                manager.build_parser().parse_args(["ui", "--codex-home", str(self.codex_home), "--no-open"])
            )

        self.assertEqual(exit_code, 0)
        open_ui.assert_called_once_with(str(self.codex_home), None, "127.0.0.1", 8786, False)

    def test_open_control_ui_returns_external_browser_instruction_by_default(self) -> None:
        with (
            mock.patch("codex_fast_proxy.control_ui.find_available_port", return_value=None),
            mock.patch("codex_fast_proxy.control_ui.webbrowser.open") as browser_open,
        ):
            result = open_control_ui(str(self.codex_home), None, "127.0.0.1", 8786, False)

        browser_open.assert_not_called()
        self.assertEqual(result["status"], "ready")
        self.assertFalse(result["opened_external_browser"])
        self.assertEqual(result["url"], "http://127.0.0.1:8786/")
        self.assertEqual(result["open_instruction"], "请在外部浏览器中打开：http://127.0.0.1:8786/")


if __name__ == "__main__":
    unittest.main()
