"""Command-line interface for github-inbox-watch."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlencode

from .core import item_from_notification, item_from_search_result
from .gh_client import GhClient, GhError
from .state import (
    default_cache_path,
    default_state_path,
    empty_state,
    load_state,
    mark_seen,
    newest_thread,
    reconcile_items,
    save_state,
    write_json_atomic,
)
from .waybar import (
    DEFAULT_MAX_TOOLTIP_ITEMS,
    build_waybar_payload,
    dumps_waybar_payload,
)


class PollError(RuntimeError):
    """Raised when a poll fails after state/cache are updated with error info."""


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _default_max_tooltip_items() -> int:
    raw = os.environ.get("GITHUB_INBOX_WATCH_MAX_TOOLTIP_ITEMS")
    if not raw:
        return DEFAULT_MAX_TOOLTIP_ITEMS
    try:
        return _non_negative_int(raw)
    except argparse.ArgumentTypeError:
        return DEFAULT_MAX_TOOLTIP_ITEMS


def _parse_github_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _format_github_time(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def search_baseline_for_state(state: dict[str, Any], *, overlap_minutes: int = 10) -> str:
    """Return the timestamp used to decide if newly discovered search items are old.

    Existing installs did not have the search fallback. When enabling it, use a
    small overlap before the last successful poll so a self-created issue from
    the current test window still appears while older authored backlog is seeded
    as already seen.
    """

    existing = state.get("search_baseline_at")
    if existing:
        return str(existing)
    last_poll_at = state.get("last_poll_at")
    if last_poll_at:
        try:
            return _format_github_time(_parse_github_time(str(last_poll_at)) - timedelta(minutes=overlap_minutes))
        except ValueError:
            pass
    return _format_github_time(datetime.now(UTC))


def _dedupe_items_by_url(items: list[Any]) -> list[Any]:
    by_url: dict[str, Any] = {}
    for item in items:
        by_url.setdefault(item.url, item)
    return list(by_url.values())


def resolve_owner(owner: str | None, client: GhClient) -> str:
    return owner or os.environ.get("GITHUB_INBOX_WATCH_OWNER") or client.authenticated_user()


def inbox_query_for_owner(owner: str) -> str:
    """Return the closest GitHub Inbox filter query for tracked notifications.

    GitHub Inbox supports filtering notification threads by original thread
    author and by issue-or-pull-request type. It does not support the issue/PR
    open-state filter that this watcher applies locally after fetching subject
    details.
    """

    return f"is:issue-or-pull-request author:{owner}"


def inbox_url_for_owner(owner: str) -> str:
    return "https://github.com/notifications?" + urlencode({"query": inbox_query_for_owner(owner)})


def write_cache(
    cache_path: Path,
    state: dict[str, Any],
    *,
    max_tooltip_items: int = DEFAULT_MAX_TOOLTIP_ITEMS,
) -> None:
    write_json_atomic(
        cache_path,
        build_waybar_payload(state, max_tooltip_items=max_tooltip_items),
    )


def poll_once(
    *,
    state_path: Path,
    cache_path: Path,
    owner: str | None = None,
    client: GhClient | None = None,
    include_authored_search: bool = False,
    max_tooltip_items: int = DEFAULT_MAX_TOOLTIP_ITEMS,
) -> dict[str, Any]:
    """Poll GitHub once, update state/cache, and return the new state."""

    client = client or GhClient()
    bootstrap = not state_path.exists()
    state = load_state(state_path)

    try:
        resolved_owner = resolve_owner(owner, client)
        notifications = client.notifications()
        items = []
        for notification in notifications:
            subject = notification.get("subject") or {}
            subject_url = subject.get("url")
            if subject.get("type") not in {"Issue", "PullRequest"} or not subject_url:
                continue
            detail = client.subject_detail(subject_url)
            item = item_from_notification(notification, detail, owner=resolved_owner)
            if item is not None:
                items.append(item)
        search_baseline_at = None
        if include_authored_search:
            for search_result in client.search_authored_open(resolved_owner):
                item = item_from_search_result(search_result, owner=resolved_owner)
                if item is not None:
                    items.append(item)
            search_baseline_at = search_baseline_for_state(state)
        items = _dedupe_items_by_url(items)
        result = reconcile_items(
            state,
            items,
            bootstrap=bootstrap,
            new_item_baseline_at=search_baseline_at,
        )
        save_state(state_path, result.state)
        write_cache(cache_path, result.state, max_tooltip_items=max_tooltip_items)
        return result.state
    except Exception as exc:  # noqa: BLE001 - CLI should preserve old state on all poll errors.
        error_state = empty_state()
        error_state.update(state)
        error_state["last_error"] = str(exc)
        save_state(state_path, error_state)
        write_cache(cache_path, error_state, max_tooltip_items=max_tooltip_items)
        raise PollError(str(exc)) from exc


def command_daemon(args: argparse.Namespace) -> int:
    client = GhClient(args.gh_binary)
    while True:
        try:
            state = poll_once(
                state_path=args.state_path,
                cache_path=args.cache_path,
                owner=args.owner,
                client=client,
                include_authored_search=args.include_authored_search,
                max_tooltip_items=args.max_tooltip_items,
            )
            print(
                f"poll ok: {state.get('unseen_count', 0)} unseen, "
                f"{len(state.get('threads') or {})} tracked",
                flush=True,
            )
        except PollError as exc:
            print(f"poll error: {exc}", file=sys.stderr, flush=True)
        time.sleep(args.poll_interval)


def command_poll_once(args: argparse.Namespace) -> int:
    try:
        state = poll_once(
            state_path=args.state_path,
            cache_path=args.cache_path,
            owner=args.owner,
            client=GhClient(args.gh_binary),
            include_authored_search=args.include_authored_search,
            max_tooltip_items=args.max_tooltip_items,
        )
    except PollError as exc:
        print(f"poll error: {exc}", file=sys.stderr)
        return 1
    print(f"{state.get('unseen_count', 0)} unseen; {len(state.get('threads') or {})} tracked")
    return 0


def command_waybar(args: argparse.Namespace) -> int:
    if args.cache_path.exists():
        print(args.cache_path.read_text(encoding="utf-8").strip())
        return 0
    print(dumps_waybar_payload(load_state(args.state_path), max_tooltip_items=args.max_tooltip_items))
    return 0


def command_mark_seen(args: argparse.Namespace) -> int:
    state = load_state(args.state_path)
    before = int(state.get("unseen_count") or 0)
    state = mark_seen(state)
    save_state(args.state_path, state)
    write_cache(args.cache_path, state, max_tooltip_items=args.max_tooltip_items)
    print(f"marked {before} item(s) seen")
    return 0


def status_summary(state: dict[str, Any]) -> dict[str, Any]:
    """Return a stable local status summary for humans and scripts."""

    threads = state.get("threads") or {}
    selected_thread = newest_thread(state, unseen_only=True) or newest_thread(state)
    selected_label = None
    if selected_thread is not None:
        selected_label = "unseen" if selected_thread.get("unseen") else "latest"
    return {
        "unseen_count": int(state.get("unseen_count") or 0),
        "tracked_count": len(threads),
        "last_poll_at": state.get("last_poll_at"),
        "last_error": state.get("last_error"),
        "selected_label": selected_label,
        "selected_thread": selected_thread,
    }


def command_status(args: argparse.Namespace) -> int:
    """Print a local state summary without talking to GitHub."""

    summary = status_summary(load_state(args.state_path))
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    print(f"{summary['unseen_count']} unseen; {summary['tracked_count']} tracked")
    if summary["last_poll_at"]:
        print(f"last poll: {summary['last_poll_at']}")
    if summary["last_error"]:
        print(f"last error: {summary['last_error']}")

    thread = summary["selected_thread"]
    if thread is not None:
        kind = thread.get("kind") or "item"
        repo = thread.get("repo") or "unknown/repo"
        number = thread.get("number") or "?"
        title = thread.get("title") or "untitled"
        print(f"{summary['selected_label']}: {kind} {repo}#{number} {title}")
        if thread.get("updated_at"):
            print(f"updated: {thread['updated_at']}")
        if thread.get("url"):
            print(str(thread["url"]))
    return 0


def _open_url(url: str) -> None:
    opener = os.environ.get("BROWSER")
    if opener:
        subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def command_open(args: argparse.Namespace) -> int:
    state = load_state(args.state_path)
    thread = newest_thread(state, unseen_only=True) or newest_thread(state)
    if thread is None:
        print("no tracked GitHub inbox items")
        return 1
    url = str(thread.get("url") or "")
    if not url:
        print("newest item has no URL", file=sys.stderr)
        return 1
    if args.print_only:
        print(url)
    else:
        _open_url(url)
    return 0


def command_inbox(args: argparse.Namespace) -> int:
    client = GhClient(args.gh_binary)
    url = inbox_url_for_owner(resolve_owner(args.owner, client))
    if args.print_only:
        print(url)
    else:
        _open_url(url)
    return 0


def command_reset(args: argparse.Namespace) -> int:
    removed = 0
    for path in (args.state_path, args.cache_path):
        if path.exists():
            path.unlink()
            removed += 1
    print(f"removed {removed} file(s)")
    return 0


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--owner", help="GitHub login to treat as author; defaults to current `gh` user")
    parser.add_argument("--gh-binary", default="gh", help="Path/name for GitHub CLI binary")
    parser.add_argument(
        "--state-path",
        type=Path,
        default=default_state_path(),
        help="Path to durable state JSON",
    )
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=default_cache_path(),
        help="Path to Waybar cache JSON",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=int(os.environ.get("GITHUB_INBOX_WATCH_INTERVAL", "30")),
        help="Polling interval in seconds for daemon mode",
    )
    parser.add_argument(
        "--include-authored-search",
        action="store_true",
        default=os.environ.get("GITHUB_INBOX_WATCH_INCLUDE_AUTHORED_SEARCH", "").lower()
        in {"1", "true", "yes", "on"},
        help="Also search open authored issues/PRs. Off by default so GitHub notifications remain source of truth.",
    )
    parser.add_argument(
        "--max-tooltip-items",
        type=_non_negative_int,
        default=_default_max_tooltip_items(),
        help=(
            "Maximum unseen items to include in the generated Waybar tooltip "
            "(env: GITHUB_INBOX_WATCH_MAX_TOOLTIP_ITEMS; default: 8)."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="github-inbox-watch",
        description="Watch GitHub notifications for activity on open issues/PRs authored by you.",
    )
    add_common_options(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    daemon = sub.add_parser("daemon", help="Run continuous 30s polling loop")
    daemon.set_defaults(func=command_daemon)

    poll_once_parser = sub.add_parser("poll-once", help="Poll once and update state/cache")
    poll_once_parser.set_defaults(func=command_poll_once)

    waybar = sub.add_parser("waybar", help="Print cached Waybar JSON without network calls")
    waybar.set_defaults(func=command_waybar)

    open_parser = sub.add_parser("open", help="Open newest unseen item, or newest tracked item")
    open_parser.add_argument("--print-only", action="store_true", help="Print URL instead of opening it")
    open_parser.set_defaults(func=command_open)

    inbox_parser = sub.add_parser("inbox", help="Open GitHub Notifications with the watcher's inbox filters")
    inbox_parser.add_argument("--print-only", action="store_true", help="Print URL instead of opening it")
    inbox_parser.set_defaults(func=command_inbox)

    mark = sub.add_parser("mark-seen", help="Mark all current unseen items as seen")
    mark.set_defaults(func=command_mark_seen)

    status = sub.add_parser("status", help="Print local inbox-watch state without network calls")
    status.add_argument("--json", action="store_true", help="Print a machine-readable status summary")
    status.set_defaults(func=command_status)

    reset = sub.add_parser("reset", help="Delete state/cache files")
    reset.set_defaults(func=command_reset)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
