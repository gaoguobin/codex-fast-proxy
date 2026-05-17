from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .core import ConfigError

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None  # type: ignore[assignment]

TOML_DECODE_ERROR = tomllib.TOMLDecodeError if tomllib else ValueError


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
