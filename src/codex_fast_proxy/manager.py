from __future__ import annotations

import argparse
import ctypes
import hashlib
import http.client
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None  # type: ignore[assignment]

TOML_DECODE_ERROR = tomllib.TOMLDecodeError if tomllib else ValueError

from . import __version__
from .auth import (
    LoginDiagnosis,
    detect_login_mode,
    environment_source,
    read_auth_json,
    read_secret_from_auth,
    resolve_env,
)
from .proxy import RUNTIME_ID, compact_json, runtime_details


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_PROXY_BASE = "/v1"
DEFAULT_SERVICE_TIER = "priority"
DEFAULT_SERVICE_TIER_POLICY = "auto"
SKILL_NAMESPACE = "codex-fast-proxy"
INTERNAL_UPSTREAM_API_KEY_ENV = "CODEX_FAST_PROXY_UPSTREAM_API_KEY"
LEGACY_SERVICE_TIER_POLICY = "inject_missing"
SERVICE_TIER_POLICIES = {"auto", "inject_missing", "preserve"}
EFFECTIVE_SERVICE_TIER_POLICIES = {"inject_missing", "preserve"}
HOOK_EVENT = "SessionStart"
HOOK_EVENT_LABEL = "session_start"
HOOK_MATCHER = "startup|resume"
HOOK_TIMEOUT_SECONDS = 10
HOOK_FEATURE_KEY = "hooks"
LEGACY_HOOK_FEATURE_KEY = "codex_hooks"
HOOK_FEATURE_KEYS = (HOOK_FEATURE_KEY, LEGACY_HOOK_FEATURE_KEY)
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENABLE_SESSION_EFFECT = (
    "Running Codex processes keep their current base_url. Restart Codex App, then resume the same conversation if desired, "
    "or open a new CLI process to use the proxy."
)
DEFER_STOP_SESSION_EFFECT = (
    "Codex config was restored, but the proxy was left running so a proxy-backed current process can finish. "
    "Restart Codex App, then resume the same conversation if desired, or open a new CLI process; then run uninstall again "
    "to stop the proxy and remove files."
)
DIRECT_UPSTREAM_RESTORE_STATUSES = {
    "already_restored",
    "already_restored_base_url",
    "restored",
    "restored_base_url",
}
CHATGPT_LOGIN_WINDOWS_TROUBLESHOOTING = {
    "trigger": "ChatGPT login fails on Windows with OSError: [WinError 10013] socket access denied.",
    "commands": [
        "net stop winnat",
        "netsh interface ipv4 show excludedportrange protocol=tcp",
        "net start winnat",
        "netsh interface ipv4 show excludedportrange protocol=tcp",
    ],
}


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
    service_tier_policy: str = DEFAULT_SERVICE_TIER_POLICY
    upstream_api_key_env: str | None = None
    upstream_api_key_file: bool = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}{normalized_base_path(self.proxy_base)}"


class ConfigError(RuntimeError):
    pass


def json_line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def provider_auth_secret(paths: ProxyPaths, provider: str) -> str | None:
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


def write_provider_auth_secret(paths: ProxyPaths, provider: str, secret: str) -> None:
    data = read_json(paths.provider_auth_path) or {"version": 1, "providers": {}}
    providers = data.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        data["providers"] = providers
    providers[provider] = {"api_key": secret}
    write_secret_json(paths.provider_auth_path, data)


def upstream_api_key_source(paths: ProxyPaths, env_name: str | None) -> str | None:
    return environment_source(paths.codex_home, env_name)


def upstream_auth_configured(settings: ProxySettings | None) -> bool:
    return bool(settings and (settings.upstream_api_key_env or settings.upstream_api_key_file))


def upstream_auth_status(paths: ProxyPaths, settings: ProxySettings | None) -> dict[str, Any]:
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
    paths: ProxyPaths,
    settings: ProxySettings | None,
    restore_status: str,
) -> dict[str, Any] | None:
    if restore_status not in DIRECT_UPSTREAM_RESTORE_STATUSES:
        return None
    return direct_upstream_auth_risk(paths, settings)


