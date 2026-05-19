"""Small `gh` CLI adapter.

The project intentionally shells out to GitHub CLI so it never stores or parses
GitHub tokens itself.
"""

from __future__ import annotations

import subprocess
from typing import Any

from .core import parse_gh_json, strip_api_host


class GhError(RuntimeError):
    """Raised when `gh` fails."""


def _stringify_field(name: str, value: str | int | bool) -> str:
    if isinstance(value, bool):
        rendered = "true" if value else "false"
    else:
        rendered = str(value)
    return f"{name}={rendered}"


class GhClient:
    """Minimal GitHub API client backed by `gh api`."""

    def __init__(self, gh_binary: str = "gh") -> None:
        self.gh_binary = gh_binary

    def _run(self, args: list[str]) -> str:
        proc = subprocess.run(
            [self.gh_binary, *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            message = proc.stderr.strip() or proc.stdout.strip() or f"gh exited {proc.returncode}"
            raise GhError(message)
        return proc.stdout

    def authenticated_user(self) -> str:
        return self._run(["api", "user", "--jq", ".login"]).strip()

    def api_json(
        self,
        endpoint: str,
        *,
        fields: dict[str, str | int | bool] | None = None,
        paginate: bool = False,
    ) -> list[Any]:
        args = ["api", "-X", "GET", strip_api_host(endpoint)]
        for name, value in (fields or {}).items():
            args.extend(["-F", _stringify_field(name, value)])
        if paginate:
            args.extend(["--paginate", "--slurp"])
        return parse_gh_json(self._run(args))

    def notifications(self) -> list[dict[str, Any]]:
        data = self.api_json(
            "/notifications",
            fields={"all": True, "participating": True, "per_page": 100},
            paginate=True,
        )
        return [item for item in data if isinstance(item, dict)]

    def search_authored_open(self, owner: str, *, limit: int = 300) -> list[dict[str, Any]]:
        """Search open issues/PRs authored by owner, newest updates first."""

        query = f"is:open author:{owner} archived:false"
        data = self.api_json(
            "/search/issues",
            fields={"q": query, "sort": "updated", "order": "desc", "per_page": 100},
            paginate=True,
        )
        results: list[dict[str, Any]] = []
        for page in data:
            if isinstance(page, dict):
                items = page.get("items") or []
                results.extend(item for item in items if isinstance(item, dict))
            elif isinstance(page, list):
                results.extend(item for item in page if isinstance(item, dict))
            if len(results) >= limit:
                break
        return results[:limit]

    def subject_detail(self, url: str) -> dict[str, Any]:
        data = self.api_json(url)
        if data and isinstance(data[0], dict):
            return data[0]
        return {}
