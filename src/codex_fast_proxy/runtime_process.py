from __future__ import annotations

import ctypes
import http.client
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .auth import detect_login_mode, read_secret_from_auth
from .auth_store import provider_auth_secret
from .config import load_toml_config, provider_name_for_base_url
from .core import ConfigError
from .defaults import INTERNAL_UPSTREAM_API_KEY_ENV, PORT_SEARCH_ATTEMPTS
from .models import ProxyPaths, ProxySettings, settings_from_dict
from .ports import find_available_port
from .proxy import RUNTIME_ID, compact_json
from .runtime_status import (
    health_matches_proxy_identity,
    health_matches_runtime,
    health_matches_settings,
    settings_restart_pending,
)
from .status_rules import LEGACY_SERVICE_TIER_POLICY, effective_service_tier_policy
from .storage import append_private_text, ensure_private_dir, open_private_append, read_json, write_private_text


@dataclass(frozen=True)
class ProxyStartPolicy:
    health_timeout: float
    defer_health_timeout: bool = False
    restart_stale_runtime: bool = True
    lock_timeout: float = 5.0


INTERACTIVE_PROXY_START_POLICY = ProxyStartPolicy(health_timeout=5.0)
AUTOSTART_PROXY_START_POLICY = ProxyStartPolicy(
    health_timeout=1.0,
    defer_health_timeout=True,
    restart_stale_runtime=False,
)
START_LOCK_STALE_SECONDS = 60.0
START_LOCK_POLL_INTERVAL = 0.05
AUTOSTART_EVENT_LIMIT = 200


class StartLockBusy(ConfigError):
    pass


class ConcurrentProxyAlreadyRunning(ConfigError):
    def __init__(self, health: dict[str, Any]) -> None:
        super().__init__("A matching codex-fast-proxy instance became healthy first.")
        self.health = health


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
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
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
    return find_available_port(host, port, attempts=1) == port


def wait_for_proxy_port_release(settings: ProxySettings, timeout: float = 5.0, interval: float = 0.05) -> None:
    deadline = time.monotonic() + timeout
    while True:
        if is_port_available(settings.host, settings.port):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
    raise ConfigError(f"Port {settings.port} is still in use on {settings.host} after stopping the previous proxy.")


def auto_select_proxy_port(host: str, preferred: int) -> tuple[int, dict[str, Any]]:
    selected = find_available_port(host, preferred, attempts=PORT_SEARCH_ATTEMPTS)
    if selected is None:
        raise ConfigError(
            f"没有找到可用的本地数据代理端口，请关闭占用 {host}:{preferred}-{preferred + PORT_SEARCH_ATTEMPTS - 1} 的旧进程后重试。"
        )
    return selected, {
        "preferred": preferred,
        "selected": selected,
        "auto_selected": selected != preferred,
    }


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


def proxy_runtime_state(
    paths: ProxyPaths,
    settings: ProxySettings | None,
) -> tuple[int | None, bool, dict[str, Any] | None, bool, bool, bool | None]:
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


def proxy_activity(health: dict[str, Any] | None) -> dict[str, Any]:
    activity = health.get("activity") if isinstance(health, dict) else None
    if isinstance(activity, dict):
        return activity
    return {
        "active_requests": 0,
        "active_streams": 0,
        "idle": True,
        "last_request_started_at": None,
        "last_request_finished_at": None,
    }


def proxy_has_active_traffic(health: dict[str, Any] | None) -> bool:
    activity = proxy_activity(health)
    try:
        return int(activity.get("active_requests") or 0) > 0 or int(activity.get("active_streams") or 0) > 0
    except (TypeError, ValueError):
        return False


def proxy_health_pid(health: dict[str, Any] | None) -> int | None:
    pid = health.get("pid") if isinstance(health, dict) else None
    return pid if isinstance(pid, int) else None


def proxy_start_lock_path(paths: ProxyPaths, settings: ProxySettings) -> Path:
    host_key = "".join(character if character.isalnum() else "_" for character in settings.host)
    return paths.state_dir / f"fast_proxy.start.{host_key}.{settings.port}.lock.json"


def start_lock_is_stale(lock_path: Path) -> bool:
    metadata: dict[str, Any] | None = None
    try:
        metadata = read_json(lock_path)
    except (OSError, json.JSONDecodeError):
        metadata = None

    pid = metadata.get("pid") if isinstance(metadata, dict) else None
    if isinstance(pid, int):
        return not is_process_running(pid)

    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return True
    return age >= START_LOCK_STALE_SECONDS


def remove_start_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


@contextmanager
def proxy_start_lock(paths: ProxyPaths, settings: ProxySettings, timeout: float) -> Iterator[None]:
    ensure_private_dir(paths.state_dir)
    lock_path = proxy_start_lock_path(paths, settings)
    deadline = time.monotonic() + max(timeout, 0.0)
    while True:
        try:
            fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            if start_lock_is_stale(lock_path):
                remove_start_lock(lock_path)
                continue
            if time.monotonic() >= deadline:
                raise StartLockBusy(f"Another codex-fast-proxy start is already in progress: {lock_path}")
            time.sleep(START_LOCK_POLL_INTERVAL)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump({
                "pid": os.getpid(),
                "host": settings.host,
                "port": settings.port,
                "created_at": time.time(),
            }, file)
            file.write("\n")
        yield
    finally:
        remove_start_lock(lock_path)


