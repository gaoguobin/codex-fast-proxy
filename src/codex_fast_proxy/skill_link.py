from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path

from .core import ConfigError


SKILL_NAMESPACE = "codex-fast-proxy"


def skill_namespace_path(skills_root: str | Path | None = None) -> Path:
    root = Path(skills_root).expanduser() if skills_root else Path.home() / ".agents" / "skills"
    return root / SKILL_NAMESPACE


def skill_target_path(repo_root: str | Path) -> Path:
    return Path(repo_root).expanduser().resolve() / "skills"


def path_points_to(path: Path, target: Path) -> bool:
    try:
        return path.resolve(strict=True) == target.resolve(strict=True)
    except OSError:
        return False


def is_windows_platform() -> bool:
    return os.name == "nt"


def path_is_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    if is_junction:
        return bool(is_junction())
    if not is_windows_platform():
        return False
    try:
        attributes = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    except AttributeError:
        return False
    invalid_file_attributes = 0xFFFFFFFF
    file_attribute_directory = 0x10
    file_attribute_reparse_point = 0x400
    return bool(
        attributes != invalid_file_attributes
        and attributes & file_attribute_directory
        and attributes & file_attribute_reparse_point
    )


def link_skill_namespace(repo_root: str | Path, skills_root: str | Path | None = None) -> dict[str, str]:
    target = skill_target_path(repo_root)
    link = skill_namespace_path(skills_root)
    if not target.is_dir():
        raise ConfigError(f"Skill target does not exist: {target}")
    if link.exists() or link.is_symlink():
        if path_points_to(link, target):
            return {"status": "already_linked", "path": str(link), "target": str(target)}
        raise ConfigError(f"Skill namespace already exists and does not point to {target}: {link}")

    link.parent.mkdir(parents=True, exist_ok=True)
    if is_windows_platform():
        completed = subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise ConfigError(f"Failed to create skill namespace junction: {detail or completed.returncode}")
        link_type = "junction"
    else:
        link.symlink_to(target, target_is_directory=True)
        link_type = "symlink"
    return {"status": "linked", "path": str(link), "target": str(target), "link_type": link_type}


def unlink_skill_namespace(repo_root: str | Path, skills_root: str | Path | None = None) -> dict[str, str]:
    target = skill_target_path(repo_root)
    link = skill_namespace_path(skills_root)
    if not link.exists() and not link.is_symlink():
        return {"status": "missing", "path": str(link), "target": str(target)}
    if not path_points_to(link, target):
        raise ConfigError(f"Refusing to remove skill namespace with unexpected target: {link}")

    if link.is_symlink():
        link.unlink()
        link_type = "symlink"
    elif path_is_junction(link):
        link.rmdir()
        link_type = "junction"
    else:
        raise ConfigError(f"Refusing to remove skill namespace that is not a symlink or junction: {link}")
    return {"status": "unlinked", "path": str(link), "target": str(target), "link_type": link_type}
