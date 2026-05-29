from __future__ import annotations

from pathlib import Path
from typing import Any


SPEED_MODE_POLICIES = {
    "fast": "auto",
    "standard": "preserve",
}
DEFERRED_STATE_MESSAGES = {
    "update": (
        "更新完成，等待当前请求结束",
        "当前 Codex 请求仍在进行。新版代理会在请求结束后自动应用。",
    ),
    "configure": (
        "已保存，等待当前请求结束",
        "当前 Codex 请求仍在进行。新的模型服务和速度模式已保存，会在请求结束后自动应用。",
    ),
    "save_provider": (
        "Provider 已保存，等待当前请求结束",
        "当前 Codex 请求仍在进行。新配置已保存，会在请求结束后自动应用。",
    ),
    "switch_provider": (
        "切换已保存，等待当前请求结束",
        "当前 Codex 请求仍在进行。新的供应商已保存，会在请求结束后自动应用。",
    ),
    "speed": (
        "速度模式已保存，等待当前请求结束",
        "当前 Codex 请求仍在进行。新的速度模式会在请求结束后自动应用。",
    ),
}


def active_restart_deferred(result: dict[str, Any]) -> bool:
    start_result = result.get("start_result")
    return (
        isinstance(start_result, dict)
        and start_result.get("status") == "deferred"
        and start_result.get("defer_reason") == "active_codex_turns"
    )


def update_restart_deferred(result: dict[str, Any]) -> bool:
    refresh = result.get("refresh")
    if not isinstance(refresh, dict):
        return False
    return active_restart_deferred(refresh)


def state(code: str, title: str, message: str, primary_action: str = "refresh", primary_label: str = "刷新状态") -> dict[str, str]:
    return {
        "code": code,
        "title": title,
        "message": message,
        "primary_action": primary_action,
        "primary_label": primary_label,
    }


def deferred_state(kind: str) -> dict[str, str]:
    title, message = DEFERRED_STATE_MESSAGES[kind]
    return state("restart_deferred_active", title, message)


def run_apply_pending_now(codex_home: str | None) -> dict[str, Any]:
    from . import manager
    from .lifecycle import clear_codex_active_turns
    from .state import collect_status, proxy_is_idle

    snapshot = collect_status(codex_home, apply_idle_pending=False)
    if not snapshot.get("settings_pending"):
        snapshot["user_state"] = state(
            "working",
            "无需应用",
            "当前没有等待应用的新设置。",
            "refresh",
            "刷新状态",
        )
        return {"status": "nothing_pending", "final_status": snapshot, "user_state": snapshot["user_state"]}
    if not proxy_is_idle(snapshot):
        user_state = state(
            "restart_deferred_active",
            "仍有请求进行中",
            "当前代理仍在处理请求。请等请求结束后再手动应用。",
        )
        snapshot["user_state"] = user_state
        return {"status": "blocked_active_proxy_requests", "final_status": snapshot, "user_state": user_state}

    paths = manager.paths_for(codex_home)
    settings = manager.read_settings(paths)
    clear_result = clear_codex_active_turns(paths, reason="manual_apply_pending")
    start_result = manager.start_background(paths, settings, False)
    final_status = collect_status(codex_home, apply_idle_pending=False)
    if final_status.get("needs_restart"):
        user_state = state(
            "restart_required",
            "已清理等待状态",
            "已确认当前请求结束，但代理仍需要刷新。请刷新状态或重启 Codex。",
        )
    else:
        user_state = state(
            "working",
            "已应用",
            "等待中的设置已应用，可以继续使用。",
            "uninstall",
            "停用并恢复",
        )
    final_status["user_state"] = user_state
    return {
        "status": "applied_pending_settings",
        "clear_result": clear_result,
        "start_result": start_result,
        "final_status": final_status,
        "user_state": user_state,
    }


def run_first_run_enable(codex_home: str | None, provider: str | None = None) -> dict[str, Any]:
    from . import manager

    paths = manager.paths_for(codex_home)
    config = manager.load_toml_config(paths.config_path)
    selected_provider = manager.choose_provider(config, provider)
    if manager.provider_auth_secret(paths, selected_provider):
        prepare_result = {
            "status": "already_prepared",
            "provider": selected_provider,
            "target_auth": "provider_auth_file",
            "settings_changed": False,
        }
    else:
        prepare_result = manager.prepare_chatgpt_login(manager_args(
            manager,
            "prepare-chatgpt-login",
            codex_home,
            "--provider",
            selected_provider,
            "--apply",
        ))

    install_args = manager_args(
        manager,
        "install",
        codex_home,
        "--provider",
        selected_provider,
        "--use-provider-auth-file",
        "--start",
    )
    install_result = manager.install_result(install_args)

    return {
        "status": "enabled",
        "provider": selected_provider,
        "chatgpt_compatibility": {
            "status": "ready" if prepare_result.get("status") in {"already_prepared", "prepared"} else "pending",
            "provider": selected_provider,
            "detail": prepare_result.get("status"),
        },
        "prepare_chatgpt_login": prepare_result,
        "install": install_result,
        "restart_required": True,
        "user_state": {
            "code": "restart_required",
            "title": "已启用，重启后接管",
            "message": (
                "当前对话可以继续。Codex 重启后，新会话会走本地代理。"
                "如果你有 ChatGPT 账号，可以在 Codex App 里登录 ChatGPT，继续使用原生 UI 功能。"
            ),
        },
        "next_user_action": "当前对话可以继续；方便时重启 Codex，然后回到此页面确认运行状态。",
    }


