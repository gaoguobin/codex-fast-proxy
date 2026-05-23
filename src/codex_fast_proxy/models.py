from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .core import ConfigError, normalized_base_path, validate_env_name
from .status_rules import LEGACY_SERVICE_TIER_POLICY, SERVICE_TIER_POLICIES
from .storage import read_json, write_json


@dataclass(frozen=True)
class ProxyPaths:
    codex_home: Path
    app_home: Path
    state_dir: Path
    config_path: Path
    hooks_path: Path
    settings_path: Path
    provider_auth_path: Path
    manifest_path: Path
    pid_path: Path
    turns_path: Path
    log_path: Path
    stdout_path: Path
    stderr_path: Path
    benchmark_path: Path
    backup_dir: Path


@dataclass(frozen=True)
class ProxySettings:
    provider: str
    host: str
    port: int
    proxy_base: str
    upstream_base: str
    service_tier: str
    service_tier_policy: str = "auto"
    upstream_api_key_env: str | None = None
    upstream_api_key_file: bool = False
    settings_revision: str | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}{normalized_base_path(self.proxy_base)}"


def paths_for(codex_home: str | Path | None) -> ProxyPaths:
    resolved_home = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    app_home = resolved_home / "codex-fast-proxy-state"
    state_dir = app_home / "state"
    return ProxyPaths(
        codex_home=resolved_home,
        app_home=app_home,
        state_dir=state_dir,
        config_path=resolved_home / "config.toml",
        hooks_path=resolved_home / "hooks.json",
        settings_path=app_home / "settings.json",
        provider_auth_path=app_home / "provider-auth.json",
        manifest_path=app_home / "install-manifest.json",
        pid_path=state_dir / "fast_proxy.pid",
        turns_path=state_dir / "codex_turns.json",
        log_path=state_dir / "fast_proxy.jsonl",
        stdout_path=state_dir / "fast_proxy.stdout.log",
        stderr_path=state_dir / "fast_proxy.stderr.log",
        benchmark_path=state_dir / "fast_proxy.benchmark.json",
        backup_dir=resolved_home / "backups" / "codex-fast-proxy",
    )


def settings_from_dict(value: dict[str, Any]) -> ProxySettings:
    upstream_api_key_env = value.get("upstream_api_key_env")
    upstream_api_key_file = value.get("upstream_api_key_file") is True
    if upstream_api_key_env and upstream_api_key_file:
        raise ConfigError("Use only one upstream auth source in settings.")
    service_tier_policy = value.get("service_tier_policy")
    inferred_policy = "preserve" if upstream_api_key_env or upstream_api_key_file else LEGACY_SERVICE_TIER_POLICY
    policy = str(service_tier_policy) if service_tier_policy else inferred_policy
    if policy not in SERVICE_TIER_POLICIES:
        names = ", ".join(sorted(SERVICE_TIER_POLICIES))
        raise ConfigError(f"Invalid service tier policy {policy!r}. Available: {names}")
    return ProxySettings(
        provider=str(value["provider"]),
        host=str(value["host"]),
        port=int(value["port"]),
        proxy_base=normalized_base_path(str(value["proxy_base"])),
        upstream_base=str(value["upstream_base"]),
        service_tier=str(value["service_tier"]),
        service_tier_policy=policy,
        upstream_api_key_env=validate_env_name(str(upstream_api_key_env)) if upstream_api_key_env else None,
        upstream_api_key_file=upstream_api_key_file,
        settings_revision=str(value.get("settings_revision") or "") or None,
    )


def read_settings(paths: ProxyPaths) -> ProxySettings:
    settings = read_json(paths.settings_path)
    if not settings:
        raise ConfigError(f"Settings not found: {paths.settings_path}")
    return settings_from_dict(settings)


def write_settings(paths: ProxyPaths, settings: ProxySettings, *, bump_revision: bool | None = None) -> None:
    previous = read_json(paths.settings_path)
    previous_revision = previous.get("settings_revision") if isinstance(previous, dict) else None
    payload = {**asdict(settings), "base_url": settings.base_url}
    comparable = {key: value for key, value in payload.items() if key not in {"base_url", "settings_revision"}}
    previous_comparable = (
        {key: value for key, value in previous.items() if key not in {"base_url", "settings_revision"}}
        if isinstance(previous, dict)
        else None
    )
    should_bump = comparable != previous_comparable if bump_revision is None else bump_revision
    payload["settings_revision"] = uuid.uuid4().hex if should_bump or not previous_revision else str(previous_revision)
    write_json(paths.settings_path, payload)
