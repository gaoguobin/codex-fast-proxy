from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .core import ConfigError, redact_sensitive_text, redact_url_secrets, safe_url_display
from .config import active_provider_name, load_toml_config, provider_name_for_base_url
from .models import ProxyPaths, paths_for, settings_from_dict
from .skill_link import link_skill_namespace
from .storage import read_json


def source_repo_root() -> Path:
    path = Path(__file__).resolve()
    if path.parents[1].name == "src":
        return path.parents[2]
    cwd = Path.cwd()
    return cwd if (cwd / ".git").exists() else path.parents[1]


def run_git(repo: Path, *args: str, timeout: float = 30.0) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ConfigError(redact_url_secrets(detail) or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def current_git_branch(repo: Path) -> str:
    branch = run_git(repo, "branch", "--show-current")
    return branch or "main"


def remote_commit_for(repo: Path, remote: str, branch: str) -> str:
    output = run_git(repo, "ls-remote", remote, f"refs/heads/{branch}", timeout=60.0)
    line = output.splitlines()[0] if output else ""
    commit = line.split()[0] if line else ""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ConfigError(f"Remote branch not found: {remote}/{branch}")
    return commit.lower()


def commit_exists_locally(repo: Path, commit: str) -> bool:
    try:
        run_git(repo, "cat-file", "-e", f"{commit}^{{commit}}")
    except ConfigError:
        return False
    return True


def commit_is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    try:
        run_git(repo, "merge-base", "--is-ancestor", ancestor, descendant)
    except ConfigError:
        return False
    return True


def commit_relation(repo: Path, local_commit: str, remote_commit: str) -> str:
    if local_commit == remote_commit:
        return "same"
    if not commit_exists_locally(repo, remote_commit):
        return "remote_unknown"
    if commit_is_ancestor(repo, remote_commit, local_commit):
        return "local_ahead"
    if commit_is_ancestor(repo, local_commit, remote_commit):
        return "remote_ahead"
    return "diverged"


def check_update(repo: Path | None = None, branch: str | None = None, remote: str = "origin") -> dict[str, Any]:
    repo = repo or source_repo_root()
    run_git(repo, "rev-parse", "--is-inside-work-tree")
    selected_branch = branch or current_git_branch(repo)
    local_commit = run_git(repo, "rev-parse", "HEAD").lower()
    local_changes = bool(run_git(repo, "status", "--porcelain"))
    remote_url = safe_url_display(run_git(repo, "remote", "get-url", remote))
    remote_commit = remote_commit_for(repo, remote, selected_branch)
    relation = commit_relation(repo, local_commit, remote_commit)
    update_available = relation in {"remote_ahead", "remote_unknown", "diverged"}
    if update_available and local_changes:
        next_action = "review local changes before updating"
    elif relation == "local_ahead":
        next_action = "none"
    elif relation == "diverged":
        next_action = "review local commits before updating"
    elif update_available:
        next_action = "run update"
    else:
        next_action = "none"
    return {
        "status": "checked",
        "read_only": True,
        "repo": str(repo),
        "remote": remote,
        "remote_url": remote_url,
        "branch": selected_branch,
        "local_commit": local_commit,
        "remote_commit": remote_commit,
        "relation": relation,
        "local_changes": local_changes,
        "update_available": update_available,
        "next_action": next_action,
    }


def run_python(args: list[str], timeout: float = 300.0) -> str:
    result = subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ConfigError(redact_sensitive_text(detail) or f"python {' '.join(args)} failed")
    return result.stdout.strip()


def parse_json_output(output: str, command: str) -> dict[str, Any]:
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{command} returned invalid JSON.") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"{command} returned an invalid JSON object.")
    return value


def run_python_json(args: list[str], timeout: float = 300.0) -> dict[str, Any]:
    return parse_json_output(run_python(args, timeout), " ".join(args))


def enabled_installation(paths: ProxyPaths, provider: str | None) -> tuple[bool, str | None]:
    settings_data = read_json(paths.settings_path)
    settings = settings_from_dict(settings_data) if settings_data else None
    config = load_toml_config(paths.config_path)
    config_provider = provider_name_for_base_url(config, settings.base_url) if settings else None
    selected_provider = provider or config_provider or (settings.provider if settings else active_provider_name(config))
    if not settings or not selected_provider:
        return False, selected_provider
    if provider and provider != config_provider and provider != settings.provider:
        return False, selected_provider
    return bool(config_provider), selected_provider


def module_args(command: str, codex_home: Path, provider: str | None = None) -> list[str]:
    args = ["-m", "codex_fast_proxy", command, "--codex-home", str(codex_home)]
    if provider:
        args.extend(["--provider", provider])
    return args


def update_installation(
    codex_home: str | Path | None,
    provider: str | None = None,
    *,
    repo: str | Path | None = None,
    remote: str = "origin",
    branch: str | None = None,
    refresh_code: bool = True,
) -> dict[str, Any]:
    paths = paths_for(codex_home)
    repo_path = Path(repo).expanduser().resolve() if repo else source_repo_root()
    was_enabled, selected_provider = enabled_installation(paths, provider)
    before_commit = run_git(repo_path, "rev-parse", "HEAD").lower()
    selected_branch = branch or current_git_branch(repo_path)
    code_update: dict[str, Any]

    if refresh_code:
        check = check_update(repo_path, selected_branch, remote)
        if check["local_changes"]:
            return {
                "status": "blocked",
                "code": "local_changes",
                "repo": str(repo_path),
                "branch": selected_branch,
                "check_update": check,
                "next_user_action": "请先处理本地改动，再从控制面板更新。",
            }
        if check["relation"] in {"local_ahead", "diverged"}:
            return {
                "status": "blocked",
                "code": check["relation"],
                "repo": str(repo_path),
                "branch": selected_branch,
                "check_update": check,
                "next_user_action": "当前安装不是可安全快进的状态，请让 Codex 查看高级诊断后再处理。",
            }
        if check["relation"] == "same":
            after_commit = before_commit
            code_update = {
                "status": "already_current",
                "before_commit": before_commit,
                "after_commit": after_commit,
                "check_update": check,
            }
        else:
            pull_output = run_git(repo_path, "pull", "--ff-only", remote, selected_branch, timeout=120.0)
            after_commit = run_git(repo_path, "rev-parse", "HEAD").lower()
            run_python(["-m", "pip", "install", "--user", "-e", str(repo_path)], timeout=300.0)
            code_update = {
                "status": "updated" if after_commit != before_commit else "already_current",
                "before_commit": before_commit,
                "after_commit": after_commit,
                "pull": "ff_only",
                "pull_output": pull_output,
                "check_update": check,
            }
    else:
        after_commit = before_commit
        code_update = {
            "status": "skipped",
            "before_commit": before_commit,
            "after_commit": after_commit,
            "reason": "code already refreshed",
        }

    skill_link = link_skill_namespace(repo_path)
    if was_enabled:
        if selected_provider == settings_from_dict(read_json(paths.settings_path)).provider:
            install_args = module_args("install", paths.codex_home, selected_provider)
            install_args.append("--start")
            refresh_result = run_python_json(install_args, timeout=300.0)
        else:
            refresh_result = run_python_json(module_args("start", paths.codex_home), timeout=300.0)
    else:
        refresh_result = run_python_json(module_args("doctor", paths.codex_home, selected_provider), timeout=120.0)
    final_status = run_python_json(module_args("status", paths.codex_home, selected_provider), timeout=120.0)

    return {
        "status": "already_current" if code_update["status"] == "already_current" else "updated",
        "repo": str(repo_path),
        "branch": selected_branch,
        "code_update": code_update,
        "skill_link": skill_link,
        "enabled_before_update": was_enabled,
        "refresh": refresh_result,
        "final_status": final_status,
        "restart_required": bool(final_status.get("needs_restart")),
        "next_user_action": (
            "更新完成，当前会话无需重启。"
            if was_enabled and not final_status.get("needs_restart")
            else "更新完成，请按控制面板状态继续。"
        ),
    }