def direct_upstream_auth_risk(
    paths: ProxyPaths,
    settings: ProxySettings | None,
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
    paths: ProxyPaths,
    manifest: dict[str, Any] | None,
    settings: ProxySettings | None,
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


def runtime_status(paths: ProxyPaths, health: dict[str, Any] | None) -> dict[str, Any]:
    proxy_runtime = health.get("runtime") if isinstance(health, dict) else None
    manager_runtime = {**runtime_details(), "manager_module_file": str(Path(__file__).resolve())}
    return {
        "manager": manager_runtime,
        "proxy": proxy_runtime if isinstance(proxy_runtime, dict) else None,
        "hook_command": command_for_hook(paths),
    }


def require_upstream_auth_available(paths: ProxyPaths, settings: ProxySettings) -> None:
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


def is_success_status(value: Any) -> bool:
    try:
        status = int(value)
    except (TypeError, ValueError):
        return False
    return 200 <= status < 400


def resolve_verification_api_key(
    paths: ProxyPaths,
    provider_config: dict[str, Any],
    settings: ProxySettings,
) -> tuple[str, str]:
    if settings.upstream_api_key_env:
        value = resolve_env(settings.upstream_api_key_env) or read_secret_from_auth(
            paths.codex_home,
            settings.upstream_api_key_env,
        )
        if not value:
            raise ConfigError(
                f"Upstream API key environment variable is not available: {settings.upstream_api_key_env}."
            )
        source = upstream_api_key_source(paths, settings.upstream_api_key_env) or "unknown"
        return f"{source}:{settings.upstream_api_key_env}", value
    if settings.upstream_api_key_file:
        value = provider_auth_secret(paths, settings.provider)
        if not value:
            raise ConfigError(f"Provider auth file does not contain an API key for provider {settings.provider!r}.")
        return "provider_auth_file", value

    from .benchmark import discover_api_key

    try:
        return discover_api_key(provider_config, None, paths.codex_home)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def verify_upstream_responses(
    paths: ProxyPaths,
    config: dict[str, Any],
    settings: ProxySettings,
    timeout: float,
) -> dict[str, Any]:
    if timeout <= 0:
        raise ConfigError("--verify-timeout must be greater than 0.")

    from .benchmark import BenchmarkTarget, run_sample

    model = config.get("model")
    reasoning_effort = config.get("model_reasoning_effort")
    if not isinstance(model, str) or not model:
        raise ConfigError("Codex config has no model; rerun set-upstream with --no-verify or configure a model first.")
    if reasoning_effort is not None and not isinstance(reasoning_effort, str):
        raise ConfigError("Codex config model_reasoning_effort must be a string.")

    provider_config = provider_config_for(config, settings.provider)
    api_key_source, api_key = resolve_verification_api_key(paths, provider_config, settings)
    login = detect_login_mode(paths.codex_home)
    request_tier = "priority" if effective_service_tier_policy(settings, login) == "inject_missing" else "default"
    target = BenchmarkTarget(
        provider=settings.provider,
        upstream_base=settings.upstream_base,
        model=model,
        profile="smoke",
        service_tier=settings.service_tier,
        api_key_source=api_key_source,
        api_key=api_key,
        reasoning_effort=reasoning_effort,
    )

    try:
        sample = run_sample(target, request_tier, timeout)
    except Exception as exc:
        raise ConfigError(f"Responses API side-path verification failed: {redact_sensitive_text(str(exc))}") from exc

    content_type = str(sample.get("response_content_type") or "")
    if not is_success_status(sample.get("status")):
        raise ConfigError(f"Responses API side-path verification returned HTTP {sample.get('status')}.")
    if "text/event-stream" not in content_type.lower():
        raise ConfigError(
            f"Responses API side-path verification did not return SSE content: {content_type or '<missing>'}."
        )

    return {
        "status": "verified",
        "request": "POST /v1/responses",
        "stream": True,
        "profile": "smoke",
        "provider": settings.provider,
        "upstream_base": settings.upstream_base,
        "model": model,
        "service_tier_request": request_tier,
        "response_status": sample.get("status"),
        "response_content_type": sample.get("response_content_type"),
        "first_event_ms": sample.get("first_event_ms"),
        "total_ms": sample.get("total_ms"),
        "response_service_tier": sample.get("response_service_tier"),
        "api_key_source": api_key_source,
    }


def install_requires_verification(
    existing_enabled: bool,
    existing_settings: ProxySettings | None,
    settings: ProxySettings,
) -> bool:
    if not existing_enabled or not existing_settings:
        return True
    return any(
        (
            existing_settings.upstream_base != settings.upstream_base,
            existing_settings.service_tier != settings.service_tier,
            existing_settings.service_tier_policy != settings.service_tier_policy,
            existing_settings.upstream_api_key_env != settings.upstream_api_key_env,
            existing_settings.upstream_api_key_file != settings.upstream_api_key_file,
        )
    )


def resolve_upstream_auth_options(
    current_env: str | None,
    current_file: bool,
    *,
    env_name: str | None = None,
    use_file: bool = False,
    clear: bool = False,
) -> tuple[str | None, bool, bool]:
    requested = sum(bool(value) for value in (env_name, use_file, clear))
    if requested > 1:
        raise ConfigError("Use only one upstream auth option at a time.")
    if clear:
        return None, False, True
    if use_file:
        return None, True, True
    if env_name:
        return validate_env_name(env_name), False, True
    return current_env, current_file, False


def verification_settings_from_args(
    paths: ProxyPaths,
    config: dict[str, Any],
    args: argparse.Namespace,
) -> ProxySettings:
    settings_data = read_json(paths.settings_path)
    existing_settings = settings_from_dict(settings_data) if settings_data else None
    provider = args.provider or (existing_settings.provider if existing_settings else choose_provider(config, None))
    if existing_settings and provider == existing_settings.provider:
        base = existing_settings
        upstream_base = validate_upstream_base(args.upstream_base) if args.upstream_base else base.upstream_base
        service_tier = args.service_tier or base.service_tier
        service_tier_policy = args.service_tier_policy or base.service_tier_policy
        upstream_api_key_env = base.upstream_api_key_env
        upstream_api_key_file = base.upstream_api_key_file
    else:
        upstream_value = args.upstream_base or provider_base_url(config, provider)
        if not upstream_value:
            raise ConfigError(f"Provider {provider!r} has no upstream base_url; pass --upstream-base.")
        upstream_base = validate_upstream_base(upstream_value)
        service_tier = args.service_tier or DEFAULT_SERVICE_TIER
        service_tier_policy = args.service_tier_policy or DEFAULT_SERVICE_TIER_POLICY
        upstream_api_key_env = None
        upstream_api_key_file = False
        base = ProxySettings(
            provider=provider,
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            proxy_base=DEFAULT_PROXY_BASE,
            upstream_base=upstream_base,
            service_tier=service_tier,
            service_tier_policy=service_tier_policy,
            upstream_api_key_env=upstream_api_key_env,
            upstream_api_key_file=upstream_api_key_file,
        )

    upstream_api_key_env, upstream_api_key_file, _auth_source_requested = resolve_upstream_auth_options(
        upstream_api_key_env,
        upstream_api_key_file,
        env_name=args.upstream_api_key_env,
        use_file=bool(getattr(args, "use_provider_auth_file", False)),
        clear=bool(args.clear_upstream_api_key_env or getattr(args, "clear_upstream_auth", False)),
    )

    if service_tier_policy not in SERVICE_TIER_POLICIES:
        names = ", ".join(sorted(SERVICE_TIER_POLICIES))
        raise ConfigError(f"Invalid service tier policy {service_tier_policy!r}. Available: {names}")

    return ProxySettings(
        provider=provider,
        host=base.host,
        port=base.port,
        proxy_base=base.proxy_base,
        upstream_base=upstream_base,
        service_tier=service_tier,
        service_tier_policy=service_tier_policy,
        upstream_api_key_env=upstream_api_key_env,
        upstream_api_key_file=upstream_api_key_file,
    )


def validate_env_name(name: str) -> str:
    value = name.strip()
    if not ENV_NAME_PATTERN.fullmatch(value):
        raise ConfigError(f"Invalid environment variable name: {name!r}")
    return value


def default_provider_env_name(provider: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", provider).strip("_").upper()
    return f"{normalized or 'PROVIDER'}_API_KEY"


def auth_api_key_names(codex_home: Path) -> list[str]:
    try:
        auth_data = read_auth_json(codex_home)
    except (OSError, json.JSONDecodeError):
        return []
    if not auth_data:
        return []
    return sorted(
        key
        for key, value in auth_data.items()
        if key.endswith("_API_KEY") and isinstance(value, str) and value
    )


def provider_auth_candidates(
    provider: str,
    provider_config: dict[str, Any],
    requested_source: str | None,
    codex_home: Path,
) -> list[str]:
    candidates: list[str] = []
    if requested_source:
        candidates.append(requested_source)
    for key in ("api_key_env_var", "env_key", "api_key_env"):
        value = provider_config.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    candidates.extend(["OPENAI_API_KEY", default_provider_env_name(provider)])
    candidates.extend(auth_api_key_names(codex_home))

    deduped: list[str] = []
    for name in candidates:
        try:
            env_name = validate_env_name(name)
        except ConfigError:
            continue
        if env_name not in deduped:
            deduped.append(env_name)
    return deduped


def discover_provider_secret(paths: ProxyPaths, candidates: list[str]) -> tuple[str, str, str]:
    for env_name in candidates:
        value = read_secret_from_auth(paths.codex_home, env_name)
        if value:
            return "auth_json", env_name, value
    for env_name in candidates:
        value = resolve_env(env_name)
        if value:
            source = upstream_api_key_source(paths, env_name) or "environment"
            return source, env_name, value
    names = ", ".join(candidates) if candidates else "<none>"
    raise ConfigError(f"No provider API key was found in auth.json or environment candidates: {names}.")


def prepare_chatgpt_login(args: argparse.Namespace) -> dict[str, Any]:
    paths = paths_for(args.codex_home)
    config = load_toml_config(paths.config_path)
    provider = choose_provider(config, args.provider)
    provider_config = provider_config_for(config, provider)
    legacy_target_env = validate_env_name(args.target_env) if args.target_env else None
    source_auth_key = validate_env_name(args.source_auth_key) if args.source_auth_key else None
    candidates = provider_auth_candidates(provider, provider_config, source_auth_key, paths.codex_home)
    source_kind, source_name, secret = discover_provider_secret(paths, candidates)
    existing_secret = provider_auth_secret(paths, provider)
    target_exists = bool(existing_secret)
    target_matches_source = existing_secret == secret if existing_secret else False
    already_prepared = target_matches_source

    applied = False
    if args.apply and not target_matches_source:
        write_provider_auth_secret(paths, provider, secret)
        applied = True
        target_exists = True
        target_matches_source = True

    status = "already_prepared" if already_prepared else ("prepared" if applied else "dry_run")
    return {
        "status": status,
        "provider": provider,
        "source": f"{source_kind}:{source_name}",
        "target_auth": "provider_auth_file",
        "legacy_target_env": legacy_target_env,
        "provider_auth_path": str(paths.provider_auth_path),
        "target_exists": target_exists,
        "target_matches_source": target_matches_source,
        "applied": applied,
        "settings_changed": False,
        "secret_printed": False,
        "next_action": (
            "run set-upstream --use-provider-auth-file"
            if applied or target_matches_source
            else "rerun prepare-chatgpt-login --apply after user approval"
        ),
        "restart_required": False,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_line(value) + "\n", encoding="utf-8")


def write_secret_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            path.chmod(0o600)
        except OSError:
            pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(json_line(value) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_base_path(value: str) -> str:
    return "/" + value.strip("/ ")


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
        log_path=state_dir / "fast_proxy.jsonl",
        stdout_path=state_dir / "fast_proxy.stdout.log",
        stderr_path=state_dir / "fast_proxy.stderr.log",
        benchmark_path=state_dir / "fast_proxy.benchmark.json",
        backup_dir=resolved_home / "backups" / "codex-fast-proxy",
    )


def skill_namespace_path(skills_root: str | Path | None = None) -> Path:
    root = Path(skills_root).expanduser() if skills_root else Path.home() / ".agents" / "skills"
    return root / SKILL_NAMESPACE


def skill_target_path(repo_root: str | Path) -> Path:
    return Path(repo_root).expanduser().resolve() / "skills"


def path_points_to(path: Path, target: Path) -> bool:
    try:
        return path.resolve(strict=True) == target.resolve(strict=True)
    except OSError:
        return False


def is_windows_platform() -> bool:
    return os.name == "nt"


def path_is_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    if is_junction:
        return bool(is_junction())
    if not is_windows_platform():
        return False
    try:
        attributes = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    except AttributeError:
        return False
    invalid_file_attributes = 0xFFFFFFFF
    file_attribute_directory = 0x10
    file_attribute_reparse_point = 0x400
    return bool(
        attributes != invalid_file_attributes
        and attributes & file_attribute_directory
        and attributes & file_attribute_reparse_point
    )


def link_skill_namespace(repo_root: str | Path, skills_root: str | Path | None = None) -> dict[str, Any]:
    target = skill_target_path(repo_root)
    link = skill_namespace_path(skills_root)
    if not target.is_dir():
        raise ConfigError(f"Skill target does not exist: {target}")
    if link.exists() or link.is_symlink():
        if path_points_to(link, target):
            return {"status": "already_linked", "path": str(link), "target": str(target)}
        raise ConfigError(f"Skill namespace already exists and does not point to {target}: {link}")

    link.parent.mkdir(parents=True, exist_ok=True)
    if is_windows_platform():
        completed = subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise ConfigError(f"Failed to create skill namespace junction: {detail or completed.returncode}")
        link_type = "junction"
    else:
        link.symlink_to(target, target_is_directory=True)
        link_type = "symlink"
    return {"status": "linked", "path": str(link), "target": str(target), "link_type": link_type}


def unlink_skill_namespace(repo_root: str | Path, skills_root: str | Path | None = None) -> dict[str, Any]:
    target = skill_target_path(repo_root)
    link = skill_namespace_path(skills_root)
    if not link.exists() and not link.is_symlink():
        return {"status": "missing", "path": str(link), "target": str(target)}
    if not path_points_to(link, target):
        raise ConfigError(f"Refusing to remove skill namespace with unexpected target: {link}")

    if link.is_symlink():
        link.unlink()
        link_type = "symlink"
    elif path_is_junction(link):
        link.rmdir()
        link_type = "junction"
    else:
        raise ConfigError(f"Refusing to remove skill namespace that is not a symlink or junction: {link}")
    return {"status": "unlinked", "path": str(link), "target": str(target), "link_type": link_type}


def load_toml_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    if tomllib is None:
        raise ConfigError("Python 3.11+ is required to read Codex TOML config.")
    return tomllib.loads(config_path.read_text(encoding="utf-8-sig"))


def active_provider_name(config: dict[str, Any]) -> str | None:
    value = config.get("model_provider")
    return value if isinstance(value, str) and value else None


def configured_providers(config: dict[str, Any]) -> dict[str, Any]:
    providers = config.get("model_providers", {})
    return providers if isinstance(providers, dict) else {}


def choose_provider(config: dict[str, Any], provider: str | None) -> str:
    if provider:
        return provider

    active_provider = active_provider_name(config)
    if active_provider:
        return active_provider

    providers = configured_providers(config)
    if len(providers) == 1:
        return next(iter(providers))

    if providers:
        names = ", ".join(sorted(providers))
        raise ConfigError(f"Codex config has multiple providers; pass --provider. Available: {names}")

    raise ConfigError("Codex config has no model provider; configure one before installing the proxy.")


def provider_base_url(config: dict[str, Any], provider: str) -> str | None:
    provider_config = provider_config_for(config, provider)
    value = provider_config.get("base_url")
    return value if isinstance(value, str) and value else None


def provider_config_for(config: dict[str, Any], provider: str) -> dict[str, Any]:
    provider_config = configured_providers(config).get(provider, {})
    if not isinstance(provider_config, dict):
        return {}
    return provider_config


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
    )


def effective_service_tier_policy(settings: ProxySettings, login: LoginDiagnosis) -> str:
    if settings.service_tier_policy in EFFECTIVE_SERVICE_TIER_POLICIES:
        return settings.service_tier_policy
    if settings.service_tier_policy != "auto":
        raise ConfigError(f"Invalid service tier policy: {settings.service_tier_policy}")
    if login.login_mode == "api_key":
        return "inject_missing"
    return "preserve"


def fast_behavior(settings: ProxySettings | None, login: LoginDiagnosis | None = None) -> str:
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
    settings: ProxySettings | None,
    *,
    running: bool,
    healthy: bool,
    pending_restart: bool,
    config_matches: bool,
    runtime_matches: bool | None,
    needs_restart: bool,
    startup_hook_ready: bool,
    login: LoginDiagnosis,
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


def provider_auth_preparation(login: LoginDiagnosis, auth: dict[str, Any]) -> dict[str, str]:
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


def chatgpt_login_hint(login: LoginDiagnosis, auth: dict[str, Any]) -> dict[str, str]:
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


def chatgpt_login_report(
    paths: ProxyPaths,
    settings: ProxySettings,
    login: LoginDiagnosis | None = None,
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


def read_settings(paths: ProxyPaths) -> ProxySettings:
    settings = read_json(paths.settings_path)
    if not settings:
        raise ConfigError(f"Settings not found: {paths.settings_path}")
    return settings_from_dict(settings)


def write_settings(paths: ProxyPaths, settings: ProxySettings) -> None:
    write_json(paths.settings_path, {**asdict(settings), "base_url": settings.base_url})


def validate_upstream_base(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"Invalid upstream base URL: {value}")
    if parsed.username or parsed.password:
        raise ConfigError("Upstream base URL must not contain usernames, passwords, or tokens.")
    if parsed.query or parsed.fragment:
        raise ConfigError("Upstream base URL must not contain query strings or fragments.")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def safe_url_display(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value
    netloc = parsed.netloc.rsplit("@", 1)[-1]
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme, netloc, path, "", ""))


def redact_url_secrets(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return safe_url_display(match.group(0))

    return re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+", replace, text)


def redact_sensitive_text(text: str) -> str:
    redacted = redact_url_secrets(text)
    redacted = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,'\"<>]+", r"\1<redacted>", redacted)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "<redacted-key>", redacted)


def source_repo_root() -> Path:
    path = Path(__file__).resolve()
    if path.parents[1].name == "src":
        return path.parents[2]
    cwd = Path.cwd()
    return cwd if (cwd / ".git").exists() else path.parents[1]


def run_git(repo: Path, *args: str, timeout: float = 30.0) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ConfigError(redact_url_secrets(detail) or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def current_git_branch(repo: Path) -> str:
    branch = run_git(repo, "branch", "--show-current")
    return branch or "main"


def remote_commit_for(repo: Path, remote: str, branch: str) -> str:
    output = run_git(repo, "ls-remote", remote, f"refs/heads/{branch}", timeout=60.0)
    line = output.splitlines()[0] if output else ""
    commit = line.split()[0] if line else ""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ConfigError(f"Remote branch not found: {remote}/{branch}")
    return commit.lower()


def commit_exists_locally(repo: Path, commit: str) -> bool:
    try:
        run_git(repo, "cat-file", "-e", f"{commit}^{{commit}}")
    except ConfigError:
        return False
    return True


def commit_is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    try:
        run_git(repo, "merge-base", "--is-ancestor", ancestor, descendant)
    except ConfigError:
        return False
    return True


def commit_relation(repo: Path, local_commit: str, remote_commit: str) -> str:
    if local_commit == remote_commit:
        return "same"
    if not commit_exists_locally(repo, remote_commit):
        return "remote_unknown"
    if commit_is_ancestor(repo, remote_commit, local_commit):
        return "local_ahead"
    if commit_is_ancestor(repo, local_commit, remote_commit):
        return "remote_ahead"
    return "diverged"


def check_update(repo: Path | None = None, branch: str | None = None, remote: str = "origin") -> dict[str, Any]:
    repo = repo or source_repo_root()
    run_git(repo, "rev-parse", "--is-inside-work-tree")
    selected_branch = branch or current_git_branch(repo)
    local_commit = run_git(repo, "rev-parse", "HEAD").lower()
    local_changes = bool(run_git(repo, "status", "--porcelain"))
    remote_url = safe_url_display(run_git(repo, "remote", "get-url", remote))
    remote_commit = remote_commit_for(repo, remote, selected_branch)
    relation = commit_relation(repo, local_commit, remote_commit)
    update_available = relation in {"remote_ahead", "remote_unknown", "diverged"}
    if update_available and local_changes:
        next_action = "review local changes before following UPDATE.md"
    elif relation == "local_ahead":
        next_action = "none"
    elif relation == "diverged":
        next_action = "review local commits before following UPDATE.md"
    elif update_available:
        next_action = "follow UPDATE.md"
    else:
        next_action = "none"
    return {
        "status": "checked",
        "read_only": True,
        "repo": str(repo),
        "remote": remote,
        "remote_url": remote_url,
        "branch": selected_branch,
        "local_commit": local_commit,
        "remote_commit": remote_commit,
        "relation": relation,
        "local_changes": local_changes,
        "update_available": update_available,
        "next_action": next_action,
    }


def read_toml_lines(path: Path) -> tuple[list[str], str]:
    if not path.exists():
        return [], "\n"
    content = path.read_text(encoding="utf-8-sig")
    newline = "\r\n" if "\r\n" in content else "\n"
    lines = content.splitlines()
    return lines, newline


def write_toml_lines(path: Path, lines: list[str], newline: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(newline.join(lines) + newline, encoding="utf-8")


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def toml_table_name(provider: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", provider):
        return f"model_providers.{provider}"
    return f"model_providers.{toml_string(provider)}"


def hook_state_table_name(key: str) -> str:
    return f"hooks.state.{toml_string(key)}"


def is_toml_key(line: str, key: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(f"{key} ") or stripped.startswith(f"{key}=")


def find_provider_table(lines: list[str], provider: str) -> int | None:
    expected = {f"model_providers.{provider}", f"model_providers.{toml_string(provider)}"}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]") and stripped[1:-1].strip() in expected:
            return index
    return None


def next_table_index(lines: list[str], start_index: int) -> int:
    for index in range(start_index + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            return index
    return len(lines)


def set_provider_base_url(config_path: Path, provider: str, base_url: str) -> None:
    lines, newline = read_toml_lines(config_path)
    table_index = find_provider_table(lines, provider)
    replacement = f"base_url = {toml_string(base_url)}"

    if table_index is None:
        if lines:
            lines.append("")
        lines.extend([f"[{toml_table_name(provider)}]", replacement])
        write_toml_lines(config_path, lines, newline)
        return

    end_index = next_table_index(lines, table_index)
    for index in range(table_index + 1, end_index):
        if is_toml_key(lines[index], "base_url"):
            indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
            lines[index] = indent + replacement
            write_toml_lines(config_path, lines, newline)
            return

    lines.insert(end_index, replacement)
    write_toml_lines(config_path, lines, newline)


def set_active_provider(config_path: Path, provider: str) -> None:
    lines, newline = read_toml_lines(config_path)
    replacement = f"model_provider = {toml_string(provider)}"

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            break
        if is_toml_key(line, "model_provider"):
            indent = line[: len(line) - len(line.lstrip())]
            lines[index] = indent + replacement
            write_toml_lines(config_path, lines, newline)
            return

    lines.insert(0, replacement)
    write_toml_lines(config_path, lines, newline)


def find_table(lines: list[str], table_name: str) -> int | None:
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]") and stripped[1:-1].strip() == table_name:
            return index
    return None


def set_feature_flag(config_path: Path, key: str, enabled: bool) -> None:
    lines, newline = read_toml_lines(config_path)
    table_index = find_table(lines, "features")
    replacement = f"{key} = {str(enabled).lower()}"

    if table_index is None:
        if lines:
            lines.append("")
        lines.extend(["[features]", replacement])
        write_toml_lines(config_path, lines, newline)
        return

    end_index = next_table_index(lines, table_index)
    for index in range(table_index + 1, end_index):
        if is_toml_key(lines[index], key):
            indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
            lines[index] = indent + replacement
            write_toml_lines(config_path, lines, newline)
            return

    lines.insert(end_index, replacement)
    write_toml_lines(config_path, lines, newline)


def remove_feature_flag(config_path: Path, key: str) -> None:
    lines, newline = read_toml_lines(config_path)
    table_index = find_table(lines, "features")
    if table_index is None:
        return

    end_index = next_table_index(lines, table_index)
    for index in range(table_index + 1, end_index):
        if is_toml_key(lines[index], key):
            del lines[index]
            new_end_index = next_table_index(lines, table_index)
            if not any(line.strip() and not line.strip().startswith("#") for line in lines[table_index + 1 : new_end_index]):
                del lines[table_index:new_end_index]
            write_toml_lines(config_path, lines, newline)
            return


def config_feature_enabled(config: dict[str, Any], key: str) -> bool:
    features = config.get("features", {})
    return isinstance(features, dict) and features.get(key) is True


def config_feature_value(config: dict[str, Any], key: str) -> bool | None:
    features = config.get("features", {})
    if not isinstance(features, dict) or key not in features:
        return None
    value = features.get(key)
    return value if isinstance(value, bool) else None


def hooks_feature_enabled(config: dict[str, Any]) -> bool:
    return any(config_feature_enabled(config, key) for key in HOOK_FEATURE_KEYS)


def set_hooks_feature_flag(config_path: Path) -> None:
    for key in HOOK_FEATURE_KEYS:
        set_feature_flag(config_path, key, True)


def remove_hook_feature_flags(config_path: Path) -> None:
    for key in HOOK_FEATURE_KEYS:
        remove_feature_flag(config_path, key)


def restore_hook_feature_flag(config_path: Path, backup_path: str | None, hook_result: dict[str, Any]) -> None:
    if hook_result.get("status") not in {"removed_file", "missing"}:
        return

    backup_config = load_toml_config(Path(backup_path)) if backup_path else {}
    for key in HOOK_FEATURE_KEYS:
        value = config_feature_value(backup_config, key)
        if value is None:
            remove_feature_flag(config_path, key)
        else:
            set_feature_flag(config_path, key, value)


def command_for_hook(paths: ProxyPaths) -> str:
    args = [
        sys.executable,
        "-m",
        "codex_fast_proxy",
        "autostart",
        "--codex-home",
        str(paths.codex_home),
        "--quiet",
    ]
    if os.name == "nt":
        return subprocess.list2cmdline(args)
    return shlex.join(args)


def hook_handler(paths: ProxyPaths) -> dict[str, Any]:
    return {
        "type": "command",
        "command": command_for_hook(paths),
        "timeout": HOOK_TIMEOUT_SECONDS,
    }


def is_fast_proxy_hook(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("type") == "command"
        and "codex_fast_proxy" in str(value.get("command", ""))
        and "autostart" in str(value.get("command", ""))
    )


def hook_key(source_path: Path, event_label: str, group_index: int, handler_index: int) -> str:
    return f"{source_path}:{event_label}:{group_index}:{handler_index}"


def canonical_json_hash(value: dict[str, Any]) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def command_hook_hash(event_label: str, matcher: str | None, hook: dict[str, Any]) -> str:
    handler = {
        "type": "command",
        "command": str(hook["command"]),
        "timeout": int(hook.get("timeout") or 600),
        "async": bool(hook.get("async", False)),
    }
    status_message = hook.get("statusMessage")
    if status_message is not None:
        handler["statusMessage"] = str(status_message)

    identity: dict[str, Any] = {"event_name": event_label, "hooks": [handler]}
    if matcher is not None:
        identity["matcher"] = matcher
    return canonical_json_hash(identity)


def fast_proxy_hook_states(paths: ProxyPaths, hooks_data: dict[str, Any]) -> list[dict[str, str]]:
    states = []
    event_hooks = hooks_data.get("hooks", {}).get(HOOK_EVENT, [])
    if not isinstance(event_hooks, list):
        return states
    for group_index, group in enumerate(event_hooks):
        if not isinstance(group, dict):
            continue
        hooks = group.get("hooks")
        if not isinstance(hooks, list):
            continue
        matcher = group.get("matcher")
        matcher = matcher if isinstance(matcher, str) else None
        for handler_index, hook in enumerate(hooks):
            if not is_fast_proxy_hook(hook):
                continue
            states.append({
                "key": hook_key(paths.hooks_path, HOOK_EVENT_LABEL, group_index, handler_index),
                "trusted_hash": command_hook_hash(HOOK_EVENT_LABEL, matcher, hook),
            })
    return states


def set_hook_state(config_path: Path, key: str, trusted_hash: str) -> None:
    lines, newline = read_toml_lines(config_path)
    table_name = hook_state_table_name(key)
    table_index = find_table(lines, table_name)
    replacements = {
        "enabled": "enabled = true",
        "trusted_hash": f"trusted_hash = {toml_string(trusted_hash)}",
    }

    if table_index is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{table_name}]")
        lines.extend(replacements.values())
        write_toml_lines(config_path, lines, newline)
        return

    end_index = next_table_index(lines, table_index)
    seen: set[str] = set()
    for index in range(table_index + 1, end_index):
        for key_name, replacement in replacements.items():
            if is_toml_key(lines[index], key_name):
                indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
                lines[index] = indent + replacement
                seen.add(key_name)
                break

    insert_at = end_index
    for key_name, replacement in replacements.items():
        if key_name not in seen:
            lines.insert(insert_at, replacement)
            insert_at += 1
    write_toml_lines(config_path, lines, newline)


def remove_hook_state(config_path: Path, key: str) -> None:
    lines, newline = read_toml_lines(config_path)
    table_index = find_table(lines, hook_state_table_name(key))
    if table_index is None:
        return
    end_index = next_table_index(lines, table_index)
    del lines[table_index:end_index]
    while table_index < len(lines) and table_index > 0 and lines[table_index].strip() == "" and lines[table_index - 1].strip() == "":
        del lines[table_index]
    write_toml_lines(config_path, lines, newline)


def trust_fast_proxy_hooks(paths: ProxyPaths, hooks_data: dict[str, Any]) -> list[dict[str, str]]:
    states = fast_proxy_hook_states(paths, hooks_data)
    for state in states:
        set_hook_state(paths.config_path, state["key"], state["trusted_hash"])
    return states


def remove_fast_proxy_hook_states(paths: ProxyPaths, hooks_data: dict[str, Any]) -> list[str]:
    keys = [state["key"] for state in fast_proxy_hook_states(paths, hooks_data)]
    remove_hook_states_by_keys(paths.config_path, keys)
    return keys


def remove_hook_states_by_keys(config_path: Path, keys: list[str]) -> None:
    for key in keys:
        remove_hook_state(config_path, key)


def fast_proxy_hook_trust_status(paths: ProxyPaths) -> dict[str, Any]:
    try:
        hooks_data = read_hooks(paths.hooks_path)
    except (ConfigError, json.JSONDecodeError):
        return {"installed": False, "feature_enabled": False, "trusted": False, "ready": False, "hooks": []}

    config = load_toml_config(paths.config_path)
    feature_enabled = hooks_feature_enabled(config)
    hooks_root = config.get("hooks", {})
    state_root = hooks_root.get("state", {}) if isinstance(hooks_root, dict) else {}
    if not isinstance(state_root, dict):
        state_root = {}

    hooks = []
    for state in fast_proxy_hook_states(paths, hooks_data):
        configured = state_root.get(state["key"], {})
        trusted_hash = configured.get("trusted_hash") if isinstance(configured, dict) else None
        enabled = configured.get("enabled") if isinstance(configured, dict) else None
        enabled = True if enabled is None else bool(enabled)
        trust_status = "trusted" if trusted_hash == state["trusted_hash"] else ("modified" if trusted_hash else "untrusted")
        hooks.append({
            **state,
            "enabled": enabled,
            "trust_status": trust_status,
            "trusted": enabled and trust_status == "trusted",
        })

    trusted = any(hook["trusted"] for hook in hooks)
    return {
        "installed": bool(hooks),
        "feature_enabled": feature_enabled,
        "trusted": trusted,
        "ready": feature_enabled and trusted,
        "hooks": hooks,
    }


def read_hooks(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"hooks": {}}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ConfigError(f"Invalid Codex hooks file: {path}")
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ConfigError(f"Invalid Codex hooks file: {path}")
    return data


def write_hooks(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def install_startup_hook(paths: ProxyPaths) -> dict[str, Any]:
    set_hooks_feature_flag(paths.config_path)
    data = read_hooks(paths.hooks_path)
    event_hooks = data["hooks"].setdefault(HOOK_EVENT, [])
    if not isinstance(event_hooks, list):
        raise ConfigError(f"Invalid {HOOK_EVENT} hooks in {paths.hooks_path}")

    handler = hook_handler(paths)
    found = False
    changed = False
    for group in event_hooks:
        if not isinstance(group, dict):
            continue
        hooks = group.get("hooks")
        if not isinstance(hooks, list):
            continue
        kept_hooks = []
        for hook in hooks:
            if not is_fast_proxy_hook(hook):
                kept_hooks.append(hook)
                continue
            if not found:
                kept_hooks.append(handler)
                found = True
                changed = changed or hook != handler
            else:
                changed = True
        if len(kept_hooks) != len(hooks):
            changed = True
        group["hooks"] = kept_hooks

    if found:
        if changed:
            write_hooks(paths.hooks_path, data)
            trust_states = trust_fast_proxy_hooks(paths, data)
            return {
                "status": "updated",
                "path": str(paths.hooks_path),
                "command": handler["command"],
                "trusted": bool(trust_states),
                "trust_states": trust_states,
            }
        trust_states = trust_fast_proxy_hooks(paths, data)
        return {
            "status": "already_installed",
            "path": str(paths.hooks_path),
            "command": handler["command"],
            "trusted": bool(trust_states),
            "trust_states": trust_states,
        }

    event_hooks.append({"matcher": HOOK_MATCHER, "hooks": [handler]})
    write_hooks(paths.hooks_path, data)
    trust_states = trust_fast_proxy_hooks(paths, data)
    return {
        "status": "installed",
        "path": str(paths.hooks_path),
        "command": handler["command"],
        "trusted": bool(trust_states),
        "trust_states": trust_states,
    }


def remove_startup_hook(paths: ProxyPaths) -> dict[str, Any]:
    if not paths.hooks_path.exists():
        return {"status": "missing", "path": str(paths.hooks_path)}

    data = read_hooks(paths.hooks_path)
    removed_state_keys = [state["key"] for state in fast_proxy_hook_states(paths, data)]
    event_hooks = data.get("hooks", {}).get(HOOK_EVENT, [])
    if not isinstance(event_hooks, list):
        raise ConfigError(f"Invalid {HOOK_EVENT} hooks in {paths.hooks_path}")

    removed = 0
    kept_groups = []
    for group in event_hooks:
        if not isinstance(group, dict):
            kept_groups.append(group)
            continue
        hooks = group.get("hooks")
        if not isinstance(hooks, list):
            kept_groups.append(group)
            continue
        kept_hooks = [hook for hook in hooks if not is_fast_proxy_hook(hook)]
        removed += len(hooks) - len(kept_hooks)
        if kept_hooks:
            kept_group = dict(group)
            kept_group["hooks"] = kept_hooks
            kept_groups.append(kept_group)

    hooks_root = data.setdefault("hooks", {})
    if kept_groups:
        hooks_root[HOOK_EVENT] = kept_groups
    else:
        hooks_root.pop(HOOK_EVENT, None)

    if not hooks_root:
        paths.hooks_path.unlink(missing_ok=True)
        return {
            "status": "removed_file",
            "path": str(paths.hooks_path),
            "removed": removed,
            "removed_state_keys": removed_state_keys,
        }

    write_hooks(paths.hooks_path, data)
    return {
        "status": "updated",
        "path": str(paths.hooks_path),
        "removed": removed,
        "removed_state_keys": removed_state_keys,
    }


def has_startup_hook(paths: ProxyPaths) -> bool:
    return bool(fast_proxy_hook_trust_status(paths)["ready"])


def current_process(paths: ProxyPaths) -> tuple[int | None, bool]:
    if not paths.pid_path.exists():
        return None, False
    try:
        pid = int(paths.pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None, False
    return pid, is_process_running(pid)


def is_process_running(pid: int) -> bool:
    if os.name == "nt":
        return windows_process_running(pid)

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def windows_process_running(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32
    process_query_limited_information = 0x1000
    still_active = 259
    process = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not process:
        return False

    exit_code = ctypes.c_ulong()
    try:
        if not kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(process)


def terminate_process(pid: int) -> None:
    if os.name != "nt":
        os.kill(pid, signal.SIGTERM)
        return

    kernel32 = ctypes.windll.kernel32
    process_terminate = 0x0001
    synchronize = 0x00100000
    process = kernel32.OpenProcess(process_terminate | synchronize, False, pid)
    if not process:
        return
    try:
        kernel32.TerminateProcess(process, 0)
        kernel32.WaitForSingleObject(process, 5000)
    finally:
        kernel32.CloseHandle(process)


def is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind((host, port))
        except OSError:
            return False
    return True


def proxy_health(settings: ProxySettings, timeout: float = 0.5) -> dict[str, Any] | None:
    connection = http.client.HTTPConnection(settings.host, settings.port, timeout=timeout)
    try:
        connection.request("GET", "/__codex_fast_proxy/health")
        response = connection.getresponse()
        if response.status != 200:
            return None
        return json.loads(response.read().decode("utf-8"))
    except (OSError, http.client.HTTPException, json.JSONDecodeError):
        return None
    finally:
        connection.close()


def health_matches_settings(
    health: dict[str, Any] | None,
    settings: ProxySettings,
    service_tier_effective_policy: str | None = None,
) -> bool:
    if not health:
        return False
    health_effective_policy = health.get(
        "service_tier_effective_policy",
        health.get("service_tier_policy", LEGACY_SERVICE_TIER_POLICY),
    )
    return (
        health.get("ok") is True
        and health.get("proxy_base") == settings.proxy_base
        and health.get("upstream_base") == settings.upstream_base
        and health.get("service_tier") == settings.service_tier
        and health.get("service_tier_policy", LEGACY_SERVICE_TIER_POLICY) == settings.service_tier_policy
        and (service_tier_effective_policy is None or health_effective_policy == service_tier_effective_policy)
        and health.get("upstream_api_key_env") == settings.upstream_api_key_env
        and bool(health.get("upstream_api_key_file")) == settings.upstream_api_key_file
    )


def health_matches_runtime(health: dict[str, Any] | None) -> bool:
    return bool(health and health.get("runtime_id") == RUNTIME_ID)


def health_matches_proxy_identity(health: dict[str, Any] | None, settings: ProxySettings, pid: int | None) -> bool:
    return bool(
        health
        and health.get("ok") is True
        and health.get("pid") == pid
        and health.get("proxy_base") == settings.proxy_base
    )


def settings_restart_pending(
    health: dict[str, Any] | None,
    settings: ProxySettings | None,
    pid: int | None,
    service_tier_effective_policy: str | None = None,
) -> bool:
    return bool(
        settings
        and health_matches_proxy_identity(health, settings, pid)
        and not health_matches_settings(health, settings, service_tier_effective_policy)
    )


def proxy_runtime_state(paths: ProxyPaths, settings: ProxySettings | None) -> tuple[int | None, bool, dict[str, Any] | None, bool, bool, bool | None]:
    pid, process_running = current_process(paths)
    health = proxy_health(settings) if settings else None
    health_pid = health.get("pid") if isinstance(health, dict) else None
    if isinstance(health_pid, int):
        pid = health_pid

    login = detect_login_mode(paths.codex_home) if settings else None
    effective_policy = effective_service_tier_policy(settings, login) if settings and login else None
    healthy = health_matches_settings(health, settings, effective_policy) if settings else False
    running = process_running or bool(healthy)
    pending_restart = settings_restart_pending(health, settings, pid, effective_policy) if settings and running else False
    runtime_matches = health_matches_runtime(health) if healthy or pending_restart else None
    return pid, running, health, healthy, pending_restart, runtime_matches


def wait_for_proxy_health(
    settings: ProxySettings,
    process: subprocess.Popen[Any],
    timeout: float = 5.0,
    service_tier_effective_policy: str | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_health = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        last_health = proxy_health(settings)
        if health_matches_settings(last_health, settings, service_tier_effective_policy):
            return last_health
        time.sleep(0.1)

    if process.poll() is not None:
        raise ConfigError("codex-fast-proxy exited before becoming healthy.")
    raise ConfigError(f"codex-fast-proxy health check failed or mismatched settings: {last_health}")


def child_environment(paths: ProxyPaths, settings: ProxySettings) -> dict[str, str]:
    environment = os.environ.copy()
    if settings.upstream_api_key_env and not environment.get(settings.upstream_api_key_env):
        auth_value = read_secret_from_auth(paths.codex_home, settings.upstream_api_key_env)
        if auth_value:
            environment[settings.upstream_api_key_env] = auth_value
    if settings.upstream_api_key_file:
        auth_value = provider_auth_secret(paths, settings.provider)
        if not auth_value:
            raise ConfigError(f"Provider auth file does not contain an API key for provider {settings.provider!r}.")
        environment[INTERNAL_UPSTREAM_API_KEY_ENV] = auth_value
    package_parent = Path(__file__).resolve().parents[1]
    if package_parent.name == "src":
        existing = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(package_parent) if not existing else f"{package_parent}{os.pathsep}{existing}"
    return environment


def stop_process(paths: ProxyPaths, force: bool = False) -> dict[str, Any]:
    pid, running = current_process(paths)
    if not running:
        paths.pid_path.unlink(missing_ok=True)
        return {"status": "not_running", "pid": pid}

    if not force:
        settings_data = read_json(paths.settings_path)
        if not settings_data:
            raise ConfigError(f"Refusing to stop process {pid} without proxy settings. Use --force if needed.")
        settings = settings_from_dict(settings_data)
        health = proxy_health(settings)
        matches_settings = bool(health and health_matches_settings(health, settings) and health.get("pid") == pid)
        matches_identity = health_matches_proxy_identity(health, settings, pid)
        if not (matches_settings or matches_identity):
            raise ConfigError(f"Refusing to stop process {pid} because health check does not match the pid file.")

    terminate_process(pid)
    for _attempt in range(30):
        time.sleep(0.1)
        if not is_process_running(pid):
            break
    if is_process_running(pid) and hasattr(signal, "SIGKILL"):
        os.kill(pid, signal.SIGKILL)

    paths.pid_path.unlink(missing_ok=True)
    return {"status": "stopped", "pid": pid}


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
        shutil.copy2(paths.config_path, backup_path)
        set_provider_base_url(backup_path, provider, settings.upstream_base)
        remove_hook_feature_flags(backup_path)
    else:
        backup_path.write_text("", encoding="utf-8")
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
        shutil.copy2(paths.config_path, backup_path)
    else:
        backup_path.write_text("", encoding="utf-8")
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


def command_install(args: argparse.Namespace) -> int:
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
    settings = ProxySettings(
        provider=provider,
        host=args.host,
        port=args.port,
        proxy_base=normalized_base_path(args.proxy_base),
        upstream_base="",
        service_tier=args.service_tier,
        service_tier_policy=service_tier_policy,
        upstream_api_key_env=upstream_api_key_env,
        upstream_api_key_file=upstream_api_key_file,
    )
    upstream_base = validate_upstream_base(resolve_upstream_base(config, paths, provider, args.upstream_base, settings.base_url))
    settings = ProxySettings(
        provider=provider,
        host=settings.host,
        port=settings.port,
        proxy_base=settings.proxy_base,
        upstream_base=upstream_base,
        service_tier=settings.service_tier,
        service_tier_policy=settings.service_tier_policy,
        upstream_api_key_env=settings.upstream_api_key_env,
        upstream_api_key_file=settings.upstream_api_key_file,
    )

    paths.app_home.mkdir(parents=True, exist_ok=True)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.backup_dir.mkdir(parents=True, exist_ok=True)
    require_upstream_auth_available(paths, settings)

    if args.prepare_only and args.start:
        raise ConfigError("Use either --prepare-only or --start, not both.")

    if args.prepare_only:
        write_settings(paths, settings)
        print(json_line({
            "status": "prepared",
            "provider": provider,
            "base_url": settings.base_url,
            "upstream_base": settings.upstream_base,
            "config_switched": False,
            "next_action": "run install --start to enable the proxy",
        }))
        return 0

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
    start_result = None
    hook_result = None
    try:
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
        if restore_previous_proxy and existing_settings:
            try:
                start_background(paths, existing_settings, args.verbose_proxy)
            except Exception:
                pass
        raise

    login = detect_login_mode(paths.codex_home)
    auth = upstream_auth_status(paths, settings)
    print(json_line({
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
        "startup_hook": hook_result,
        "verification": verification,
        "switch_order": "proxy_started_before_config_switch",
        "current_session_effect": ENABLE_SESSION_EFFECT,
        "start_result": start_result,
    }))
    return 0


def command_set_upstream(args: argparse.Namespace) -> int:
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
    config_base_url = provider_base_url(config, old_settings.provider)
    if config_base_url != old_settings.base_url:
        raise ConfigError(
            f"Refusing to update upstream because provider {old_settings.provider!r} no longer points to the local proxy. "
            "Review config.toml, then run install --start if you want to enable the proxy again."
        )
    require_upstream_auth_available(paths, new_settings)
    verify_arg_present = hasattr(args, "verify")
    verify_requested = bool(getattr(args, "verify", False))
    verify_timeout = float(getattr(args, "verify_timeout", 60.0))
    verification = {"status": "skipped", "reason": "--no-verify" if verify_arg_present else "not_requested"}
    if verify_requested:
        verification = verify_upstream_responses(paths, config, new_settings, verify_timeout)

    paths.backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = choose_config_backup(paths, old_settings.provider, new_settings, config)
    config_hash_before = sha256_file(backup_path)
    config_bytes_before = paths.config_path.read_bytes() if paths.config_path.exists() else None
    hooks_bytes_before = paths.hooks_path.read_bytes() if paths.hooks_path.exists() else None
    settings_bytes_before = paths.settings_path.read_bytes() if paths.settings_path.exists() else None
    restart_required = False
    start_result = None
    hook_result = None

    try:
        _pid, running, health, healthy, pending_restart, runtime_matches = proxy_runtime_state(paths, new_settings)

        write_settings(paths, new_settings)
        if running and not args.restart:
            restart_required = bool(pending_restart or not healthy or runtime_matches is False or auth_source_requested)
            start_result = already_running_result(paths, new_settings, _pid, health, runtime_matches=runtime_matches is not False)
            if restart_required:
                start_result = {
                    **start_result,
                    "status": "deferred",
                    "reason": "running_proxy_left_untouched",
                    "next_action": "restart Codex App, open a new CLI process, or run start to apply the new upstream",
                }
        else:
            start_result = start_background(paths, new_settings, args.verbose_proxy)
        set_provider_base_url(paths.config_path, new_settings.provider, new_settings.base_url)
        hook_result = install_startup_hook(paths)
        config_hash_after = sha256_file(paths.config_path)
        write_install_manifest(
            paths,
            new_settings.provider,
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
    print(json_line({
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
    }))
    return 0


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


def already_running_result(
    paths: ProxyPaths,
    settings: ProxySettings,
    pid: int,
    health: dict[str, Any],
    *,
    runtime_matches: bool = True,
) -> dict[str, Any]:
    return {
        "status": "already_running",
        "pid": pid,
        "healthy": True,
        "runtime_id": health.get("runtime_id"),
        "runtime_matches": runtime_matches,
        "needs_restart": not runtime_matches,
        "base_url": settings.base_url,
        "upstream_base": settings.upstream_base,
        "log": str(paths.log_path),
    }


def restart_background(
    paths: ProxyPaths,
    settings: ProxySettings,
    verbose_proxy: bool,
    pid: int,
    health: dict[str, Any],
    *,
    reason: str = "runtime_changed",
    force_stop: bool = False,
) -> dict[str, Any]:
    stop_result = stop_process(paths, force=force_stop)
    try:
        start_result = launch_background(paths, settings, verbose_proxy)
    except Exception as exc:
        previous_settings = ProxySettings(
            provider=settings.provider,
            host=settings.host,
            port=settings.port,
            proxy_base=str(health.get("proxy_base") or settings.proxy_base),
            upstream_base=str(health.get("upstream_base") or settings.upstream_base),
            service_tier=str(health.get("service_tier") or settings.service_tier),
            service_tier_policy=str(health.get("service_tier_policy") or LEGACY_SERVICE_TIER_POLICY),
            upstream_api_key_env=health.get("upstream_api_key_env") if isinstance(health.get("upstream_api_key_env"), str) else None,
            upstream_api_key_file=bool(health.get("upstream_api_key_file")),
        )
        try:
            launch_background(paths, previous_settings, verbose_proxy)
        except Exception as restore_exc:
            raise ConfigError(
                f"codex-fast-proxy restart failed and restoring the previous proxy also failed: {exc}; restore_error={restore_exc}"
            ) from exc
        raise ConfigError(f"codex-fast-proxy restart failed; restored the previous proxy: {exc}") from exc
    return {
        "status": "restarted",
        "reason": reason,
        "old_pid": pid,
        "old_runtime_id": health.get("runtime_id"),
        "runtime_id": RUNTIME_ID,
        "base_url": settings.base_url,
        "upstream_base": settings.upstream_base,
        "stop_result": stop_result,
        "start_result": start_result,
    }


def start_background(
    paths: ProxyPaths,
    settings: ProxySettings,
    verbose_proxy: bool,
    *,
    restart_stale_runtime: bool = True,
) -> dict[str, Any]:
    paths.state_dir.mkdir(parents=True, exist_ok=True)

    pid, running, health, healthy, _pending_restart, runtime_matches = proxy_runtime_state(paths, settings)
    if running:
        if healthy:
            if runtime_matches:
                return already_running_result(paths, settings, pid, health)
            if not restart_stale_runtime:
                return already_running_result(paths, settings, pid, health, runtime_matches=False)
            return restart_background(paths, settings, verbose_proxy, pid, health)
        if health_matches_proxy_identity(health, settings, pid):
            return restart_background(
                paths,
                settings,
                verbose_proxy,
                pid,
                health,
                reason="settings_changed",
                force_stop=True,
            )
        raise ConfigError(f"Existing proxy process {pid} is running with different or unhealthy settings. Stop it first.")
    paths.pid_path.unlink(missing_ok=True)

    return launch_background(paths, settings, verbose_proxy)


def launch_background(paths: ProxyPaths, settings: ProxySettings, verbose_proxy: bool) -> dict[str, Any]:
    paths.state_dir.mkdir(parents=True, exist_ok=True)

    if not is_port_available(settings.host, settings.port):
        raise ConfigError(f"Port {settings.port} is already in use on {settings.host}.")

    login = detect_login_mode(paths.codex_home)
    effective_policy = effective_service_tier_policy(settings, login)
    command = [
        sys.executable,
        "-m",
        "codex_fast_proxy",
        "serve",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
        "--proxy-base",
        settings.proxy_base,
        "--upstream-base",
        settings.upstream_base,
        "--service-tier",
        settings.service_tier,
        "--service-tier-policy",
        settings.service_tier_policy,
        "--service-tier-effective-policy",
        effective_policy,
        "--log-dir",
        str(paths.state_dir),
    ]
    if settings.upstream_api_key_env:
        command.extend(["--upstream-api-key-env", settings.upstream_api_key_env])
    elif settings.upstream_api_key_file:
        command.extend([
            "--upstream-api-key-env",
            INTERNAL_UPSTREAM_API_KEY_ENV,
            "--upstream-api-key-source",
            "provider_auth_file",
        ])
    if verbose_proxy:
        command.append("--verbose")

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with paths.stdout_path.open("ab") as stdout, paths.stderr_path.open("ab") as stderr:
        process = subprocess.Popen(
            command,
            cwd=str(Path.cwd()),
            env=child_environment(paths, settings),
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            creationflags=creation_flags,
            start_new_session=(os.name != "nt"),
        )

    try:
        health = wait_for_proxy_health(settings, process, service_tier_effective_policy=effective_policy)
    except ConfigError:
        error_text = paths.stderr_path.read_text(encoding="utf-8", errors="replace") if paths.stderr_path.exists() else ""
        detail = f" {error_text.strip()}" if error_text.strip() else ""
        terminate_process(process.pid)
        raise ConfigError(f"codex-fast-proxy did not become healthy.{detail}")

    return {
        "status": "started",
        "pid": process.pid,
        "healthy": True,
        "base_url": settings.base_url,
        "upstream_base": settings.upstream_base,
        "health": health,
        "log": str(paths.log_path),
        "stdout": str(paths.stdout_path),
        "stderr": str(paths.stderr_path),
    }


def append_autostart_event(paths: ProxyPaths, event: dict[str, Any]) -> None:
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    event_path = paths.state_dir / "fast_proxy.autostart.jsonl"
    with event_path.open("a", encoding="utf-8") as log_file:
        log_file.write(compact_json({"ts": time.time(), **event}) + "\n")


def should_log_autostart_event(event: dict[str, Any], quiet: bool) -> bool:
    if not quiet:
        return True
    return event.get("status") not in {"already_running", "skipped"}


def autostart_proxy(paths: ProxyPaths, verbose_proxy: bool) -> dict[str, Any]:
    settings_data = read_json(paths.settings_path)
    if not settings_data:
        return {"status": "skipped", "reason": "settings_missing"}

    settings = settings_from_dict(settings_data)
    config = load_toml_config(paths.config_path)
    config_base_url = provider_base_url(config, settings.provider)
    if config_base_url != settings.base_url:
        return {"status": "skipped", "reason": "config_not_proxy", "provider": settings.provider}

    return start_background(paths, settings, verbose_proxy, restart_stale_runtime=False)


def command_autostart(args: argparse.Namespace) -> int:
    paths = paths_for(args.codex_home)
    try:
        result = autostart_proxy(paths, args.verbose_proxy)
    except Exception as exc:
        result = {"status": "error", "error": str(exc)}

    if should_log_autostart_event(result, args.quiet):
        append_autostart_event(paths, result)
    if not args.quiet:
        print(json_line(result))
    return 0


def command_stop(args: argparse.Namespace) -> int:
    paths = paths_for(args.codex_home)
    settings_data = read_json(paths.settings_path)
    settings = settings_from_dict(settings_data) if settings_data else None
    if settings and not args.force:
        config = load_toml_config(paths.config_path)
        config_base_url = provider_base_url(config, settings.provider)
        if config_base_url == settings.base_url:
            raise ConfigError(
                "Refusing to stop while Codex config still points to the proxy. "
                "Use uninstall --defer-stop to disable safely, or stop --force if you understand the risk."
            )

    print(json_line(stop_process(paths, args.force)))
    return 0


def command_status(args: argparse.Namespace) -> int:
    from .state import collect_status

    print(json_line(collect_status(args.codex_home, args.provider)))
    return 0


def command_ui(args: argparse.Namespace) -> int:
    from .control_ui import open_control_ui, serve_control_ui

    if args.foreground:
        return serve_control_ui(args.codex_home, args.provider, args.host, args.port)
    print(json_line(open_control_ui(
        args.codex_home,
        args.provider,
        args.host,
        args.port,
        args.open_browser and not args.no_open,
    )))
    return 0


def doctor_report(paths: ProxyPaths, provider: str | None) -> dict[str, Any]:
    config = load_toml_config(paths.config_path)
    selected_provider = provider or active_provider_name(config)
    upstream_base = provider_base_url(config, selected_provider) if selected_provider else None
    settings_data = read_json(paths.settings_path)
    settings = settings_from_dict(settings_data) if settings_data else None
    pid, running, health, healthy, pending_restart, runtime_matches = proxy_runtime_state(paths, settings)
    hooks_enabled = hooks_feature_enabled(config)
    hook_status = fast_proxy_hook_trust_status(paths)
    login = detect_login_mode(paths.codex_home)
    auth = upstream_auth_status(paths, settings)
    effective_policy = effective_service_tier_policy(settings, login) if settings else None

    checks = [
        {"name": "python", "ok": sys.version_info >= (3, 11), "detail": sys.version.split()[0]},
        {"name": "codex_config", "ok": paths.config_path.exists(), "detail": str(paths.config_path)},
        {"name": "active_provider", "ok": bool(selected_provider), "detail": selected_provider},
        {"name": "provider_base_url", "ok": bool(upstream_base), "detail": upstream_base},
        {"name": "runtime_source", "ok": True, "detail": runtime_status(paths, health)},
        {"name": "login_mode", "ok": True, "detail": login.login_mode},
    ]
    if settings_data:
        checks.extend([
            {"name": "proxy_settings", "ok": True, "detail": str(paths.settings_path)},
            {"name": "config_points_to_proxy", "ok": upstream_base == settings.base_url, "detail": upstream_base},
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
            {"name": "proxy_pending_restart", "ok": True, "detail": pending_restart},
            {"name": "proxy_runtime", "ok": not healthy or runtime_matches, "detail": health.get("runtime_id") if health else None},
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
    return {
        "ok": all(check["ok"] for check in required_checks),
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
    if args.pairs < 1:
        raise ConfigError("--pairs must be at least 1.")
    if args.pairs > 20:
        raise ConfigError("--pairs must be 20 or less.")
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
    result = run_benchmark(target, args.pairs, args.timeout, mode=args.mode)
    if args.save:
        save_benchmark_result(paths.benchmark_path, result)
        result["saved_to"] = str(paths.benchmark_path)
    print(json_line(result))
    return 0


def command_check_update(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve() if args.repo else None
    print(json_line(check_update(repo, args.branch, args.remote)))
    return 0


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


def command_uninstall(args: argparse.Namespace) -> int:
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
        print(json_line({
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
        }))
        return 4
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
        current_hash = sha256_file(config_path)
        if current_hash == manifest.get("config_hash_before"):
            restore_status = "already_restored"
            can_stop = True
        elif current_hash == manifest.get("config_hash_after"):
            shutil.copy2(backup_path, config_path)
            restore_status = "restored"
            can_stop = True
        else:
            settings = manifest_settings
            config = load_toml_config(config_path)
            config_base_url = provider_base_url(config, settings.provider)
            if config_base_url == settings.base_url:
                set_provider_base_url(config_path, settings.provider, settings.upstream_base)
                restore_hook_feature_flag(config_path, backup_path, hook_result)
                restore_status = "restored_base_url"
                can_stop = True
            elif config_base_url == settings.upstream_base:
                restore_hook_feature_flag(config_path, backup_path, hook_result)
                restore_status = "already_restored_base_url"
                can_stop = True
            elif args.force:
                shutil.copy2(backup_path, config_path)
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
    print(json_line(result))
    return 3 if restore_status == "skipped_config_changed" else 0


def add_shared_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codex-home", default=str(Path.home() / ".codex"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex Fast proxy for OpenAI-compatible Responses API providers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the foreground proxy server.")
    serve.add_argument("--host", default=DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
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
    install.add_argument("--port", type=int, default=DEFAULT_PORT)
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

    autostart = subparsers.add_parser("autostart", help="Start proxy from a Codex SessionStart hook if enabled.")
    add_shared_options(autostart)
    autostart.add_argument("--quiet", action="store_true")
    autostart.add_argument("--verbose-proxy", action="store_true")

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
    ui.add_argument("--open-browser", action="store_true")
    ui.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)

    doctor = subparsers.add_parser("doctor", help="Check Codex config and proxy environment.")
    add_shared_options(doctor)
    doctor.add_argument("--provider")

    benchmark = subparsers.add_parser("benchmark", help="Run an opt-in default vs priority latency benchmark.")
    add_shared_options(benchmark)
    benchmark.add_argument("--pairs", type=int, default=3)
    benchmark.add_argument("--timeout", type=float, default=600.0)
    benchmark.add_argument("--model")
    benchmark.add_argument("--reasoning-effort")
    benchmark.add_argument("--profile", default="full")
    benchmark.add_argument("--mode", choices=("codex-cli", "direct"), default="codex-cli")
    benchmark.add_argument("--api-key-env")
    benchmark.add_argument("--save", action=argparse.BooleanOptionalAction, default=True)

    check_update_parser = subparsers.add_parser("check-update", help="Read-only check for newer GitHub commits.")
    check_update_parser.add_argument("--repo")
    check_update_parser.add_argument("--remote", default="origin")
    check_update_parser.add_argument("--branch")

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
        "stop": command_stop,
        "status": command_status,
        "ui": command_ui,
        "doctor": command_doctor,
        "benchmark": command_benchmark,
        "check-update": command_check_update,
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
