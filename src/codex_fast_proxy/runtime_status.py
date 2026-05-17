from __future__ import annotations

from pathlib import Path
from typing import Any

from .hooks import command_for_hook
from .proxy import RUNTIME_ID, runtime_details


def runtime_status(paths: Any, health: dict[str, Any] | None) -> dict[str, Any]:
    proxy_runtime = health.get("runtime") if isinstance(health, dict) else None
    manager_runtime = {**runtime_details(), "manager_module_file": str(Path(__file__).with_name("manager.py").resolve())}
    return {
        "manager": manager_runtime,
        "proxy": proxy_runtime if isinstance(proxy_runtime, dict) else None,
        "hook_command": command_for_hook(paths),
    }


def health_matches_settings(
    health: dict[str, Any] | None,
    settings: Any,
    service_tier_effective_policy: str | None = None,
) -> bool:
    if not health:
        return False
    health_effective_policy = health.get(
        "service_tier_effective_policy",
        health.get("service_tier_policy", "inject_missing"),
    )
    return (
        health.get("ok") is True
        and health.get("proxy_base") == settings.proxy_base
        and health.get("upstream_base") == settings.upstream_base
        and health.get("service_tier") == settings.service_tier
        and health.get("service_tier_policy") == settings.service_tier_policy
        and (service_tier_effective_policy is None or health_effective_policy == service_tier_effective_policy)
        and health.get("upstream_api_key_env") == settings.upstream_api_key_env
        and bool(health.get("upstream_api_key_file")) == settings.upstream_api_key_file
    )


def health_matches_runtime(health: dict[str, Any] | None) -> bool:
    return bool(health and health.get("runtime_id") == RUNTIME_ID)


def health_matches_proxy_identity(health: dict[str, Any] | None, settings: Any, pid: int | None) -> bool:
    return bool(
        health
        and health.get("ok") is True
        and health.get("pid") == pid
        and health.get("proxy_base") == settings.proxy_base
    )


def settings_restart_pending(
    health: dict[str, Any] | None,
    settings: Any | None,
    pid: int | None,
    service_tier_effective_policy: str | None = None,
) -> bool:
    return bool(
        settings
        and health_matches_proxy_identity(health, settings, pid)
        and not health_matches_settings(health, settings, service_tier_effective_policy)
    )
