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

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None  # type: ignore[assignment]

TOML_DECODE_ERROR = tomllib.TOMLDecodeError if tomllib else ValueError

from . import __version__
from .proxy import RUNTIME_ID, compact_json


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_PROXY_BASE = "/v1"
DEFAULT_SERVICE_TIER = "priority"
HOOK_EVENT = "SessionStart"
HOOK_MATCHER = "startup|resume"
HOOK_TIMEOUT_SECONDS = 10
ENABLE_SESSION_EFFECT = (
    "Running Codex processes keep their current base_url. Restart Codex App, then resume the same conversation if desired, "
    "or open a new CLI process to use the proxy."
)
DEFER_STOP_SESSION_EFFECT = (
    "Codex config was restored, but the proxy was left running so a proxy-backed current process can finish. "
    "Restart Codex App, then resume the same conversation if desired, or open a new CLI process; then run uninstall again "
    "to stop the proxy and remove files."
)


@dataclass(frozen=True)
class ProxyPaths:
    codex_home: Path
    app_home: Path
    state_dir: Path
    config_path: Path
    hooks_path: Path
    settings_path: Path
    manifest_path: Path
    pid_path: Path
    log_path: Path
    stdout_path: Path
    stderr_path: Path
    backup_dir: Path


@dataclass(frozen=True)
class ProxySettings:
    provider: str
    host: str
    port: int
    proxy_base: str
    upstream_base: str
    service_tier: str

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


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_line(value) + "\n", encoding="utf-8")


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
        manifest_path=app_home / "install-manifest.json",
        pid_path=state_dir / "fast_proxy.pid",
        log_path=state_dir / "fast_proxy.jsonl",
        stdout_path=state_dir / "fast_proxy.stdout.log",
        stderr_path=state_dir / "fast_proxy.stderr.log",
        backup_dir=resolved_home / "backups" / "codex-fast-proxy",
    )


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
    provider_config = configured_providers(config).get(provider, {})
    if not isinstance(provider_config, dict):
        return None
    value = provider_config.get("base_url")
    return value if isinstance(value, str) and value else None


def settings_from_dict(value: dict[str, Any]) -> ProxySettings:
    return ProxySettings(
        provider=str(value["provider"]),
        host=str(value["host"]),
        port=int(value["port"]),
        proxy_base=normalized_base_path(str(value["proxy_base"])),
        upstream_base=str(value["upstream_base"]),
        service_tier=str(value["service_tier"]),
    )


def read_settings(paths: ProxyPaths) -> ProxySettings:
    settings = read_json(paths.settings_path)
    if not settings:
        raise ConfigError(f"Settings not found: {paths.settings_path}")
    return settings_from_dict(settings)


def write_settings(paths: ProxyPaths, settings: ProxySettings) -> None:
    write_json(paths.settings_path, {**asdict(settings), "base_url": settings.base_url})


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
            write_toml_lines(config_path, lines, newline)
            return


def config_feature_enabled(config: dict[str, Any], key: str) -> bool:
    features = config.get("features", {})
    return isinstance(features, dict) and features.get(key) is True


def restore_hook_feature_flag(config_path: Path, backup_path: str | None, hook_result: dict[str, Any]) -> None:
    if hook_result.get("status") not in {"removed_file", "missing"}:
        return

    backup_config = load_toml_config(Path(backup_path)) if backup_path else {}
    if config_feature_enabled(backup_config, "codex_hooks"):
        set_feature_flag(config_path, "codex_hooks", True)
    else:
        remove_feature_flag(config_path, "codex_hooks")


