from __future__ import annotations

from pathlib import Path
from typing import Any

from .auth import detect_login_mode, environment_source
from .config import load_toml_config, provider_base_url
from .core import ConfigError
from .storage import read_json, sha256_file, write_secret_json
from .status_rules import (
    CHATGPT_LOGIN_WINDOWS_TROUBLESHOOTING,
    chatgpt_login_hint,
    provider_auth_preparation,
)


DIRECT_UPSTREAM_RESTORE_STATUSES = {
    "already_restored",
    "already_restored_base_url",
    "restored",
    "restored_base_url",
}


def provider_auth_secret(paths: Any, provider: str) -> str | None:
    data = read_json(paths.provider_auth_path)
    if not data:
        return None
    providers = data.get("providers")
    if not isinstance(providers, dict):
        return None
    entry = providers.get(provider)
    if not isinstance(entry, dict):
        return None
    value = entry.get("api_key")
    return value if isinstance(value, str) and value else None


def write_provider_auth_secret(paths: Any, provider: str, secret: str) -> None:
    data = read_json(paths.provider_auth_path) or {"version": 1, "providers": {}}
    providers = data.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        data["providers"] = providers
    providers[provider] = {"api_key": secret}
    write_secret_json(paths.provider_auth_path, data)


def upstream_api_key_source(paths: Any, env_name: str | None) -> str | None:
    return environment_source(paths.codex_home, env_name)


def upstream_auth_configured(settings: Any | None) -> bool:
    return bool(settings and (settings.upstream_api_key_env or settings.upstream_api_key_file))


def upstream_auth_status(paths: Any, settings: Any | None) -> dict[str, Any]:
    env_name = settings.upstream_api_key_env if settings else None
    file_enabled = bool(settings and settings.upstream_api_key_file)
    if env_name:
        source = upstream_api_key_source(paths, env_name)
        persistent_source = source in {"process_env", "windows_user_env"}
    elif settings and file_enabled:
        source = "provider_auth_file" if provider_auth_secret(paths, settings.provider) else None
        persistent_source = bool(source)
    else:
        source = None
        persistent_source = None
    return {
        "upstream_auth": "override_configured" if upstream_auth_configured(settings) else "preserved",
        "upstream_api_key_env": env_name,
        "upstream_api_key_file": file_enabled if settings else None,
        "upstream_api_key_ref": "provider_auth_file" if file_enabled else env_name,
        "upstream_api_key_available": bool(source) if upstream_auth_configured(settings) else None,
        "upstream_api_key_source": source,
        "upstream_api_key_persistent": persistent_source if upstream_auth_configured(settings) else None,
    }


def direct_upstream_auth_warning(
    paths: Any,
    settings: Any | None,
    restore_status: str,
) -> dict[str, Any] | None:
    if restore_status not in DIRECT_UPSTREAM_RESTORE_STATUSES:
        return None
    return direct_upstream_auth_risk(paths, settings)


def direct_upstream_auth_risk(
    paths: Any,
    settings: Any | None,
) -> dict[str, Any] | None:
    login = detect_login_mode(paths.codex_home)
    if not login.chatgpt_auth:
        return None
    return {
        "code": "chatgpt_auth_direct_upstream",
        "severity": "high",
        "message": (
            "Codex config now points directly at the upstream provider, so the proxy auth override no longer "
            "protects model requests. If Codex App remains signed in with ChatGPT, third-party provider "
            "requests may receive ChatGPT auth and fail with 401."
        ),
        "next_user_action": (
            "Before restarting Codex after uninstall, switch Codex App back to API-key/third-party provider "
            "auth, or keep the proxy enabled if you want ChatGPT login UI with a third-party provider."
        ),
        "login_mode": login.login_mode,
        "upstream_base": settings.upstream_base if settings else None,
        "previous_upstream_auth": "override_configured" if upstream_auth_configured(settings) else "preserved",
        "upstream_api_key_env": settings.upstream_api_key_env if settings else None,
        "upstream_api_key_file": settings.upstream_api_key_file if settings else None,
    }


def uninstall_needs_chatgpt_direct_confirmation(
    paths: Any,
    manifest: dict[str, Any] | None,
    settings: Any | None,
    force: bool,
) -> dict[str, Any] | None:
    warning = direct_upstream_auth_risk(paths, settings)
    if not warning or not manifest or not settings:
        return None

    config_path = Path(manifest["config_path"])
    current_hash = sha256_file(config_path)
    if current_hash == manifest.get("config_hash_before"):
        return None
    if current_hash == manifest.get("config_hash_after"):
        return warning

    config = load_toml_config(config_path)
    config_base_url = provider_base_url(config, settings.provider)
    if config_base_url == settings.base_url:
        return warning
    if force and config_base_url != settings.upstream_base:
        return warning
    return None


def require_upstream_auth_available(paths: Any, settings: Any) -> None:
    if settings.upstream_api_key_env and not upstream_api_key_source(paths, settings.upstream_api_key_env):
        raise ConfigError(
            f"Upstream API key environment variable is not available: {settings.upstream_api_key_env}. "
            "Set it locally first, then retry. The key value must not be pasted into chat."
        )
    if settings.upstream_api_key_file and not provider_auth_secret(paths, settings.provider):
        raise ConfigError(
            f"Provider auth file does not contain an API key for provider {settings.provider!r}. "
            "Run prepare-chatgpt-login --apply first; the key value must not be pasted into chat."
        )


def chatgpt_login_report(
    paths: Any,
    settings: Any,
    login: Any | None = None,
    auth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    login = login or detect_login_mode(paths.codex_home)
    auth = auth or upstream_auth_status(paths, settings)
    hint = chatgpt_login_hint(login, auth)
    report: dict[str, Any] = {
        "provider_auth_preparation": provider_auth_preparation(login, auth),
        "chatgpt_login_hint": hint,
        "next_user_action": hint["next_user_action"],
    }
    if hint["status"] == "ready":
        report["chatgpt_login_windows_troubleshooting"] = CHATGPT_LOGIN_WINDOWS_TROUBLESHOOTING
    return report
