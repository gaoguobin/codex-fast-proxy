from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ConfigError(RuntimeError):
    pass


def normalized_base_path(value: str) -> str:
    return "/" + value.strip("/ ")


def validate_upstream_base(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"Invalid upstream base URL: {value}")
    if parsed.username or parsed.password:
        raise ConfigError("Upstream base URL must not contain usernames, passwords, or tokens.")
    if parsed.query or parsed.fragment:
        raise ConfigError("Upstream base URL must not contain query strings or fragments.")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def safe_url_display(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value
    netloc = parsed.netloc.rsplit("@", 1)[-1]
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme, netloc, path, "", ""))


def redact_url_secrets(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return safe_url_display(match.group(0))

    return re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+", replace, text)


def redact_sensitive_text(text: str) -> str:
    redacted = redact_url_secrets(text)
    redacted = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,'\"<>]+", r"\1<redacted>", redacted)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "<redacted-key>", redacted)


def is_success_status(value: object) -> bool:
    try:
        status = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return 200 <= status < 400


def validate_env_name(name: str) -> str:
    value = name.strip()
    if not ENV_NAME_PATTERN.fullmatch(value):
        raise ConfigError(f"Invalid environment variable name: {name!r}")
    return value
