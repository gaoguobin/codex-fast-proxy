from __future__ import annotations

from typing import Any


SPEED_MODE_POLICIES = {
    "fast": "auto",
    "standard": "preserve",
}


def state(code: str, title: str, message: str, primary_action: str = "refresh", primary_label: str = "重新检查") -> dict[str, str]:
    return {
        "code": code,
        "title": title,
        "message": message,
        "primary_action": primary_action,
        "primary_label": primary_label,
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
        "prepare_chatgpt_login": prepare_result,
        "install": install_result,
        "restart_required": True,
        "user_state": {
            "code": "restart_required",
            "title": "已启用，重启后接管",
            "message": "当前对话可以继续。Codex 重启后，新会话会走本地代理，并按速度模式处理请求。",
        },
        "next_user_action": "当前对话可以继续；方便时重启 Codex，然后回到此页面确认运行状态。",
    }


def run_update(codex_home: str | None, provider: str | None = None) -> dict[str, Any]:
    from . import manager

    result = manager.update_installation(codex_home, provider)
    if result.get("status") == "blocked":
        result["user_state"] = state(
            "update_blocked",
            "更新被暂停",
            str(result.get("next_user_action") or "当前安装状态不能安全更新，请打开诊断。"),
            "diagnostics",
            "打开诊断",
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
    if result.get("restart_required"):
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
                "建议先切回 API Key 或第三方服务登录，重启 Codex 后再回来停用。"
            ),
            "refresh",
            "重新检查",
        )
    elif result.get("stop_result", {}).get("status") == "deferred":
        result["user_state"] = state(
            "uninstalled_deferred",
            "已恢复，请重启 Codex",
            "Codex 已恢复到原模型服务。请重启 Codex，重启后再次打开控制面板完成清理。",
        )
    else:
        result["control_ui_cleanup"] = {"path": str(paths.app_home)}
        result["user_state"] = state(
            "uninstalled",
            "已清理完成",
            "本地代理已停止，相关状态会在控制面板关闭后清理。Codex 会继续使用原模型服务。",
        )
    return result


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
