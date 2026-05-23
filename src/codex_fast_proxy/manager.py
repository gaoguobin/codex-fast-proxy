from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from . import __version__
from . import runtime_process as _runtime_process
from .auth import LoginDiagnosis, detect_login_mode
from .auth_prepare import (
    auth_api_key_names,
    default_provider_env_name,
    discover_provider_secret,
    prepare_chatgpt_login,
    provider_auth_candidates,
)
from .auth_store import (
    chatgpt_login_report,
    delete_provider_auth_entry,
    direct_upstream_auth_warning,
    provider_auth_base_url,
    provider_auth_provider_names,
    provider_auth_secret,
    require_upstream_auth_available,
    uninstall_needs_chatgpt_direct_confirmation,
    upstream_api_key_source,
    upstream_auth_configured,
    upstream_auth_status,
    write_provider_auth_entry,
    write_provider_auth_secret,
)
from .config import (
    TOML_DECODE_ERROR,
    active_provider_name,
    choose_provider,
    config_feature_value,
    configured_providers,
    load_toml_config,
    provider_base_url,
    provider_config_for,
    provider_name_for_base_url,
    set_active_provider,
    set_provider_base_url,
)
from .core import (
    ConfigError,
    normalized_base_path,
    redact_sensitive_text,
    redact_url_secrets,
    safe_url_display,
    validate_upstream_base,
)
from .defaults import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_PROXY_BASE,
    DEFAULT_SERVICE_TIER,
    DEFAULT_SERVICE_TIER_POLICY,
    INTERNAL_UPSTREAM_API_KEY_ENV,
)
from .hooks import (
    HOOK_FEATURE_KEYS,
    fast_proxy_hook_trust_status,
    has_startup_hook,
    hooks_feature_enabled,
    install_startup_hook,
    read_hooks,
    remove_hook_feature_flags,
    remove_hook_states_by_keys,
    remove_startup_hook,
    restore_hook_feature_flag,
)
from .models import ProxyPaths, ProxySettings, paths_for, read_settings, settings_from_dict, write_settings
from .ports import find_available_port
from .proxy import RUNTIME_ID, compact_json
from .runtime_status import health_matches_proxy_identity, runtime_status
from .skill_link import (
    is_windows_platform,
    link_skill_namespace,
    path_is_junction,
    path_points_to,
    skill_namespace_path,
    skill_target_path,
    unlink_skill_namespace,
)
from .storage import copy_private_file, ensure_private_dir, json_line, read_json, sha256_file, write_json, write_private_text
from .updater import (
    check_update,
    commit_exists_locally,
    commit_is_ancestor,
    commit_relation,
    current_git_branch,
    enabled_installation,
    module_args,
    parse_json_output,
    remote_commit_for,
    run_git,
    run_python,
    run_python_json,
    source_repo_root,
    update_installation,
)
from .verification import (
    install_requires_verification,
    resolve_upstream_auth_options,
    resolve_verification_api_key,
    verification_settings_from_args,
    verify_upstream_responses,
)
from .status_rules import (
    EFFECTIVE_SERVICE_TIER_POLICIES,
    CHATGPT_LOGIN_WINDOWS_TROUBLESHOOTING,
    SERVICE_TIER_POLICIES,
    chatgpt_login_hint,
    effective_service_tier_policy,
    fast_behavior,
    provider_auth_preparation,
    status_diagnosis,
)


ENABLE_SESSION_EFFECT = (
    "Running Codex processes keep their current base_url. Restart Codex App, then resume the same conversation if desired, "
    "or open a new CLI process to use the proxy."
)
ENABLED_UPDATE_SESSION_EFFECT = (
    "Codex was already pointed at the proxy, and the enabled update refreshed proxy settings. "
    "Use the final status output to decide whether a restart is needed; if needs_restart=false, no Codex restart is required for this update."
)
DEFER_STOP_SESSION_EFFECT = (
    "Codex config was restored, but the proxy was left running so a proxy-backed current process can finish. "
    "Restart Codex App, then resume the same conversation if desired, or open a new CLI process; then run uninstall again "
    "to stop the proxy and remove files."
)
ProxyStartPolicy = _runtime_process.ProxyStartPolicy
INTERACTIVE_PROXY_START_POLICY = _runtime_process.INTERACTIVE_PROXY_START_POLICY
AUTOSTART_PROXY_START_POLICY = _runtime_process.AUTOSTART_PROXY_START_POLICY


def _call_runtime(name: str, *args: Any, sync: tuple[str, ...] = (), **kwargs: Any) -> Any:
    target = _RUNTIME_IMPLS.get(name, getattr(_runtime_process, name))
    originals = {item: getattr(_runtime_process, item) for item in sync}
    try:
        for item in sync:
            setattr(_runtime_process, item, _runtime_dependency(item))
        return target(*args, **kwargs)
    finally:
        for item, value in originals.items():
            setattr(_runtime_process, item, value)


_RUNTIME_IMPLS = {
    item: getattr(_runtime_process, item)
    for item in (
        "already_running_result",
        "append_autostart_event",
        "auto_select_proxy_port",
        "autostart_proxy",
        "child_environment",
        "current_process",
        "find_available_port",
        "is_port_available",
        "is_process_running",
        "launch_background",
        "os",
        "proxy_health",
        "proxy_runtime_state",
        "restart_background",
        "should_log_autostart_event",
        "start_background",
        "stop_process",
        "subprocess",
        "terminate_process",
        "wait_for_proxy_port_release",
        "wait_for_proxy_health",
        "windows_process_running",
    )
    if hasattr(_runtime_process, item)
}


def _runtime_dependency(name: str) -> Any:
    return globals()[name]


current_process = _runtime_process.current_process
is_process_running = _runtime_process.is_process_running
windows_process_running = _runtime_process.windows_process_running
terminate_process = _runtime_process.terminate_process
is_port_available = _runtime_process.is_port_available
wait_for_proxy_port_release = _runtime_process.wait_for_proxy_port_release
proxy_health = _runtime_process.proxy_health
child_environment = _runtime_process.child_environment
already_running_result = _runtime_process.already_running_result
append_autostart_event = _runtime_process.append_autostart_event
should_log_autostart_event = _runtime_process.should_log_autostart_event


def auto_select_proxy_port(host: str, preferred: int) -> tuple[int, dict[str, Any]]:
    return _call_runtime("auto_select_proxy_port", host, preferred, sync=("find_available_port",))


def proxy_runtime_state(
    paths: ProxyPaths,
    settings: ProxySettings | None,
) -> tuple[int | None, bool, dict[str, Any] | None, bool, bool, bool | None]:
    return _call_runtime("proxy_runtime_state", paths, settings, sync=("current_process", "proxy_health"))


