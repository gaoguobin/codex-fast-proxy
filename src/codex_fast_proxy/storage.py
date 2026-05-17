from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def json_line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_line(value) + "\n", encoding="utf-8")


def write_secret_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            path.chmod(0o600)
        except OSError:
            pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(json_line(value) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
