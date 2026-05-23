from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .auth import detect_login_mode
from .auth_store import chatgpt_login_report, upstream_auth_status
from .config import active_provider_name, configured_providers, load_toml_config, provider_base_url, provider_name_for_base_url
from .hooks import fast_proxy_hook_trust_status
from .models import paths_for, settings_from_dict
from .proxy import RUNTIME_ID
from .runtime_process import is_port_available, proxy_activity, proxy_runtime_state, start_background
from .runtime_status import runtime_status
from .status_rules import effective_service_tier_policy, fast_behavior, status_diagnosis
from .storage import read_json
from .telemetry import read_benchmark_result, recent_provider_metadata_events, recent_response_events


SCHEMA_VERSION = 1
RuntimeProbe = Callable[[Any, Any], tuple[int | None, bool, dict[str, Any] | None, bool, bool, bool | None]]
PortProbe = Callable[[str, int], bool]


def collect_status(
    codex_home: str | None,
    provider: str | None = None,
    *,
    runtime_probe: RuntimeProbe = proxy_runtime_state,
    port_probe: PortProbe = is_port_available,
    apply_idle_pending: bool = False,
) -> dict[str, Any]:
    paths = paths_for(codex_home)
    settings_data = read_json(paths.settings_path)
    settings = settings_from_dict(settings_data) if settings_data else None
    pid, running, health, healthy, pending_restart, runtime_matches = runtime_probe(paths, settings)
    activity = proxy_activity(health)
    auto_apply_result: dict[str, Any] | None = None
    if (
        apply_idle_pending
        and settings
        and running
        and pending_restart
        and not activity.get("active_requests")
        and not activity.get("active_streams")
    ):
        try:
            auto_apply_result = start_background(paths, settings, False)
            pid, running, health, healthy, pending_restart, runtime_matches = runtime_probe(paths, settings)
            activity = proxy_activity(health)
        except Exception as exc:
            auto_apply_result = {"status": "error", "error": str(exc)}
    config = load_toml_config(paths.config_path)
    providers = configured_providers(config)
    active_provider = active_provider_name(config)
    config_provider = provider_name_for_base_url(config, settings.base_url) if settings else None
    selected_provider = provider or (settings.provider if settings else active_provider)
    if not selected_provider and len(providers) == 1:
        selected_provider = next(iter(providers))
    route_provider = config_provider or active_provider or selected_provider
    config_base_url = provider_base_url(config, route_provider) if route_provider else None
    proxy_upstream_provider = settings.provider if settings else None
    hook_status = fast_proxy_hook_trust_status(paths)
    login = detect_login_mode(paths.codex_home)
    auth = upstream_auth_status(paths, settings)
    config_matches = bool(settings and config_provider)
    needs_restart = bool(pending_restart or (healthy and not runtime_matches))
    behavior = fast_behavior(settings, login)
    effective_policy = effective_service_tier_policy(settings, login) if settings else None
    login_report = (
        chatgpt_login_report(paths, settings, login, auth)
        if settings
        else {"provider_auth_preparation": None, "chatgpt_login_hint": None, "next_user_action": None}
    )
    diagnosis = status_diagnosis(
        settings,
        running=running,
        healthy=healthy,
        pending_restart=pending_restart,
        config_matches=config_matches,
        runtime_matches=runtime_matches,
        needs_restart=needs_restart,
        startup_hook_ready=bool(hook_status["ready"]),
        login=login,
        auth=auth,
        behavior=behavior,
    )

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "status": "running" if running else "stopped",
        "pid": pid,
        "healthy": healthy,
        "runtime_id": RUNTIME_ID,
        "runtime": runtime_status(paths, health),
        "runtime_matches": runtime_matches,
        "needs_restart": needs_restart,
        "pending_restart": pending_restart,
        "diagnosis": diagnosis,
        "provider": selected_provider,
        "config_provider": config_provider or active_provider,
        "codex_model_provider": active_provider,
        "codex_config_provider": active_provider,
        "codex_proxy_provider": config_provider,
        "proxy_route_provider": config_provider,
        "proxy_upstream_provider": proxy_upstream_provider,
        "managed_upstream_provider": proxy_upstream_provider,
        "base_url": settings.base_url if settings else None,
        "upstream_base": settings.upstream_base if settings else None,
        "provider_route": {
            "codex_model_provider": active_provider,
            "codex_proxy_provider": config_provider,
            "local_proxy": settings.base_url if settings else None,
            "proxy_upstream_provider": proxy_upstream_provider,
            "upstream_base": settings.upstream_base if settings else None,
        },
        "service_tier_policy": settings.service_tier_policy if settings else None,
        "service_tier_effective_policy": effective_policy,
        "fast_behavior": behavior,
        "login_mode": login.login_mode,
        "chatgpt_auth": login.chatgpt_auth,
        "api_key_auth": login.api_key_auth,
        "upstream_auth": auth["upstream_auth"],
        "upstream_api_key_env": auth["upstream_api_key_env"],
        "upstream_api_key_file": auth["upstream_api_key_file"],
        "upstream_api_key_ref": auth["upstream_api_key_ref"],
        "upstream_api_key_available": auth["upstream_api_key_available"],
        "upstream_api_key_source": auth["upstream_api_key_source"],
        "upstream_api_key_persistent": auth["upstream_api_key_persistent"],
        "chatgpt_login_compatible": bool(auth["upstream_api_key_persistent"]) if login.chatgpt_auth else None,
        **login_report,
        "config_base_url": config_base_url,
        "config_matches": config_matches,
        "startup_hook": hook_status["ready"],
        "startup_hook_trust": hook_status,
        "port_available": port_probe(settings.host, settings.port) if settings else None,
        "health": health,
        "proxy_activity": activity,
        "auto_apply_result": auto_apply_result,
        "log": str(paths.log_path),
        "stdout": str(paths.stdout_path),
        "stderr": str(paths.stderr_path),
        "recent_response_events": recent_response_events(paths.log_path),
        "recent_provider_metadata_events": recent_provider_metadata_events(paths.log_path),
        "benchmark_result": read_benchmark_result(paths.log_path),
    }
    from .manager import provider_inventory

    snapshot.update(provider_inventory(paths.codex_home, selected_provider))
    return {**snapshot, "user_state": user_state(snapshot)}


