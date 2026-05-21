from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, IO


PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def json_line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def chmod_best_effort(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    chmod_best_effort(path, PRIVATE_DIR_MODE)


def ensure_private_parent(path: Path) -> None:
    ensure_private_dir(path.parent)


def write_private_text(path: Path, text: str) -> None:
    ensure_private_parent(path)
    if path.exists():
        chmod_best_effort(path, PRIVATE_FILE_MODE)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_FILE_MODE)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(text)
    chmod_best_effort(path, PRIVATE_FILE_MODE)


def append_private_text(path: Path, text: str) -> None:
    ensure_private_parent(path)
    if path.exists():
        chmod_best_effort(path, PRIVATE_FILE_MODE)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, PRIVATE_FILE_MODE)
    with os.fdopen(fd, "a", encoding="utf-8") as file:
        file.write(text)
    chmod_best_effort(path, PRIVATE_FILE_MODE)


def open_private_append(path: Path, *, binary: bool = False) -> IO[Any]:
    ensure_private_parent(path)
    if path.exists():
        chmod_best_effort(path, PRIVATE_FILE_MODE)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, PRIVATE_FILE_MODE)
    os.close(fd)
    chmod_best_effort(path, PRIVATE_FILE_MODE)
    if binary:
        return path.open("ab")
    return path.open("a", encoding="utf-8")


def write_json(path: Path, value: Any) -> None:
    write_private_text(path, json_line(value) + "\n")


def copy_private_file(source: Path, destination: Path) -> None:
    ensure_private_parent(destination)
    shutil.copy2(source, destination)
    chmod_best_effort(destination, PRIVATE_FILE_MODE)


def write_secret_json(path: Path, value: Any) -> None:
    write_json(path, value)


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