def wait_for_proxy_health(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _call_runtime("wait_for_proxy_health", *args, sync=("proxy_health",), **kwargs)


def stop_process(paths: ProxyPaths, force: bool = False) -> dict[str, Any]:
    return _call_runtime(
        "stop_process",
        paths,
        force,
        sync=("current_process", "proxy_health", "terminate_process", "is_process_running"),
    )


def restart_background(
    paths: ProxyPaths,
    settings: ProxySettings,
    verbose_proxy: bool,
    pid: int,
    health: dict[str, Any],
    *,
    reason: str = "runtime_changed",
    force_stop: bool = False,
    start_policy: ProxyStartPolicy = INTERACTIVE_PROXY_START_POLICY,
) -> dict[str, Any]:
    return _call_runtime(
        "restart_background",
        paths,
        settings,
        verbose_proxy,
        pid,
        health,
        reason=reason,
        force_stop=force_stop,
        start_policy=start_policy,
        sync=("stop_process", "launch_background", "wait_for_proxy_port_release", "is_port_available"),
    )


def start_background(
    paths: ProxyPaths,
    settings: ProxySettings,
    verbose_proxy: bool,
    *,
    start_policy: ProxyStartPolicy = INTERACTIVE_PROXY_START_POLICY,
) -> dict[str, Any]:
    return _call_runtime(
        "start_background",
        paths,
        settings,
        verbose_proxy,
        start_policy=start_policy,
        sync=("proxy_runtime_state", "already_running_result", "restart_background", "launch_background"),
    )


def launch_background(
    paths: ProxyPaths,
    settings: ProxySettings,
    verbose_proxy: bool,
    *,
    start_policy: ProxyStartPolicy = INTERACTIVE_PROXY_START_POLICY,
) -> dict[str, Any]:
    return _call_runtime(
        "launch_background",
        paths,
        settings,
        verbose_proxy,
        start_policy=start_policy,
        sync=(
            "os",
            "subprocess",
            "is_port_available",
            "current_process",
            "proxy_health",
            "already_running_result",
            "child_environment",
            "wait_for_proxy_health",
            "terminate_process",
        ),
    )


def replace_running_proxy(
    paths: ProxyPaths,
    old_settings: ProxySettings,
    new_settings: ProxySettings,
    verbose_proxy: bool,
    *,
    reason: str,
) -> dict[str, Any]:
    pid, running, health, _healthy, _pending_restart, _runtime_matches = proxy_runtime_state(paths, old_settings)
    if running and health_matches_proxy_identity(health, old_settings, pid):
        if _runtime_process.runtime_has_active_work(paths, health):
            return _runtime_process.deferred_restart_result(paths, new_settings, pid, health, reason=reason)
        stop_result = stop_process(paths, force=True)
        wait_for_proxy_port_release(new_settings)
        try:
            start_result = launch_background(paths, new_settings, verbose_proxy)
        except Exception as exc:
            try:
                wait_for_proxy_port_release(old_settings)
                launch_background(paths, old_settings, verbose_proxy)
            except Exception as restore_exc:
                raise ConfigError(
                    f"codex-fast-proxy restart failed and restoring the previous proxy also failed: {exc}; "
                    f"restore_error={restore_exc}"
                ) from exc
            raise ConfigError(f"codex-fast-proxy restart failed; restored the previous proxy: {exc}") from exc
        return {
            "status": "restarted",
            "reason": reason,
            "old_pid": pid,
            "old_runtime_id": health.get("runtime_id") if isinstance(health, dict) else None,
            "runtime_id": RUNTIME_ID,
            "provider": new_settings.provider,
            "base_url": new_settings.base_url,
            "upstream_base": new_settings.upstream_base,
            "stop_result": stop_result,
            "start_result": start_result,
        }
    return start_background(paths, new_settings, verbose_proxy)


def autostart_proxy(paths: ProxyPaths, verbose_proxy: bool) -> dict[str, Any]:
    return _call_runtime("autostart_proxy", paths, verbose_proxy, sync=("start_background",))


def autostart_control_ui(paths: ProxyPaths) -> dict[str, Any]:
    settings_data = read_json(paths.settings_path)
    if not settings_data:
        return {"status": "skipped", "reason": "settings_missing"}

    settings = settings_from_dict(settings_data)
    config = load_toml_config(paths.config_path)
    if not provider_name_for_base_url(config, settings.base_url):
        return {"status": "skipped", "reason": "config_not_proxy", "provider": settings.provider}

    from .control_ui import ensure_control_ui_for_hook

    return ensure_control_ui_for_hook(str(paths.codex_home), None, DEFAULT_HOST, 8786)


def resolve_upstream_base(
    config: dict[str, Any],
    paths: ProxyPaths,
    provider: str,
    requested_upstream: str | None,
    local_base_url: str,
) -> str:
    if requested_upstream:
        return requested_upstream

    current_base_url = provider_base_url(config, provider)
    if current_base_url and current_base_url != local_base_url:
        return current_base_url

    existing_settings = read_json(paths.settings_path)
    if existing_settings and existing_settings.get("upstream_base"):
        return str(existing_settings["upstream_base"])

    raise ConfigError(f"Provider {provider!r} has no usable upstream base_url; pass --upstream-base.")


def backup_matches_upstream(path: Path, provider: str, upstream_base: str) -> bool:
    try:
        return provider_base_url(load_toml_config(path), provider) == upstream_base
    except (ConfigError, OSError, TOML_DECODE_ERROR):
        return False


def find_upstream_backup(paths: ProxyPaths, provider: str, upstream_base: str) -> Path | None:
    if not paths.backup_dir.exists():
        return None
    backups = sorted(paths.backup_dir.glob("config.toml.*.bak"), key=lambda path: path.stat().st_mtime, reverse=True)
    for backup in backups:
        if backup_matches_upstream(backup, provider, upstream_base):
            return backup
    return None


def create_synthetic_upstream_backup(paths: ProxyPaths, provider: str, settings: ProxySettings) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_path = paths.backup_dir / f"config.toml.{timestamp}.bak"
    if paths.config_path.exists():
        copy_private_file(paths.config_path, backup_path)
        set_provider_base_url(backup_path, provider, settings.upstream_base)
        remove_hook_feature_flags(backup_path)
    else:
        write_private_text(backup_path, "")
    return backup_path


def choose_config_backup(paths: ProxyPaths, provider: str, settings: ProxySettings, config: dict[str, Any]) -> Path:
    enabled = provider_base_url(config, provider) == settings.base_url
    manifest = read_json(paths.manifest_path)
    if enabled and manifest:
        manifest_backup_value = manifest.get("backup_path")
        manifest_backup = Path(str(manifest_backup_value)) if manifest_backup_value else None
        if manifest_backup and backup_matches_upstream(manifest_backup, provider, settings.upstream_base):
            return manifest_backup

        upstream_backup = find_upstream_backup(paths, provider, settings.upstream_base)
        if upstream_backup:
            return upstream_backup

        return create_synthetic_upstream_backup(paths, provider, settings)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_path = paths.backup_dir / f"config.toml.{timestamp}.bak"
    if paths.config_path.exists():
        copy_private_file(paths.config_path, backup_path)
    else:
        write_private_text(backup_path, "")
    return backup_path


def write_install_manifest(
    paths: ProxyPaths,
    provider: str,
    backup_path: Path,
    config_hash_before: str | None,
    config_hash_after: str | None,
    hook_result: dict[str, Any] | None,
    settings: ProxySettings,
) -> dict[str, Any]:
    manifest = {
        "version": __version__,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provider": provider,
        "config_path": str(paths.config_path),
        "hooks_path": str(paths.hooks_path),
        "backup_path": str(backup_path),
        "config_hash_before": config_hash_before,
        "config_hash_after": config_hash_after,
        "hook": hook_result,
        "settings": {**asdict(settings), "base_url": settings.base_url},
    }
    write_json(paths.manifest_path, manifest)
    return manifest


def validate_provider_name(provider: str) -> str:
    name = provider.strip()
    if not name:
        raise ConfigError("Provider name is required.")
    if any(ord(char) < 32 for char in name):
        raise ConfigError("Provider name must not contain control characters.")
    return name


def provider_auth_state(paths: ProxyPaths, provider: str, provider_config: dict[str, Any]) -> tuple[str, int | None]:
    secret = provider_auth_secret(paths, provider)
    if secret:
        return "saved", len(secret)
    candidates = provider_auth_candidates(provider, provider_config, None, paths.codex_home)
    for env_name in candidates:
        source = upstream_api_key_source(paths, env_name)
        if source:
            return f"{source}:{env_name}", None
    return "missing", None


def provider_auth_label(paths: ProxyPaths, provider: str, provider_config: dict[str, Any]) -> str:
    label, _length = provider_auth_state(paths, provider, provider_config)
    return label


def provider_inventory(
    codex_home: str | Path | None,
    selected_provider: str | None = None,
    *,
    current_provider: str | None = None,
    pending_provider: str | None = None,
) -> dict[str, Any]:
    paths = paths_for(codex_home)
    config = load_toml_config(paths.config_path)
    settings_data = read_json(paths.settings_path)
    settings = settings_from_dict(settings_data) if settings_data else None
    active_provider = active_provider_name(config)
    configured = configured_providers(config)
    saved_names = provider_auth_provider_names(paths)
    names = set(configured)
    if settings:
        names |= saved_names
        names.add(settings.provider)
        config_proxy_provider = provider_name_for_base_url(config, settings.base_url)
        if config_proxy_provider and config_proxy_provider != settings.provider and config_proxy_provider not in saved_names:
            names.discard(config_proxy_provider)
    active_selection = current_provider or selected_provider or (settings.provider if settings else active_provider)
    if active_selection:
        names.add(active_selection)
    if pending_provider:
        names.add(pending_provider)
    if not active_selection and len(names) == 1:
        active_selection = next(iter(names))

    providers: list[dict[str, Any]] = []
    for name in sorted(names):
        provider_config = provider_config_for(config, name)
        config_base = provider_base_url(config, name)
        api_key_label, api_key_length = provider_auth_state(paths, name, provider_config)
        proxy_enabled = bool(settings and name == settings.provider)
        current = name == active_selection
        pending = name == pending_provider
        upstream_base = (
            settings.upstream_base
            if settings and name == settings.provider
            else (provider_auth_base_url(paths, name) if settings else None) or config_base
        )
        providers.append({
            "name": name,
            "active": name == active_provider,
            "current": current,
            "pending": pending,
            "proxy_enabled": proxy_enabled,
            "base_url": upstream_base,
            "api_key": api_key_label,
            "api_key_length": api_key_length,
            "deletable": name in saved_names and not current and not pending,
        })

    return {
        "providers": providers,
        "active_provider": active_provider,
        "current_provider": active_selection,
        "pending_provider": pending_provider,
    }


def install_result(args: argparse.Namespace) -> dict[str, Any]:
    paths = paths_for(args.codex_home)
    config = load_toml_config(paths.config_path)
    active_provider = active_provider_name(config)
    provider = choose_provider(config, args.provider)
    existing_settings_data = read_json(paths.settings_path)
    existing_settings = settings_from_dict(existing_settings_data) if existing_settings_data else None
    existing_enabled = bool(
        existing_settings
        and existing_settings.provider == provider
        and provider_base_url(config, provider) == existing_settings.base_url
    )
    service_tier_policy = args.service_tier_policy or (
        existing_settings.service_tier_policy if existing_enabled and existing_settings else DEFAULT_SERVICE_TIER_POLICY
    )
    current_auth_env = existing_settings.upstream_api_key_env if existing_enabled and existing_settings else None
    current_auth_file = existing_settings.upstream_api_key_file if existing_enabled and existing_settings else False
    upstream_api_key_env, upstream_api_key_file, _auth_source_requested = resolve_upstream_auth_options(
        current_auth_env,
        current_auth_file,
        env_name=args.upstream_api_key_env,
        use_file=bool(getattr(args, "use_provider_auth_file", False)),
    )
    arg_port = getattr(args, "port", None)
    requested_port = int(arg_port) if arg_port is not None else (
        existing_settings.port if existing_enabled and existing_settings else DEFAULT_PORT
    )
    settings = ProxySettings(
        provider=provider,
        host=args.host,
        port=requested_port,
        proxy_base=normalized_base_path(args.proxy_base),
        upstream_base="",
        service_tier=args.service_tier,
        service_tier_policy=service_tier_policy,
        upstream_api_key_env=upstream_api_key_env,
        upstream_api_key_file=upstream_api_key_file,
    )
    upstream_base = validate_upstream_base(resolve_upstream_base(config, paths, provider, args.upstream_base, settings.base_url))
    port_selection = {
        "preferred": requested_port,
        "selected": requested_port,
        "auto_selected": False,
        "preserved_existing": bool(existing_enabled),
    }
    selected_port = requested_port
    if not existing_enabled:
        selected_port, port_selection = auto_select_proxy_port(settings.host, requested_port)
    settings = replace(settings, port=selected_port, upstream_base=upstream_base)

    ensure_private_dir(paths.app_home)
    ensure_private_dir(paths.state_dir)
    ensure_private_dir(paths.backup_dir.parent)
    ensure_private_dir(paths.backup_dir)
    require_upstream_auth_available(paths, settings)

    if args.prepare_only and args.start:
        raise ConfigError("Use either --prepare-only or --start, not both.")

    if args.prepare_only:
        write_settings(paths, settings)
        return {
            "status": "prepared",
            "provider": provider,
            "base_url": settings.base_url,
            "upstream_base": settings.upstream_base,
            "config_switched": False,
            "port_selection": port_selection,
            "next_action": "run install --start to enable the proxy",
        }

    if not args.start:
        raise ConfigError("Refusing to switch Codex config without a running proxy. Use install --start.")

    verify_requested = bool(getattr(args, "verify", True))
    verify_timeout = float(getattr(args, "verify_timeout", 60.0))
    verification = {"status": "skipped", "reason": "--no-verify"}
    if verify_requested:
        if install_requires_verification(existing_enabled, existing_settings, settings):
            verification = verify_upstream_responses(paths, config, settings, verify_timeout)
        else:
            verification = {"status": "skipped", "reason": "existing_enabled_no_model_path_change"}

    backup_path = choose_config_backup(paths, provider, settings, config)
    config_hash_before = sha256_file(backup_path)
    config_bytes_before = paths.config_path.read_bytes() if paths.config_path.exists() else None
    hooks_bytes_before = paths.hooks_path.read_bytes() if paths.hooks_path.exists() else None
    settings_bytes_before = paths.settings_path.read_bytes() if paths.settings_path.exists() else None
    auth_bytes_before = paths.provider_auth_path.read_bytes() if paths.provider_auth_path.exists() else None
    start_result = None
    hook_result = None
    try:
        if settings.upstream_api_key_file:
            write_provider_auth_entry(paths, provider, base_url=settings.upstream_base)
        write_settings(paths, settings)
        start_result = start_background(paths, settings, args.verbose_proxy)

        set_provider_base_url(paths.config_path, provider, settings.base_url)
        if args.activate_provider or active_provider is None:
            set_active_provider(paths.config_path, provider)
        hook_result = install_startup_hook(paths)
        config_hash_after = sha256_file(paths.config_path)

        write_install_manifest(paths, provider, backup_path, config_hash_before, config_hash_after, hook_result, settings)
    except Exception:
        restore_previous_proxy = bool(start_result and start_result.get("status") == "restarted" and existing_settings)
        if start_result and start_result.get("status") in {"started", "restarted"}:
            stop_process(paths, force=True)
        if hooks_bytes_before is None:
            paths.hooks_path.unlink(missing_ok=True)
        else:
            paths.hooks_path.write_bytes(hooks_bytes_before)
        if config_bytes_before is None:
            paths.config_path.unlink(missing_ok=True)
        else:
            paths.config_path.write_bytes(config_bytes_before)
        if settings_bytes_before is None:
            paths.settings_path.unlink(missing_ok=True)
        else:
            paths.settings_path.write_bytes(settings_bytes_before)
        if auth_bytes_before is None:
            paths.provider_auth_path.unlink(missing_ok=True)
        else:
            paths.provider_auth_path.write_bytes(auth_bytes_before)
        if restore_previous_proxy and existing_settings:
            try:
                start_background(paths, existing_settings, args.verbose_proxy)
            except Exception:
                pass
        raise

    login = detect_login_mode(paths.codex_home)
    auth = upstream_auth_status(paths, settings)
    return {
        "status": "installed",
        "provider": provider,
        "base_url": settings.base_url,
        "upstream_base": settings.upstream_base,
        "service_tier_policy": settings.service_tier_policy,
        "service_tier_effective_policy": effective_service_tier_policy(settings, login),
        "fast_behavior": fast_behavior(settings, login),
        "login_mode": login.login_mode,
        "upstream_auth": auth["upstream_auth"],
        "upstream_api_key_env": auth["upstream_api_key_env"],
        "upstream_api_key_file": auth["upstream_api_key_file"],
        "upstream_api_key_ref": auth["upstream_api_key_ref"],
        "upstream_api_key_available": auth["upstream_api_key_available"],
        "upstream_api_key_source": auth["upstream_api_key_source"],
        "upstream_api_key_persistent": auth["upstream_api_key_persistent"],
        "chatgpt_login_compatible": bool(auth["upstream_api_key_persistent"]) if login.chatgpt_auth else None,
        **chatgpt_login_report(paths, settings, login, auth),
        "backup_path": str(backup_path),
        "started": True,
        "config_switched": True,
        "port_selection": port_selection,
        "startup_hook": hook_result,
        "verification": verification,
        "switch_order": "proxy_started_before_config_switch",
        "current_session_effect": ENABLED_UPDATE_SESSION_EFFECT if existing_enabled else ENABLE_SESSION_EFFECT,
        "start_result": start_result,
    }


def command_install(args: argparse.Namespace) -> int:
    print(json_line(install_result(args)))
    return 0


def set_upstream_result(args: argparse.Namespace) -> dict[str, Any]:
    paths = paths_for(args.codex_home)
    old_settings = read_settings(paths)
    service_tier_policy_arg = getattr(args, "service_tier_policy", None)
    upstream_base = validate_upstream_base(args.upstream_base) if args.upstream_base else old_settings.upstream_base
    service_tier_policy = service_tier_policy_arg or old_settings.service_tier_policy
    if service_tier_policy not in SERVICE_TIER_POLICIES:
        names = ", ".join(sorted(SERVICE_TIER_POLICIES))
        raise ConfigError(f"Invalid service tier policy {service_tier_policy!r}. Available: {names}")
    upstream_api_key_env, upstream_api_key_file, auth_source_requested = resolve_upstream_auth_options(
        old_settings.upstream_api_key_env,
        old_settings.upstream_api_key_file,
        env_name=getattr(args, "upstream_api_key_env", None),
        use_file=bool(getattr(args, "use_provider_auth_file", False)),
        clear=bool(getattr(args, "clear_upstream_api_key_env", False) or getattr(args, "clear_upstream_auth", False)),
    )
    new_settings = ProxySettings(
        provider=old_settings.provider,
        host=old_settings.host,
        port=old_settings.port,
        proxy_base=old_settings.proxy_base,
        upstream_base=upstream_base,
        service_tier=old_settings.service_tier,
        service_tier_policy=service_tier_policy,
        upstream_api_key_env=upstream_api_key_env,
        upstream_api_key_file=upstream_api_key_file,
    )
    config = load_toml_config(paths.config_path)
    config_provider = provider_name_for_base_url(config, old_settings.base_url) or old_settings.provider
    config_base_url = provider_base_url(config, config_provider)
    if config_base_url != old_settings.base_url:
        raise ConfigError(
            f"Refusing to update upstream because Codex config no longer points to the local proxy. "
            "Review config.toml, then run install --start if you want to enable the proxy again."
        )
    require_upstream_auth_available(paths, new_settings)
    verify_arg_present = hasattr(args, "verify")
    verify_requested = bool(getattr(args, "verify", False))
    verify_timeout = float(getattr(args, "verify_timeout", 60.0))
    verification = {"status": "skipped", "reason": "--no-verify" if verify_arg_present else "not_requested"}
    if verify_requested:
        verification = verify_upstream_responses(paths, config, new_settings, verify_timeout)

    ensure_private_dir(paths.backup_dir.parent)
    ensure_private_dir(paths.backup_dir)
    backup_path = choose_config_backup(paths, config_provider, new_settings, config)
    config_hash_before = sha256_file(backup_path)
    config_bytes_before = paths.config_path.read_bytes() if paths.config_path.exists() else None
    hooks_bytes_before = paths.hooks_path.read_bytes() if paths.hooks_path.exists() else None
    settings_bytes_before = paths.settings_path.read_bytes() if paths.settings_path.exists() else None
    auth_bytes_before = paths.provider_auth_path.read_bytes() if paths.provider_auth_path.exists() else None
    restart_required = False
    start_result = None
    hook_result = None

    try:
        _pid, running, health, healthy, pending_restart, runtime_matches = proxy_runtime_state(paths, new_settings)

        if new_settings.upstream_api_key_file:
            write_provider_auth_entry(paths, new_settings.provider, base_url=new_settings.upstream_base)
        write_settings(paths, new_settings, bump_revision=True if auth_source_requested else None)
        if running and not args.restart:
            restart_required = bool(pending_restart or not healthy or runtime_matches is False or auth_source_requested)
            if restart_required:
                start_result = replace_running_proxy(
                    paths,
                    old_settings,
                    new_settings,
                    args.verbose_proxy,
                    reason="settings_updated",
                )
                restart_required = start_result.get("status") == "deferred"
            else:
                start_result = already_running_result(paths, new_settings, _pid, health, runtime_matches=runtime_matches is not False)
        else:
            start_result = start_background(paths, new_settings, args.verbose_proxy)
        set_provider_base_url(paths.config_path, config_provider, new_settings.base_url)
        hook_result = install_startup_hook(paths)
        config_hash_after = sha256_file(paths.config_path)
        write_install_manifest(
            paths,
            config_provider,
            backup_path,
            config_hash_before,
            config_hash_after,
            hook_result,
            new_settings,
        )
    except Exception:
        if start_result and start_result.get("status") in {"started", "restarted"}:
            stop_process(paths, force=True)
        if hooks_bytes_before is None:
            paths.hooks_path.unlink(missing_ok=True)
        else:
            paths.hooks_path.write_bytes(hooks_bytes_before)
        if config_bytes_before is None:
            paths.config_path.unlink(missing_ok=True)
        else:
            paths.config_path.write_bytes(config_bytes_before)
        if settings_bytes_before is None:
            paths.settings_path.unlink(missing_ok=True)
        else:
            paths.settings_path.write_bytes(settings_bytes_before)
        if auth_bytes_before is None:
            paths.provider_auth_path.unlink(missing_ok=True)
        else:
            paths.provider_auth_path.write_bytes(auth_bytes_before)
        if start_result and start_result.get("status") in {"started", "restarted"}:
            try:
                start_background(paths, old_settings, args.verbose_proxy)
            except Exception:
                pass
        raise

    login = detect_login_mode(paths.codex_home)
    auth = upstream_auth_status(paths, new_settings)
    auth_changed = (
        old_settings.upstream_api_key_env != new_settings.upstream_api_key_env
        or old_settings.upstream_api_key_file != new_settings.upstream_api_key_file
    )
    if restart_required and upstream_auth_configured(new_settings) and auth_changed:
        next_user_action = (
            "Provider auth split is verified and saved, but the running proxy has not loaded it yet. "
            "Before signing in with ChatGPT, restart Codex App or run python -m codex_fast_proxy start; "
            "do not switch while needs_restart=true."
        )
    elif restart_required:
        next_user_action = (
            "Restart Codex App, open a new CLI process, or run python -m codex_fast_proxy start later "
            "to apply the new proxy settings."
        )
    elif upstream_auth_configured(new_settings):
        next_user_action = (
            "Provider auth split is active. You may keep the current mode, or sign in with ChatGPT if "
            "you want the full Codex App UI. If Windows login fails with WinError 10013, use "
            "chatgpt_login_windows_troubleshooting."
        )
    else:
        next_user_action = "No restart is required for the current proxy settings."
    chatgpt_login_windows_troubleshooting = (
        CHATGPT_LOGIN_WINDOWS_TROUBLESHOOTING
        if upstream_auth_configured(new_settings) and not restart_required
        else None
    )
    return {
        "status": "upstream_updated",
        "provider": new_settings.provider,
        "base_url": new_settings.base_url,
        "previous_upstream_base": old_settings.upstream_base,
        "upstream_base": new_settings.upstream_base,
        "service_tier_policy": new_settings.service_tier_policy,
        "service_tier_effective_policy": effective_service_tier_policy(new_settings, login),
        "fast_behavior": fast_behavior(new_settings, login),
        "upstream_auth": auth["upstream_auth"],
        "upstream_api_key_env": auth["upstream_api_key_env"],
        "upstream_api_key_file": auth["upstream_api_key_file"],
        "upstream_api_key_ref": auth["upstream_api_key_ref"],
        "upstream_api_key_available": auth["upstream_api_key_available"],
        "upstream_api_key_source": auth["upstream_api_key_source"],
        "upstream_api_key_persistent": auth["upstream_api_key_persistent"],
        "backup_path": str(backup_path),
        "config_matches": True,
        "restart_required": restart_required,
        "verification": verification,
        "start_result": start_result,
        "startup_hook": hook_result,
        "next_user_action": next_user_action,
        "chatgpt_login_windows_troubleshooting": chatgpt_login_windows_troubleshooting,
        "current_session_effect": (
            "Existing Codex processes keep their current proxy connection. If restart_required is true, restart Codex App, "
            "open a new CLI process, or run start later to apply the new upstream. Also restart Codex if you changed API key, "
            "model, or other Codex config."
        ),
    }


def command_set_upstream(args: argparse.Namespace) -> int:
    print(json_line(set_upstream_result(args)))
    return 0


def configure_upstream(
    codex_home: str | Path | None,
    upstream_base: str | None,
    api_key: str | None,
    *,
    service_tier_policy: str | None = None,
    restart: bool = False,
    verify: bool = True,
    verify_timeout: float = 60.0,
) -> dict[str, Any]:
    paths = paths_for(codex_home)
    settings = read_settings(paths)
    normalized_upstream = validate_upstream_base(upstream_base) if upstream_base else None
    stripped_key = api_key.strip() if api_key else None
    if not normalized_upstream and not stripped_key and not service_tier_policy:
        raise ConfigError("No upstream URL or API key change was requested.")

    previous_auth = paths.provider_auth_path.read_bytes() if paths.provider_auth_path.exists() else None
    if stripped_key:
        write_provider_auth_secret(paths, settings.provider, stripped_key)
    try:
        result = set_upstream_result(argparse.Namespace(
            codex_home=str(paths.codex_home),
            upstream_base=normalized_upstream,
            service_tier_policy=service_tier_policy,
            upstream_api_key_env=None,
            use_provider_auth_file=bool(stripped_key),
            clear_upstream_auth=False,
            clear_upstream_api_key_env=False,
            verify=verify,
            verify_timeout=verify_timeout,
            restart=restart,
            verbose_proxy=False,
        ))
    except Exception:
        if stripped_key:
            if previous_auth is None:
                paths.provider_auth_path.unlink(missing_ok=True)
            else:
                paths.provider_auth_path.write_bytes(previous_auth)
        raise

    return {
        **result,
        "api_key_changed": bool(stripped_key),
        "secret_printed": False,
    }


def save_provider(
    codex_home: str | Path | None,
    provider: str,
    upstream_base: str,
    api_key: str | None,
    *,
    verify: bool = True,
    verify_timeout: float = 60.0,
) -> dict[str, Any]:
    paths = paths_for(codex_home)
    name = validate_provider_name(provider)
    normalized_upstream = validate_upstream_base(upstream_base)
    settings_data = read_json(paths.settings_path)
    settings = settings_from_dict(settings_data) if settings_data else None
    config = load_toml_config(paths.config_path)
    if settings and settings.provider == name:
        auth_bytes_before = paths.provider_auth_path.read_bytes() if paths.provider_auth_path.exists() else None
        settings_bytes_before = paths.settings_path.read_bytes() if paths.settings_path.exists() else None
        stripped_key = api_key.strip() if api_key else None
        start_result = None
        try:
            write_provider_auth_entry(paths, name, api_key=stripped_key, base_url=normalized_upstream)
            new_settings = replace(
                settings,
                upstream_base=normalized_upstream,
                upstream_api_key_file=settings.upstream_api_key_file or bool(provider_auth_secret(paths, name)),
            )
            require_upstream_auth_available(paths, new_settings)
            verification = (
                verify_upstream_responses(paths, config, new_settings, verify_timeout)
                if verify
                else {"status": "skipped"}
            )
            write_settings(paths, new_settings, bump_revision=bool(stripped_key))
            start_result = replace_running_proxy(
                paths,
                settings,
                new_settings,
                False,
                reason="provider_saved",
            )
        except Exception:
            if start_result and start_result.get("status") in {"started", "restarted"}:
                stop_process(paths, force=True)
            if auth_bytes_before is None:
                paths.provider_auth_path.unlink(missing_ok=True)
            else:
                paths.provider_auth_path.write_bytes(auth_bytes_before)
            if settings_bytes_before is None:
                paths.settings_path.unlink(missing_ok=True)
            else:
                paths.settings_path.write_bytes(settings_bytes_before)
            try:
                start_background(paths, settings, False)
            except Exception:
                pass
            raise

        login = detect_login_mode(paths.codex_home)
        auth = upstream_auth_status(paths, new_settings)
        restart_required = bool(start_result and start_result.get("status") == "deferred")
        return {
            "status": "provider_saved",
            "provider": name,
            "base_url": new_settings.base_url,
            "previous_upstream_base": settings.upstream_base,
            "upstream_base": new_settings.upstream_base,
            "service_tier_policy": new_settings.service_tier_policy,
            "service_tier_effective_policy": effective_service_tier_policy(new_settings, login),
            "fast_behavior": fast_behavior(new_settings, login),
            "upstream_auth": auth["upstream_auth"],
            "upstream_api_key_file": auth["upstream_api_key_file"],
            "upstream_api_key_source": auth["upstream_api_key_source"],
            "api_key_changed": bool(stripped_key),
            "config_changed": False,
            "restart_required": restart_required,
            "verification": verification,
            "start_result": start_result,
            "provider_inventory": provider_inventory(paths.codex_home, name),
            "secret_printed": False,
        }

    auth_bytes_before = paths.provider_auth_path.read_bytes() if paths.provider_auth_path.exists() else None
    stripped_key = api_key.strip() if api_key else None
    try:
        write_provider_auth_entry(paths, name, api_key=stripped_key, base_url=normalized_upstream)
        if verify:
            verify_settings = ProxySettings(
                provider=name,
                host=settings.host if settings else DEFAULT_HOST,
                port=settings.port if settings else DEFAULT_PORT,
                proxy_base=settings.proxy_base if settings else DEFAULT_PROXY_BASE,
                upstream_base=normalized_upstream,
                service_tier=settings.service_tier if settings else DEFAULT_SERVICE_TIER,
                service_tier_policy=settings.service_tier_policy if settings else DEFAULT_SERVICE_TIER_POLICY,
                upstream_api_key_file=bool(provider_auth_secret(paths, name)),
            )
            verify_upstream_responses(paths, config, verify_settings, verify_timeout)
    except Exception:
        if auth_bytes_before is None:
            paths.provider_auth_path.unlink(missing_ok=True)
        else:
            paths.provider_auth_path.write_bytes(auth_bytes_before)
        raise

    return {
        "status": "provider_saved",
        "provider": name,
        "upstream_base": normalized_upstream,
        "api_key_changed": bool(stripped_key),
        "secret_printed": False,
        "provider_inventory": provider_inventory(paths.codex_home, name),
    }


def switch_provider(
    codex_home: str | Path | None,
    provider: str,
    *,
    verify: bool = True,
    verify_timeout: float = 60.0,
) -> dict[str, Any]:
    paths = paths_for(codex_home)
    name = validate_provider_name(provider)
    config = load_toml_config(paths.config_path)
    settings_data = read_json(paths.settings_path)
    settings = settings_from_dict(settings_data) if settings_data else None
    config_base = provider_base_url(config, name)
    upstream_base = settings.upstream_base if settings and settings.provider == name else provider_auth_base_url(paths, name) or config_base
    if not upstream_base:
        raise ConfigError(f"Provider {name!r} has no model service URL.")

    if not settings:
        return {
            "status": "provider_selected",
            "provider": name,
            "upstream_base": upstream_base,
            "restart_required": False,
            "provider_inventory": provider_inventory(paths.codex_home, name),
        }

    auth_bytes_before = paths.provider_auth_path.read_bytes() if paths.provider_auth_path.exists() else None
    settings_bytes_before = paths.settings_path.read_bytes() if paths.settings_path.exists() else None
    prepare_result: dict[str, Any] | None = None
    try:
        if not provider_auth_secret(paths, name):
            try:
                prepare_result = prepare_chatgpt_login(argparse.Namespace(
                    codex_home=str(paths.codex_home),
                    provider=name,
                    source_auth_key=None,
                    target_env=None,
                    apply=True,
                ))
            except ConfigError as exc:
                raise ConfigError(f"Provider {name!r} needs an API key before switching.") from exc
        write_provider_auth_entry(paths, name, base_url=validate_upstream_base(upstream_base))
        new_settings = replace(
            settings,
            provider=name,
            upstream_base=validate_upstream_base(upstream_base),
            upstream_api_key_env=None,
            upstream_api_key_file=True,
        )
        require_upstream_auth_available(paths, new_settings)
        if verify:
            verify_upstream_responses(paths, config, new_settings, verify_timeout)
    except Exception:
        if auth_bytes_before is None:
            paths.provider_auth_path.unlink(missing_ok=True)
        else:
            paths.provider_auth_path.write_bytes(auth_bytes_before)
        raise

    start_result = None
    try:
        write_settings(paths, new_settings)
        start_result = replace_running_proxy(
            paths,
            settings,
            new_settings,
            False,
            reason="provider_switched",
        )
    except Exception:
        if start_result and start_result.get("status") in {"started", "restarted"}:
            stop_process(paths, force=True)
        if settings_bytes_before is None:
            paths.settings_path.unlink(missing_ok=True)
        else:
            paths.settings_path.write_bytes(settings_bytes_before)
        if auth_bytes_before is None:
            paths.provider_auth_path.unlink(missing_ok=True)
        else:
            paths.provider_auth_path.write_bytes(auth_bytes_before)
        try:
            start_background(paths, settings, False)
        except Exception:
            pass
        raise

    login = detect_login_mode(paths.codex_home)
    auth = upstream_auth_status(paths, new_settings)
    restart_required = bool(start_result and start_result.get("status") == "deferred")
    return {
        "status": "provider_switched",
        "provider": name,
        "previous_provider": settings.provider,
        "base_url": new_settings.base_url,
        "upstream_base": new_settings.upstream_base,
        "service_tier_policy": new_settings.service_tier_policy,
        "service_tier_effective_policy": effective_service_tier_policy(new_settings, login),
        "fast_behavior": fast_behavior(new_settings, login),
        "upstream_auth": auth["upstream_auth"],
        "upstream_api_key_file": auth["upstream_api_key_file"],
        "upstream_api_key_source": auth["upstream_api_key_source"],
        "prepare_chatgpt_login": prepare_result,
        "restart_required": restart_required,
        "start_result": start_result,
        "config_changed": False,
        "provider_inventory": provider_inventory(paths.codex_home, name),
        "secret_printed": False,
    }


def delete_provider(codex_home: str | Path | None, provider: str) -> dict[str, Any]:
    paths = paths_for(codex_home)
    name = validate_provider_name(provider)
    settings_data = read_json(paths.settings_path)
    settings = settings_from_dict(settings_data) if settings_data else None
    if settings and settings.provider == name:
        raise ConfigError("Cannot delete the provider currently used by the proxy.")
    if not provider_auth_base_url(paths, name) and not provider_auth_secret(paths, name):
        raise ConfigError(f"Provider {name!r} is not stored by the proxy.")

    removed = delete_provider_auth_entry(paths, name)
    if not removed:
        raise ConfigError(f"Provider {name!r} is not stored by the proxy.")
    return {
        "status": "provider_deleted",
        "provider": name,
        "config_changed": False,
        "restart_required": False,
        "provider_inventory": provider_inventory(paths.codex_home, settings.provider if settings else None),
        "secret_printed": False,
    }


def command_start(args: argparse.Namespace) -> int:
    paths = paths_for(args.codex_home)
    settings = read_settings(paths)
    result = start_background(paths, settings, args.verbose_proxy)
    login = detect_login_mode(paths.codex_home)
    auth = upstream_auth_status(paths, settings)
    print(json_line({
        **result,
        **chatgpt_login_report(paths, settings, login, auth),
    }))
    return 0


def command_autostart(args: argparse.Namespace) -> int:
    paths = paths_for(args.codex_home)
    started_at = time.monotonic()
    timings: dict[str, float] = {}
    try:
        proxy_started_at = time.monotonic()
        proxy_result = autostart_proxy(paths, args.verbose_proxy)
    except Exception as exc:
        proxy_result = {"status": "error", "error": str(exc)}
    timings["proxy"] = round((time.monotonic() - proxy_started_at) * 1000, 1)

    result = {**proxy_result, "status": proxy_result.get("status", "unknown"), "proxy": proxy_result}
    if proxy_result.get("status") not in {"error", "skipped"}:
        try:
            ui_started_at = time.monotonic()
            result["control_ui"] = autostart_control_ui(paths)
        except Exception as exc:
            result["control_ui"] = {"status": "error", "error": str(exc)}
        timings["control_ui"] = round((time.monotonic() - ui_started_at) * 1000, 1)
    timings["total"] = round((time.monotonic() - started_at) * 1000, 1)
    result["timing_ms"] = timings

    if should_log_autostart_event(result, args.quiet):
        append_autostart_event(paths, result)
    if not args.quiet:
        print(json_line(result))
    elif getattr(args, "hook_summary", False):
        hook_context = autostart_hook_context(result)
        if hook_context:
            print(hook_context)
    return 0


def command_lifecycle_hook(args: argparse.Namespace) -> int:
    from .lifecycle import record_codex_hook_event

    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if isinstance(payload, dict):
            record_codex_hook_event(paths_for(args.codex_home), payload)
    except Exception:
        return 0
    return 0


def autostart_hook_context(result: dict[str, Any]) -> str | None:
    proxy = result.get("proxy") if isinstance(result.get("proxy"), dict) else result
    control_ui = result.get("control_ui") if isinstance(result.get("control_ui"), dict) else {}
    proxy_status = str(proxy.get("status") or result.get("status") or "unknown")
    ui_status = str(control_ui.get("status") or "")
    provider = proxy.get("provider")
    provider_text = f" for {provider}" if isinstance(provider, str) and provider else ""
    ui_url = control_ui.get("url")
    ui_text = f"; Control UI {ui_url}" if isinstance(ui_url, str) and ui_url else ""

    if proxy_status == "error":
        return "Codex Model Gateway autostart failed; open Control UI diagnostics for details."
    if ui_status == "error":
        return "Codex Model Gateway proxy is available, but Control UI autostart failed; open diagnostics when convenient."
    if proxy_status == "deferred":
        return f"Codex Model Gateway saved new settings{provider_text}; it will apply them after the active model request finishes{ui_text}."
    if proxy.get("needs_restart"):
        return f"Codex Model Gateway is running with an older runtime{provider_text}; restart Codex or run update/start when convenient{ui_text}."
    if proxy_status in {"started", "restarted"}:
        action = "started" if proxy_status == "started" else "restarted"
        return f"Codex Model Gateway {action}{provider_text}{ui_text}."
    if proxy_status == "starting":
        return f"Codex Model Gateway is starting{provider_text}{ui_text}."
    if control_ui.get("started_background_process"):
        return f"Codex Model Gateway proxy is already running{provider_text}; Control UI started at {ui_url}."
    return None


def command_stop(args: argparse.Namespace) -> int:
    paths = paths_for(args.codex_home)
    settings_data = read_json(paths.settings_path)
    settings = settings_from_dict(settings_data) if settings_data else None
    if settings and not args.force:
        config = load_toml_config(paths.config_path)
        if provider_name_for_base_url(config, settings.base_url):
            raise ConfigError(
                "Refusing to stop while Codex config still points to the proxy. "
                "Use uninstall --defer-stop to disable safely, or stop --force if you understand the risk."
            )

    print(json_line(stop_process(paths, args.force)))
    return 0


def command_status(args: argparse.Namespace) -> int:
    from .state import collect_status

    print(json_line(collect_status(
        args.codex_home,
        args.provider,
        runtime_probe=proxy_runtime_state,
        port_probe=is_port_available,
    )))
    return 0


def command_ui(args: argparse.Namespace) -> int:
    from .control_ui import open_control_ui, serve_control_ui

    if args.foreground:
        return serve_control_ui(args.codex_home, args.provider, args.host, args.port)
    result = open_control_ui(
        args.codex_home,
        args.provider,
        args.host,
        args.port,
    )
    print(json_line(result))
    return 2 if result.get("status") == "error" else 0


def user_file_permission_report(paths: ProxyPaths) -> dict[str, Any]:
    candidates = [
        paths.codex_home,
        paths.config_path,
        paths.codex_home / "auth.json",
        paths.hooks_path,
        paths.backup_dir.parent,
        paths.backup_dir,
        paths.app_home,
        paths.settings_path,
        paths.provider_auth_path,
        paths.manifest_path,
        paths.state_dir,
        paths.log_path,
        paths.stdout_path,
        paths.stderr_path,
        paths.benchmark_path,
        paths.state_dir / "fast_proxy.autostart.jsonl",
        paths.state_dir / "control_ui.pid",
        paths.state_dir / "control_ui.stdout.log",
        paths.state_dir / "control_ui.stderr.log",
    ]
    if paths.backup_dir.exists():
        candidates.extend(sorted(paths.backup_dir.glob("config.toml.*.bak")))
    entries: list[dict[str, Any]] = []
    for path in candidates:
        try:
            mode = path.stat().st_mode & 0o777
        except FileNotFoundError:
            continue
        group_or_other = mode & 0o077
        entries.append({
            "path": str(path),
            "mode": oct(mode),
            "owner_only": group_or_other == 0,
        })
    loose = [entry for entry in entries if not entry["owner_only"]]
    return {
        "ok": not loose,
        "checked": len(entries),
        "loose": loose,
    }


def doctor_report(paths: ProxyPaths, provider: str | None) -> dict[str, Any]:
    config = load_toml_config(paths.config_path)
    settings_data = read_json(paths.settings_path)
    settings = settings_from_dict(settings_data) if settings_data else None
    config_proxy_provider = provider_name_for_base_url(config, settings.base_url) if settings else None
    codex_model_provider = active_provider_name(config)
    selected_provider = provider or config_proxy_provider or codex_model_provider
    upstream_base = provider_base_url(config, selected_provider) if selected_provider else None
    pid, running, health, healthy, pending_restart, runtime_matches = proxy_runtime_state(paths, settings)
    hooks_enabled = hooks_feature_enabled(config)
    hook_status = fast_proxy_hook_trust_status(paths)
    login = detect_login_mode(paths.codex_home)
    auth = upstream_auth_status(paths, settings)
    effective_policy = effective_service_tier_policy(settings, login) if settings else None
    file_permissions = user_file_permission_report(paths)
    needs_restart = bool(pending_restart or (healthy and runtime_matches is False))

    checks = [
        {"name": "python", "ok": sys.version_info >= (3, 11), "detail": sys.version.split()[0]},
        {"name": "codex_config", "ok": paths.config_path.exists(), "detail": str(paths.config_path)},
        {"name": "active_provider", "ok": bool(selected_provider), "detail": selected_provider},
        {"name": "codex_model_provider", "ok": bool(codex_model_provider), "detail": codex_model_provider},
        {"name": "provider_base_url", "ok": bool(upstream_base), "detail": upstream_base},
        {"name": "runtime_source", "ok": True, "detail": runtime_status(paths, health)},
        {"name": "login_mode", "ok": True, "detail": login.login_mode},
        {"name": "user_file_permissions", "ok": file_permissions["ok"], "severity": "warning", "detail": file_permissions},
    ]
    if settings_data:
        checks.extend([
            {"name": "proxy_settings", "ok": True, "detail": str(paths.settings_path)},
            {"name": "config_points_to_proxy", "ok": bool(config_proxy_provider), "detail": upstream_base},
            {"name": "codex_proxy_provider", "ok": bool(config_proxy_provider), "detail": config_proxy_provider},
            {"name": "proxy_upstream_provider", "ok": bool(settings.provider), "detail": settings.provider},
            {"name": "provider_route", "ok": bool(config_proxy_provider and settings.provider), "detail": {
                "codex_model_provider": codex_model_provider,
                "codex_proxy_provider": config_proxy_provider,
                "local_proxy": settings.base_url,
                "proxy_upstream_provider": settings.provider,
                "upstream_base": settings.upstream_base,
            }},
            {"name": "upstream_saved", "ok": bool(settings.upstream_base), "detail": settings.upstream_base},
            {"name": "service_tier_policy", "ok": effective_policy in EFFECTIVE_SERVICE_TIER_POLICIES, "detail": {
                "configured": settings.service_tier_policy,
                "effective": effective_policy,
                "fast_behavior": fast_behavior(settings, login),
            }},
            {
                "name": "upstream_auth",
                "ok": not upstream_auth_configured(settings) or bool(auth["upstream_api_key_available"]),
                "detail": auth,
            },
            {"name": "proxy_health", "ok": not running or healthy or pending_restart, "detail": health},
            {"name": "proxy_pending_restart", "ok": True, "detail": needs_restart},
            {"name": "proxy_runtime", "ok": not healthy or runtime_matches is not False, "detail": {
                "current": health.get("runtime_id") if health else None,
                "expected": RUNTIME_ID,
            }},
            {
                "name": "hooks_enabled",
                "ok": hooks_enabled,
                "detail": {key: config_feature_value(config, key) for key in HOOK_FEATURE_KEYS},
            },
            {"name": "startup_hook", "ok": hook_status["ready"], "detail": hook_status},
        ])
    else:
        checks.append({"name": "proxy_settings", "ok": False, "detail": str(paths.settings_path)})

    required_checks = checks if settings_data else checks[:4]
    functional_checks = [check for check in required_checks if check.get("severity") != "warning"]
    warnings = [check for check in checks if check.get("severity") == "warning" and not check["ok"]]
    return {
        "ok": all(check["ok"] for check in functional_checks),
        "functional_ok": all(check["ok"] for check in functional_checks),
        "warnings": warnings,
        "installed": bool(settings_data),
        "running": running,
        "pid": pid,
        "provider": selected_provider,
        "health": health,
        "checks": checks,
    }


def command_doctor(args: argparse.Namespace) -> int:
    report = doctor_report(paths_for(args.codex_home), args.provider)
    print(json_line(report))
    return 0 if report["ok"] else 2


def command_benchmark(args: argparse.Namespace) -> int:
    from .benchmark import BenchmarkTarget, discover_api_key, profile_for_name, run_benchmark, save_benchmark_result

    paths = paths_for(args.codex_home)
    settings = read_settings(paths)
    config = load_toml_config(paths.config_path)
    provider_config = provider_config_for(config, settings.provider)
    model = args.model or config.get("model")
    reasoning_effort = args.reasoning_effort or config.get("model_reasoning_effort")
    if not isinstance(model, str) or not model:
        raise ConfigError("Codex config has no model; rerun with --model.")
    if reasoning_effort is not None and not isinstance(reasoning_effort, str):
        raise ConfigError("Codex config model_reasoning_effort must be a string; rerun with --reasoning-effort.")
    pairs = args.pairs if args.pairs is not None else (12 if args.kind == "strict" else 3)
    if pairs < 1:
        raise ConfigError("--pairs must be at least 1.")
    if pairs > 20:
        raise ConfigError("--pairs must be 20 or less.")
    if args.kind == "strict" and args.mode != "direct":
        raise ConfigError("--kind strict requires --mode direct.")
    try:
        profile_for_name(args.profile)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc

    if args.api_key_env:
        try:
            api_key_source, api_key = discover_api_key(provider_config, args.api_key_env, paths.codex_home)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
    elif upstream_auth_configured(settings):
        api_key_source, api_key = resolve_verification_api_key(paths, provider_config, settings)
    else:
        try:
            api_key_source, api_key = discover_api_key(provider_config, None, paths.codex_home)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc

    target = BenchmarkTarget(
        provider=settings.provider,
        upstream_base=settings.upstream_base,
        model=model,
        profile=args.profile,
        service_tier=settings.service_tier,
        api_key_source=api_key_source,
        api_key=api_key,
        reasoning_effort=reasoning_effort,
    )
    result = run_benchmark(
        target,
        pairs,
        args.timeout,
        mode=args.mode,
        benchmark_kind=args.kind,
        randomized_order=args.kind == "strict",
    )
    if args.save:
        save_benchmark_result(paths.benchmark_path, result)
        result["saved_to"] = str(paths.benchmark_path)
    print(json_line(result))
    return 0


def command_check_update(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve() if args.repo else None
    print(json_line(check_update(repo, args.branch, args.remote)))
    return 0


def command_update(args: argparse.Namespace) -> int:
    result = update_installation(
        args.codex_home,
        args.provider,
        repo=args.repo,
        remote=args.remote,
        branch=args.branch,
        refresh_code=not args.skip_self_update,
    )
    print(json_line(result))
    return 2 if result.get("status") == "blocked" else 0


def command_verify_upstream(args: argparse.Namespace) -> int:
    paths = paths_for(args.codex_home)
    config = load_toml_config(paths.config_path)
    settings = verification_settings_from_args(paths, config, args)
    require_upstream_auth_available(paths, settings)
    verification = verify_upstream_responses(paths, config, settings, args.verify_timeout)
    login = detect_login_mode(paths.codex_home)
    print(json_line({
        "status": "verified",
        "provider": settings.provider,
        "upstream_base": settings.upstream_base,
        "service_tier_policy": settings.service_tier_policy,
        "service_tier_effective_policy": effective_service_tier_policy(settings, login),
        "fast_behavior": fast_behavior(settings, login),
        "upstream_auth": "override_configured" if upstream_auth_configured(settings) else "preserved",
        "upstream_api_key_env": settings.upstream_api_key_env,
        "upstream_api_key_file": settings.upstream_api_key_file,
        "settings_changed": False,
        "config_changed": False,
        "proxy_restarted": False,
        "verification": verification,
    }))
    return 0


def command_prepare_chatgpt_login(args: argparse.Namespace) -> int:
    print(json_line(prepare_chatgpt_login(args)))
    return 0


def command_link_skill(args: argparse.Namespace) -> int:
    print(json_line(link_skill_namespace(args.repo_root, args.skills_root)))
    return 0


def command_unlink_skill(args: argparse.Namespace) -> int:
    print(json_line(unlink_skill_namespace(args.repo_root, args.skills_root)))
    return 0


def uninstall_result(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    paths = paths_for(args.codex_home)
    manifest = read_json(paths.manifest_path)
    manifest_settings = settings_from_dict(manifest["settings"]) if manifest else None
    confirmation = uninstall_needs_chatgpt_direct_confirmation(
        paths,
        manifest,
        manifest_settings,
        getattr(args, "force", False),
    )
    if confirmation and not getattr(args, "confirm_chatgpt_direct_uninstall", False):
        return {
            "status": "confirmation_required",
            "code": "chatgpt_auth_direct_upstream_uninstall_requires_confirmation",
            "message": (
                "ChatGPT login appears to be active. Uninstall would restore Codex config to the direct "
                "third-party upstream before the proxy auth override is in the path, so future model "
                "requests may fail with 401."
            ),
            "direct_upstream_auth_warning": confirmation,
            "config_changed": False,
            "config_restore": "not_attempted",
            "startup_hook": {"status": "unchanged"},
            "stop_result": {"status": "not_attempted"},
            "files": "kept",
            "next_user_action": (
                "Keep the proxy enabled for ChatGPT-login UI with a third-party provider, switch Codex App "
                "back to API-key/third-party provider auth before uninstalling, or explicitly confirm "
                "uninstall with --confirm-chatgpt-direct-uninstall."
            ),
        }, 4
    stop_result: dict[str, Any] = {"status": "not_attempted", "reason": "config_not_restored"}
    restore_status = "no_manifest"
    backup_path = None
    can_stop = args.force or manifest is None
    try:
        hook_result = remove_startup_hook(paths)
    except ConfigError as exc:
        hook_result = {"status": "error", "error": str(exc), "path": str(paths.hooks_path)}

    if manifest:
        config_path = Path(manifest["config_path"])
        backup_path = manifest["backup_path"]
        manifest_provider = str(manifest.get("provider") or manifest_settings.provider)
        current_hash = sha256_file(config_path)
        if current_hash == manifest.get("config_hash_before"):
            restore_status = "already_restored"
            can_stop = True
        elif current_hash == manifest.get("config_hash_after"):
            copy_private_file(Path(backup_path), config_path)
            restore_status = "restored"
            can_stop = True
        else:
            settings = manifest_settings
            config = load_toml_config(config_path)
            config_base_url = provider_base_url(config, manifest_provider)
            if config_base_url == settings.base_url:
                set_provider_base_url(config_path, manifest_provider, settings.upstream_base)
                restore_hook_feature_flag(config_path, backup_path, hook_result)
                restore_status = "restored_base_url"
                can_stop = True
            elif config_base_url == settings.upstream_base:
                restore_hook_feature_flag(config_path, backup_path, hook_result)
                restore_status = "already_restored_base_url"
                can_stop = True
            elif args.force:
                copy_private_file(Path(backup_path), config_path)
                restore_status = "restored"
                can_stop = True
            else:
                restore_status = "skipped_config_changed"

    if restore_status != "skipped_config_changed":
        state_keys = hook_result.get("removed_state_keys", []) if isinstance(hook_result, dict) else []
        if isinstance(state_keys, list):
            remove_hook_states_by_keys(paths.config_path, [key for key in state_keys if isinstance(key, str)])

    if can_stop and args.defer_stop:
        stop_result = {"status": "deferred", "reason": "restart_codex_before_stopping_proxy"}
        can_stop = False

    if can_stop:
        stop_result = stop_process(paths, args.force)

    files_status = "kept"
    if can_stop and not args.keep_state and paths.app_home.exists():
        shutil.rmtree(paths.app_home)
        files_status = "removed"

    result = {
        "status": "uninstalled",
        "stop_result": stop_result,
        "config_restore": restore_status,
        "startup_hook": hook_result,
        "backup_path": backup_path,
        "files": files_status,
    }
    warning = direct_upstream_auth_warning(paths, manifest_settings, restore_status)
    if warning:
        result["direct_upstream_auth_warning"] = warning
    if args.defer_stop and restore_status != "skipped_config_changed":
        result["current_session_effect"] = DEFER_STOP_SESSION_EFFECT
    return result, 3 if restore_status == "skipped_config_changed" else 0


def command_uninstall(args: argparse.Namespace) -> int:
    result, exit_code = uninstall_result(args)
    print(json_line(result))
    return exit_code


def add_shared_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codex-home", default=str(Path.home() / ".codex"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex Model Gateway for OpenAI-compatible Responses API providers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the foreground proxy server.")
    serve.add_argument("--host", default=DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--provider")
    serve.add_argument("--settings-revision")
    serve.add_argument("--proxy-base", default=DEFAULT_PROXY_BASE)
    serve.add_argument("--upstream-base", required=True)
    serve.add_argument("--service-tier", default=DEFAULT_SERVICE_TIER)
    serve.add_argument("--service-tier-policy", choices=sorted(SERVICE_TIER_POLICIES), default=DEFAULT_SERVICE_TIER_POLICY)
    serve.add_argument("--service-tier-effective-policy", choices=sorted(EFFECTIVE_SERVICE_TIER_POLICIES))
    serve.add_argument("--upstream-api-key-env")
    serve.add_argument("--upstream-api-key-source", choices=("env", "provider_auth_file"))
    serve.add_argument("--log-dir", default=str(Path.home() / ".codex" / "codex-fast-proxy-state" / "state"))
    serve.add_argument("--verbose", action="store_true")

    install = subparsers.add_parser("install", help="Start proxy and switch Codex config safely.")
    add_shared_options(install)
    install.add_argument("--provider")
    install.add_argument("--activate-provider", action="store_true")
    install.add_argument("--host", default=DEFAULT_HOST)
    install.add_argument("--port", type=int, default=None)
    install.add_argument("--proxy-base", default=DEFAULT_PROXY_BASE)
    install.add_argument("--upstream-base")
    install.add_argument("--service-tier", default=DEFAULT_SERVICE_TIER)
    install.add_argument("--service-tier-policy", choices=sorted(SERVICE_TIER_POLICIES))
    install.add_argument("--upstream-api-key-env")
    install.add_argument("--use-provider-auth-file", action="store_true")
    install.add_argument("--no-verify", dest="verify", action="store_false", default=True)
    install.add_argument("--verify-timeout", type=float, default=60.0)
    install.add_argument("--start", action="store_true")
    install.add_argument("--prepare-only", action="store_true")
    install.add_argument("--verbose-proxy", action="store_true")

    start = subparsers.add_parser("start", help="Start the background proxy.")
    add_shared_options(start)
    start.add_argument("--verbose-proxy", action="store_true")

    set_upstream = subparsers.add_parser("set-upstream", help="Update proxy-managed upstream settings while keeping Codex on the local proxy.")
    add_shared_options(set_upstream)
    set_upstream.add_argument("--upstream-base")
    set_upstream.add_argument("--service-tier-policy", choices=sorted(SERVICE_TIER_POLICIES))
    set_upstream.add_argument("--upstream-api-key-env")
    set_upstream.add_argument("--use-provider-auth-file", action="store_true")
    set_upstream.add_argument("--clear-upstream-auth", action="store_true")
    set_upstream.add_argument("--clear-upstream-api-key-env", action="store_true")
    set_upstream.add_argument("--no-verify", dest="verify", action="store_false", default=True)
    set_upstream.add_argument("--verify-timeout", type=float, default=60.0)
    set_upstream.add_argument("--restart", action="store_true")
    set_upstream.add_argument("--verbose-proxy", action="store_true")

    verify_upstream = subparsers.add_parser("verify-upstream", help="Read-only streaming Responses API check for an upstream route.")
    add_shared_options(verify_upstream)
    verify_upstream.add_argument("--provider")
    verify_upstream.add_argument("--upstream-base")
    verify_upstream.add_argument("--service-tier", default=None)
    verify_upstream.add_argument("--service-tier-policy", choices=sorted(SERVICE_TIER_POLICIES))
    verify_upstream.add_argument("--upstream-api-key-env")
    verify_upstream.add_argument("--use-provider-auth-file", action="store_true")
    verify_upstream.add_argument("--clear-upstream-auth", action="store_true")
    verify_upstream.add_argument("--clear-upstream-api-key-env", action="store_true")
    verify_upstream.add_argument("--verify-timeout", type=float, default=60.0)

    autostart = subparsers.add_parser("autostart", help="Start proxy and Control UI from a Codex SessionStart hook if enabled.")
    add_shared_options(autostart)
    autostart.add_argument("--quiet", action="store_true")
    autostart.add_argument("--hook-summary", action="store_true")
    autostart.add_argument("--verbose-proxy", action="store_true")

    lifecycle_hook = subparsers.add_parser("lifecycle-hook", help="Record Codex turn lifecycle from hooks.")
    add_shared_options(lifecycle_hook)

    stop = subparsers.add_parser("stop", help="Stop the background proxy.")
    add_shared_options(stop)
    stop.add_argument("--force", action="store_true")

    status = subparsers.add_parser("status", help="Show proxy and Codex config status.")
    add_shared_options(status)
    status.add_argument("--provider")

    ui = subparsers.add_parser("ui", help="Start the local Control UI and print its URL.")
    add_shared_options(ui)
    ui.add_argument("--provider")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8786)
    ui.add_argument("--foreground", action="store_true")

    doctor = subparsers.add_parser("doctor", help="Check Codex config and proxy environment.")
    add_shared_options(doctor)
    doctor.add_argument("--provider")

    benchmark = subparsers.add_parser("benchmark", help="Run an opt-in default vs priority latency benchmark.")
    add_shared_options(benchmark)
    benchmark.add_argument("--pairs", type=int)
    benchmark.add_argument("--timeout", type=float, default=600.0)
    benchmark.add_argument("--model")
    benchmark.add_argument("--reasoning-effort")
    benchmark.add_argument("--profile", default="full")
    benchmark.add_argument("--mode", choices=("codex-cli", "direct"), default="direct")
    benchmark.add_argument("--kind", choices=("quick", "strict"), default="quick")
    benchmark.add_argument("--api-key-env")
    benchmark.add_argument("--save", action=argparse.BooleanOptionalAction, default=True)

    check_update_parser = subparsers.add_parser("check-update", help="Read-only check for newer GitHub commits.")
    check_update_parser.add_argument("--repo")
    check_update_parser.add_argument("--remote", default="origin")
    check_update_parser.add_argument("--branch")

    update_parser = subparsers.add_parser("update", help="Update codex-fast-proxy and refresh enabled runtime state.")
    add_shared_options(update_parser)
    update_parser.add_argument("--provider")
    update_parser.add_argument("--repo")
    update_parser.add_argument("--remote", default="origin")
    update_parser.add_argument("--branch")
    update_parser.add_argument("--skip-self-update", action="store_true")

    prepare_login = subparsers.add_parser(
        "prepare-chatgpt-login",
        help="Prepare provider auth split before signing in to Codex App with ChatGPT.",
    )
    add_shared_options(prepare_login)
    prepare_login.add_argument("--provider")
    prepare_login.add_argument("--source-auth-key")
    prepare_login.add_argument("--target-env")
    prepare_login.add_argument("--apply", action="store_true")

    link_skill = subparsers.add_parser("link-skill", help="Link this repository's skill namespace.")
    link_skill.add_argument("--repo-root", required=True)
    link_skill.add_argument("--skills-root")

    unlink_skill = subparsers.add_parser("unlink-skill", help="Remove this repository's skill namespace link.")
    unlink_skill.add_argument("--repo-root", required=True)
    unlink_skill.add_argument("--skills-root")

    uninstall = subparsers.add_parser("uninstall", help="Stop proxy and restore the backed-up Codex config.")
    add_shared_options(uninstall)
    uninstall.add_argument("--force", action="store_true")
    uninstall.add_argument("--keep-state", action="store_true")
    uninstall.add_argument("--defer-stop", action="store_true")
    uninstall.add_argument("--confirm-chatgpt-direct-uninstall", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        from .proxy import main as serve_main

        serve_args = [
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--proxy-base",
            args.proxy_base,
            "--upstream-base",
            args.upstream_base,
            "--service-tier",
            args.service_tier,
            "--service-tier-policy",
            args.service_tier_policy,
        ]
        effective_policy = args.service_tier_effective_policy or ("preserve" if args.service_tier_policy == "auto" else args.service_tier_policy)
        if args.provider:
            serve_args.extend(["--provider", args.provider])
        if args.settings_revision:
            serve_args.extend(["--settings-revision", args.settings_revision])
        serve_args.extend(["--service-tier-effective-policy", effective_policy])
        serve_args.extend(["--log-dir", args.log_dir])
        if args.upstream_api_key_env:
            serve_args.extend(["--upstream-api-key-env", args.upstream_api_key_env])
        if args.upstream_api_key_source:
            serve_args.extend(["--upstream-api-key-source", args.upstream_api_key_source])
        if args.verbose:
            serve_args.append("--verbose")
        return serve_main(serve_args)

    commands = {
        "install": command_install,
        "set-upstream": command_set_upstream,
        "start": command_start,
        "autostart": command_autostart,
        "lifecycle-hook": command_lifecycle_hook,
        "stop": command_stop,
        "status": command_status,
        "ui": command_ui,
        "doctor": command_doctor,
        "benchmark": command_benchmark,
        "check-update": command_check_update,
        "update": command_update,
        "verify-upstream": command_verify_upstream,
        "prepare-chatgpt-login": command_prepare_chatgpt_login,
        "link-skill": command_link_skill,
        "unlink-skill": command_unlink_skill,
        "uninstall": command_uninstall,
    }
    try:
        return commands[args.command](args)
    except ConfigError as exc:
        print(compact_json({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 2