def user_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    diagnosis = snapshot.get("diagnosis") if isinstance(snapshot.get("diagnosis"), dict) else {}
    code = diagnosis.get("code")
    provider_ready = bool(snapshot.get("provider") and snapshot.get("config_base_url"))
    activity = snapshot.get("proxy_activity") if isinstance(snapshot.get("proxy_activity"), dict) else {}
    active_traffic = bool((activity.get("active_requests") or 0) or (activity.get("active_streams") or 0))

    if snapshot.get("config_matches") and snapshot.get("healthy") and not snapshot.get("needs_restart"):
        view = ("working", "运行正常", "Codex 已准备好继续使用当前模型服务。", "uninstall", "停用并恢复")
    elif snapshot.get("config_matches") and snapshot.get("needs_restart") and active_traffic:
        view = (
            "restart_deferred_active",
            "已保存，等待当前请求结束",
            "当前有模型请求正在返回。新设置已保存，请求结束后控制面板会自动应用。",
            "refresh",
            "刷新状态",
        )
    elif snapshot.get("config_matches") and snapshot.get("needs_restart"):
        view = (
            "restart_required",
            "已启用，重启后接管",
            "当前对话可以继续。Codex 重启后，新会话会走本地代理，并按速度模式处理请求。",
            "refresh",
            "刷新状态",
        )
    elif snapshot.get("base_url") and not snapshot.get("config_matches"):
        view = (
            "cleanup_pending",
            "已停用",
            "Codex 已恢复到原模型服务。你可以重新启用，或完成清理并移除本地代理状态。",
            "enable",
            "重新启用",
        )
    elif provider_ready and code in {"not_enabled", "config_not_proxy"}:
        view = (
            "ready_to_enable",
            "准备启用",
            "点击启用后，会自动准备当前模型服务路径，并提前准备 ChatGPT 账户登录兼容性。",
            "enable",
            "启用",
        )
    elif code == "not_enabled" and not provider_ready:
        message = (
            "没有检测到可接管的第三方模型服务入口；当前还没有发起上游请求。"
            "请先在 Codex config.toml 配置 provider，再回到控制面板启用。"
        )
        view = (
            "missing_provider",
            "需要先配置供应商",
            message,
            "diagnostics",
            "打开高级诊断",
        )
    else:
        view = (
            "needs_attention",
            "需要处理",
            "当前环境还不能直接完成启用。请打开高级诊断，或让 Codex 根据诊断结果修复。",
            "diagnostics",
            "打开高级诊断",
        )
    code, title, message, primary_action, primary_label = view
    return {
        "code": code,
        "title": title,
        "message": message,
        "primary_action": primary_action,
        "primary_label": primary_label,
    }