def run_update(codex_home: str | None, provider: str | None = None) -> dict[str, Any]:
    from . import manager

    result = manager.update_installation(codex_home, provider)
    if result.get("status") == "blocked":
        next_action = str(result.get("next_user_action") or "当前安装状态不能安全更新，请打开高级诊断。")
        result["user_state"] = state(
            "update_blocked",
            "更新被暂停",
            f"本地安装有未处理改动，更新已暂停；当前代理状态不受影响。{next_action}",
            "diagnostics",
            "打开高级诊断",
        )
        return result

    final_status = result.get("final_status") if isinstance(result.get("final_status"), dict) else {}
    code_update = result.get("code_update") if isinstance(result.get("code_update"), dict) else {}
    if result.get("status") == "already_current":
        result["user_state"] = state(
            "already_current",
            "已是最新",
            "当前已经是最新版本，可以继续使用。",
        )
    elif update_restart_deferred(result):
        result["user_state"] = deferred_state("update")
    elif final_status.get("needs_restart"):
        result["user_state"] = state(
            "restart_required",
            "更新完成，请重启 Codex",
            "更新已完成，但当前 Codex 进程需要重启后才会使用新的代理状态。",
        )
    elif code_update.get("status") == "updated":
        result["control_ui_reload_required"] = True
        result["user_state"] = state(
            "updated",
            "更新完成",
            "已刷新到最新版本，正在打开新版控制面板。当前代理可以继续使用。",
        )
    else:
        result["user_state"] = state(
            "updated",
            "更新完成",
            "已刷新到最新版本，当前状态可以继续使用。",
        )
    return result


def run_check_update(codex_home: str | None = None) -> dict[str, Any]:
    from . import manager

    result = manager.check_update()
    if result.get("local_changes"):
        result["user_state"] = state(
            "update_checked_dirty",
            "已检查，有本地改动",
            "远端检查完成；当前本地有未提交改动，更新会先暂停。",
            "diagnostics",
            "打开高级诊断",
        )
    elif result.get("update_available"):
        result["user_state"] = state(
            "update_available",
            "发现可用更新",
            "远端有新提交；确认当前工作区状态后，可以在设置里更新。",
        )
    else:
        result["user_state"] = state(
            "already_current",
            "已是最新",
            "远端检查完成，当前已经是最新版本。",
        )
    return result


def run_verify_provider(codex_home: str | None, provider: str | None = None) -> dict[str, Any]:
    from . import manager

    paths = manager.paths_for(codex_home)
    config = manager.load_toml_config(paths.config_path)
    settings_data = manager.read_json(paths.settings_path)
    settings = manager.settings_from_dict(settings_data) if settings_data else None
    name = manager.validate_provider_name(provider or (settings.provider if settings else manager.choose_provider(config, None)))
    config_base = manager.provider_base_url(config, name)
    upstream_base = settings.upstream_base if settings and settings.provider == name else manager.provider_auth_base_url(paths, name) or config_base
    if not upstream_base:
        raise ValueError(f"Provider {name!r} 没有模型服务地址。")

    if settings and settings.provider == name:
        verify_settings = settings
    else:
        verify_settings = manager.ProxySettings(
            provider=name,
            host=settings.host if settings else manager.DEFAULT_HOST,
            port=settings.port if settings else manager.DEFAULT_PORT,
            proxy_base=settings.proxy_base if settings else manager.DEFAULT_PROXY_BASE,
            upstream_base=manager.validate_upstream_base(upstream_base),
            service_tier=settings.service_tier if settings else manager.DEFAULT_SERVICE_TIER,
            service_tier_policy=settings.service_tier_policy if settings else manager.DEFAULT_SERVICE_TIER_POLICY,
            upstream_api_key_file=bool(manager.provider_auth_secret(paths, name)),
        )

    verification = manager.verify_upstream_responses(paths, config, verify_settings, 60.0)
    duration = verification.get("total_ms") or verification.get("first_event_ms")
    duration_text = f"{float(duration) / 1000:.2f}s" if isinstance(duration, (int, float)) else "已响应"
    return {
        "status": "provider_verified",
        "provider": name,
        "verification": verification,
        "user_state": state(
            "provider_verified",
            "模型服务可用",
            f"{name} 已通过 Responses 流式检查，耗时 {duration_text}。",
        ),
    }


