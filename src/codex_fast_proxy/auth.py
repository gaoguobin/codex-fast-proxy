from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LoginDiagnosis:
    login_mode: str
    api_key_auth: bool
    chatgpt_auth: bool
    detail: str


def read_auth_json(codex_home: Path) -> dict[str, Any] | None:
    path = codex_home / "auth.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_secret_from_auth(codex_home: Path, name: str) -> str | None:
    try:
        auth = read_auth_json(codex_home)
    except (OSError, json.JSONDecodeError):
        return None
    if not auth:
        return None
    value = auth.get(name)
    return value if isinstance(value, str) and value else None


def non_empty_auth_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, dict):
        return any(non_empty_auth_value(child) for child in value.values())
    if isinstance(value, list):
        return any(non_empty_auth_value(child) for child in value)
    return value is not None


def detect_login_mode(codex_home: Path) -> LoginDiagnosis:
    try:
        auth = read_auth_json(codex_home)
    except (OSError, json.JSONDecodeError):
        return LoginDiagnosis("unknown", False, False, "auth_json_unreadable")
    if not auth:
        return LoginDiagnosis("unknown", False, False, "auth_json_missing")

    api_key_auth = any(
        key.endswith("_API_KEY") and isinstance(value, str) and bool(value)
        for key, value in auth.items()
    )
    chatgpt_keys = {
        "account",
        "accounts",
        "access_token",
        "chatgpt",
        "id_token",
        "oauth",
        "refresh_token",
        "tokens",
    }
    chatgpt_auth = any(key in auth and non_empty_auth_value(auth.get(key)) for key in chatgpt_keys)

    if api_key_auth and chatgpt_auth:
        return LoginDiagnosis("mixed", api_key_auth, chatgpt_auth, "api_key_and_chatgpt_auth_detected")
    if chatgpt_auth:
        return LoginDiagnosis("chatgpt", api_key_auth, chatgpt_auth, "chatgpt_auth_detected")
    if api_key_auth:
        return LoginDiagnosis("api_key", api_key_auth, chatgpt_auth, "api_key_auth_detected")
    return LoginDiagnosis("unknown", api_key_auth, chatgpt_auth, "auth_json_unclassified")


def windows_user_env(name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return value if isinstance(value, str) and value else None


def write_windows_user_env(name: str, value: str) -> None:
    if os.name != "nt":
        raise OSError("Windows user environment variables are supported only on Windows.")
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def resolve_env(name: str) -> str | None:
    return os.environ.get(name) or windows_user_env(name)


def environment_source(codex_home: Path, name: str | None) -> str | None:
    if not name:
        return None
    if os.environ.get(name):
        return "process_env"
    if windows_user_env(name):
        return "windows_user_env"
    if read_secret_from_auth(codex_home, name):
        return "auth_json_fallback"
    return None
