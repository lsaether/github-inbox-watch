"""Waybar JSON payload rendering."""

from __future__ import annotations

import json
from typing import Any

GITHUB_ICON = ""


def _sorted_unseen_threads(state: dict[str, Any]) -> list[dict[str, Any]]:
    threads = [
        thread
        for thread in (state.get("threads") or {}).values()
        if thread.get("unseen")
    ]
    return sorted(threads, key=lambda thread: thread.get("updated_at") or "", reverse=True)


def build_waybar_payload(state: dict[str, Any], *, max_tooltip_items: int = 8) -> dict[str, str]:
    """Build a Waybar custom module JSON payload."""

    last_error = state.get("last_error")
    if last_error:
        return {
            "text": f"{GITHUB_ICON} !",
            "class": "error",
            "tooltip": f"GitHub inbox watch error:\n{last_error}",
        }

    unseen = _sorted_unseen_threads(state)
    count = int(state.get("unseen_count") or len(unseen))
    if count <= 0:
        return {
            "text": GITHUB_ICON,
            "class": "clean",
            "tooltip": "No new activity on open authored GitHub issues/PRs.",
        }

    lines = []
    for thread in unseen[:max_tooltip_items]:
        repo = thread.get("repo", "unknown/repo")
        number = thread.get("number", "?")
        title = thread.get("title", "Untitled")
        lines.append(f"{repo}#{number} — {title}")
    if count > len(lines):
        lines.append(f"…and {count - len(lines)} more")

    return {
        "text": f"{GITHUB_ICON} {count}",
        "class": "unseen",
        "tooltip": "\n".join(lines),
    }


def dumps_waybar_payload(state: dict[str, Any]) -> str:
    return json.dumps(build_waybar_payload(state), ensure_ascii=False)