def command_for_hook(paths: ProxyPaths) -> str:
    args = [
        "python",
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
            return {"status": "updated", "path": str(paths.hooks_path), "command": handler["command"]}
        return {"status": "already_installed", "path": str(paths.hooks_path), "command": handler["command"]}

    event_hooks.append({"matcher": HOOK_MATCHER, "hooks": [handler]})
    write_hooks(paths.hooks_path, data)
    return {"status": "installed", "path": str(paths.hooks_path), "command": handler["command"]}


def remove_startup_hook(paths: ProxyPaths) -> dict[str, Any]:
    if not paths.hooks_path.exists():
        return {"status": "missing", "path": str(paths.hooks_path)}

    data = read_hooks(paths.hooks_path)
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
        return {"status": "removed_file", "path": str(paths.hooks_path), "removed": removed}

    write_hooks(paths.hooks_path, data)
    return {"status": "updated", "path": str(paths.hooks_path), "removed": removed}


def has_startup_hook(paths: ProxyPaths) -> bool:
    if not paths.hooks_path.exists():
        return False
    try:
        data = read_hooks(paths.hooks_path)
    except (ConfigError, json.JSONDecodeError):
        return False
    event_hooks = data.get("hooks", {}).get(HOOK_EVENT, [])
    if not isinstance(event_hooks, list):
        return False
    for group in event_hooks:
        if isinstance(group, dict) and isinstance(group.get("hooks"), list):
            if any(is_fast_proxy_hook(hook) for hook in group["hooks"]):
                return True
    return False


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


def health_matches_settings(health: dict[str, Any] | None, settings: ProxySettings) -> bool:
    if not health:
        return False
    return (
        health.get("ok") is True
        and health.get("proxy_base") == settings.proxy_base
        and health.get("upstream_base") == settings.upstream_base
        and health.get("service_tier") == settings.service_tier
    )


def health_matches_runtime(health: dict[str, Any] | None) -> bool:
    return bool(health and health.get("runtime_id") == RUNTIME_ID)


def wait_for_proxy_health(settings: ProxySettings, process: subprocess.Popen[Any], timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_health = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        last_health = proxy_health(settings)
        if health_matches_settings(last_health, settings):
            return last_health
        time.sleep(0.1)

    if process.poll() is not None:
        raise ConfigError("codex-fast-proxy exited before becoming healthy.")
    raise ConfigError(f"codex-fast-proxy health check failed or mismatched settings: {last_health}")


def child_environment() -> dict[str, str]:
    environment = os.environ.copy()
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
        if not health_matches_settings(health, settings) or health.get("pid") != pid:
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
        remove_feature_flag(backup_path, "codex_hooks")
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


def command_install(args: argparse.Namespace) -> int:
    paths = paths_for(args.codex_home)
    config = load_toml_config(paths.config_path)
    active_provider = active_provider_name(config)
    provider = choose_provider(config, args.provider)
    settings = ProxySettings(
        provider=provider,
        host=args.host,
        port=args.port,
        proxy_base=normalized_base_path(args.proxy_base),
        upstream_base="",
        service_tier=args.service_tier,
    )
    upstream_base = resolve_upstream_base(config, paths, provider, args.upstream_base, settings.base_url)
    settings = ProxySettings(
        provider=provider,
        host=settings.host,
        port=settings.port,
        proxy_base=settings.proxy_base,
        upstream_base=upstream_base,
        service_tier=settings.service_tier,
    )

    paths.app_home.mkdir(parents=True, exist_ok=True)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.backup_dir.mkdir(parents=True, exist_ok=True)

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

    backup_path = choose_config_backup(paths, provider, settings, config)
    config_hash_before = sha256_file(backup_path)
    config_bytes_before = paths.config_path.read_bytes() if paths.config_path.exists() else None
    hooks_bytes_before = paths.hooks_path.read_bytes() if paths.hooks_path.exists() else None
    start_result = None
    hook_result = None
    try:
        write_settings(paths, settings)
        start_result = start_background(paths, settings, args.verbose_proxy)

        set_provider_base_url(paths.config_path, provider, settings.base_url)
        if args.activate_provider or active_provider is None:
            set_active_provider(paths.config_path, provider)
        set_feature_flag(paths.config_path, "codex_hooks", True)
        hook_result = install_startup_hook(paths)
        config_hash_after = sha256_file(paths.config_path)

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
    except Exception:
        if start_result and start_result.get("status") == "started":
            stop_process(paths)
        if hooks_bytes_before is None:
            paths.hooks_path.unlink(missing_ok=True)
        else:
            paths.hooks_path.write_bytes(hooks_bytes_before)
        if config_bytes_before is None:
            paths.config_path.unlink(missing_ok=True)
        else:
            paths.config_path.write_bytes(config_bytes_before)
        raise

    print(json_line({
        "status": "installed",
        "provider": provider,
        "base_url": settings.base_url,
        "upstream_base": settings.upstream_base,
        "backup_path": str(backup_path),
        "started": True,
        "config_switched": True,
        "startup_hook": hook_result,
        "switch_order": "proxy_started_before_config_switch",
        "current_session_effect": ENABLE_SESSION_EFFECT,
        "start_result": start_result,
    }))
    return 0


def command_start(args: argparse.Namespace) -> int:
    paths = paths_for(args.codex_home)
    settings = read_settings(paths)
    print(json_line(start_background(paths, settings, args.verbose_proxy)))
    return 0


def already_running_result(paths: ProxyPaths, settings: ProxySettings, pid: int, health: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "already_running",
        "pid": pid,
        "healthy": True,
        "runtime_id": health.get("runtime_id"),
        "runtime_matches": True,
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
) -> dict[str, Any]:
    stop_result = stop_process(paths)
    start_result = launch_background(paths, settings, verbose_proxy)
    return {
        "status": "restarted",
        "reason": "runtime_changed",
        "old_pid": pid,
        "old_runtime_id": health.get("runtime_id"),
        "runtime_id": RUNTIME_ID,
        "base_url": settings.base_url,
        "upstream_base": settings.upstream_base,
        "stop_result": stop_result,
        "start_result": start_result,
    }


def start_background(paths: ProxyPaths, settings: ProxySettings, verbose_proxy: bool) -> dict[str, Any]:
    paths.state_dir.mkdir(parents=True, exist_ok=True)

    pid, running = current_process(paths)
    if running:
        health = proxy_health(settings)
        if health_matches_settings(health, settings):
            if health_matches_runtime(health):
                return already_running_result(paths, settings, pid, health)
            return restart_background(paths, settings, verbose_proxy, pid, health)
        raise ConfigError(f"Existing proxy process {pid} is running with different or unhealthy settings. Stop it first.")
    paths.pid_path.unlink(missing_ok=True)

    return launch_background(paths, settings, verbose_proxy)


def launch_background(paths: ProxyPaths, settings: ProxySettings, verbose_proxy: bool) -> dict[str, Any]:
    paths.state_dir.mkdir(parents=True, exist_ok=True)

    if not is_port_available(settings.host, settings.port):
        raise ConfigError(f"Port {settings.port} is already in use on {settings.host}.")

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
        "--log-dir",
        str(paths.state_dir),
    ]
    if verbose_proxy:
        command.append("--verbose")

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with paths.stdout_path.open("ab") as stdout, paths.stderr_path.open("ab") as stderr:
        process = subprocess.Popen(
            command,
            cwd=str(Path.cwd()),
            env=child_environment(),
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

    try:
        health = wait_for_proxy_health(settings, process)
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

    pid, running = current_process(paths)
    if running:
        health = proxy_health(settings)
        if health_matches_settings(health, settings):
            if health_matches_runtime(health):
                return already_running_result(paths, settings, pid, health)
            return restart_background(paths, settings, verbose_proxy, pid, health)
        return {"status": "error", "reason": "running_unhealthy_or_mismatched", "pid": pid}

    return start_background(paths, settings, verbose_proxy)


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
    paths = paths_for(args.codex_home)
    settings_data = read_json(paths.settings_path)
    settings = settings_from_dict(settings_data) if settings_data else None
    pid, running = current_process(paths)
    config = load_toml_config(paths.config_path)
    provider = args.provider or (settings.provider if settings else active_provider_name(config))
    config_base_url = provider_base_url(config, provider) if provider else None
    health = proxy_health(settings) if settings and running else None
    healthy = health_matches_settings(health, settings) if settings and running else False
    runtime_matches = health_matches_runtime(health) if healthy else None

    print(json_line({
        "status": "running" if running else "stopped",
        "pid": pid,
        "healthy": healthy,
        "runtime_id": RUNTIME_ID,
        "runtime_matches": runtime_matches,
        "needs_restart": bool(healthy and not runtime_matches),
        "provider": provider,
        "base_url": settings.base_url if settings else None,
        "upstream_base": settings.upstream_base if settings else None,
        "config_base_url": config_base_url,
        "config_matches": bool(settings and config_base_url == settings.base_url),
        "startup_hook": has_startup_hook(paths),
        "port_available": is_port_available(settings.host, settings.port) if settings else None,
        "health": health,
        "log": str(paths.log_path),
        "stdout": str(paths.stdout_path),
        "stderr": str(paths.stderr_path),
    }))
    return 0


def doctor_report(paths: ProxyPaths, provider: str | None) -> dict[str, Any]:
    config = load_toml_config(paths.config_path)
    selected_provider = provider or active_provider_name(config)
    upstream_base = provider_base_url(config, selected_provider) if selected_provider else None
    settings_data = read_json(paths.settings_path)
    settings = settings_from_dict(settings_data) if settings_data else None
    pid, running = current_process(paths)
    health = proxy_health(settings) if settings and running else None
    healthy = health_matches_settings(health, settings) if settings and running else False
    runtime_matches = health_matches_runtime(health) if healthy else None
    hooks_enabled = config_feature_enabled(config, "codex_hooks")

    checks = [
        {"name": "python", "ok": sys.version_info >= (3, 11), "detail": sys.version.split()[0]},
        {"name": "codex_config", "ok": paths.config_path.exists(), "detail": str(paths.config_path)},
        {"name": "active_provider", "ok": bool(selected_provider), "detail": selected_provider},
        {"name": "provider_base_url", "ok": bool(upstream_base), "detail": upstream_base},
    ]
    if settings_data:
        checks.extend([
            {"name": "proxy_settings", "ok": True, "detail": str(paths.settings_path)},
            {"name": "config_points_to_proxy", "ok": upstream_base == settings.base_url, "detail": upstream_base},
            {"name": "upstream_saved", "ok": bool(settings.upstream_base), "detail": settings.upstream_base},
            {"name": "proxy_health", "ok": not running or healthy, "detail": health},
            {"name": "proxy_runtime", "ok": not healthy or runtime_matches, "detail": health.get("runtime_id") if health else None},
            {"name": "codex_hooks_enabled", "ok": hooks_enabled, "detail": hooks_enabled},
            {"name": "startup_hook", "ok": has_startup_hook(paths), "detail": str(paths.hooks_path)},
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


def command_uninstall(args: argparse.Namespace) -> int:
    paths = paths_for(args.codex_home)
    manifest = read_json(paths.manifest_path)
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
            settings = settings_from_dict(manifest["settings"])
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
    install.add_argument("--start", action="store_true")
    install.add_argument("--prepare-only", action="store_true")
    install.add_argument("--verbose-proxy", action="store_true")

    start = subparsers.add_parser("start", help="Start the background proxy.")
    add_shared_options(start)
    start.add_argument("--verbose-proxy", action="store_true")

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

    doctor = subparsers.add_parser("doctor", help="Check Codex config and proxy environment.")
    add_shared_options(doctor)
    doctor.add_argument("--provider")

    uninstall = subparsers.add_parser("uninstall", help="Stop proxy and restore the backed-up Codex config.")
    add_shared_options(uninstall)
    uninstall.add_argument("--force", action="store_true")
    uninstall.add_argument("--keep-state", action="store_true")
    uninstall.add_argument("--defer-stop", action="store_true")

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
            "--log-dir",
            args.log_dir,
        ]
        if args.verbose:
            serve_args.append("--verbose")
        return serve_main(serve_args)

    commands = {
        "install": command_install,
        "start": command_start,
        "autostart": command_autostart,
        "stop": command_stop,
        "status": command_status,
        "doctor": command_doctor,
        "uninstall": command_uninstall,
    }
    try:
        return commands[args.command](args)
    except ConfigError as exc:
        print(compact_json({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 2
