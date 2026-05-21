from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import stat
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import codex_fast_proxy.manager as manager  # noqa: E402
import codex_fast_proxy.benchmark as benchmark  # noqa: E402
import codex_fast_proxy.skill_link as skill_link  # noqa: E402
import codex_fast_proxy.updater as updater  # noqa: E402
from codex_fast_proxy.manager import (  # noqa: E402
    autostart_proxy,
    choose_provider,
    command_install,
    command_set_upstream,
    command_stop,
    command_uninstall,
    ConfigError,
    child_environment,
    doctor_report,
    has_startup_hook,
    install_startup_hook,
    load_toml_config,
    paths_for,
    provider_base_url,
    read_hooks,
    set_provider_base_url,
    settings_from_dict,
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
        self.assertEqual(paths.provider_auth_path, paths.app_home / "provider-auth.json")

    def test_provider_auth_file_status_is_persistent_without_printing_secret(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        manager.write_provider_auth_secret(paths, "acme", "provider-secret")
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )

        status = manager.upstream_auth_status(paths, settings)
        status_text = json.dumps(status)

        self.assertEqual(status["upstream_auth"], "override_configured")
        self.assertTrue(status["upstream_api_key_file"])
        self.assertEqual(status["upstream_api_key_ref"], "provider_auth_file")
        self.assertEqual(status["upstream_api_key_source"], "provider_auth_file")
        self.assertTrue(status["upstream_api_key_persistent"])
        self.assertNotIn("provider-secret", status_text)

    @unittest.skipIf(os.name == "nt", "POSIX mode bits are not meaningful on Windows.")
    def test_provider_auth_file_is_owner_only_on_posix(self) -> None:
        paths = paths_for(self.temp_dir / ".codex")

        manager.write_provider_auth_secret(paths, "acme", "provider-secret")

        mode = stat.S_IMODE(paths.provider_auth_path.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_child_environment_loads_provider_auth_file_into_private_env(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        manager.write_provider_auth_secret(paths, "acme", "provider-secret")
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_file=True,
        )

        env = child_environment(paths, settings)

        self.assertEqual(env[manager.INTERNAL_UPSTREAM_API_KEY_ENV], "provider-secret")

    def test_link_skill_namespace_uses_manager_owned_platform_branch(self) -> None:
        repo_root = self.temp_dir / "repo"
        target = repo_root / "skills"
        target.mkdir(parents=True)
        skills_root = self.temp_dir / "skills-root"
        calls: list[list[str]] = []

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        original_is_windows = skill_link.is_windows_platform
        original_run = skill_link.subprocess.run
        skill_link.is_windows_platform = lambda: True
        skill_link.subprocess.run = lambda command, **_kwargs: calls.append(command) or Completed()
        try:
            result = manager.link_skill_namespace(repo_root, skills_root)
        finally:
            skill_link.is_windows_platform = original_is_windows
            skill_link.subprocess.run = original_run

        self.assertEqual(result["status"], "linked")
        self.assertEqual(result["link_type"], "junction")
        self.assertEqual(calls[0][:4], ["cmd", "/d", "/c", "mklink"])

    def test_link_skill_namespace_refuses_existing_unrelated_path(self) -> None:
        repo_root = self.temp_dir / "repo"
        (repo_root / "skills").mkdir(parents=True)
        skills_root = self.temp_dir / "skills-root"
        manager.skill_namespace_path(skills_root).mkdir(parents=True)

        with self.assertRaises(ConfigError):
            manager.link_skill_namespace(repo_root, skills_root)

    def test_unlink_skill_namespace_refuses_plain_directory(self) -> None:
        repo_root = self.temp_dir / "repo"
        target = repo_root / "skills"
        target.mkdir(parents=True)
        skills_root = self.temp_dir / "skills-root"
        link = manager.skill_namespace_path(skills_root)
        link.mkdir(parents=True)

        original_points_to = skill_link.path_points_to
        skill_link.path_points_to = lambda _path, _target: True
        try:
            with self.assertRaises(ConfigError):
                manager.unlink_skill_namespace(repo_root, skills_root)
        finally:
            skill_link.path_points_to = original_points_to

    def test_benchmark_default_timeout_allows_long_codex_runs(self) -> None:
        args = manager.build_parser().parse_args(["benchmark"])

        self.assertEqual(args.timeout, 600.0)

    def test_set_upstream_verification_is_enabled_by_default_in_cli(self) -> None:
        parser = manager.build_parser()
        default_args = parser.parse_args(["set-upstream", "--upstream-base", "https://api.new.test/v1"])
        skipped_args = parser.parse_args(["set-upstream", "--upstream-base", "https://api.new.test/v1", "--no-verify"])

        self.assertTrue(default_args.verify)
        self.assertEqual(default_args.verify_timeout, 60.0)
        self.assertFalse(skipped_args.verify)

    def test_install_verification_is_enabled_by_default_in_cli(self) -> None:
        parser = manager.build_parser()
        default_args = parser.parse_args(["install", "--start"])
        skipped_args = parser.parse_args(["install", "--start", "--no-verify"])

        self.assertTrue(default_args.verify)
        self.assertEqual(default_args.verify_timeout, 60.0)
        self.assertFalse(skipped_args.verify)

    def test_verify_upstream_cli_is_read_only_shape(self) -> None:
        args = manager.build_parser().parse_args([
            "verify-upstream",
            "--upstream-base",
            "https://api.new.test/v1",
            "--upstream-api-key-env",
            "ACME_API_KEY",
        ])

        self.assertEqual(args.command, "verify-upstream")
        self.assertEqual(args.upstream_base, "https://api.new.test/v1")
        self.assertEqual(args.upstream_api_key_env, "ACME_API_KEY")
        self.assertEqual(args.verify_timeout, 60.0)

    def test_prepare_chatgpt_login_cli_is_dry_run_by_default(self) -> None:
        args = manager.build_parser().parse_args([
            "prepare-chatgpt-login",
            "--provider",
            "acme",
            "--source-auth-key",
            "OPENAI_API_KEY",
            "--target-env",
            "ACME_API_KEY",
        ])

        self.assertEqual(args.command, "prepare-chatgpt-login")
        self.assertEqual(args.provider, "acme")
        self.assertEqual(args.source_auth_key, "OPENAI_API_KEY")
        self.assertEqual(args.target_env, "ACME_API_KEY")
        self.assertFalse(args.apply)

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
            service_tier_policy=None,
            upstream_api_key_env=None,
            verify=False,
            verify_timeout=60.0,
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

    def test_install_start_auto_selects_available_proxy_port_for_new_enable(self) -> None:
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
        captured: dict[str, manager.ProxySettings] = {}

        original_find_available_port = manager.find_available_port
        original_start_background = manager.start_background
        manager.find_available_port = lambda _host, _preferred, attempts=100, reserved_ports=(): 18789

        def fake_start_background(_paths, settings, _verbose_proxy):
            captured["settings"] = settings
            return {"status": "started", "pid": 1234, "base_url": settings.base_url}

        manager.start_background = fake_start_background
        try:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_install(install_args), 0)
        finally:
            manager.find_available_port = original_find_available_port
            manager.start_background = original_start_background

        result = json.loads(output.getvalue())
        config = load_toml_config(config_path)
        settings = json.loads(paths.settings_path.read_text(encoding="utf-8"))
        manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(captured["settings"].port, 18789)
        self.assertEqual(settings["port"], 18789)
        self.assertEqual(manifest["settings"]["port"], 18789)
        self.assertEqual(provider_base_url(config, "acme"), "http://127.0.0.1:18789/v1")
        self.assertEqual(result["base_url"], "http://127.0.0.1:18789/v1")
        self.assertEqual(result["port_selection"]["preferred"], 18787)
        self.assertEqual(result["port_selection"]["selected"], 18789)
        self.assertTrue(result["port_selection"]["auto_selected"])

    def test_install_start_preserves_existing_policy_and_upstream_auth_env_on_update(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        config_path = codex_home / "config.toml"
        config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "service_tier_policy": "inject_missing",
                "upstream_api_key_env": "ACME_API_KEY",
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )
        (paths.codex_home / "auth.json").write_text(json.dumps({"ACME_API_KEY": "secret"}), encoding="utf-8")

        original_start_background = manager.start_background

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234, "policy": settings.service_tier_policy}

        manager.start_background = fake_start_background
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(self.install_args(codex_home)), 0)
        finally:
            manager.start_background = original_start_background

        settings = json.loads(paths.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(settings["service_tier_policy"], "inject_missing")
        self.assertEqual(settings["upstream_api_key_env"], "ACME_API_KEY")

    def test_install_start_failure_rolls_back_settings_file(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        paths = paths_for(codex_home)
        config_path = codex_home / "config.toml"
        original = (
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n'
        )
        config_path.write_text(original, encoding="utf-8")

        original_start_background = manager.start_background

        def fail_start_background(_paths, _settings, _verbose_proxy):
            raise ConfigError("missing key")

        manager.start_background = fail_start_background
        try:
            with self.assertRaises(ConfigError):
                command_install(self.install_args(codex_home))
        finally:
            manager.start_background = original_start_background

        self.assertEqual(config_path.read_text(encoding="utf-8"), original)
        self.assertFalse(paths.settings_path.exists())

    def test_child_environment_falls_back_to_auth_json_for_upstream_key(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.codex_home.mkdir(parents=True)
        (paths.codex_home / "auth.json").write_text(json.dumps({"ACME_API_KEY": "secret"}), encoding="utf-8")
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_env="ACME_API_KEY",
        )
        old_env = os.environ.pop("ACME_API_KEY", None)
        try:
            env = child_environment(paths, settings)
        finally:
            if old_env is not None:
                os.environ["ACME_API_KEY"] = old_env

        self.assertEqual(env["ACME_API_KEY"], "secret")

    def test_prepare_chatgpt_login_dry_run_uses_auth_json_without_printing_secret(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.codex_home.mkdir(parents=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        (paths.codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "provider-secret"}), encoding="utf-8")

        args = argparse.Namespace(
            codex_home=str(codex_home),
            provider=None,
            source_auth_key=None,
            target_env=None,
            apply=False,
        )
        result = manager.prepare_chatgpt_login(args)
        result_text = json.dumps(result)

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["provider"], "acme")
        self.assertEqual(result["source"], "auth_json:OPENAI_API_KEY")
        self.assertEqual(result["target_auth"], "provider_auth_file")
        self.assertEqual(result["provider_auth_path"], str(paths.provider_auth_path))
        self.assertFalse(result["settings_changed"])
        self.assertIn("prepare-chatgpt-login --apply", result["next_action"])
        self.assertNotIn("provider-secret", result_text)

    def test_prepare_chatgpt_login_apply_writes_provider_auth_file_without_printing_secret(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.codex_home.mkdir(parents=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        (paths.codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "provider-secret"}), encoding="utf-8")

        args = argparse.Namespace(
            codex_home=str(codex_home),
            provider=None,
            source_auth_key=None,
            target_env="PACKY_API_KEY",
            apply=True,
        )
        result = manager.prepare_chatgpt_login(args)
        result_text = json.dumps(result)
        stored = json.loads(paths.provider_auth_path.read_text(encoding="utf-8"))

        self.assertEqual(stored["providers"]["acme"]["api_key"], "provider-secret")
        self.assertEqual(result["status"], "prepared")
        self.assertEqual(result["legacy_target_env"], "PACKY_API_KEY")
        self.assertTrue(result["applied"])
        self.assertFalse(result["restart_required"])
        self.assertIn("set-upstream --use-provider-auth-file", result["next_action"])
        self.assertNotIn("provider-secret", result_text)

    def test_prepare_chatgpt_login_updates_existing_provider_auth_file_for_key_rotation(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.codex_home.mkdir(parents=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        (paths.codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "provider-secret"}), encoding="utf-8")
        manager.write_provider_auth_secret(paths, "acme", "old-secret")

        args = argparse.Namespace(
            codex_home=str(codex_home),
            provider=None,
            source_auth_key=None,
            target_env=None,
            apply=True,
        )
        result = manager.prepare_chatgpt_login(args)
        stored = json.loads(paths.provider_auth_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "prepared")
        self.assertEqual(stored["providers"]["acme"]["api_key"], "provider-secret")
        self.assertNotIn("provider-secret", json.dumps(result))
        self.assertNotIn("old-secret", json.dumps(result))

    def test_prepare_chatgpt_login_rejects_invalid_target_env_without_printing_secret(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.codex_home.mkdir(parents=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        (paths.codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "provider-secret"}), encoding="utf-8")

        args = argparse.Namespace(
            codex_home=str(codex_home),
            provider=None,
            source_auth_key=None,
            target_env="1_BAD_ENV",
            apply=False,
        )
        with self.assertRaises(ConfigError) as caught:
            manager.prepare_chatgpt_login(args)

        self.assertIn("Invalid environment variable name", str(caught.exception))
        self.assertNotIn("provider-secret", str(caught.exception))

    def test_command_prepare_chatgpt_login_output_does_not_leak_secret(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.codex_home.mkdir(parents=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        (paths.codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "provider-secret"}), encoding="utf-8")

        args = argparse.Namespace(
            codex_home=str(codex_home),
            provider=None,
            source_auth_key=None,
            target_env=None,
            apply=False,
        )
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(manager.command_prepare_chatgpt_login(args), 0)

        output = stdout.getvalue()
        result = json.loads(output)
        self.assertFalse(result["secret_printed"])
        self.assertNotIn("provider-secret", output)

    def test_legacy_settings_without_policy_keep_global_fast_behavior(self) -> None:
        settings = settings_from_dict({
            "provider": "acme",
            "host": "127.0.0.1",
            "port": 18787,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
        })

        self.assertEqual(settings.service_tier_policy, "inject_missing")

    def test_auth_split_settings_without_policy_default_to_app_controlled(self) -> None:
        settings = settings_from_dict({
            "provider": "acme",
            "host": "127.0.0.1",
            "port": 18787,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "upstream_api_key_env": "ACME_API_KEY",
        })

        self.assertEqual(settings.service_tier_policy, "preserve")

    def test_provider_auth_file_settings_without_policy_default_to_app_controlled(self) -> None:
        settings = settings_from_dict({
            "provider": "acme",
            "host": "127.0.0.1",
            "port": 18787,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "upstream_api_key_file": True,
        })

        self.assertEqual(settings.service_tier_policy, "preserve")

    def test_settings_reject_multiple_upstream_auth_sources(self) -> None:
        with self.assertRaises(ConfigError):
            settings_from_dict({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "upstream_api_key_env": "ACME_API_KEY",
                "upstream_api_key_file": True,
            })

    def test_settings_reject_invalid_upstream_api_key_env_name(self) -> None:
        with self.assertRaises(ConfigError):
            settings_from_dict({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "upstream_api_key_env": "1_BAD_ENV",
            })

    def test_install_requires_verification_for_new_or_changed_model_path(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            service_tier_policy="auto",
            upstream_api_key_env=None,
        )
        same_settings = manager.ProxySettings(**settings.__dict__)
        changed_auth = manager.ProxySettings(**{**settings.__dict__, "upstream_api_key_env": "ACME_API_KEY"})

        self.assertTrue(manager.install_requires_verification(False, None, settings))
        self.assertFalse(manager.install_requires_verification(True, same_settings, settings))
        self.assertTrue(manager.install_requires_verification(True, same_settings, changed_auth))

    def test_verify_upstream_command_does_not_write_settings_or_config(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model = "gpt-test"\n'
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        original_settings = {
            "provider": "acme",
            "host": "127.0.0.1",
            "port": 18787,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "service_tier_policy": "preserve",
            "upstream_api_key_env": "ACME_API_KEY",
        }
        paths.settings_path.write_text(json.dumps(original_settings), encoding="utf-8")
        (paths.codex_home / "auth.json").write_text(json.dumps({"ACME_API_KEY": "secret"}), encoding="utf-8")
        config_before = paths.config_path.read_text(encoding="utf-8")
        settings_before = paths.settings_path.read_text(encoding="utf-8")
        captured: dict[str, object] = {}

        original_verify = manager.verify_upstream_responses

        def fake_verify(paths, config, settings, timeout):
            captured["settings"] = settings
            captured["timeout"] = timeout
            return {
                "status": "verified",
                "request": "POST /v1/responses",
                "stream": True,
                "response_status": 200,
                "response_content_type": "text/event-stream",
            }

        manager.verify_upstream_responses = fake_verify
        try:
            args = argparse.Namespace(
                codex_home=str(codex_home),
                provider=None,
                upstream_base="https://api.new.test/v1",
                service_tier=None,
                service_tier_policy="inject_missing",
                upstream_api_key_env=None,
                clear_upstream_api_key_env=False,
                verify_timeout=42.0,
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(manager.command_verify_upstream(args), 0)
        finally:
            manager.verify_upstream_responses = original_verify

        result = json.loads(output.getvalue())
        verified_settings = captured["settings"]
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["upstream_base"], "https://api.new.test/v1")
        self.assertEqual(result["service_tier_policy"], "inject_missing")
        self.assertFalse(result["settings_changed"])
        self.assertFalse(result["config_changed"])
        self.assertEqual(captured["timeout"], 42.0)
        self.assertEqual(verified_settings.upstream_api_key_env, "ACME_API_KEY")
        self.assertEqual(paths.config_path.read_text(encoding="utf-8"), config_before)
        self.assertEqual(paths.settings_path.read_text(encoding="utf-8"), settings_before)

    def test_new_settings_default_to_auto_policy(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
        )

        self.assertEqual(settings.service_tier_policy, "auto")

    def test_auto_policy_injects_for_api_key_auth_and_preserves_for_chatgpt_auth(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
        )

        (codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "secret"}), encoding="utf-8")
        api_key_login = manager.detect_login_mode(codex_home)
        self.assertEqual(api_key_login.login_mode, "api_key")
        self.assertEqual(manager.effective_service_tier_policy(settings, api_key_login), "inject_missing")
        self.assertEqual(manager.fast_behavior(settings, api_key_login), "auto_global_priority")

        (codex_home / "auth.json").write_text(json.dumps({"tokens": {"access_token": "secret"}}), encoding="utf-8")
        chatgpt_login = manager.detect_login_mode(codex_home)
        self.assertEqual(chatgpt_login.login_mode, "chatgpt")
        self.assertEqual(manager.effective_service_tier_policy(settings, chatgpt_login), "preserve")
        self.assertEqual(manager.fast_behavior(settings, chatgpt_login), "app_controlled")

    def test_provider_auth_preparation_reports_non_secret_state(self) -> None:
        login = manager.LoginDiagnosis("chatgpt", False, True, "chatgpt_auth_detected")

        prepared = manager.provider_auth_preparation(login, {
            "upstream_auth": "override_configured",
            "upstream_api_key_persistent": True,
            "upstream_api_key_available": True,
        })
        missing = manager.provider_auth_preparation(login, {
            "upstream_auth": "preserved",
            "upstream_api_key_persistent": None,
            "upstream_api_key_available": None,
        })

        self.assertEqual(prepared["status"], "prepared")
        self.assertEqual(missing["status"], "not_prepared")
        self.assertNotIn("secret", json.dumps(prepared))
        self.assertNotIn("secret", json.dumps(missing))

    def test_chatgpt_login_hint_reports_optional_setup_after_enable(self) -> None:
        login = manager.LoginDiagnosis("api_key", True, False, "api_key_auth_detected")
        hint = manager.chatgpt_login_hint(login, {
            "upstream_auth": "preserved",
            "upstream_api_key_available": None,
            "upstream_api_key_persistent": None,
        })

        self.assertEqual(hint["status"], "optional_setup_available")
        self.assertIn("prepare-chatgpt-login", hint["message"])
        self.assertIn("prepare-chatgpt-login", hint["next_user_action"])
        self.assertIn("plugin marketplace", hint["message"])
        self.assertIn("voice input", hint["message"])

    def test_start_outputs_chatgpt_login_troubleshooting_when_ready(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        manager.write_settings(paths, manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            service_tier_policy="auto",
            upstream_api_key_env="ACME_API_KEY",
        ))
        args = argparse.Namespace(codex_home=str(codex_home), verbose_proxy=False)
        with (
            mock.patch.dict(os.environ, {"ACME_API_KEY": "provider-secret"}),
            mock.patch.object(manager, "start_background", return_value={"status": "started", "pid": 1234}),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(manager.command_start(args), 0)

        result = json.loads(output.getvalue())
        self.assertEqual(result["chatgpt_login_hint"]["status"], "ready")
        self.assertIn("WinError 10013", result["next_user_action"])
        self.assertIn("net stop winnat", result["chatgpt_login_windows_troubleshooting"]["commands"])
        self.assertNotIn("provider-secret", output.getvalue())

    def test_install_start_outputs_chatgpt_login_hint(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n',
            encoding="utf-8",
        )
        (codex_home / "auth.json").write_text(
            json.dumps({"OPENAI_API_KEY": "provider-secret"}),
            encoding="utf-8",
        )

        original_start_background = manager.start_background
        manager.start_background = lambda _paths, _settings, _verbose_proxy: {"status": "started", "pid": 1234}
        try:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_install(self.install_args(codex_home)), 0)
            output_text = output.getvalue()
            result = json.loads(output_text)
        finally:
            manager.start_background = original_start_background

        self.assertEqual(result["chatgpt_login_hint"]["status"], "optional_setup_available")
        self.assertIn("prepare-chatgpt-login", result["chatgpt_login_hint"]["message"])
        self.assertIn("prepare-chatgpt-login", result["next_user_action"])
        self.assertNotIn("provider-secret", output_text)

    def test_validate_upstream_rejects_userinfo_query_and_fragment(self) -> None:
        with self.assertRaises(ConfigError):
            manager.validate_upstream_base("https://token:secret@api.acme.test/v1")
        with self.assertRaises(ConfigError):
            manager.validate_upstream_base("https://api.acme.test/v1?api_key=secret")
        with self.assertRaises(ConfigError):
            manager.validate_upstream_base("https://api.acme.test/v1#secret")

    def test_redacts_git_remote_urls_before_reporting(self) -> None:
        self.assertEqual(
            manager.safe_url_display("https://token:secret@github.com/example/repo.git?x=secret#frag"),
            "https://github.com/example/repo.git",
        )
        redacted = manager.redact_url_secrets(
            "fatal: unable to access 'https://token:secret@github.com/example/repo.git/': failed"
        )
        self.assertNotIn("token", redacted)
        self.assertNotIn("secret", redacted)
        self.assertIn("https://github.com/example/repo.git", redacted)
        fake_key = "sk-" + "secretvalue123456"
        sensitive = manager.redact_sensitive_text(f"Authorization: Bearer {fake_key} failed")
        self.assertNotIn(fake_key, sensitive)
        self.assertIn("Bearer <redacted>", sensitive)

    def test_settings_reject_invalid_service_tier_policy(self) -> None:
        with self.assertRaises(ConfigError):
            settings_from_dict({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "service_tier_policy": "always",
            })

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

        self.assertTrue(config["features"]["hooks"])
        self.assertTrue(config["features"]["codex_hooks"])
        self.assertTrue(has_startup_hook(paths))
        hook_status = manager.fast_proxy_hook_trust_status(paths)
        self.assertTrue(hook_status["feature_enabled"])
        self.assertTrue(hook_status["trusted"])
        self.assertTrue(hook_status["ready"])
        self.assertEqual(len(hook_status["hooks"]), 1)
        hook_state = config["hooks"]["state"][hook_status["hooks"][0]["key"]]
        self.assertTrue(hook_state["enabled"])
        self.assertEqual(hook_state["trusted_hash"], hook_status["hooks"][0]["trusted_hash"])
        self.assertEqual(session_start[0]["matcher"], "startup|resume")
        self.assertIn(sys.executable, command)
        self.assertIn("codex_fast_proxy", command)
        self.assertIn("autostart", command)
        self.assertIn("--quiet", command)

    def test_hooks_feature_detection_accepts_current_and_legacy_keys(self) -> None:
        self.assertTrue(manager.hooks_feature_enabled({"features": {"hooks": True}}))
        self.assertTrue(manager.hooks_feature_enabled({"features": {"codex_hooks": True}}))
        self.assertFalse(manager.hooks_feature_enabled({"features": {"hooks": False, "codex_hooks": False}}))

    def test_trusted_hook_is_not_ready_when_feature_flags_are_disabled(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        paths = paths_for(codex_home)
        paths.config_path.write_text("", encoding="utf-8")

        install_startup_hook(paths)
        manager.remove_hook_feature_flags(paths.config_path)

        hook_status = manager.fast_proxy_hook_trust_status(paths)
        self.assertFalse(hook_status["feature_enabled"])
        self.assertTrue(hook_status["trusted"])
        self.assertFalse(hook_status["ready"])
        self.assertFalse(has_startup_hook(paths))

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
        self.assertTrue(has_startup_hook(paths))

    def test_modified_startup_hook_is_not_reported_as_usable(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        paths = paths_for(codex_home)
        paths.config_path.write_text("", encoding="utf-8")

        install_startup_hook(paths)
        hooks_data = read_hooks(paths.hooks_path)
        hooks_data["hooks"]["SessionStart"][0]["hooks"][0]["command"] += " --changed"
        paths.hooks_path.write_text(json.dumps(hooks_data), encoding="utf-8")

        hook_status = manager.fast_proxy_hook_trust_status(paths)
        self.assertFalse(hook_status["trusted"])
        self.assertEqual(hook_status["hooks"][0]["trust_status"], "modified")
        self.assertFalse(has_startup_hook(paths))

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

    def test_set_upstream_updates_runtime_state_and_uninstall_baseline(self) -> None:
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

        original_current_process = manager.current_process
        original_proxy_health = manager.proxy_health
        original_start_background = manager.start_background
        original_stop_process = manager.stop_process
        calls: list[str] = []

        def fake_start_background(paths, settings, verbose_proxy):
            calls.append(f"start:{settings.upstream_base}")
            return {"status": "started", "pid": 1234, "base_url": settings.base_url}

        def fake_stop_process(paths, force=False):
            calls.append("stop")
            return {"status": "stopped", "pid": 1234}

        manager.start_background = fake_start_background
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)

            manager.current_process = lambda _paths: (1234, True)
            manager.proxy_health = lambda _settings: {
                "ok": True,
                "pid": 1234,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "service_tier_policy": "inject_missing",
                "runtime_id": manager.RUNTIME_ID,
            }
            manager.stop_process = fake_stop_process
            set_args = argparse.Namespace(
                codex_home=str(codex_home),
                upstream_base="https://api.new.test/v1",
                restart=False,
                verbose_proxy=False,
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_set_upstream(set_args), 0)
            result = json.loads(output.getvalue())
            settings_after = json.loads(paths.settings_path.read_text(encoding="utf-8"))
            manifest_after = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
            backup_path = Path(manifest_after["backup_path"])
            config_after_update = load_toml_config(config_path)

            with contextlib.redirect_stdout(io.StringIO()) as status_output:
                self.assertEqual(manager.command_status(argparse.Namespace(codex_home=str(codex_home), provider=None)), 0)
            status_after_update = json.loads(status_output.getvalue())

            calls_after_update = list(calls)
            calls.clear()
            uninstall_args = argparse.Namespace(codex_home=str(codex_home), force=False, keep_state=False, defer_stop=False)
            manager.current_process = lambda _paths: (None, False)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_uninstall(uninstall_args), 0)
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health
            manager.start_background = original_start_background
            manager.stop_process = original_stop_process

        config = load_toml_config(config_path)
        self.assertEqual(calls_after_update, ["start:https://api.acme.test/v1"])
        self.assertEqual(calls, ["stop"])
        self.assertEqual(result["status"], "upstream_updated")
        self.assertEqual(result["previous_upstream_base"], "https://api.acme.test/v1")
        self.assertEqual(result["upstream_base"], "https://api.new.test/v1")
        self.assertTrue(result["restart_required"])
        self.assertEqual(result["start_result"]["status"], "deferred")
        self.assertTrue(status_after_update["pending_restart"])
        self.assertTrue(status_after_update["needs_restart"])
        self.assertEqual(status_after_update["diagnosis"]["level"], "attention")
        self.assertEqual(status_after_update["diagnosis"]["code"], "settings_pending_restart")
        self.assertEqual(settings_after["upstream_base"], "https://api.new.test/v1")
        self.assertEqual(manifest_after["settings"]["upstream_base"], "https://api.new.test/v1")
        self.assertEqual(provider_base_url(load_toml_config(backup_path), "acme"), "https://api.new.test/v1")
        self.assertEqual(provider_base_url(config_after_update, "acme"), "http://127.0.0.1:18787/v1")
        self.assertFalse(paths.settings_path.exists())
        self.assertEqual(provider_base_url(config, "acme"), "https://api.new.test/v1")

    def test_set_upstream_noop_running_proxy_does_not_defer_restart(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model = "gpt-test"\n'
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "service_tier_policy": "preserve",
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )

        original_current_process = manager.current_process
        original_proxy_health = manager.proxy_health
        original_start_background = manager.start_background
        manager.current_process = lambda _paths: (1234, True)
        manager.proxy_health = lambda _settings: {
            "ok": True,
            "pid": 1234,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "service_tier_policy": "preserve",
            "service_tier_effective_policy": "preserve",
            "runtime_id": manager.RUNTIME_ID,
        }
        manager.start_background = lambda *_args, **_kwargs: self.fail("start_background should not run")
        try:
            set_args = argparse.Namespace(
                codex_home=str(codex_home),
                upstream_base="https://api.acme.test/v1",
                service_tier_policy=None,
                upstream_api_key_env=None,
                clear_upstream_api_key_env=False,
                verify=False,
                verify_timeout=60.0,
                restart=False,
                verbose_proxy=False,
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_set_upstream(set_args), 0)
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health
            manager.start_background = original_start_background

        result = json.loads(output.getvalue())
        self.assertFalse(result["restart_required"])
        self.assertEqual(result["start_result"]["status"], "already_running")
        self.assertFalse(result["start_result"]["needs_restart"])

    def test_set_upstream_verifies_candidate_before_writing_settings(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model = "gpt-test"\n'
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        original_settings = {
            "provider": "acme",
            "host": "127.0.0.1",
            "port": 18787,
            "proxy_base": "/v1",
            "upstream_base": "https://api.old.test/v1",
            "service_tier": "priority",
            "base_url": "http://127.0.0.1:18787/v1",
        }
        paths.settings_path.write_text(json.dumps(original_settings), encoding="utf-8")

        original_verify = manager.verify_upstream_responses
        original_start_background = manager.start_background

        def fake_verify(_paths, _config, new_settings, timeout):
            current_settings = json.loads(paths.settings_path.read_text(encoding="utf-8"))
            self.assertEqual(current_settings["upstream_base"], "https://api.old.test/v1")
            self.assertEqual(new_settings.upstream_base, "https://api.new.test/v1")
            self.assertEqual(timeout, 12.5)
            return {"status": "verified", "request": "POST /v1/responses"}

        manager.verify_upstream_responses = fake_verify
        manager.start_background = lambda _paths, _settings, _verbose_proxy: {"status": "started", "pid": 1234}
        try:
            set_args = argparse.Namespace(
                codex_home=str(codex_home),
                upstream_base="https://api.new.test/v1",
                service_tier_policy=None,
                upstream_api_key_env=None,
                clear_upstream_api_key_env=False,
                verify=True,
                verify_timeout=12.5,
                restart=False,
                verbose_proxy=False,
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_set_upstream(set_args), 0)
        finally:
            manager.verify_upstream_responses = original_verify
            manager.start_background = original_start_background

        result = json.loads(output.getvalue())
        settings = json.loads(paths.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(result["verification"]["status"], "verified")
        self.assertEqual(settings["upstream_base"], "https://api.new.test/v1")

    def test_set_upstream_provider_auth_file_tracks_provider_base_url(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model = "gpt-test"\n'
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        manager.write_settings(
            paths,
            manager.ProxySettings(
                provider="acme",
                host="127.0.0.1",
                port=18787,
                proxy_base="/v1",
                upstream_base="https://api.old.test/v1",
                service_tier="priority",
                upstream_api_key_file=True,
            ),
        )
        manager.write_provider_auth_secret(paths, "acme", "provider-secret")

        with (
            mock.patch("codex_fast_proxy.manager.proxy_runtime_state", return_value=(1234, True, {"ok": True}, True, False, True)),
            mock.patch("codex_fast_proxy.manager.install_startup_hook", return_value={"status": "installed"}),
        ):
            result = manager.set_upstream_result(argparse.Namespace(
                codex_home=str(codex_home),
                upstream_base="https://api.new.test/v1",
                service_tier_policy=None,
                upstream_api_key_env=None,
                use_provider_auth_file=False,
                clear_upstream_api_key_env=False,
                clear_upstream_auth=False,
                verify=False,
                verify_timeout=60.0,
                restart=False,
                verbose_proxy=False,
            ))

        stored_auth = json.loads(paths.provider_auth_path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "upstream_updated")
        self.assertEqual(stored_auth["providers"]["acme"]["api_key"], "provider-secret")
        self.assertEqual(stored_auth["providers"]["acme"]["base_url"], "https://api.new.test/v1")

    def test_set_upstream_verification_failure_does_not_write_settings(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model = "gpt-test"\n'
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        original_settings = {
            "provider": "acme",
            "host": "127.0.0.1",
            "port": 18787,
            "proxy_base": "/v1",
            "upstream_base": "https://api.old.test/v1",
            "service_tier": "priority",
            "base_url": "http://127.0.0.1:18787/v1",
        }
        paths.settings_path.write_text(json.dumps(original_settings), encoding="utf-8")

        original_verify = manager.verify_upstream_responses
        original_start_background = manager.start_background
        manager.verify_upstream_responses = lambda *_args, **_kwargs: (_ for _ in ()).throw(ConfigError("probe failed"))
        manager.start_background = lambda *_args, **_kwargs: self.fail("start_background should not run")
        try:
            set_args = argparse.Namespace(
                codex_home=str(codex_home),
                upstream_base="https://api.new.test/v1",
                service_tier_policy=None,
                upstream_api_key_env=None,
                clear_upstream_api_key_env=False,
                verify=True,
                verify_timeout=60.0,
                restart=False,
                verbose_proxy=False,
            )
            with self.assertRaises(ConfigError):
                command_set_upstream(set_args)
        finally:
            manager.verify_upstream_responses = original_verify
            manager.start_background = original_start_background

        self.assertEqual(json.loads(paths.settings_path.read_text(encoding="utf-8")), original_settings)

    def test_set_upstream_no_verify_skips_side_path_probe(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.old.test/v1",
                "service_tier": "priority",
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )

        original_verify = manager.verify_upstream_responses
        original_start_background = manager.start_background
        manager.verify_upstream_responses = lambda *_args, **_kwargs: self.fail("verify should not run")
        manager.start_background = lambda _paths, _settings, _verbose_proxy: {"status": "started", "pid": 1234}
        try:
            set_args = argparse.Namespace(
                codex_home=str(codex_home),
                upstream_base="https://api.new.test/v1",
                service_tier_policy=None,
                upstream_api_key_env=None,
                clear_upstream_api_key_env=False,
                verify=False,
                verify_timeout=60.0,
                restart=False,
                verbose_proxy=False,
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_set_upstream(set_args), 0)
        finally:
            manager.verify_upstream_responses = original_verify
            manager.start_background = original_start_background

        result = json.loads(output.getvalue())
        self.assertEqual(result["verification"], {"status": "skipped", "reason": "--no-verify"})

    def test_status_uses_health_when_windows_pid_probe_is_unavailable(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )

        original_current_process = manager.current_process
        original_proxy_health = manager.proxy_health
        original_is_port_available = manager.is_port_available
        manager.current_process = lambda _paths: (8096, False)
        manager.proxy_health = lambda _settings: {
            "ok": True,
            "pid": 8096,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "service_tier_policy": "inject_missing",
            "runtime_id": manager.RUNTIME_ID,
        }
        manager.is_port_available = lambda _host, _port: False
        try:
            with contextlib.redirect_stdout(io.StringIO()) as status_output:
                self.assertEqual(manager.command_status(argparse.Namespace(codex_home=str(codex_home), provider=None)), 0)
            status = json.loads(status_output.getvalue())
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health
            manager.is_port_available = original_is_port_available

        self.assertEqual(status["status"], "running")
        self.assertTrue(status["healthy"])
        self.assertEqual(status["pid"], 8096)

    def test_status_reports_auth_and_fast_state_without_secret(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        (paths.codex_home / "auth.json").write_text(
            json.dumps({"tokens": {"access_token": "chatgpt-secret"}, "ACME_API_KEY": "provider-secret"}),
            encoding="utf-8",
        )
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "service_tier_policy": "auto",
                "upstream_api_key_env": "ACME_API_KEY",
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )

        original_current_process = manager.current_process
        original_proxy_health = manager.proxy_health
        original_is_port_available = manager.is_port_available
        manager.current_process = lambda _paths: (8096, False)
        manager.proxy_health = lambda _settings: {
            "ok": True,
            "pid": 8096,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "service_tier_policy": "auto",
            "service_tier_effective_policy": "preserve",
            "upstream_api_key_env": "ACME_API_KEY",
            "runtime_id": manager.RUNTIME_ID,
            "runtime": {
                "runtime_id": manager.RUNTIME_ID,
                "python_executable": "proxy-python",
                "module_file": "proxy-module",
                "source_root": "proxy-root",
                "source_layout": "source_checkout",
            },
        }
        manager.is_port_available = lambda _host, _port: False
        try:
            with contextlib.redirect_stdout(io.StringIO()) as status_output:
                self.assertEqual(manager.command_status(argparse.Namespace(codex_home=str(codex_home), provider=None)), 0)
            status_text = status_output.getvalue()
            status = json.loads(status_text)
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health
            manager.is_port_available = original_is_port_available

        self.assertEqual(status["login_mode"], "mixed")
        self.assertEqual(status["service_tier_policy"], "auto")
        self.assertEqual(status["service_tier_effective_policy"], "preserve")
        self.assertEqual(status["fast_behavior"], "app_controlled")
        self.assertEqual(status["upstream_auth"], "override_configured")
        self.assertEqual(status["upstream_api_key_env"], "ACME_API_KEY")
        self.assertTrue(status["upstream_api_key_available"])
        self.assertEqual(status["upstream_api_key_source"], "auth_json_fallback")
        self.assertFalse(status["upstream_api_key_persistent"])
        self.assertFalse(status["chatgpt_login_compatible"])
        self.assertEqual(status["diagnosis"]["level"], "attention")
        self.assertEqual(status["diagnosis"]["code"], "upstream_auth_not_persistent")
        self.assertEqual(status["runtime"]["proxy"]["python_executable"], "proxy-python")
        self.assertEqual(status["runtime"]["manager"]["python_executable"], sys.executable)
        self.assertIn("manager.py", status["runtime"]["manager"]["manager_module_file"])
        self.assertIn("codex_fast_proxy", status["runtime"]["hook_command"])
        self.assertIn("autostart", status["runtime"]["hook_command"])
        self.assertNotIn("provider-secret", status_text)
        self.assertNotIn("chatgpt-secret", status_text)

    def test_status_requires_hook_feature_flag_for_startup_hook_ready(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        (paths.codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "secret"}), encoding="utf-8")
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "service_tier_policy": "inject_missing",
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )
        install_startup_hook(paths)
        manager.remove_hook_feature_flags(paths.config_path)

        original_current_process = manager.current_process
        original_proxy_health = manager.proxy_health
        original_is_port_available = manager.is_port_available
        manager.current_process = lambda _paths: (8096, True)
        manager.proxy_health = lambda _settings: {
            "ok": True,
            "pid": 8096,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "service_tier_policy": "inject_missing",
            "runtime_id": manager.RUNTIME_ID,
        }
        manager.is_port_available = lambda _host, _port: False
        try:
            with contextlib.redirect_stdout(io.StringIO()) as status_output:
                self.assertEqual(manager.command_status(argparse.Namespace(codex_home=str(codex_home), provider=None)), 0)
            status = json.loads(status_output.getvalue())
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health
            manager.is_port_available = original_is_port_available

        self.assertFalse(status["startup_hook"])
        self.assertFalse(status["startup_hook_trust"]["feature_enabled"])
        self.assertTrue(status["startup_hook_trust"]["trusted"])
        self.assertFalse(status["startup_hook_trust"]["ready"])
        self.assertEqual(status["diagnosis"]["code"], "startup_hook_not_ready")

    def test_status_diagnosis_ready_when_core_state_is_consistent(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            service_tier_policy="auto",
            upstream_api_key_env="ACME_API_KEY",
        )
        diagnosis = manager.status_diagnosis(
            settings,
            running=True,
            healthy=True,
            pending_restart=False,
            config_matches=True,
            runtime_matches=True,
            needs_restart=False,
            startup_hook_ready=True,
            login=manager.LoginDiagnosis("chatgpt", False, True, "test"),
            auth={
                "upstream_auth": "override_configured",
                "upstream_api_key_available": True,
                "upstream_api_key_persistent": True,
            },
            behavior="app_controlled",
        )

        self.assertEqual(diagnosis["level"], "ready")
        self.assertEqual(diagnosis["code"], "ready")

    def test_status_diagnosis_reports_auth_risk_before_pending_restart(self) -> None:
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            service_tier_policy="preserve",
            upstream_api_key_env="ACME_API_KEY",
        )
        diagnosis = manager.status_diagnosis(
            settings,
            running=True,
            healthy=False,
            pending_restart=True,
            config_matches=True,
            runtime_matches=True,
            needs_restart=True,
            startup_hook_ready=True,
            login=manager.LoginDiagnosis("chatgpt", False, True, "chatgpt_auth_detected"),
            auth={
                "upstream_auth": "override_configured",
                "upstream_api_key_available": False,
                "upstream_api_key_persistent": False,
            },
            behavior="preserve_only",
        )

        self.assertEqual(diagnosis["level"], "risk")
        self.assertEqual(diagnosis["code"], "upstream_auth_missing")

    def test_verify_upstream_responses_uses_streaming_smoke_without_reporting_secret(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.codex_home.mkdir(parents=True)
        paths.config_path.write_text(
            'model = "gpt-test"\n'
            'model_reasoning_effort = "high"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        (paths.codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "provider-secret"}), encoding="utf-8")
        config = load_toml_config(paths.config_path)
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            service_tier_policy="inject_missing",
        )

        original_run_sample = benchmark.run_sample

        def fake_run_sample(target, label, timeout):
            self.assertEqual(target.model, "gpt-test")
            self.assertEqual(target.profile, "smoke")
            self.assertEqual(target.reasoning_effort, "low")
            self.assertEqual(target.api_key, "provider-secret")
            self.assertEqual(label, "priority")
            self.assertEqual(timeout, 42.0)
            return {
                "status": 200,
                "response_content_type": "text/event-stream",
                "first_event_ms": 1.0,
                "total_ms": 2.0,
                "response_service_tier": "priority",
            }

        benchmark.run_sample = fake_run_sample
        try:
            result = manager.verify_upstream_responses(paths, config, settings, 42.0)
        finally:
            benchmark.run_sample = original_run_sample

        result_text = json.dumps(result)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["request"], "POST /v1/responses")
        self.assertEqual(result["reasoning_effort"], "low")
        self.assertEqual(result["service_tier_request"], "priority")
        self.assertNotIn("provider-secret", result_text)

    def test_verify_upstream_responses_rejects_non_sse_response(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.codex_home.mkdir(parents=True)
        paths.config_path.write_text('model = "gpt-test"\n', encoding="utf-8")
        (paths.codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "provider-secret"}), encoding="utf-8")
        config = load_toml_config(paths.config_path)
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            service_tier_policy="preserve",
        )

        original_run_sample = benchmark.run_sample
        benchmark.run_sample = lambda *_args, **_kwargs: {"status": 200, "response_content_type": "application/json"}
        try:
            with self.assertRaises(ConfigError) as caught:
                manager.verify_upstream_responses(paths, config, settings, 42.0)
        finally:
            benchmark.run_sample = original_run_sample

        self.assertNotIn("provider-secret", str(caught.exception))
        self.assertIn("did not return SSE", str(caught.exception))

    def test_benchmark_uses_provider_auth_file_when_configured(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model = "gpt-test"\n'
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "upstream_api_key_file": True,
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )
        manager.write_provider_auth_secret(paths, "acme", "provider-secret")
        captured: dict[str, object] = {}

        original_run_benchmark = benchmark.run_benchmark

        def fake_run_benchmark(target, *_args, **_kwargs):
            captured["target"] = target
            return {"ok": True}

        benchmark.run_benchmark = fake_run_benchmark
        try:
            args = argparse.Namespace(
                codex_home=str(codex_home),
                pairs=1,
                timeout=30.0,
                model=None,
                reasoning_effort=None,
                profile="smoke",
                mode="direct",
                api_key_env=None,
                save=False,
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(manager.command_benchmark(args), 0)
        finally:
            benchmark.run_benchmark = original_run_benchmark

        target = captured["target"]
        self.assertEqual(target.api_key, "provider-secret")
        self.assertEqual(target.api_key_source, "provider_auth_file")
        self.assertNotIn("provider-secret", output.getvalue())

    def test_process_env_auth_source_is_chatgpt_login_compatible_without_printing_secret(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_env="ACME_API_KEY",
        )
        old_env = os.environ.get("ACME_API_KEY")
        os.environ["ACME_API_KEY"] = "provider-secret"
        try:
            status = manager.upstream_auth_status(paths, settings)
        finally:
            if old_env is None:
                os.environ.pop("ACME_API_KEY", None)
            else:
                os.environ["ACME_API_KEY"] = old_env

        self.assertEqual(status["upstream_api_key_source"], "process_env")
        self.assertTrue(status["upstream_api_key_persistent"])
        self.assertNotIn("provider-secret", json.dumps(status))

    def test_auth_source_order_matches_proxy_env_resolution(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_env="ACME_API_KEY",
        )
        old_env = os.environ.get("ACME_API_KEY")

        os.environ["ACME_API_KEY"] = "process-secret"
        try:
            from codex_fast_proxy import auth

            original_windows_user_env = auth.windows_user_env
            auth.windows_user_env = lambda _name: "windows-secret"
            try:
                status = manager.upstream_auth_status(paths, settings)
            finally:
                auth.windows_user_env = original_windows_user_env
        finally:
            if old_env is None:
                os.environ.pop("ACME_API_KEY", None)
            else:
                os.environ["ACME_API_KEY"] = old_env

        self.assertEqual(status["upstream_api_key_source"], "process_env")

    def test_check_update_is_read_only_and_reports_available_update(self) -> None:
        repo = self.temp_dir / "repo"
        calls: list[tuple[str, ...]] = []
        original_run_git = updater.run_git

        def fake_run_git(_repo, *args, timeout=30.0):
            calls.append(args)
            if args == ("rev-parse", "--is-inside-work-tree"):
                return "true"
            if args == ("branch", "--show-current"):
                return "main"
            if args == ("rev-parse", "HEAD"):
                return "a" * 40
            if args == ("status", "--porcelain"):
                return " M README.md"
            if args == ("remote", "get-url", "origin"):
                return "https://token:secret@github.com/example/repo.git?x=secret#frag"
            if args == ("ls-remote", "origin", "refs/heads/main"):
                return f"{'b' * 40}\trefs/heads/main"
            if args == ("cat-file", "-e", f"{'b' * 40}^{{commit}}"):
                raise ConfigError("missing remote commit")
            raise AssertionError(args)

        updater.run_git = fake_run_git
        try:
            result = manager.check_update(repo)
        finally:
            updater.run_git = original_run_git

        self.assertTrue(result["read_only"])
        self.assertTrue(result["update_available"])
        self.assertTrue(result["local_changes"])
        self.assertEqual(result["relation"], "remote_unknown")
        self.assertEqual(result["remote_url"], "https://github.com/example/repo.git")
        self.assertEqual(result["next_action"], "review local changes before updating")
        self.assertNotIn(("pull",), calls)
        self.assertNotIn(("fetch",), calls)

    def test_check_update_reports_up_to_date(self) -> None:
        repo = self.temp_dir / "repo"
        commit = "a" * 40
        original_run_git = updater.run_git

        def fake_run_git(_repo, *args, timeout=30.0):
            if args == ("rev-parse", "--is-inside-work-tree"):
                return "true"
            if args == ("branch", "--show-current"):
                return "main"
            if args == ("rev-parse", "HEAD"):
                return commit
            if args == ("status", "--porcelain"):
                return ""
            if args == ("remote", "get-url", "origin"):
                return "https://github.com/example/repo.git"
            if args == ("ls-remote", "origin", "refs/heads/main"):
                return f"{commit}\trefs/heads/main"
            raise AssertionError(args)

        updater.run_git = fake_run_git
        try:
            result = manager.check_update(repo)
        finally:
            updater.run_git = original_run_git

        self.assertFalse(result["update_available"])
        self.assertFalse(result["local_changes"])
        self.assertEqual(result["relation"], "same")
        self.assertEqual(result["next_action"], "none")

    def test_check_update_reports_local_ahead_as_no_update_available(self) -> None:
        repo = self.temp_dir / "repo"
        local_commit = "c" * 40
        remote_commit = "b" * 40
        original_run_git = updater.run_git

        def fake_run_git(_repo, *args, timeout=30.0):
            if args == ("rev-parse", "--is-inside-work-tree"):
                return "true"
            if args == ("branch", "--show-current"):
                return "main"
            if args == ("rev-parse", "HEAD"):
                return local_commit
            if args == ("status", "--porcelain"):
                return ""
            if args == ("remote", "get-url", "origin"):
                return "https://github.com/example/repo.git"
            if args == ("ls-remote", "origin", "refs/heads/main"):
                return f"{remote_commit}\trefs/heads/main"
            if args == ("cat-file", "-e", f"{remote_commit}^{{commit}}"):
                return ""
            if args == ("merge-base", "--is-ancestor", remote_commit, local_commit):
                return ""
            raise AssertionError(args)

        updater.run_git = fake_run_git
        try:
            result = manager.check_update(repo)
        finally:
            updater.run_git = original_run_git

        self.assertEqual(result["relation"], "local_ahead")
        self.assertFalse(result["update_available"])
        self.assertEqual(result["next_action"], "none")

    def test_check_update_reports_diverged_without_local_changes(self) -> None:
        repo = self.temp_dir / "repo"
        local_commit = "c" * 40
        remote_commit = "b" * 40
        original_run_git = updater.run_git

        def fake_run_git(_repo, *args, timeout=30.0):
            if args == ("rev-parse", "--is-inside-work-tree"):
                return "true"
            if args == ("branch", "--show-current"):
                return "main"
            if args == ("rev-parse", "HEAD"):
                return local_commit
            if args == ("status", "--porcelain"):
                return ""
            if args == ("remote", "get-url", "origin"):
                return "https://github.com/example/repo.git"
            if args == ("ls-remote", "origin", "refs/heads/main"):
                return f"{remote_commit}\trefs/heads/main"
            if args == ("cat-file", "-e", f"{remote_commit}^{{commit}}"):
                return ""
            if args in {
                ("merge-base", "--is-ancestor", remote_commit, local_commit),
                ("merge-base", "--is-ancestor", local_commit, remote_commit),
            }:
                raise ConfigError("not ancestor")
            raise AssertionError(args)

        updater.run_git = fake_run_git
        try:
            result = manager.check_update(repo)
        finally:
            updater.run_git = original_run_git

        self.assertEqual(result["relation"], "diverged")
        self.assertTrue(result["update_available"])
        self.assertEqual(result["next_action"], "review local commits before updating")

    def test_update_installation_refreshes_enabled_proxy_through_manager_commands(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
        )
        manager.write_settings(paths, settings)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            f'base_url = "{settings.base_url}"\n',
            encoding="utf-8",
        )
        repo = self.temp_dir / "repo"
        repo.mkdir()
        git_calls: list[tuple[str, ...]] = []
        python_calls: list[tuple[str, ...]] = []
        json_calls: list[tuple[str, ...]] = []
        commits = iter(["a" * 40, "b" * 40])

        def fake_run_git(_repo, *args, timeout=30.0):
            git_calls.append(args)
            if args == ("rev-parse", "HEAD"):
                return next(commits)
            if args == ("pull", "--ff-only", "origin", "main"):
                return "Updating a..b"
            raise AssertionError(args)

        def fake_run_python(args, timeout=300.0):
            python_calls.append(tuple(args))
            return ""

        def fake_run_python_json(args, timeout=300.0):
            json_calls.append(tuple(args))
            if "install" in args:
                return {"status": "installed"}
            if "status" in args:
                return {"status": "running", "needs_restart": False}
            raise AssertionError(args)

        with (
            mock.patch("codex_fast_proxy.updater.check_update", return_value={
                "status": "checked",
                "local_changes": False,
                "relation": "remote_ahead",
            }),
            mock.patch("codex_fast_proxy.updater.run_git", side_effect=fake_run_git),
            mock.patch("codex_fast_proxy.updater.run_python", side_effect=fake_run_python),
            mock.patch("codex_fast_proxy.updater.run_python_json", side_effect=fake_run_python_json),
            mock.patch("codex_fast_proxy.updater.link_skill_namespace", return_value={"status": "already_linked"}),
        ):
            result = manager.update_installation(codex_home, repo=repo, branch="main")

        self.assertEqual(result["status"], "updated")
        self.assertTrue(result["enabled_before_update"])
        self.assertFalse(result["restart_required"])
        self.assertIn(("pull", "--ff-only", "origin", "main"), git_calls)
        self.assertIn(("-m", "pip", "install", "--user", "-e", str(repo.resolve())), python_calls)
        self.assertTrue(any(call[2] == "install" and "--start" in call for call in json_calls))

    def test_update_installation_skips_pull_and_pip_when_already_current(self) -> None:
        repo = self.temp_dir / "repo"
        repo.mkdir()
        commit = "a" * 40
        git_calls: list[tuple[str, ...]] = []
        json_calls: list[tuple[str, ...]] = []

        def fake_run_git(_repo, *args, timeout=30.0):
            git_calls.append(args)
            if args == ("rev-parse", "HEAD"):
                return commit
            raise AssertionError(args)

        def fake_run_python_json(args, timeout=300.0):
            json_calls.append(tuple(args))
            if "doctor" in args:
                return {"ok": True}
            if "status" in args:
                return {"status": "stopped", "needs_restart": False}
            raise AssertionError(args)

        with (
            mock.patch("codex_fast_proxy.updater.check_update", return_value={
                "status": "checked",
                "local_changes": False,
                "relation": "same",
            }),
            mock.patch("codex_fast_proxy.updater.run_git", side_effect=fake_run_git),
            mock.patch("codex_fast_proxy.updater.run_python") as run_python,
            mock.patch("codex_fast_proxy.updater.run_python_json", side_effect=fake_run_python_json),
            mock.patch("codex_fast_proxy.updater.link_skill_namespace", return_value={"status": "already_linked"}),
        ):
            result = manager.update_installation(self.temp_dir / ".codex", repo=repo, branch="main")

        self.assertEqual(result["status"], "already_current")
        self.assertEqual(result["code_update"]["status"], "already_current")
        self.assertNotIn(("pull", "--ff-only", "origin", "main"), git_calls)
        run_python.assert_not_called()
        self.assertTrue(any(call[2] == "doctor" for call in json_calls))

    def test_update_installation_keeps_unenabled_doctor_failure_as_attention(self) -> None:
        repo = self.temp_dir / "repo"
        repo.mkdir()
        commit = "a" * 40

        def fake_run_git(_repo, *args, timeout=30.0):
            if args == ("rev-parse", "HEAD"):
                return commit
            raise AssertionError(args)

        def fake_run_python_json(args, timeout=300.0):
            if "doctor" in args:
                raise ConfigError("not enabled")
            if "status" in args:
                return {"status": "stopped", "needs_restart": False}
            raise AssertionError(args)

        with (
            mock.patch("codex_fast_proxy.updater.check_update", return_value={
                "status": "checked",
                "local_changes": False,
                "relation": "same",
            }),
            mock.patch("codex_fast_proxy.updater.run_git", side_effect=fake_run_git),
            mock.patch("codex_fast_proxy.updater.run_python") as run_python,
            mock.patch("codex_fast_proxy.updater.run_python_json", side_effect=fake_run_python_json),
            mock.patch("codex_fast_proxy.updater.link_skill_namespace", return_value={"status": "already_linked"}),
        ):
            result = manager.update_installation(self.temp_dir / ".codex", repo=repo, branch="main")

        self.assertEqual(result["status"], "already_current")
        self.assertEqual(result["refresh"]["status"], "attention")
        self.assertIn("not enabled", result["refresh"]["error"])
        run_python.assert_not_called()

    def test_update_installation_blocks_local_changes_before_pull_or_pip(self) -> None:
        repo = self.temp_dir / "repo"
        repo.mkdir()

        with (
            mock.patch("codex_fast_proxy.updater.run_git", return_value="a" * 40),
            mock.patch("codex_fast_proxy.updater.check_update", return_value={
                "status": "checked",
                "local_changes": True,
                "relation": "remote_ahead",
            }),
            mock.patch("codex_fast_proxy.updater.run_python") as run_python,
        ):
            result = manager.update_installation(self.temp_dir / ".codex", repo=repo, branch="main")

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "local_changes")
        run_python.assert_not_called()

    def test_start_background_noops_when_health_is_available_but_pid_probe_fails(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
        )

        original_current_process = manager.current_process
        original_proxy_health = manager.proxy_health
        original_launch_background = manager.launch_background
        manager.current_process = lambda _paths: (8096, False)
        manager.proxy_health = lambda _settings: {
            "ok": True,
            "pid": 8096,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "service_tier_policy": "auto",
            "service_tier_effective_policy": "preserve",
            "runtime_id": manager.RUNTIME_ID,
        }
        manager.launch_background = lambda *_args, **_kwargs: self.fail("launch_background should not run")
        try:
            result = manager.start_background(paths, settings, verbose_proxy=False)
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health
            manager.launch_background = original_launch_background

        self.assertEqual(result["status"], "already_running")
        self.assertEqual(result["pid"], 8096)

    def test_set_upstream_refuses_when_config_no_longer_points_to_proxy(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://manual.example/v1"\n',
            encoding="utf-8",
        )
        write_settings = {
            "provider": "acme",
            "host": "127.0.0.1",
            "port": 18787,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "base_url": "http://127.0.0.1:18787/v1",
        }
        paths.settings_path.write_text(json.dumps(write_settings), encoding="utf-8")
        set_args = argparse.Namespace(
            codex_home=str(codex_home),
            upstream_base="https://api.new.test/v1",
            restart=False,
            verbose_proxy=False,
        )

        with self.assertRaises(ConfigError):
            command_set_upstream(set_args)

        settings = json.loads(paths.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(settings["upstream_base"], "https://api.acme.test/v1")

    def test_set_upstream_can_update_policy_and_auth_env_without_new_url(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )
        (paths.codex_home / "auth.json").write_text(json.dumps({"ACME_API_KEY": "secret"}), encoding="utf-8")

        original_start_background = manager.start_background

        def fake_start_background(paths, settings, verbose_proxy):
            return {
                "status": "started",
                "pid": 1234,
                "policy": settings.service_tier_policy,
                "upstream_api_key_env": settings.upstream_api_key_env,
            }

        manager.start_background = fake_start_background
        try:
            set_args = argparse.Namespace(
                codex_home=str(codex_home),
                upstream_base=None,
                service_tier_policy="inject_missing",
                upstream_api_key_env="ACME_API_KEY",
                restart=False,
                verbose_proxy=False,
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_set_upstream(set_args), 0)
        finally:
            manager.start_background = original_start_background

        result = json.loads(output.getvalue())
        settings = json.loads(paths.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(result["upstream_base"], "https://api.acme.test/v1")
        self.assertEqual(settings["service_tier_policy"], "inject_missing")
        self.assertEqual(settings["upstream_api_key_env"], "ACME_API_KEY")

    def test_set_upstream_auth_env_warns_before_chatgpt_login_when_restart_deferred(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "service_tier_policy": "auto",
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )
        (paths.codex_home / "auth.json").write_text(json.dumps({"ACME_API_KEY": "secret"}), encoding="utf-8")

        original_current_process = manager.current_process
        original_proxy_health = manager.proxy_health
        manager.current_process = lambda _paths: (1234, True)
        manager.proxy_health = lambda _settings: {
            "ok": True,
            "pid": 1234,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "service_tier_policy": "auto",
            "service_tier_effective_policy": "inject_missing",
            "upstream_api_key_env": None,
            "runtime_id": manager.RUNTIME_ID,
        }
        try:
            set_args = argparse.Namespace(
                codex_home=str(codex_home),
                upstream_base=None,
                service_tier_policy=None,
                upstream_api_key_env="ACME_API_KEY",
                clear_upstream_api_key_env=False,
                restart=False,
                verbose_proxy=False,
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_set_upstream(set_args), 0)
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health

        result = json.loads(output.getvalue())
        self.assertTrue(result["restart_required"])
        self.assertEqual(result["start_result"]["status"], "deferred")
        self.assertIn("Before signing in with ChatGPT", result["next_user_action"])
        self.assertIn("needs_restart=true", result["next_user_action"])

    def test_set_upstream_provider_auth_file_request_defers_restart_even_when_settings_match(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "service_tier_policy": "auto",
                "upstream_api_key_file": True,
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )
        manager.write_provider_auth_secret(paths, "acme", "provider-secret")

        original_current_process = manager.current_process
        original_proxy_health = manager.proxy_health
        manager.current_process = lambda _paths: (1234, True)
        manager.proxy_health = lambda _settings: {
            "ok": True,
            "pid": 1234,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "service_tier_policy": "auto",
            "service_tier_effective_policy": "inject_missing",
            "upstream_api_key_env": None,
            "upstream_api_key_file": True,
            "runtime_id": manager.RUNTIME_ID,
        }
        try:
            set_args = argparse.Namespace(
                codex_home=str(codex_home),
                upstream_base=None,
                service_tier_policy=None,
                upstream_api_key_env=None,
                use_provider_auth_file=True,
                clear_upstream_api_key_env=False,
                clear_upstream_auth=False,
                verify=False,
                verify_timeout=60.0,
                restart=False,
                verbose_proxy=False,
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_set_upstream(set_args), 0)
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health

        result = json.loads(output.getvalue())
        self.assertTrue(result["restart_required"])
        self.assertEqual(result["start_result"]["status"], "deferred")

    def test_set_upstream_can_clear_auth_env_without_new_url(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "upstream_api_key_env": "ACME_API_KEY",
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )

        original_start_background = manager.start_background
        manager.start_background = lambda _paths, _settings, _verbose_proxy: {"status": "started", "pid": 1234}
        try:
            set_args = argparse.Namespace(
                codex_home=str(codex_home),
                upstream_base=None,
                service_tier_policy=None,
                upstream_api_key_env=None,
                clear_upstream_api_key_env=True,
                restart=False,
                verbose_proxy=False,
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_set_upstream(set_args), 0)
        finally:
            manager.start_background = original_start_background

        result = json.loads(output.getvalue())
        settings = json.loads(paths.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(result["upstream_auth"], "preserved")
        self.assertIsNone(settings.get("upstream_api_key_env"))

    def test_set_upstream_rejects_auth_env_and_clear_auth_env_together(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.acme.test/v1",
                "service_tier": "priority",
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )
        set_args = argparse.Namespace(
            codex_home=str(codex_home),
            upstream_base=None,
            service_tier_policy=None,
            upstream_api_key_env="ACME_API_KEY",
            clear_upstream_api_key_env=True,
            restart=False,
            verbose_proxy=False,
        )

        with self.assertRaises(ConfigError):
            command_set_upstream(set_args)

    def test_set_upstream_rejects_missing_auth_env_before_writing_settings(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n',
            encoding="utf-8",
        )
        original_settings = {
            "provider": "acme",
            "host": "127.0.0.1",
            "port": 18787,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "base_url": "http://127.0.0.1:18787/v1",
        }
        paths.settings_path.write_text(json.dumps(original_settings), encoding="utf-8")
        set_args = argparse.Namespace(
            codex_home=str(codex_home),
            upstream_base=None,
            service_tier_policy=None,
            upstream_api_key_env="MISSING_ACME_API_KEY",
            clear_upstream_api_key_env=False,
            restart=False,
            verbose_proxy=False,
        )

        with self.assertRaises(ConfigError):
            command_set_upstream(set_args)

        self.assertEqual(json.loads(paths.settings_path.read_text(encoding="utf-8")), original_settings)

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

    def test_install_failure_after_proxy_restart_restores_previous_proxy(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        paths = paths_for(codex_home)
        config_path = codex_home / "config.toml"
        original_config = (
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "http://127.0.0.1:18787/v1"\n'
        )
        original_settings = {
            "provider": "acme",
            "host": "127.0.0.1",
            "port": 18787,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "service_tier_policy": "inject_missing",
            "base_url": "http://127.0.0.1:18787/v1",
        }
        config_path.write_text(original_config, encoding="utf-8")
        paths.settings_path.parent.mkdir(parents=True, exist_ok=True)
        paths.settings_path.write_text(json.dumps(original_settings), encoding="utf-8")

        install_args = self.install_args(codex_home)
        install_args.service_tier_policy = "preserve"
        calls: list[str] = []
        original_start_background = manager.start_background
        original_stop_process = manager.stop_process
        original_install_startup_hook = manager.install_startup_hook

        def fake_start_background(paths, settings, verbose_proxy):
            calls.append(f"start:{settings.service_tier_policy}")
            if len(calls) == 1:
                return {"status": "restarted", "pid": 1234}
            return {"status": "started", "pid": 4321}

        def fake_stop_process(paths, force=False):
            calls.append(f"stop:{force}")
            return {"status": "stopped", "pid": 1234}

        manager.start_background = fake_start_background
        manager.stop_process = fake_stop_process
        manager.install_startup_hook = lambda _paths: (_ for _ in ()).throw(ConfigError("hook failed"))
        try:
            with self.assertRaises(ConfigError):
                command_install(install_args)
        finally:
            manager.start_background = original_start_background
            manager.stop_process = original_stop_process
            manager.install_startup_hook = original_install_startup_hook

        self.assertEqual(calls, ["start:preserve", "stop:True", "start:inject_missing"])
        self.assertEqual(config_path.read_text(encoding="utf-8"), original_config)
        self.assertEqual(json.loads(paths.settings_path.read_text(encoding="utf-8")), original_settings)

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

    def test_stop_process_allows_same_proxy_with_pending_settings_change(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.new.test/v1",
                "service_tier": "priority",
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )

        original_current_process = manager.current_process
        original_proxy_health = manager.proxy_health
        original_is_process_running = manager.is_process_running
        original_terminate_process = manager.terminate_process
        terminated: list[int] = []

        manager.current_process = lambda _paths: (9999, True)
        manager.proxy_health = lambda _settings: {
            "ok": True,
            "pid": 9999,
            "proxy_base": "/v1",
            "upstream_base": "https://api.old.test/v1",
            "service_tier": "priority",
            "runtime_id": manager.RUNTIME_ID,
        }
        manager.is_process_running = lambda _pid: False
        manager.terminate_process = terminated.append
        try:
            result = stop_process(paths)
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health
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

        def fake_start_background(paths, settings, verbose_proxy, **_kwargs):
            return {"status": "started", "pid": 1234, "base_url": settings.base_url}

        manager.start_background = fake_start_background
        try:
            result = autostart_proxy(paths, verbose_proxy=False)
        finally:
            manager.start_background = original_start_background

        self.assertEqual(result["status"], "started")
        self.assertEqual(result["base_url"], "http://127.0.0.1:18787/v1")

    def test_autostart_leaves_running_stale_runtime_untouched(self) -> None:
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
        original_launch_background = manager.launch_background
        calls: list[str] = []

        def fake_stop_process(paths, force=False):
            calls.append("stop")
            self.assertFalse(force)
            return {"status": "stopped", "pid": 9999}

        def fake_launch_background(paths, settings, verbose_proxy):
            calls.append("start")
            return {"status": "started", "pid": 1234, "base_url": settings.base_url}

        manager.current_process = lambda _paths: (9999, True)
        manager.proxy_health = lambda _settings: {
            "ok": True,
            "pid": 9999,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "service_tier_policy": "inject_missing",
            "runtime_id": "old-runtime",
        }
        manager.stop_process = fake_stop_process
        manager.launch_background = fake_launch_background
        try:
            result = autostart_proxy(paths, verbose_proxy=False)
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health
            manager.stop_process = original_stop_process
            manager.launch_background = original_launch_background

        self.assertEqual(result["status"], "already_running")
        self.assertFalse(result["runtime_matches"])
        self.assertTrue(result["needs_restart"])
        self.assertEqual(calls, [])

    def test_start_restarts_when_running_runtime_is_stale(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
        )

        original_current_process = manager.current_process
        original_proxy_health = manager.proxy_health
        original_stop_process = manager.stop_process
        original_launch_background = manager.launch_background
        calls: list[str] = []

        def fake_stop_process(paths, force=False):
            calls.append("stop")
            self.assertFalse(force)
            return {"status": "stopped", "pid": 9999}

        def fake_launch_background(paths, settings, verbose_proxy):
            calls.append("start")
            return {"status": "started", "pid": 1234, "base_url": settings.base_url}

        manager.current_process = lambda _paths: (9999, True)
        manager.proxy_health = lambda _settings: {
            "ok": True,
            "pid": 9999,
            "proxy_base": "/v1",
            "upstream_base": "https://api.acme.test/v1",
            "service_tier": "priority",
            "service_tier_policy": "auto",
            "service_tier_effective_policy": "preserve",
            "runtime_id": "old-runtime",
        }
        manager.stop_process = fake_stop_process
        manager.launch_background = fake_launch_background
        try:
            result = manager.start_background(paths, settings, verbose_proxy=False)
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health
            manager.stop_process = original_stop_process
            manager.launch_background = original_launch_background

        self.assertEqual(result["status"], "restarted")
        self.assertEqual(result["reason"], "runtime_changed")
        self.assertEqual(calls, ["stop", "start"])

    def test_start_restarts_when_running_settings_changed(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        paths.app_home.mkdir(parents=True)
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.new.test/v1",
            service_tier="priority",
        )
        paths.settings_path.write_text(
            json.dumps({
                "provider": "acme",
                "host": "127.0.0.1",
                "port": 18787,
                "proxy_base": "/v1",
                "upstream_base": "https://api.new.test/v1",
                "service_tier": "priority",
                "base_url": "http://127.0.0.1:18787/v1",
            }),
            encoding="utf-8",
        )

        original_current_process = manager.current_process
        original_proxy_health = manager.proxy_health
        original_stop_process = manager.stop_process
        original_launch_background = manager.launch_background
        calls: list[str] = []

        def fake_stop_process(paths, force=False):
            calls.append(f"stop:{force}")
            self.assertTrue(force)
            return {"status": "stopped", "pid": 9999}

        def fake_launch_background(paths, settings, verbose_proxy):
            calls.append("start")
            return {"status": "started", "pid": 1234, "base_url": settings.base_url}

        manager.current_process = lambda _paths: (9999, True)
        manager.proxy_health = lambda _settings: {
            "ok": True,
            "pid": 9999,
            "proxy_base": "/v1",
            "upstream_base": "https://api.old.test/v1",
            "service_tier": "priority",
            "runtime_id": manager.RUNTIME_ID,
        }
        manager.stop_process = fake_stop_process
        manager.launch_background = fake_launch_background
        try:
            result = manager.start_background(paths, settings, verbose_proxy=False)
        finally:
            manager.current_process = original_current_process
            manager.proxy_health = original_proxy_health
            manager.stop_process = original_stop_process
            manager.launch_background = original_launch_background

        self.assertEqual(result["status"], "restarted")
        self.assertEqual(result["reason"], "settings_changed")
        self.assertEqual(calls, ["stop:True", "start"])

    def test_restart_restores_previous_proxy_when_new_launch_fails(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.new.test/v1",
            service_tier="priority",
            service_tier_policy="inject_missing",
            upstream_api_key_env="ACME_NEW_KEY",
        )
        health = {
            "ok": True,
            "pid": 9999,
            "proxy_base": "/v1",
            "upstream_base": "https://api.old.test/v1",
            "service_tier": "priority",
            "service_tier_policy": "preserve",
            "upstream_api_key_env": "ACME_OLD_KEY",
            "runtime_id": manager.RUNTIME_ID,
        }
        original_stop_process = manager.stop_process
        original_launch_background = manager.launch_background
        calls: list[str] = []

        def fake_launch_background(paths, launch_settings, verbose_proxy):
            calls.append(launch_settings.upstream_base)
            if launch_settings.upstream_base == "https://api.new.test/v1":
                raise ConfigError("new proxy failed")
            return {"status": "started", "pid": 1234, "base_url": launch_settings.base_url}

        manager.stop_process = lambda _paths, force=False: {"status": "stopped", "pid": 9999}
        manager.launch_background = fake_launch_background
        try:
            with self.assertRaises(ConfigError) as raised:
                manager.restart_background(paths, settings, False, 9999, health, force_stop=True)
        finally:
            manager.stop_process = original_stop_process
            manager.launch_background = original_launch_background

        self.assertIn("restored the previous proxy", str(raised.exception))
        self.assertEqual(calls, ["https://api.new.test/v1", "https://api.old.test/v1"])

    def test_launch_background_detaches_process_on_posix(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
        )
        captured: dict[str, object] = {}

        class FakeProcess:
            pid = 1234

        original_is_port_available = manager.is_port_available
        original_wait_for_proxy_health = manager.wait_for_proxy_health
        original_popen = manager.subprocess.Popen

        def fake_popen(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return FakeProcess()

        manager.is_port_available = lambda _host, _port: True
        manager.wait_for_proxy_health = lambda _settings, _process, **_kwargs: {"ok": True, "pid": _process.pid}
        manager.subprocess.Popen = fake_popen
        try:
            result = manager.launch_background(paths, settings, verbose_proxy=False)
        finally:
            manager.is_port_available = original_is_port_available
            manager.wait_for_proxy_health = original_wait_for_proxy_health
            manager.subprocess.Popen = original_popen

        self.assertEqual(result["status"], "started")
        self.assertEqual(captured["command"][0], sys.executable)
        self.assertIn("--service-tier-policy", captured["command"])
        self.assertIn("preserve", captured["command"])
        self.assertEqual(captured["kwargs"]["start_new_session"], manager.os.name != "nt")

    def test_launch_background_passes_upstream_key_env_name_not_secret(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        settings = manager.ProxySettings(
            provider="acme",
            host="127.0.0.1",
            port=18787,
            proxy_base="/v1",
            upstream_base="https://api.acme.test/v1",
            service_tier="priority",
            upstream_api_key_env="ACME_API_KEY",
        )
        captured: dict[str, object] = {}

        class FakeProcess:
            pid = 1234

        original_is_port_available = manager.is_port_available
        original_wait_for_proxy_health = manager.wait_for_proxy_health
        original_popen = manager.subprocess.Popen

        def fake_popen(command, **kwargs):
            captured["command"] = command
            return FakeProcess()

        manager.is_port_available = lambda _host, _port: True
        manager.wait_for_proxy_health = lambda _settings, _process, **_kwargs: {"ok": True, "pid": _process.pid}
        manager.subprocess.Popen = fake_popen
        try:
            manager.launch_background(paths, settings, verbose_proxy=False)
        finally:
            manager.is_port_available = original_is_port_available
            manager.wait_for_proxy_health = original_wait_for_proxy_health
            manager.subprocess.Popen = original_popen

        command = captured["command"]
        self.assertIn("--upstream-api-key-env", command)
        self.assertIn("ACME_API_KEY", command)
        self.assertNotIn("secret", " ".join(command))

    def test_quiet_autostart_does_not_log_noop_events(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        event_path = paths.state_dir / "fast_proxy.autostart.jsonl"
        args = argparse.Namespace(codex_home=str(codex_home), quiet=True, verbose_proxy=False)
        original_autostart_proxy = manager.autostart_proxy

        manager.autostart_proxy = lambda _paths, _verbose_proxy: {"status": "already_running", "pid": 1234}
        try:
            self.assertEqual(manager.command_autostart(args), 0)
            self.assertFalse(event_path.exists())

            manager.autostart_proxy = lambda _paths, _verbose_proxy: {"status": "skipped", "reason": "config_not_proxy"}
            self.assertEqual(manager.command_autostart(args), 0)
            self.assertFalse(event_path.exists())
        finally:
            manager.autostart_proxy = original_autostart_proxy

    def test_quiet_autostart_logs_runtime_changes(self) -> None:
        codex_home = self.temp_dir / ".codex"
        paths = paths_for(codex_home)
        event_path = paths.state_dir / "fast_proxy.autostart.jsonl"
        args = argparse.Namespace(codex_home=str(codex_home), quiet=True, verbose_proxy=False)
        original_autostart_proxy = manager.autostart_proxy

        manager.autostart_proxy = lambda _paths, _verbose_proxy: {"status": "restarted", "reason": "runtime_changed"}
        try:
            self.assertEqual(manager.command_autostart(args), 0)
        finally:
            manager.autostart_proxy = original_autostart_proxy

        self.assertTrue(event_path.exists())
        self.assertIn('"status":"restarted"', event_path.read_text(encoding="utf-8"))

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

    def test_deferred_uninstall_requires_confirmation_before_chatgpt_direct_upstream_restore(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        original = (
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n'
        )
        config_path.write_text(original, encoding="utf-8")
        (codex_home / "auth.json").write_text(
            json.dumps({"tokens": {"access_token": "chatgpt-token"}}),
            encoding="utf-8",
        )
        install_args = self.install_args(codex_home)
        install_args.upstream_api_key_env = "ACME_API_KEY"

        previous_env = os.environ.get("ACME_API_KEY")
        original_start_background = manager.start_background
        original_stop_process = manager.stop_process
        stop_calls = 0

        def fake_stop_process(paths, force=False):
            nonlocal stop_calls
            stop_calls += 1
            return {"status": "stopped", "pid": 1234}

        os.environ["ACME_API_KEY"] = "provider-secret"
        manager.start_background = lambda _paths, _settings, _verbose_proxy: {"status": "started", "pid": 1234}
        manager.stop_process = fake_stop_process
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)

            installed_config = config_path.read_text(encoding="utf-8")
            installed_hooks = paths_for(codex_home).hooks_path.read_text(encoding="utf-8")
            uninstall_args = argparse.Namespace(
                codex_home=str(codex_home),
                force=False,
                keep_state=False,
                defer_stop=True,
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_uninstall(uninstall_args), 4)
            output_text = output.getvalue()
            result = json.loads(output_text)
        finally:
            if previous_env is None:
                os.environ.pop("ACME_API_KEY", None)
            else:
                os.environ["ACME_API_KEY"] = previous_env
            manager.start_background = original_start_background
            manager.stop_process = original_stop_process

        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(result["code"], "chatgpt_auth_direct_upstream_uninstall_requires_confirmation")
        self.assertFalse(result["config_changed"])
        self.assertEqual(result["startup_hook"]["status"], "unchanged")
        self.assertEqual(result["stop_result"]["status"], "not_attempted")
        self.assertEqual(config_path.read_text(encoding="utf-8"), installed_config)
        self.assertEqual(paths_for(codex_home).hooks_path.read_text(encoding="utf-8"), installed_hooks)
        self.assertTrue(has_startup_hook(paths_for(codex_home)))
        self.assertTrue(paths_for(codex_home).app_home.exists())
        self.assertEqual(stop_calls, 0)
        self.assertNotIn("provider-secret", output_text)
        self.assertNotIn("chatgpt-token", output_text)

    def test_deferred_uninstall_warns_chatgpt_auth_direct_upstream_risk_after_confirmation(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        original = (
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n'
        )
        config_path.write_text(original, encoding="utf-8")
        (codex_home / "auth.json").write_text(
            json.dumps({"tokens": {"access_token": "chatgpt-token"}}),
            encoding="utf-8",
        )
        install_args = self.install_args(codex_home)
        install_args.upstream_api_key_env = "ACME_API_KEY"

        previous_env = os.environ.get("ACME_API_KEY")
        original_start_background = manager.start_background
        original_stop_process = manager.stop_process
        stop_calls = 0

        def fake_start_background(paths, settings, verbose_proxy):
            return {"status": "started", "pid": 1234}

        def fake_stop_process(paths, force=False):
            nonlocal stop_calls
            stop_calls += 1
            return {"status": "stopped", "pid": 1234}

        os.environ["ACME_API_KEY"] = "provider-secret"
        manager.start_background = fake_start_background
        manager.stop_process = fake_stop_process
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)

            uninstall_args = argparse.Namespace(
                codex_home=str(codex_home),
                force=False,
                keep_state=False,
                defer_stop=True,
                confirm_chatgpt_direct_uninstall=True,
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_uninstall(uninstall_args), 0)
            output_text = output.getvalue()
            result = json.loads(output_text)
        finally:
            if previous_env is None:
                os.environ.pop("ACME_API_KEY", None)
            else:
                os.environ["ACME_API_KEY"] = previous_env
            manager.start_background = original_start_background
            manager.stop_process = original_stop_process

        warning = result["direct_upstream_auth_warning"]
        self.assertEqual(warning["code"], "chatgpt_auth_direct_upstream")
        self.assertEqual(warning["severity"], "high")
        self.assertEqual(warning["previous_upstream_auth"], "override_configured")
        self.assertEqual(warning["upstream_api_key_env"], "ACME_API_KEY")
        self.assertEqual(warning["upstream_base"], "https://api.acme.test/v1")
        self.assertIn("401", warning["message"])
        self.assertNotIn("provider-secret", output_text)
        self.assertNotIn("chatgpt-token", output_text)
        self.assertEqual(stop_calls, 0)

    def test_deferred_uninstall_does_not_warn_for_api_key_auth(self) -> None:
        codex_home = self.temp_dir / ".codex"
        codex_home.mkdir()
        config_path = codex_home / "config.toml"
        original = (
            'model_provider = "acme"\n\n'
            "[model_providers.acme]\n"
            'base_url = "https://api.acme.test/v1"\n'
        )
        config_path.write_text(original, encoding="utf-8")
        (codex_home / "auth.json").write_text(
            json.dumps({"OPENAI_API_KEY": "provider-secret"}),
            encoding="utf-8",
        )
        install_args = self.install_args(codex_home)

        original_start_background = manager.start_background
        manager.start_background = lambda _paths, _settings, _verbose_proxy: {"status": "started", "pid": 1234}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command_install(install_args), 0)

            uninstall_args = argparse.Namespace(
                codex_home=str(codex_home),
                force=False,
                keep_state=False,
                defer_stop=True,
            )
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command_uninstall(uninstall_args), 0)
            result = json.loads(output.getvalue())
        finally:
            manager.start_background = original_start_background

        self.assertNotIn("direct_upstream_auth_warning", result)

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
            self.assertNotIn("hooks", first_config.get("features", {}))
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
