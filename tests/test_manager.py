from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import codex_fast_proxy.manager as manager  # noqa: E402
from codex_fast_proxy.manager import (  # noqa: E402
    autostart_proxy,
    choose_provider,
    command_install,
    command_stop,
    command_uninstall,
    ConfigError,
    doctor_report,
    has_startup_hook,
    install_startup_hook,
    load_toml_config,
    paths_for,
    provider_base_url,
    read_hooks,
    set_provider_base_url,
    stop_process,
)


class ManagerConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_root = ROOT / ".test_tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp_dir = temp_root / f"codex-fast-proxy-test-{uuid.uuid4().hex}"
        self.temp_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def test_choose_provider_uses_active_provider(self) -> None:
        config = {
            "model_provider": "acme",
            "model_providers": {
                "acme": {"base_url": "https://api.acme.test/v1"},
                "other": {"base_url": "https://api.other.test/v1"},
            },
        }

        self.assertEqual(choose_provider(config, None), "acme")

    def test_set_provider_base_url_preserves_other_provider(self) -> None:
        config_path = self.temp_dir / "config.toml"
        config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n'
            'api_key_env_var = "ACME_API_KEY"\n\n'
            "[model_providers.other]\n"
            'base_url = "https://api.other.test/v1"\n',
            encoding="utf-8",
        )

        set_provider_base_url(config_path, "acme", "http://127.0.0.1:8787/v1")
        config = load_toml_config(config_path)

        self.assertEqual(provider_base_url(config, "acme"), "http://127.0.0.1:8787/v1")
        self.assertEqual(provider_base_url(config, "other"), "https://api.other.test/v1")
        self.assertEqual(config["model_providers"]["acme"]["api_key_env_var"], "ACME_API_KEY")

    def test_runtime_state_dir_does_not_collide_with_default_repo_install_dir(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)

        self.assertEqual(paths.app_home, codex_home / "codex-fast-proxy-state")
        self.assertNotEqual(paths.app_home, codex_home / "codex-fast-proxy")

    def install_args(self, codex_home: Path, *, start: bool = True, prepare_only: bool = False) -> argparse.Namespace:
        return argparse.Namespace(
            codex_home=str(codex_home),
            provider=None,
            activate_provider=False,
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base=None,
            service_tier="priority",
            start=start,
            prepare_only=prepare_only,
            verbose_proxy=False,
        )

    def test_prepare_only_saves_upstream_without_switching_config(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        original = (
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n'
        )
        config_path.write_text(original, encoding="utf-8")

        install_args = self.install_args(codex_home, start=False, prepare_only=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(command_install(install_args), 0)

        paths = paths_for(codex_home)
        settings = json.loads(paths.settings_path.read_text(encoding="utf-8"))
        config = load_toml_config(config_path)
        self.assertEqual(settings["provider"], "acme")
        self.assertEqual(settings["upstream_base"], "https://api.acme.test/v1")
        self.assertEqual(provider_base_url(config, "acme"), "https://api.acme.test/v1")

    def test_install_without_start_is_rejected(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        (codex_home / "config.toml").write_text(
            'model_provider = "acme"\n\n[model_providers.acme]\nbase_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )

        with self.assertRaises(ConfigError):
            command_install(self.install_args(codex_home, start=False))

    def test_install_sets_active_provider_when_config_has_none(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        config_path.write_text(
            '[model_providers.acme]\nbase_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        manager.start_background = fake_start_background
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)
        finally:
            manager.start_background = original_start_background

        config = load_toml_config(config_path)
        self.assertEqual(config["model_provider"], "acme")
        self.assertEqual(provider_base_url(config, "acme"), "http://127.0.0.1:18787/v1")

    def test_install_start_does_not_switch_config_until_proxy_starts(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        original = (
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n'
        )
        config_path.write_text(original, encoding="utf-8")
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background

        def fake_start_background(paths, settings, verbose_proxy):
            config = load_toml_config(config_path)
            self.assertEqual(provider_base_url(config, "acme"), "https://api.acme.test/v1")
            return {"status": "started", "pid": 1234}

        manager.start_background = fake_start_background
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)
        finally:
            manager.start_background = original_start_background

        config = load_toml_config(config_path)
        self.assertEqual(provider_base_url(config, "acme"), "http://127.0.0.1:18787/v1")

    def test_install_start_installs_codex_startup_hook(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        manager.start_background = fake_start_background
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)
        finally:
            manager.start_background = original_start_background

        paths = paths_for(codex_home)
        config = load_toml_config(config_path)
        hooks = read_hooks(paths.hooks_path)
        session_start = hooks["hooks"]["SessionStart"]
        command = session_start[0]["hooks"][0]["command"]

        self.assertTrue(config["features"]["codex_hooks"])
        self.assertTrue(has_startup_hook(paths))
        self.assertEqual(session_start[0]["matcher"], "startup|resume")
        self.assertIn("codex_fast_proxy", command)
        self.assertIn("autostart", command)
        self.assertIn("--quiet", command)

    def test_install_startup_hook_updates_existing_fast_proxy_hook(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.hooks_path.parent.mkdir(parents=True)
        paths.hooks_path.write_text(
            json.dumps({
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup|resume",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python -m codex_fast_proxy autostart --quiet",
                                },
                                {
                                    "type": "command",
                                    "command": "python -m codex_fast_proxy autostart --quiet",
                                },
                            ],
                        }
                    ]
                }
            }),
            encoding="utf-8",
        )

        result = install_startup_hook(paths)
        hooks = read_hooks(paths.hooks_path)["hooks"]["SessionStart"][0]["hooks"]

        self.assertEqual(result["status"], "updated")
        self.assertEqual(len(hooks), 1)
        self.assertIn("--codex-home", hooks[0]["command"])

    def test_enabled_update_preserves_upstream_backup_for_uninstall(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        paths = paths_for(codex_home)
        config_path = codex_home / "config.toml"
        config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background
        original_stop_process = manager.stop_process

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        def fake_stop_process(paths, force=False):
            return {"status": "stopped", "pid": 1234}

        manager.start_background = fake_start_background
        manager.stop_process = fake_stop_process
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)
            first_manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
            first_backup = Path(first_manifest["backup_path"])

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)
            second_manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
            second_backup = Path(second_manifest["backup_path"])

            uninstall_args = argparse.Namespace(codex_home=str(codex_home), force=False, keep_state=False, defer_stop=False)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_uninstall(uninstall_args), 0)
        finally:
            manager.start_background = original_start_background
            manager.stop_process = original_stop_process

        self.assertEqual(second_backup, first_backup)
        self.assertEqual(provider_base_url(load_toml_config(second_backup), "acme"), "https://api.acme.test/v1")
        config = load_toml_config(config_path)
        self.assertEqual(provider_base_url(config, "acme"), "https://api.acme.test/v1")
        self.assertFalse(paths.app_home.exists())

    def test_enabled_update_recovers_from_proxy_backup_manifest(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        paths = paths_for(codex_home)
        config_path = codex_home / "config.toml"
        config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background
        original_stop_process = manager.stop_process

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        def fake_stop_process(paths, force=False):
            return {"status": "stopped", "pid": 1234}

        manager.start_background = fake_start_background
        manager.stop_process = fake_stop_process
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)
            original_backup = Path(json.loads(paths.manifest_path.read_text(encoding="utf-8"))["backup_path"])

            bad_backup = paths.backup_dir / "config.toml.20990101-000000.bak"
            bad_backup.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
            bad_manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
            bad_manifest["backup_path"] = str(bad_backup)
            paths.manifest_path.write_text(json.dumps(bad_manifest), encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)
            repaired_manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
            repaired_backup = Path(repaired_manifest["backup_path"])

            uninstall_args = argparse.Namespace(codex_home=str(codex_home), force=False, keep_state=False, defer_stop=False)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_uninstall(uninstall_args), 0)
        finally:
            manager.start_background = original_start_background
            manager.stop_process = original_stop_process

        self.assertEqual(repaired_backup, original_backup)
        self.assertEqual(provider_base_url(load_toml_config(repaired_backup), "acme"), "https://api.acme.test/v1")
        config = load_toml_config(config_path)
        self.assertEqual(provider_base_url(config, "acme"), "https://api.acme.test/v1")

    def test_install_start_and_uninstall_restore_before_stop(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        original = (
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n'
        )
        config_path.write_text(original, encoding="utf-8")
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background
        original_stop_process = manager.stop_process

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        def fake_stop_process(paths, force=False):
            config = load_toml_config(config_path)
            self.assertEqual(provider_base_url(config, "acme"), "https://api.acme.test/v1")
            self.assertFalse(force)
            return {"status": "stopped", "pid": 1234}

        manager.start_background = fake_start_background
        manager.stop_process = fake_stop_process
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)
            uninstall_args = argparse.Namespace(codex_home=str(codex_home), force=False, keep_state=False, defer_stop=False)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_uninstall(uninstall_args), 0)
        finally:
            manager.start_background = original_start_background
            manager.stop_process = original_stop_process

        self.assertEqual(config_path.read_text(encoding="utf-8"), original)

    def test_uninstall_removes_fast_proxy_hook_and_keeps_other_hooks(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        paths = paths_for(codex_home)
        config_path = codex_home / "config.toml"
        config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        paths.hooks_path.write_text(
            json.dumps({
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python -c \"print('keep')\"",
                                }
                            ],
                        }
                    ]
                }
            }),
            encoding="utf-8",
        )
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background
        original_stop_process = manager.stop_process

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        def fake_stop_process(paths, force=False):
            return {"status": "stopped", "pid": 1234}

        manager.start_background = fake_start_background
        manager.stop_process = fake_stop_process
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)
            self.assertTrue(has_startup_hook(paths))
            uninstall_args = argparse.Namespace(codex_home=str(codex_home), force=False, keep_state=False, defer_stop=False)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_uninstall(uninstall_args), 0)
        finally:
            manager.start_background = original_start_background
            manager.stop_process = original_stop_process

        hooks = read_hooks(paths.hooks_path)
        kept = hooks["hooks"]["SessionStart"][0]["hooks"][0]
        self.assertEqual(kept["command"], "python -c \"print('keep')\"")
        self.assertFalse(has_startup_hook(paths))

    def test_install_start_failure_leaves_config_unchanged(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        original = (
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n'
        )
        config_path.write_text(original, encoding="utf-8")
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background

        def fail_start_background(paths, settings, verbose_proxy):
            raise ConfigError("proxy failed to start")

        manager.start_background = fail_start_background
        try:
            with self.assertRaises(ConfigError):
                command_install(install_args)
        finally:
            manager.start_background = original_start_background

        self.assertEqual(config_path.read_text(encoding="utf-8"), original)

    def test_install_failure_after_hook_change_restores_original_hooks(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        paths = paths_for(codex_home)
        config_path = codex_home / "config.toml"
        original_config = (
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n'
        )
        original_hooks = json.dumps({
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "hooks": [{"type": "command", "command": "python -c \"print('keep')\""}],
                    }
                ]
            }
        })
        config_path.write_text(original_config, encoding="utf-8")
        paths.hooks_path.write_text(original_hooks, encoding="utf-8")

        original_start_background = manager.start_background
        original_install_startup_hook = manager.install_startup_hook

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        def fail_after_writing_hook(paths):
            paths.hooks_path.write_text(json.dumps({"hooks": {"SessionStart": []}}), encoding="utf-8")
            raise ConfigError("hook failed")

        manager.start_background = fake_start_background
        manager.install_startup_hook = fail_after_writing_hook
        try:
            with self.assertRaises(ConfigError):
                command_install(self.install_args(codex_home))
        finally:
            manager.start_background = original_start_background
            manager.install_startup_hook = original_install_startup_hook

        self.assertEqual(config_path.read_text(encoding="utf-8"), original_config)
        self.assertEqual(paths.hooks_path.read_text(encoding="utf-8"), original_hooks)

    def test_uninstall_skips_stop_and_files_when_config_changed(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        config_path.write_text(
            'model_provider = "acme"\n\n[model_providers.acme]\nbase_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background
        original_stop_process = manager.stop_process
        stop_called = False

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        def fake_stop_process(paths, force=False):
            nonlocal stop_called
            stop_called = True
            return {"status": "stopped", "pid": 1234}

        manager.start_background = fake_start_background
        manager.stop_process = fake_stop_process
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)
            config_path.write_text(
                'model_provider = "acme"\n\n[model_providers.acme]\nbase_url = "https://manual.example/v1"\n',
                encoding="utf-8",
            )
            uninstall_args = argparse.Namespace(codex_home=str(codex_home), force=False, keep_state=False, defer_stop=False)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_uninstall(uninstall_args), 3)
        finally:
            manager.start_background = original_start_background
            manager.stop_process = original_stop_process

        self.assertFalse(stop_called)
        self.assertTrue((paths_for(codex_home).app_home).exists())

    def test_uninstall_preserves_user_config_changes_when_proxy_base_url_is_still_active(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        config_path.write_text(
            'model_provider = "acme"\n'
            'model = "gpt-5.4"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n'
            'api_key_env_var = "ACME_API_KEY"\n',
            encoding="utf-8",
        )
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background
        original_stop_process = manager.stop_process
        stop_called = False

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        def fake_stop_process(paths, force=False):
            nonlocal stop_called
            stop_called = True
            return {"status": "stopped", "pid": 1234}

        manager.start_background = fake_start_background
        manager.stop_process = fake_stop_process
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)
            config_path.write_text(
                'model_provider = "acme"\n'
                'model = "gpt-5.5"\n'
                'sandbox_mode = "workspace-write"\n\n'
                "[model_providers.acme]\n"
                'base_url = "http://127.0.0.1:18787/v1"\n'
                'api_key_env_var = "ACME_API_KEY"\n',
                encoding="utf-8",
            )
            uninstall_args = argparse.Namespace(codex_home=str(codex_home), force=False, keep_state=False, defer_stop=False)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_uninstall(uninstall_args), 0)
            result = json.loads(output.getvalue())
        finally:
            manager.start_background = original_start_background
            manager.stop_process = original_stop_process

        config = load_toml_config(config_path)
        self.assertEqual(result["config_restore"], "restored_base_url")
        self.assertEqual(provider_base_url(config, "acme"), "https://api.acme.test/v1")
        self.assertEqual(config["model"], "gpt-5.5")
        self.assertEqual(config["sandbox_mode"], "workspace-write")
        self.assertEqual(config["model_providers"]["acme"]["api_key_env_var"], "ACME_API_KEY")
        self.assertTrue(stop_called)
        self.assertFalse((paths_for(codex_home).app_home).exists())

    def test_stop_refuses_when_config_still_points_to_proxy(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        config_path.write_text(
            'model_provider = "acme"\n\n[model_providers.acme]\nbase_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        manager.start_background = fake_start_background
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)
            stop_args = argparse.Namespace(codex_home=str(codex_home), force=False)
            with self.assertRaises(ConfigError):
                command_stop(stop_args)
        finally:
            manager.start_background = original_start_background

    def test_stop_process_refuses_when_health_does_not_match_pid_file(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
            }),
            encoding="utf-8",
        )

        original_current_process = manager.current_process
        original_proxy_health = manager.proxy_health
        original_terminate_process = manager.terminate_process
        terminated: list[int] = []

        manager.current_process = lambda _paths: (9999, True)
        manager.proxy_health = lambda _settings: None
        manager.terminate_process = terminated.append
        try:
            with self.assertRaises(ConfigError):
                stop_process(paths)
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health
            manager.terminate_process = original_terminate_process

        self.assertEqual(terminated, [])

    def test_stop_process_force_skips_health_match(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)

        original_current_process = manager.current_process
        original_is_process_running = manager.is_process_running
        original_terminate_process = manager.terminate_process
        terminated: list[int] = []

        manager.current_process = lambda _paths: (9999, True)
        manager.is_process_running = lambda _pid: False
        manager.terminate_process = terminated.append
        try:
            result = stop_process(paths, force=True)
        finally:
            manager.current_process = original_current_process
            manager.is_process_running = original_is_process_running
            manager.terminate_process = original_terminate_process

        self.assertEqual(result, {"status": "stopped", "pid": 9999})
        self.assertEqual(terminated, [9999])

    def test_autostart_skips_when_config_no_longer_points_to_proxy(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
            }),
            encoding="utf-8",
        )
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n[model_providers.acme]\nbase_url = "https://manual.example/v1"\n',
            encoding="utf-8",
        )

        original_start_background = manager.start_background
        start_called = False

        def fake_start_background(paths, settings, verbose_proxy):
            nonlocal start_called
            start_called = True
            return {"status": "started", "pid": 1234}

        manager.start_background = fake_start_background
        try:
            result = autostart_proxy(paths, verbose_proxy=False)
        finally:
            manager.start_background = original_start_background

        self.assertFalse(start_called)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "config_not_proxy")

    def test_autostart_starts_when_config_points_to_proxy(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
            }),
            encoding="utf-8",
        )
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n[model_providers.acme]\nbase_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )

        original_start_background = manager.start_background

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234, "base_url": settings.base_url}

        manager.start_background = fake_start_background
        try:
            result = autostart_proxy(paths, verbose_proxy=False)
        finally:
            manager.start_background = original_start_background

        self.assertEqual(result["status"], "started")
        self.assertEqual(result["base_url"], "http://127.0.0.1:18787/v1")

    def test_autostart_restarts_when_running_runtime_is_stale(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
            }),
            encoding="utf-8",
        )
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n[model_providers.acme]\nbase_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )

        original_current_process = manager.current_process
        original_proxy_health = manager.proxy_health
        original_stop_process = manager.stop_process
        original_start_background = manager.start_background
        calls: list[str] = []

        def fake_stop_process(paths, force=False):
            calls.append("stop")
            self.assertFalse(force)
            return {"status": "stopped", "pid": 9999}

        def fake_start_background(paths, settings, verbose_proxy):
            calls.append("start")
            return {"status": "started", "pid": 1234, "base_url": settings.base_url}

        manager.current_process = lambda _paths: (9999, True)
        manager.proxy_health = lambda _settings: {
            "ok": True,
            "pid": 9999,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "runtime_id": "old-runtime",
        }
        manager.stop_process = fake_stop_process
        manager.start_background = fake_start_background
        try:
            result = autostart_proxy(paths, verbose_proxy=False)
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health
            manager.stop_process = original_stop_process
            manager.start_background = original_start_background

        self.assertEqual(result["status"], "restarted")
        self.assertEqual(result["reason"], "runtime_changed")
        self.assertEqual(calls, ["stop", "start"])

    def test_uninstall_defer_stop_restores_config_and_keeps_proxy_for_restart(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        original = (
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n'
        )
        config_path.write_text(original, encoding="utf-8")
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background
        original_stop_process = manager.stop_process
        stop_calls = 0

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        def fake_stop_process(paths, force=False):
            nonlocal stop_calls
            stop_calls += 1
            self.assertFalse(force)
            return {"status": "stopped", "pid": 1234}

        manager.start_background = fake_start_background
        manager.stop_process = fake_stop_process
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)

            first_uninstall = argparse.Namespace(
                codex_home=str(codex_home),
                force=False,
                keep_state=False,
                defer_stop=True,
            )
            with contextlib.redirect_stdout(io.StringIO()) as first_output:
                self.assertEqual(command_uninstall(first_uninstall), 0)
            first_result = json.loads(first_output.getvalue())

            self.assertEqual(config_path.read_text(encoding="utf-8"), original)
            self.assertEqual(first_result["stop_result"]["status"], "deferred")
            self.assertEqual(stop_calls, 0)
            self.assertTrue(paths_for(codex_home).app_home.exists())

            second_uninstall = argparse.Namespace(
                codex_home=str(codex_home),
                force=False,
                keep_state=False,
                defer_stop=False,
            )
            with contextlib.redirect_stdout(io.StringIO()) as second_output:
                self.assertEqual(command_uninstall(second_uninstall), 0)
            second_result = json.loads(second_output.getvalue())
        finally:
            manager.start_background = original_start_background
            manager.stop_process = original_stop_process

        self.assertEqual(second_result["config_restore"], "already_restored")
        self.assertEqual(stop_calls, 1)
        self.assertFalse(paths_for(codex_home).app_home.exists())

    def test_deferred_uninstall_can_finish_after_base_url_only_restore(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        config_path.write_text(
            'model_provider = "acme"\n'
            'model = "gpt-5.4"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background
        original_stop_process = manager.stop_process
        stop_calls = 0

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        def fake_stop_process(paths, force=False):
            nonlocal stop_calls
            stop_calls += 1
            return {"status": "stopped", "pid": 1234}

        manager.start_background = fake_start_background
        manager.stop_process = fake_stop_process
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)

            config_path.write_text(
                'model_provider = "acme"\n'
                'model = "gpt-5.5"\n\n'
                "[model_providers.acme]\n"
                'base_url = "http://127.0.0.1:18787/v1"\n\n'
                "[features]\n"
                "codex_hooks = true\n",
                encoding="utf-8",
            )

            first_uninstall = argparse.Namespace(
                codex_home=str(codex_home),
                force=False,
                keep_state=False,
                defer_stop=True,
            )
            with contextlib.redirect_stdout(io.StringIO()) as first_output:
                self.assertEqual(command_uninstall(first_uninstall), 0)
            first_result = json.loads(first_output.getvalue())

            first_config = load_toml_config(config_path)
            self.assertEqual(first_result["config_restore"], "restored_base_url")
            self.assertEqual(provider_base_url(first_config, "acme"), "https://api.acme.test/v1")
            self.assertEqual(first_config["model"], "gpt-5.5")
            self.assertNotIn("codex_hooks", first_config.get("features", {}))
            self.assertEqual(stop_calls, 0)

            second_uninstall = argparse.Namespace(
                codex_home=str(codex_home),
                force=False,
                keep_state=False,
                defer_stop=False,
            )
            with contextlib.redirect_stdout(io.StringIO()) as second_output:
                self.assertEqual(command_uninstall(second_uninstall), 0)
            second_result = json.loads(second_output.getvalue())
        finally:
            manager.start_background = original_start_background
            manager.stop_process = original_stop_process

        self.assertEqual(second_result["config_restore"], "already_restored_base_url")
        self.assertEqual(stop_calls, 1)
        self.assertFalse(paths_for(codex_home).app_home.exists())

    def test_doctor_fails_when_installed_config_no_longer_points_to_proxy(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        config_path.write_text(
            'model_provider = "acme"\n\n[model_providers.acme]\nbase_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        manager.start_background = fake_start_background
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)
        finally:
            manager.start_background = original_start_background

        config_path.write_text(
            'model_provider = "acme"\n\n[model_providers.acme]\nbase_url = "https://manual.example/v1"\n',
            encoding="utf-8",
        )
        report = doctor_report(paths_for(codex_home), None)
        self.assertFalse(report["ok"])


if __name__ == "__main__":
    unittest.main()
