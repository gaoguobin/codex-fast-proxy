from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .auth import read_auth_json, read_secret_from_auth, resolve_env
from .auth_store import provider_auth_secret, upstream_api_key_source, write_provider_auth_secret
from .config import choose_provider, load_toml_config, provider_config_for
from .core import ConfigError, validate_env_name
from .models import ProxyPaths, paths_for


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
