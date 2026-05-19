"""Pure helpers for normalizing GitHub notification activity."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class ActivityItem:
    """A normalized issue or pull request activity item."""

    thread_id: str
    repo: str
    number: int
    title: str
    url: str
    kind: str
    updated_at: str
    github_unread: bool | None = None
    github_last_read_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_gh_json(stdout: str) -> list[Any]:
    """Parse JSON emitted by `gh api`, flattening `--paginate --slurp` pages.

    `gh api --paginate --slurp` commonly returns an array of page arrays. For
    non-paginated object responses, callers still get a one-item list.
    """

    text = stdout.strip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, list) and all(isinstance(page, list) for page in data):
        return [item for page in data for item in page]
    if isinstance(data, list):
        return data
    return [data]


def strip_api_host(url: str) -> str:
    """Convert a GitHub API URL to a path accepted by `gh api`."""

    parsed = urlparse(url)
    if parsed.netloc == "api.github.com":
        return parsed.path
    return url


def repo_from_html_url(url: str) -> str | None:
    """Extract owner/repo from a GitHub issue or PR HTML URL."""

    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return None


def repo_from_api_url(url: str) -> str | None:
    """Extract owner/repo from a GitHub REST API URL."""

    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 3 and parts[0] == "repos":
        return f"{parts[1]}/{parts[2]}"
    return None


def item_from_notification(
    notification: dict[str, Any],
    subject_detail: dict[str, Any],
    *,
    owner: str,
) -> ActivityItem | None:
    """Return a normalized item if this notification is relevant to `owner`.

    Relevant means: open Issue/PullRequest, authored by `owner`.
    """

    subject = notification.get("subject") or {}
    subject_type = subject.get("type")
    if subject_type not in {"Issue", "PullRequest"}:
        return None

    author = ((subject_detail.get("user") or {}).get("login") or "").lower()
    if author != owner.lower():
        return None

    if subject_detail.get("state") != "open":
        return None

    html_url = subject_detail.get("html_url") or subject.get("url")
    repo = (
        (notification.get("repository") or {}).get("full_name")
        or repo_from_html_url(html_url or "")
        or repo_from_api_url(subject.get("url") or "")
    )
    number = subject_detail.get("number")
    title = subject_detail.get("title") or subject.get("title")
    updated_at = notification.get("updated_at") or subject_detail.get("updated_at")
    thread_id = notification.get("id")

    if not all([repo, number, title, html_url, updated_at, thread_id]):
        return None

    kind = "pr" if subject_type == "PullRequest" else "issue"
    unread_value = notification.get("unread")
    last_read_at_value = notification.get("last_read_at")
    return ActivityItem(
        thread_id=str(thread_id),
        repo=str(repo),
        number=int(number),
        title=str(title),
        url=str(html_url),
        kind=kind,
        updated_at=str(updated_at),
        github_unread=unread_value if isinstance(unread_value, bool) else None,
        github_last_read_at=str(last_read_at_value) if last_read_at_value else None,
    )


def item_from_search_result(result: dict[str, Any], *, owner: str) -> ActivityItem | None:
    """Normalize a GitHub Search API issue/PR result for the watcher.

    Search can be opted into as a fallback because GitHub does not create
    notification threads for every action you take yourself, such as opening
    your own issue. It is not part of the default inbox-native mode.
    """

    author = ((result.get("user") or {}).get("login") or "").lower()
    if author != owner.lower():
        return None
    if result.get("state") != "open":
        return None

    html_url = result.get("html_url")
    repo = repo_from_api_url(result.get("repository_url") or "") or repo_from_html_url(html_url or "")
    number = result.get("number")
    title = result.get("title")
    updated_at = result.get("updated_at")
    kind = "pr" if result.get("pull_request") else "issue"

    if repo is None or number is None or not title or not html_url or not updated_at:
        return None

    number_int = int(str(number))
    return ActivityItem(
        thread_id=f"search:{kind}:{repo}#{number_int}",
        repo=str(repo),
        number=number_int,
        title=str(title),
        url=str(html_url),
        kind=kind,
        updated_at=str(updated_at),
    )


def sort_items_newest_first(items: list[ActivityItem]) -> list[ActivityItem]:
    """Sort items newest first by ISO timestamp string."""

    return sorted(items, key=lambda item: item.updated_at, reverse=True)
