from __future__ import annotations

import argparse
from typing import Any

from .auth import detect_login_mode, read_secret_from_auth, resolve_env
from .auth_store import provider_auth_secret, upstream_api_key_source
from .config import choose_provider, provider_base_url, provider_config_for
from .core import ConfigError, is_success_status, redact_sensitive_text, validate_env_name, validate_upstream_base
from .defaults import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_PROXY_BASE, DEFAULT_SERVICE_TIER, DEFAULT_SERVICE_TIER_POLICY
from .models import ProxyPaths, ProxySettings, settings_from_dict
from .status_rules import SERVICE_TIER_POLICIES, effective_service_tier_policy
from .storage import read_json


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
