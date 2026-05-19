import tempfile
import unittest
from pathlib import Path

from github_inbox_watch.cli import inbox_query_for_owner, inbox_url_for_owner, poll_once


class DummyClient:
    def __init__(self):
        self.search_called = False

    def authenticated_user(self):
        return "example-user"

    def notifications(self):
        return [
            {
                "id": "thread-1",
                "updated_at": "2026-05-18T13:00:00Z",
                "repository": {"full_name": "owner/repo"},
                "subject": {
                    "type": "Issue",
                    "url": "https://api.github.com/repos/owner/repo/issues/123",
                    "title": "Fallback title",
                },
            }
        ]

    def subject_detail(self, url):
        return {
            "user": {"login": "example-user"},
            "state": "open",
            "number": 123,
            "title": "Real title",
            "html_url": "https://github.com/owner/repo/issues/123",
        }

    def search_authored_open(self, owner) -> list[dict[str, object]]:
        self.search_called = True
        raise AssertionError("authored search should be opt-in, not default")


class CliUrlTests(unittest.TestCase):
    def test_inbox_url_uses_github_notification_filters_for_tracked_threads(self):
        self.assertEqual(inbox_query_for_owner("example-user"), "is:issue-or-pull-request author:example-user")
        self.assertEqual(
            inbox_url_for_owner("example-user"),
            "https://github.com/notifications?query=is%3Aissue-or-pull-request+author%3Aexample-user",
        )


class CliPollTests(unittest.TestCase):
    def test_poll_once_defaults_to_github_notifications_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client = DummyClient()
            state = poll_once(
                state_path=Path(tmpdir) / "state.json",
                cache_path=Path(tmpdir) / "cache.json",
                client=client,
            )

        self.assertFalse(client.search_called)
        self.assertEqual(state["unseen_count"], 0)
        self.assertEqual(list(state["threads"]), ["thread-1"])

    def test_poll_once_can_opt_into_authored_search_fallback(self):
        class SearchClient(DummyClient):
            def search_authored_open(self, owner):
                self.search_called = True
                return [
                    {
                        "number": 22,
                        "title": "smoke test",
                        "html_url": "https://github.com/example-user/example-repo/issues/22",
                        "repository_url": "https://api.github.com/repos/example-user/example-repo",
                        "updated_at": "2026-05-18T16:00:56Z",
                        "state": "open",
                        "user": {"login": "example-user"},
                    }
                ]

        with tempfile.TemporaryDirectory() as tmpdir:
            client = SearchClient()
            state = poll_once(
                state_path=Path(tmpdir) / "state.json",
                cache_path=Path(tmpdir) / "cache.json",
                client=client,
                include_authored_search=True,
            )

        self.assertTrue(client.search_called)
        self.assertEqual(
            set(state["threads"]),
            {"thread-1", "search:issue:example-user/example-repo#22"},
        )


if __name__ == "__main__":
    unittest.main()