def deferred_restart_result(
    paths: ProxyPaths,
    settings: ProxySettings,
    pid: int | None,
    health: dict[str, Any] | None,
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "status": "deferred",
        "reason": reason,
        "defer_reason": "active_requests",
        "pid": pid,
        "needs_restart": True,
        "provider": settings.provider,
        "base_url": settings.base_url,
        "upstream_base": settings.upstream_base,
        "activity": proxy_activity(health),
        "log": str(paths.log_path),
        "next_action": "The new settings are saved and will apply after the active model request finishes.",
    }


def starting_result(
    paths: ProxyPaths,
    settings: ProxySettings,
    pid: int | None,
    *,
    reason: str,
    health_timeout: float | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "starting",
        "pid": pid,
        "healthy": False,
        "reason": reason,
        "provider": settings.provider,
        "base_url": settings.base_url,
        "upstream_base": settings.upstream_base,
        "health_check": "deferred",
        "log": str(paths.log_path),
        "stdout": str(paths.stdout_path),
        "stderr": str(paths.stderr_path),
    }
    if health_timeout is not None:
        result["health_timeout_ms"] = round(health_timeout * 1000, 1)
    return result


def matching_proxy_result(
    paths: ProxyPaths,
    settings: ProxySettings,
    health: dict[str, Any] | None,
    service_tier_effective_policy: str | None,
    *,
    reason: str,
) -> dict[str, Any] | None:
    if not health_matches_settings(health, settings, service_tier_effective_policy):
        return None
    pid = proxy_health_pid(health)
    if pid is None:
        return None
    result = already_running_result(
        paths,
        settings,
        pid,
        health,
        runtime_matches=health_matches_runtime(health),
    )
    result["reason"] = reason
    return result


def port_owner_start_result(
    paths: ProxyPaths,
    settings: ProxySettings,
    service_tier_effective_policy: str | None,
    start_policy: ProxyStartPolicy,
    *,
    reason: str,
) -> dict[str, Any] | None:
    result = matching_proxy_result(
        paths,
        settings,
        proxy_health(settings),
        service_tier_effective_policy,
        reason=reason,
    )
    if result:
        return result

    if not start_policy.defer_health_timeout:
        return None
    pid, running = current_process(paths)
    if running:
        return starting_result(paths, settings, pid, reason=reason, health_timeout=start_policy.health_timeout)
    return None


def wait_for_proxy_health(
    settings: ProxySettings,
    process: subprocess.Popen[Any],
    timeout: float = 5.0,
    service_tier_effective_policy: str | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_health = None
    while time.monotonic() < deadline:
        last_health = proxy_health(settings)
        if health_matches_settings(last_health, settings, service_tier_effective_policy):
            health_pid = proxy_health_pid(last_health)
            if health_pid is not None and health_pid != process.pid:
                raise ConcurrentProxyAlreadyRunning(last_health)
            if health_pid is None:
                time.sleep(0.1)
                continue
            return last_health
        if process.poll() is not None:
            break
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
        "provider": settings.provider,
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
    start_policy: ProxyStartPolicy = INTERACTIVE_PROXY_START_POLICY,
) -> dict[str, Any]:
    stop_result = stop_process(paths, force=force_stop)
    wait_for_proxy_port_release(settings)
    try:
        start_result = launch_background(
            paths,
            settings,
            verbose_proxy,
            start_policy=start_policy,
        )
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
            wait_for_proxy_port_release(previous_settings)
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
        "provider": settings.provider,
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
    start_policy: ProxyStartPolicy = INTERACTIVE_PROXY_START_POLICY,
) -> dict[str, Any]:
    ensure_private_dir(paths.app_home)
    ensure_private_dir(paths.state_dir)
    try:
        with proxy_start_lock(paths, settings, start_policy.lock_timeout):
            return start_background_locked(paths, settings, verbose_proxy, start_policy=start_policy)
    except StartLockBusy:
        pid, running, health, healthy, _pending_restart, runtime_matches = proxy_runtime_state(paths, settings)
        if running and healthy:
            return already_running_result(paths, settings, pid, health, runtime_matches=runtime_matches is not False)
        return starting_result(paths, settings, pid if running else None, reason="start_lock_busy")


