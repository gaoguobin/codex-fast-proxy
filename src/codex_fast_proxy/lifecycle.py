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
RECENT_EVENT_LIMIT = 20
TURN_EVENTS = {"UserPromptSubmit", "Stop"}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc_timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


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


def text_field(payload: dict[str, Any], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def nested_hook_output(payload: dict[str, Any]) -> dict[str, Any]:
    for name in ("hookSpecificOutput", "hook_specific_output"):
        value = payload.get(name)
        if isinstance(value, dict):
            return value
    return {}


def hook_event_name(payload: dict[str, Any]) -> str | None:
    return text_field(payload, ("hook_event_name", "hookEventName", "event")) or text_field(
        nested_hook_output(payload),
        ("hook_event_name", "hookEventName", "event"),
    )


def hook_turn_id(payload: dict[str, Any]) -> str | None:
    return text_field(payload, ("turn_id", "turnId"))


def hook_session_id(payload: dict[str, Any]) -> str | None:
    return text_field(payload, ("session_id", "sessionId", "thread_id", "threadId"))


def turn_key(session_id: str | None, turn_id: str) -> str:
    return f"{session_id}:{turn_id}" if session_id else turn_id


def payload_field_names(payload: dict[str, Any]) -> list[str]:
    return sorted(key for key in payload if isinstance(key, str))


def event_entry(
    *,
    event: str | None,
    status: str,
    reason: str | None,
    payload: dict[str, Any] | None,
    session_id: str | None = None,
    turn_id: str | None = None,
    key: str | None = None,
    now_text: str | None = None,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "event": event,
        "status": status,
        "reason": reason,
        "recorded_at": now_text or utc_now(),
        "recorded_at_epoch": now_epoch if now_epoch is not None else time.time(),
        "session_id": session_id,
        "turn_id": turn_id,
        "turn_key": key,
    }
    if payload is not None:
        entry["payload_fields"] = payload_field_names(payload)
    return entry


def append_recent_event(data: dict[str, Any], entry: dict[str, Any]) -> None:
    recent = data.get("recent_events")
    if not isinstance(recent, list):
        recent = []
    recent.append(entry)
    data["last_event"] = entry
    data["recent_events"] = recent[-RECENT_EVENT_LIMIT:]


def event_epoch(entry: dict[str, Any]) -> float | None:
    value = entry.get("recorded_at_epoch")
    if isinstance(value, (int, float)):
        return float(value)
    return parse_utc_timestamp(entry.get("recorded_at"))


def latest_session_stop_epochs(data: dict[str, Any]) -> dict[str, float]:
    recent = data.get("recent_events")
    if not isinstance(recent, list):
        return {}
    latest: dict[str, float] = {}
    for entry in recent:
        if not isinstance(entry, dict) or entry.get("event") != "Stop" or entry.get("status") != "recorded":
            continue
        session_id = entry.get("session_id")
        epoch = event_epoch(entry)
        if not isinstance(session_id, str) or epoch is None:
            continue
        latest[session_id] = max(latest.get(session_id, 0.0), epoch)
    return latest


def active_turn_items(data: dict[str, Any], *, now: float | None = None) -> dict[str, dict[str, Any]]:
    turns = data.get("active_turns")
    if not isinstance(turns, dict):
        return {}
    stopped_sessions = latest_session_stop_epochs(data)
    active: dict[str, dict[str, Any]] = {}
    for turn_id, item in turns.items():
        if not isinstance(turn_id, str) or not isinstance(item, dict):
            continue
        updated_at_epoch = item.get("updated_at_epoch") or item.get("started_at_epoch")
        if stale_timestamp(updated_at_epoch, now=now):
            continue
        session_id = item.get("session_id")
        if isinstance(session_id, str) and stopped_sessions.get(session_id, 0.0) >= float(updated_at_epoch):
            continue
        active[turn_id] = item
    return active


def remove_session_turns(active: dict[str, dict[str, Any]], session_id: str | None) -> None:
    if not session_id:
        return
    for key, item in list(active.items()):
        if item.get("session_id") == session_id:
            active.pop(key, None)


def codex_activity(paths: ProxyPaths) -> dict[str, Any]:
    data = read_turn_state(paths)
    active = active_turn_items(data)
    last_event = data.get("last_event")
    return {
        "active_turns": len(active),
        "idle": not active,
        "last_event": last_event if isinstance(last_event, dict) else None,
        "turns": [
            {
                "session_id": item.get("session_id"),
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
    event = hook_event_name(payload)
    session_id = hook_session_id(payload)
    turn_id = hook_turn_id(payload)
    now_epoch = time.time()
    now_text = utc_now()
    key = turn_key(session_id, turn_id) if turn_id else None
    status = "recorded"
    reason = None
    if event not in TURN_EVENTS:
        status = "ignored"
        reason = "unsupported_event"
    elif not turn_id:
        status = "ignored"
        reason = "missing_turn_id"

    with turn_state_lock(paths) as locked:
        if not locked:
            return {"status": "busy", "event": event}
        data = read_turn_state(paths)
        active = active_turn_items(data, now=now_epoch)
        if status == "recorded" and turn_id and key:
            if event == "UserPromptSubmit":
                previous = active.pop(key, None)
                if key != turn_id:
                    previous = previous or active.pop(turn_id, None)
                remove_session_turns(active, session_id)
                previous = previous or {}
                active[key] = {
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "turn_key": key,
                    "started_at": previous.get("started_at") or now_text,
                    "started_at_epoch": previous.get("started_at_epoch") or now_epoch,
                    "updated_at": now_text,
                    "updated_at_epoch": now_epoch,
                }
            else:
                active.pop(key, None)
                if key != turn_id:
                    active.pop(turn_id, None)
                remove_session_turns(active, session_id)
        next_state = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": now_text,
            "active_turns": active,
            "recent_events": data.get("recent_events") if isinstance(data.get("recent_events"), list) else [],
        }
        append_recent_event(next_state, event_entry(
            event=event,
            status=status,
            reason=reason,
            payload=payload,
            session_id=session_id,
            turn_id=turn_id,
            key=key,
            now_text=now_text,
            now_epoch=now_epoch,
        ))
        write_json(paths.turns_path, next_state)

    return {"status": status, "event": event, "reason": reason, **codex_activity(paths)}


def record_codex_hook_error(paths: ProxyPaths, *, reason: str) -> dict[str, Any]:
    now_epoch = time.time()
    now_text = utc_now()
    with turn_state_lock(paths) as locked:
        if not locked:
            return {"status": "busy", "event": None}
        data = read_turn_state(paths)
        active = active_turn_items(data)
        next_state = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": now_text,
            "active_turns": active,
            "recent_events": data.get("recent_events") if isinstance(data.get("recent_events"), list) else [],
        }
        append_recent_event(next_state, event_entry(
            event=None,
            status="error",
            reason=reason,
            payload=None,
            now_text=now_text,
            now_epoch=now_epoch,
        ))
        write_json(paths.turns_path, next_state)
    return {"status": "error", "reason": reason, **codex_activity(paths)}


def clear_codex_active_turns(paths: ProxyPaths, *, reason: str) -> dict[str, Any]:
    now_epoch = time.time()
    now_text = utc_now()
    with turn_state_lock(paths) as locked:
        if not locked:
            return {"status": "busy", "cleared": 0}
        data = read_turn_state(paths)
        active = active_turn_items(data, now=now_epoch)
        next_state = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": now_text,
            "active_turns": {},
            "recent_events": data.get("recent_events") if isinstance(data.get("recent_events"), list) else [],
        }
        append_recent_event(next_state, event_entry(
            event="ManualClear",
            status="recorded",
            reason=reason,
            payload=None,
            now_text=now_text,
            now_epoch=now_epoch,
        ))
        write_json(paths.turns_path, next_state)
    return {"status": "recorded", "reason": reason, "cleared": len(active), **codex_activity(paths)}
