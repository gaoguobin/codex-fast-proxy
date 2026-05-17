from __future__ import annotations

from typing import Any

from .core import ConfigError


CHATGPT_LOGIN_WINDOWS_TROUBLESHOOTING = {
    "trigger": "ChatGPT login fails on Windows with OSError: [WinError 10013] socket access denied.",
    "commands": [
        "net stop winnat",
        "netsh interface ipv4 show excludedportrange protocol=tcp",
        "net start winnat",
        "netsh interface ipv4 show excludedportrange protocol=tcp",
    ],
}
SERVICE_TIER_POLICIES = {"auto", "inject_missing", "preserve"}
EFFECTIVE_SERVICE_TIER_POLICIES = {"inject_missing", "preserve"}
LEGACY_SERVICE_TIER_POLICY = "inject_missing"


def effective_service_tier_policy(settings: Any, login: Any) -> str:
    if settings.service_tier_policy in EFFECTIVE_SERVICE_TIER_POLICIES:
        return settings.service_tier_policy
    if settings.service_tier_policy != "auto":
        raise ConfigError(f"Invalid service tier policy: {settings.service_tier_policy}")
    if login.login_mode == "api_key":
        return "inject_missing"
    return "preserve"


def fast_behavior(settings: Any | None, login: Any | None = None) -> str:
    if not settings:
        return "unknown"
    if settings.service_tier_policy == "preserve":
        return "preserve_only"
    if settings.service_tier_policy == "inject_missing":
        return "global_priority"
    if settings.service_tier_policy == "auto":
        if login and login.login_mode == "api_key":
            return "auto_global_priority"
        if login and login.login_mode in {"chatgpt", "mixed"}:
            return "app_controlled"
        return "unknown_conservative"
    return "unknown"


def status_diagnosis(
    settings: Any | None,
    *,
    running: bool,
    healthy: bool,
    pending_restart: bool,
    config_matches: bool,
    runtime_matches: bool | None,
    needs_restart: bool,
    startup_hook_ready: bool,
    login: Any,
    auth: dict[str, Any],
    behavior: str,
) -> dict[str, str]:
    if not settings:
        return {
            "level": "attention",
            "code": "not_enabled",
            "message": "Proxy settings are not installed; run install before enabling the proxy.",
        }
    if not config_matches:
        return {
            "level": "attention",
            "code": "config_not_proxy",
            "message": "Codex config does not currently point to this proxy.",
        }
    if not running:
        return {
            "level": "risk",
            "code": "proxy_stopped",
            "message": "Codex config points to the proxy, but the proxy is not running.",
        }
    if login.chatgpt_auth and auth["upstream_auth"] == "preserved":
        return {
            "level": "risk",
            "code": "chatgpt_auth_preserved",
            "message": "ChatGPT auth is present and upstream auth is not split; provider requests may receive the wrong bearer token.",
        }
    if auth["upstream_auth"] == "override_configured" and not auth["upstream_api_key_available"]:
        return {
            "level": "risk",
            "code": "upstream_auth_missing",
            "message": "Upstream auth override is configured, but the provider key environment variable is unavailable.",
        }
    if login.chatgpt_auth and auth["upstream_auth"] == "override_configured" and not auth["upstream_api_key_persistent"]:
        return {
            "level": "attention",
            "code": "upstream_auth_not_persistent",
            "message": "Provider auth currently depends on an auth.json fallback; move it to the proxy provider auth file or an environment variable before relying on ChatGPT login.",
        }
    if pending_restart:
        return {
            "level": "attention",
            "code": "settings_pending_restart",
            "message": "Proxy settings changed, but the running proxy was left untouched to avoid interrupting current sessions.",
        }
    if not healthy:
        return {
            "level": "risk",
            "code": "proxy_unhealthy",
            "message": "The proxy process is present, but its health check does not match settings.",
        }
    if needs_restart or runtime_matches is False:
        return {
            "level": "attention",
            "code": "runtime_stale",
            "message": "The proxy is healthy, but the running process does not match the installed code; restart Codex App or the proxy when safe.",
        }
    if not startup_hook_ready:
        return {
            "level": "attention",
            "code": "startup_hook_not_ready",
            "message": "The proxy is running now, but the Codex startup hook is not installed, enabled, and trusted.",
        }
    if behavior == "unknown_conservative":
        return {
            "level": "attention",
            "code": "fast_policy_unknown",
            "message": "Fast policy is conservative because the current Codex login state is unclear.",
        }
    return {
        "level": "ready",
        "code": "ready",
        "message": "Proxy config, runtime, hook, auth, and Fast policy are consistent.",
    }


def provider_auth_preparation(login: Any, auth: dict[str, Any]) -> dict[str, str]:
    if auth["upstream_auth"] == "override_configured" and auth["upstream_api_key_persistent"]:
        return {
            "status": "prepared",
            "message": "Provider auth is split through a proxy-managed auth file or environment variable.",
        }
    if auth["upstream_auth"] == "override_configured" and auth["upstream_api_key_available"]:
        return {
            "status": "needs_persistent_env",
            "message": "Provider auth works through a fallback, but should be moved to the proxy provider auth file before ChatGPT login.",
        }
    if login.chatgpt_auth:
        return {
            "status": "not_prepared",
            "message": "ChatGPT auth is present, but upstream provider auth is not split.",
        }
    return {
        "status": "optional",
        "message": "Run prepare-chatgpt-login before switching Codex App to ChatGPT login.",
    }


def chatgpt_login_hint(login: Any, auth: dict[str, Any]) -> dict[str, str]:
    if auth["upstream_auth"] == "override_configured" and auth["upstream_api_key_persistent"]:
        return {
            "status": "ready",
            "message": (
                "Optional: provider auth is prepared for ChatGPT login. You may keep API-key mode, or sign in "
                "with ChatGPT to use richer Codex App UI features such as plugin marketplace, GitHub/Apps/"
                "connectors, manual Fast controls, status hints, and voice input. If Windows login fails with "
                "WinError 10013, use chatgpt_login_windows_troubleshooting."
            ),
            "next_user_action": (
                "Optional: keep current mode, or sign in with ChatGPT if you want the full Codex App UI. "
                "If Windows login fails with WinError 10013, use chatgpt_login_windows_troubleshooting."
            ),
        }
    if auth["upstream_auth"] == "override_configured" and auth["upstream_api_key_available"]:
        return {
            "status": "needs_persistent_env",
            "message": (
                "Optional: provider auth works now, but move it to the proxy provider auth file before "
                "relying on ChatGPT login."
            ),
            "next_user_action": "Run prepare-chatgpt-login before switching to ChatGPT login.",
        }
    if login.chatgpt_auth:
        return {
            "status": "needs_auth_split",
            "message": (
                "ChatGPT login is detected, but provider auth is not split. Prepare upstream provider auth "
                "before relying on this setup for third-party model requests."
            ),
            "next_user_action": "Run prepare-chatgpt-login and set-upstream --use-provider-auth-file before relying on ChatGPT login.",
        }
    return {
        "status": "optional_setup_available",
        "message": (
            "Optional: keep the current API-key mode for third-party API plus global Fast. If you want the "
            "full Codex App UI, such as plugin marketplace, GitHub/Apps/connectors, manual Fast controls, "
            "status hints, and voice input, run prepare-chatgpt-login before switching Codex App to ChatGPT login."
        ),
        "next_user_action": (
            "Keep API-key mode, or run prepare-chatgpt-login before switching Codex App to ChatGPT login "
            "for plugin marketplace, GitHub/Apps/connectors, manual Fast controls, status hints, and voice input."
        ),
    }
