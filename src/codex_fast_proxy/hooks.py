from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import (
    config_feature_enabled,
    config_feature_value,
    find_table,
    hook_state_table_name,
    is_toml_key,
    load_toml_config,
    next_table_index,
    read_toml_lines,
    remove_feature_flag,
    set_feature_flag,
    toml_string,
    write_toml_lines,
)
from .core import ConfigError
from .storage import write_json


HOOK_EVENT = "SessionStart"
HOOK_EVENT_LABEL = "session_start"
HOOK_MATCHER = "startup|resume"
HOOK_TIMEOUT_SECONDS = 20
HOOK_FEATURE_KEY = "hooks"
LEGACY_HOOK_FEATURE_KEY = "codex_hooks"
HOOK_FEATURE_KEYS = (HOOK_FEATURE_KEY, LEGACY_HOOK_FEATURE_KEY)


def hooks_feature_enabled(config: dict[str, Any]) -> bool:
    return any(config_feature_enabled(config, key) for key in HOOK_FEATURE_KEYS)


def set_hooks_feature_flag(config_path: Path) -> None:
    set_feature_flag(config_path, HOOK_FEATURE_KEY, True)
    remove_feature_flag(config_path, LEGACY_HOOK_FEATURE_KEY)


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


def command_for_hook(paths: Any) -> str:
    args = [
        sys.executable,
        "-m",
        "codex_fast_proxy",
        "autostart",
        "--codex-home",
        str(paths.codex_home),
        "--quiet",
        "--hook-summary",
    ]
    if os.name == "nt":
        return subprocess.list2cmdline(args)
    return shlex.join(args)


def hook_handler(paths: Any) -> dict[str, Any]:
    return {
        "type": "command",
        "command": command_for_hook(paths),
        "timeout": HOOK_TIMEOUT_SECONDS,
        "statusMessage": "Checking Codex Model Gateway",
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


def fast_proxy_hook_states(paths: Any, hooks_data: dict[str, Any]) -> list[dict[str, str]]:
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


def trust_fast_proxy_hooks(paths: Any, hooks_data: dict[str, Any]) -> list[dict[str, str]]:
    states = fast_proxy_hook_states(paths, hooks_data)
    for state in states:
        set_hook_state(paths.config_path, state["key"], state["trusted_hash"])
    return states


def remove_fast_proxy_hook_states(paths: Any, hooks_data: dict[str, Any]) -> list[str]:
    keys = [state["key"] for state in fast_proxy_hook_states(paths, hooks_data)]
    remove_hook_states_by_keys(paths.config_path, keys)
    return keys


def remove_hook_states_by_keys(config_path: Path, keys: list[str]) -> None:
    for key in keys:
        remove_hook_state(config_path, key)


def fast_proxy_hook_trust_status(paths: Any) -> dict[str, Any]:
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
    write_json(path, value)


def install_startup_hook(paths: Any) -> dict[str, Any]:
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


def remove_startup_hook(paths: Any) -> dict[str, Any]:
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


def has_startup_hook(paths: Any) -> bool:
    return bool(fast_proxy_hook_trust_status(paths)["ready"])
