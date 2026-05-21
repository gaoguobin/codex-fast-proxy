from __future__ import annotations

from pathlib import Path
from typing import Any


SPEED_MODE_POLICIES = {
    "fast": "auto",
    "standard": "preserve",
}


def state(code: str, title: str, message: str, primary_action: str = "refresh", primary_label: str = "刷新状态") -> dict[str, str]:
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
    if result.get("restart_required"):
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
    if result.get("restart_required"):
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