def run_benchmark(codex_home: str | None, confirm: bool = False, benchmark_kind: str = "quick") -> dict[str, Any]:
    if not confirm:
        raise ValueError("运行基准测试前需要确认。")

    from . import manager
    from .benchmark import (
        BenchmarkTarget,
        discover_api_key,
        profile_for_name,
        run_benchmark as execute_benchmark,
        save_benchmark_result,
    )

    kind = benchmark_kind if benchmark_kind in {"quick", "strict"} else "quick"
    pairs = 12 if kind == "strict" else 3
    timeout = 600.0
    profile = "full"
    mode = "direct"
    paths = manager.paths_for(codex_home)
    settings = manager.read_settings(paths)
    config = manager.load_toml_config(paths.config_path)
    provider_config = manager.provider_config_for(config, settings.provider)
    model = config.get("model")
    reasoning_effort = config.get("model_reasoning_effort")
    if not isinstance(model, str) or not model:
        raise manager.ConfigError("Codex config has no model; configure a model before running benchmark.")
    if reasoning_effort is not None and not isinstance(reasoning_effort, str):
        raise manager.ConfigError("Codex config model_reasoning_effort must be a string.")
    try:
        profile_for_name(profile)
    except ValueError as exc:
        raise manager.ConfigError(str(exc)) from exc

    if manager.upstream_auth_configured(settings):
        api_key_source, api_key = manager.resolve_verification_api_key(paths, provider_config, settings)
    else:
        try:
            api_key_source, api_key = discover_api_key(provider_config, None, paths.codex_home)
        except ValueError as exc:
            raise manager.ConfigError(str(exc)) from exc

    target = BenchmarkTarget(
        provider=settings.provider,
        upstream_base=settings.upstream_base,
        model=model,
        profile=profile,
        service_tier=settings.service_tier,
        api_key_source=api_key_source,
        api_key=api_key,
        reasoning_effort=reasoning_effort,
    )
    result = execute_benchmark(
        target,
        pairs,
        timeout,
        mode=mode,
        benchmark_kind=kind,
        randomized_order=kind == "strict",
    )
    save_benchmark_result(paths.benchmark_path, result)
    result["saved_to"] = str(paths.benchmark_path)
    result["status"] = "benchmark_saved"
    result["reload_required"] = True
    result["user_state"] = state(
        "benchmark_saved",
        "基准测试完成",
        f"已完成 {pairs} 组标准和优先请求，结果已保存到请求记录页。",
    )
    return result


def run_configure_upstream(
    codex_home: str | None,
    upstream_base: str | None,
    api_key: str | None,
    speed_mode: str | None = None,
) -> dict[str, Any]:
    from . import manager

    result = manager.configure_upstream(
        codex_home,
        upstream_base,
        api_key,
        service_tier_policy=service_tier_policy_for_speed_mode(speed_mode),
    )
    if active_restart_deferred(result):
        result["user_state"] = deferred_state("configure")
    elif result.get("restart_required"):
        result["user_state"] = state(
            "restart_required",
            "配置已保存，重启后接管",
            "当前对话可以继续。Codex 重启后，新配置和速度模式会应用到新的会话。",
        )
    else:
        result["user_state"] = state(
            "configured",
            "配置已保存",
            "模型服务和速度模式已保存，当前状态可以继续使用。",
        )
    return result


def run_save_provider(
    codex_home: str | None,
    provider: str | None,
    upstream_base: str | None,
    api_key: str | None,
) -> dict[str, Any]:
    from . import manager

    if not provider or not upstream_base:
        raise ValueError("Provider 和模型服务地址都不能为空。")
    result = manager.save_provider(codex_home, provider, upstream_base, api_key)
    if active_restart_deferred(result):
        result["user_state"] = deferred_state("save_provider")
    else:
        result["user_state"] = state(
            "provider_saved",
            "Provider 已保存",
            "模型服务地址和接口密钥已保存。需要使用它时，点击切换。",
        )
    return result


def run_delete_provider(codex_home: str | None, provider: str | None) -> dict[str, Any]:
    from . import manager

    if not provider:
        raise ValueError("请选择 Provider。")
    result = manager.delete_provider(codex_home, provider)
    result["user_state"] = state(
        "provider_deleted",
        "已删除",
        "已删除这个保存项，当前模型服务不受影响。",
    )
    return result


