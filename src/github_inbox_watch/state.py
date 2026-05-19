"""State and cache helpers for github-inbox-watch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any

from .core import ActivityItem, sort_items_newest_first

STATE_VERSION = 1


@dataclass(frozen=True)
class ReconcileResult:
    state: dict[str, Any]
    unseen_count: int


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_state_path() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "github-inbox-watch" / "state.json"


def default_cache_path() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "github-inbox-watch" / "waybar.json"


def empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "threads": {},
        "unseen_count": 0,
        "last_poll_at": None,
        "last_error": None,
        "search_baseline_at": None,
    }


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_state()
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return empty_state()
    state = empty_state()
    state.update(data)
    if not isinstance(state.get("threads"), dict):
        state["threads"] = {}
    return state


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(path)


def save_state(path: Path, state: dict[str, Any]) -> None:
    write_json_atomic(path, state)


def thread_from_item(item: ActivityItem, *, seen_at: str, unseen: bool) -> dict[str, Any]:
    thread = item.to_dict()
    thread["seen_at"] = seen_at
    thread["unseen"] = unseen
    return thread


def reconcile_items(
    state: dict[str, Any],
    items: list[ActivityItem],
    *,
    bootstrap: bool,
    now: str | None = None,
    new_item_baseline_at: str | None = None,
) -> ReconcileResult:
    """Merge a fresh poll into state and compute local unseen status.

    `bootstrap=True` treats every current item as seen. Later polls mark new
    threads or newer thread timestamps as unseen until `mark_seen` is called.
    If `new_item_baseline_at` is set, newly discovered items at or before that
    timestamp are seeded as seen so enabling a broader source does not surface
    an old authored backlog.
    """

    old_threads = state.get("threads") or {}
    old_threads_by_url = {
        str(thread.get("url")): thread
        for thread in old_threads.values()
        if isinstance(thread, dict) and thread.get("url")
    }
    next_threads: dict[str, Any] = {}

    for item in sort_items_newest_first(items):
        previous = old_threads.get(item.thread_id) or old_threads_by_url.get(item.url) or {}
        if bootstrap or item.github_unread is False:
            seen_at = item.updated_at
        else:
            seen_at = str(previous.get("seen_at") or "")
            if not seen_at and new_item_baseline_at and item.updated_at <= new_item_baseline_at:
                seen_at = item.updated_at

        unseen = False if bootstrap or item.github_unread is False else not seen_at or item.updated_at > seen_at
        next_threads[item.thread_id] = thread_from_item(
            item,
            seen_at=seen_at,
            unseen=unseen,
        )

    next_state = empty_state()
    next_state.update(state)
    next_state["version"] = STATE_VERSION
    next_state["threads"] = next_threads
    next_state["unseen_count"] = sum(1 for thread in next_threads.values() if thread.get("unseen"))
    next_state["last_poll_at"] = now or utc_now()
    next_state["last_error"] = None
    if new_item_baseline_at and not next_state.get("search_baseline_at"):
        next_state["search_baseline_at"] = new_item_baseline_at
    return ReconcileResult(state=next_state, unseen_count=int(next_state["unseen_count"]))


def mark_seen(state: dict[str, Any]) -> dict[str, Any]:
    next_state = empty_state()
    next_state.update(state)
    threads = {}
    for thread_id, thread in (state.get("threads") or {}).items():
        updated = dict(thread)
        updated["seen_at"] = updated.get("updated_at") or updated.get("seen_at") or utc_now()
        updated["unseen"] = False
        threads[thread_id] = updated
    next_state["threads"] = threads
    next_state["unseen_count"] = 0
    return next_state


def newest_thread(state: dict[str, Any], *, unseen_only: bool = False) -> dict[str, Any] | None:
    threads = list((state.get("threads") or {}).values())
    if unseen_only:
        threads = [thread for thread in threads if thread.get("unseen")]
    if not threads:
        return None
    return sorted(threads, key=lambda thread: thread.get("updated_at") or "", reverse=True)[0]