def start_background_locked(
    paths: ProxyPaths,
    settings: ProxySettings,
    verbose_proxy: bool,
    *,
    start_policy: ProxyStartPolicy,
) -> dict[str, Any]:
    pid, running, health, healthy, _pending_restart, runtime_matches = proxy_runtime_state(paths, settings)
    if running:
        if healthy:
            if runtime_matches:
                return already_running_result(paths, settings, pid, health)
            if not start_policy.restart_stale_runtime:
                return already_running_result(paths, settings, pid, health, runtime_matches=False)
            if proxy_has_active_traffic(health):
                return deferred_restart_result(paths, settings, pid, health, reason="runtime_changed")
            return restart_background(
                paths,
                settings,
                verbose_proxy,
                pid,
                health,
                start_policy=start_policy,
            )
        if health_matches_proxy_identity(health, settings, pid):
            if proxy_has_active_traffic(health):
                return deferred_restart_result(paths, settings, pid, health, reason="settings_changed")
            return restart_background(
                paths,
                settings,
                verbose_proxy,
                pid,
                health,
                reason="settings_changed",
                force_stop=True,
                start_policy=start_policy,
            )
        raise ConfigError(f"Existing proxy process {pid} is running with different or unhealthy settings. Stop it first.")
    paths.pid_path.unlink(missing_ok=True)

    return launch_background(
        paths,
        settings,
        verbose_proxy,
        start_policy=start_policy,
    )


def launch_background(
    paths: ProxyPaths,
    settings: ProxySettings,
    verbose_proxy: bool,
    *,
    start_policy: ProxyStartPolicy = INTERACTIVE_PROXY_START_POLICY,
) -> dict[str, Any]:
    ensure_private_dir(paths.app_home)
    ensure_private_dir(paths.state_dir)

    login = detect_login_mode(paths.codex_home)
    effective_policy = effective_service_tier_policy(settings, login)
    settings_data = read_json(paths.settings_path)
    settings_revision = settings_data.get("settings_revision") if isinstance(settings_data, dict) else None
    if not is_port_available(settings.host, settings.port):
        result = port_owner_start_result(
            paths,
            settings,
            effective_policy,
            start_policy,
            reason="port_in_use",
        )
        if result:
            return result
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
        "--provider",
        settings.provider,
        "--settings-revision",
        str(settings_revision or ""),
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
    with open_private_append(paths.stdout_path, binary=True) as stdout, open_private_append(paths.stderr_path, binary=True) as stderr:
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
        health = wait_for_proxy_health(
            settings,
            process,
            timeout=start_policy.health_timeout,
            service_tier_effective_policy=effective_policy,
        )
    except ConcurrentProxyAlreadyRunning as exc:
        if process.poll() is None:
            terminate_process(process.pid)
        pid = proxy_health_pid(exc.health)
        if pid is not None:
            result = already_running_result(
                paths,
                settings,
                pid,
                exc.health,
                runtime_matches=health_matches_runtime(exc.health),
            )
            result["reason"] = "concurrent_start"
            return result
        raise ConfigError("A matching codex-fast-proxy instance became healthy first, but did not report its pid.") from exc
    except ConfigError:
        result = port_owner_start_result(
            paths,
            settings,
            effective_policy,
            start_policy,
            reason="concurrent_start",
        )
        if result:
            if process.poll() is None:
                terminate_process(process.pid)
            return result
        if start_policy.defer_health_timeout and process.poll() is None:
            return starting_result(
                paths,
                settings,
                process.pid,
                reason="health_check_deferred",
                health_timeout=start_policy.health_timeout,
            )
        error_text = paths.stderr_path.read_text(encoding="utf-8", errors="replace") if paths.stderr_path.exists() else ""
        detail = f" {error_text.strip()}" if error_text.strip() else ""
        terminate_process(process.pid)
        raise ConfigError(f"codex-fast-proxy did not become healthy.{detail}")

    return {
        "status": "started",
        "pid": process.pid,
        "healthy": True,
        "provider": settings.provider,
        "base_url": settings.base_url,
        "upstream_base": settings.upstream_base,
        "health": health,
        "log": str(paths.log_path),
        "stdout": str(paths.stdout_path),
        "stderr": str(paths.stderr_path),
    }


def append_autostart_event(paths: ProxyPaths, event: dict[str, Any]) -> None:
    event_path = paths.state_dir / "fast_proxy.autostart.jsonl"
    append_private_text(event_path, compact_json({"ts": time.time(), **event}) + "\n")
    trim_autostart_events(event_path)


def trim_autostart_events(event_path: Path, limit: int = AUTOSTART_EVENT_LIMIT) -> None:
    try:
        lines = event_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= limit:
        return
    write_private_text(event_path, "\n".join(lines[-limit:]) + "\n")


def should_log_autostart_event(_event: dict[str, Any], _quiet: bool) -> bool:
    return True


def autostart_proxy(paths: ProxyPaths, verbose_proxy: bool) -> dict[str, Any]:
    settings_data = read_json(paths.settings_path)
    if not settings_data:
        return {"status": "skipped", "reason": "settings_missing"}

    settings = settings_from_dict(settings_data)
    config = load_toml_config(paths.config_path)
    if not provider_name_for_base_url(config, settings.base_url):
        return {"status": "skipped", "reason": "config_not_proxy", "provider": settings.provider}

    return start_background(
        paths,
        settings,
        verbose_proxy,
        start_policy=AUTOSTART_PROXY_START_POLICY,
    )