def run_switch_provider(codex_home: str | None, provider: str | None) -> dict[str, Any]:
    from . import manager

    if not provider:
        raise ValueError("请选择 Provider。")
    result = manager.switch_provider(codex_home, provider)
    if active_restart_deferred(result):
        result["user_state"] = deferred_state("switch_provider")
    elif result.get("restart_required"):
        result["user_state"] = state(
            "restart_required",
            "Provider 已切换，重启后接管",
            "当前对话可以继续。Codex 重启后，新会话会使用新的模型服务。",
        )
    elif result.get("status") == "provider_switched":
        result["user_state"] = state(
            "provider_switched",
            "供应商已切换",
            "当前代理已经使用新的模型服务，Codex 配置仍保持在本地代理入口。",
        )
    else:
        result["user_state"] = state(
            "provider_selected",
            "供应商已选择",
            "点击启用后会使用这个模型服务。",
            "enable",
            "启用",
        )
    return result


def run_set_speed_mode(codex_home: str | None, speed_mode: str | None) -> dict[str, Any]:
    from . import manager

    result = manager.configure_upstream(
        codex_home,
        None,
        None,
        service_tier_policy=service_tier_policy_for_speed_mode(speed_mode),
    )
    if active_restart_deferred(result):
        result["user_state"] = deferred_state("speed")
    elif result.get("restart_required"):
        result["user_state"] = state(
            "restart_required",
            "速度模式已保存，重启后接管",
            "当前对话可以继续。Codex 重启后，新速度模式会应用到新的会话。",
        )
    else:
        result["user_state"] = state(
            "speed_saved",
            "速度模式已保存",
            "当前状态可以继续使用。",
        )
    return result


def run_uninstall(codex_home: str | None, confirm_chatgpt_direct_uninstall: bool = False) -> dict[str, Any]:
    from . import manager

    paths = manager.paths_for(codex_home)
    defer_stop, _provider = manager.enabled_installation(paths, None)
    args = ["--defer-stop"] if defer_stop else []
    if not defer_stop:
        args.append("--keep-state")
    if confirm_chatgpt_direct_uninstall:
        args.append("--confirm-chatgpt-direct-uninstall")
    result, exit_code = manager.uninstall_result(manager_args(manager, "uninstall", codex_home, *args))
    if exit_code not in {0, 4}:
        detail = result.get("message") or result.get("error") or f"exit code {exit_code}"
        raise ValueError(str(detail))
    if result.get("status") == "confirmation_required":
        result["user_state"] = state(
            "confirmation_required",
            "停用前需要处理登录方式",
            (
                "你现在是 ChatGPT 账户登录。直接停用后，Codex 可能无法继续使用当前模型服务。"
                "建议先切回接口密钥或第三方服务登录，重启 Codex 后再回来停用。"
            ),
            "refresh",
            "刷新状态",
        )
    elif result.get("stop_result", {}).get("status") == "deferred":
        result["user_state"] = state(
            "uninstalled_deferred",
            "已恢复，请重启 Codex",
            "Codex 已恢复到原模型服务。请重启 Codex，重启后再次打开控制面板完成清理。",
        )
    else:
        result["control_ui_cleanup"] = control_ui_cleanup(paths, manager.source_repo_root())
        result["user_state"] = state(
            "uninstalled",
            "已清理完成",
            "本地代理已停止。控制面板关闭后会移除本地安装、状态、skill 和备份，Codex 会继续使用原模型服务。",
        )
    return result


def control_ui_cleanup(paths: Any, repo_root: Path) -> dict[str, str]:
    expected_repo = paths.codex_home / "codex-fast-proxy"
    try:
        deep_removal = repo_root.resolve() == expected_repo.resolve()
    except OSError:
        deep_removal = False
    if not deep_removal:
        return {"mode": "runtime_state", "path": str(paths.app_home)}
    return {
        "mode": "deep_install_removal",
        "app_home": str(paths.app_home),
        "repo_root": str(repo_root),
        "backup_dir": str(paths.backup_dir),
        "package": "codex-fast-proxy",
    }


def manager_args(manager: Any, command: str, codex_home: str | None, *args: str) -> Any:
    argv = [command]
    if codex_home:
        argv.extend(["--codex-home", codex_home])
    argv.extend(args)
    return manager.build_parser().parse_args(argv)


def service_tier_policy_for_speed_mode(speed_mode: str | None) -> str | None:
    if not speed_mode:
        return None
    try:
        return SPEED_MODE_POLICIES[speed_mode]
    except KeyError as exc:
        raise ValueError("Unknown speed mode.") from exc
