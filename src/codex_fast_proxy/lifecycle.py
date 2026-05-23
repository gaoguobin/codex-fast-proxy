from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import ProxyPaths
from .storage import ensure_private_dir, read_json, write_json


SCHEMA_VERSION = 1
TURN_STALE_SECONDS = 12 * 60 * 60
TURN_LOCK_STALE_SECONDS = 5.0
TURN_LOCK_POLL_INTERVAL = 0.05


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def monotonic_deadline(seconds: float) -> float:
    return time.monotonic() + max(seconds, 0.0)


def stale_timestamp(timestamp: Any, *, now: float | None = None) -> bool:
    if not isinstance(timestamp, (int, float)):
        return True
    return (time.time() if now is None else now) - float(timestamp) > TURN_STALE_SECONDS


def turn_lock_path(paths: ProxyPaths) -> Path:
    return paths.turns_path.with_suffix(paths.turns_path.suffix + ".lock")


def lock_is_stale(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime >= TURN_LOCK_STALE_SECONDS
    except OSError:
        return True


@contextmanager
def turn_state_lock(paths: ProxyPaths, timeout: float = 4.0) -> Iterator[bool]:
    ensure_private_dir(paths.state_dir)
    lock_path = turn_lock_path(paths)
    deadline = monotonic_deadline(timeout)
    while True:
        try:
            fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            if lock_is_stale(lock_path):
                lock_path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                yield False
                return
            time.sleep(TURN_LOCK_POLL_INTERVAL)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump({"pid": os.getpid(), "created_at": time.time()}, file)
            file.write("\n")
        yield True
    finally:
        lock_path.unlink(missing_ok=True)


def read_turn_state(paths: ProxyPaths) -> dict[str, Any]:
    try:
        data = read_json(paths.turns_path)
    except (OSError, json.JSONDecodeError):
        data = None
    if not isinstance(data, dict):
        return {"schema_version": SCHEMA_VERSION, "active_turns": {}}
    active_turns = data.get("active_turns")
    if not isinstance(active_turns, dict):
        data["active_turns"] = {}
    return data


def active_turn_items(data: dict[str, Any], *, now: float | None = None) -> dict[str, dict[str, Any]]:
    turns = data.get("active_turns")
    if not isinstance(turns, dict):
        return {}
    active: dict[str, dict[str, Any]] = {}
    for turn_id, item in turns.items():
        if not isinstance(turn_id, str) or not isinstance(item, dict):
            continue
        updated_at_epoch = item.get("updated_at_epoch") or item.get("started_at_epoch")
        if stale_timestamp(updated_at_epoch, now=now):
            continue
        active[turn_id] = item
    return active


def codex_activity(paths: ProxyPaths) -> dict[str, Any]:
    active = active_turn_items(read_turn_state(paths))
    return {
        "active_turns": len(active),
        "idle": not active,
        "turns": [
            {
                "turn_id": item.get("turn_id"),
                "started_at": item.get("started_at"),
                "updated_at": item.get("updated_at"),
            }
            for item in active.values()
        ],
    }


def codex_has_active_turns(paths: ProxyPaths) -> bool:
    return bool(codex_activity(paths)["active_turns"])


def record_codex_hook_event(paths: ProxyPaths, payload: dict[str, Any]) -> dict[str, Any]:
    event = payload.get("hook_event_name")
    turn_id = payload.get("turn_id")
    if event not in {"UserPromptSubmit", "Stop"} or not isinstance(turn_id, str) or not turn_id:
        return {"status": "ignored", "event": event}

    now_epoch = time.time()
    now_text = utc_now()
    with turn_state_lock(paths) as locked:
        if not locked:
            return {"status": "busy", "event": event}
        data = read_turn_state(paths)
        active = active_turn_items(data, now=now_epoch)
        if event == "UserPromptSubmit":
            active[turn_id] = {
                "turn_id": turn_id,
                "started_at": active.get(turn_id, {}).get("started_at") or now_text,
                "started_at_epoch": active.get(turn_id, {}).get("started_at_epoch") or now_epoch,
                "updated_at": now_text,
                "updated_at_epoch": now_epoch,
            }
        else:
            active.pop(turn_id, None)
        write_json(paths.turns_path, {
            "schema_version": SCHEMA_VERSION,
            "updated_at": now_text,
            "active_turns": active,
        })

    return {"status": "recorded", "event": event, **codex_activity(paths)}
