from contextlib import redirect_stdout
from io import StringIO
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from github_inbox_watch.cli import inbox_query_for_owner, inbox_url_for_owner, main, poll_once


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


class CliStatusTests(unittest.TestCase):
    def run_status(self, tmpdir: str, *extra_args: str) -> tuple[int, str]:
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "--state-path",
                    str(Path(tmpdir) / "state.json"),
                    "--cache-path",
                    str(Path(tmpdir) / "cache.json"),
                    "status",
                    *extra_args,
                ]
            )
        return code, stdout.getvalue()

    def write_state(self, tmpdir: str) -> None:
        state = {
            "version": 1,
            "threads": {
                "thread-older": {
                    "thread_id": "thread-older",
                    "repo": "owner/repo",
                    "number": 122,
                    "title": "Older update",
                    "url": "https://github.com/owner/repo/issues/122",
                    "kind": "issue",
                    "updated_at": "2026-05-18T13:00:00Z",
                    "seen_at": "2026-05-18T13:00:00Z",
                    "unseen": False,
                },
                "thread-newer": {
                    "thread_id": "thread-newer",
                    "repo": "owner/repo",
                    "number": 123,
                    "title": "New review comment",
                    "url": "https://github.com/owner/repo/pull/123",
                    "kind": "pr",
                    "updated_at": "2026-05-19T22:00:00Z",
                    "seen_at": "2026-05-19T21:00:00Z",
                    "unseen": True,
                },
            },
            "unseen_count": 1,
            "last_poll_at": "2026-05-19T22:01:00Z",
            "last_error": None,
            "search_baseline_at": None,
        }
        Path(tmpdir, "state.json").write_text(json.dumps(state), encoding="utf-8")

    def test_status_reports_empty_local_state_without_network(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            code, output = self.run_status(tmpdir)

        self.assertEqual(code, 0)
        self.assertEqual(output, "0 unseen; 0 tracked\n")

    def test_status_reports_current_unseen_thread_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.write_state(tmpdir)
            code, output = self.run_status(tmpdir)

        self.assertEqual(code, 0)
        self.assertIn("1 unseen; 2 tracked", output)
        self.assertIn("last poll: 2026-05-19T22:01:00Z", output)
        self.assertIn("unseen: pr owner/repo#123 New review comment", output)
        self.assertIn("updated: 2026-05-19T22:00:00Z", output)
        self.assertIn("https://github.com/owner/repo/pull/123", output)

    def test_status_json_outputs_stable_summary_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.write_state(tmpdir)
            code, output = self.run_status(tmpdir, "--json")

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["unseen_count"], 1)
        self.assertEqual(payload["tracked_count"], 2)
        self.assertEqual(payload["last_poll_at"], "2026-05-19T22:01:00Z")
        self.assertIsNone(payload["last_error"])
        self.assertEqual(payload["selected_label"], "unseen")
        self.assertEqual(payload["selected_thread"]["thread_id"], "thread-newer")

    def test_waybar_fallback_respects_env_tooltip_item_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "version": 1,
                "threads": {
                    "thread-older": {
                        "thread_id": "thread-older",
                        "repo": "owner/repo",
                        "number": 122,
                        "title": "Older unseen update",
                        "url": "https://github.com/owner/repo/issues/122",
                        "kind": "issue",
                        "updated_at": "2026-05-18T13:00:00Z",
                        "seen_at": "2026-05-18T12:00:00Z",
                        "unseen": True,
                    },
                    "thread-newer": {
                        "thread_id": "thread-newer",
                        "repo": "owner/repo",
                        "number": 123,
                        "title": "Newer unseen update",
                        "url": "https://github.com/owner/repo/pull/123",
                        "kind": "pr",
                        "updated_at": "2026-05-19T22:00:00Z",
                        "seen_at": "2026-05-19T21:00:00Z",
                        "unseen": True,
                    },
                },
                "unseen_count": 2,
                "last_poll_at": "2026-05-19T22:01:00Z",
                "last_error": None,
                "search_baseline_at": None,
            }
            Path(tmpdir, "state.json").write_text(json.dumps(state), encoding="utf-8")
            stdout = StringIO()
            with mock.patch.dict(os.environ, {"GITHUB_INBOX_WATCH_MAX_TOOLTIP_ITEMS": "1"}):
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--state-path",
                            str(Path(tmpdir) / "state.json"),
                            "--cache-path",
                            str(Path(tmpdir) / "missing-cache.json"),
                            "waybar",
                        ]
                    )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["text"], " 2")
        self.assertEqual(
            payload["tooltip"].splitlines(),
            ["owner/repo#123 — Newer unseen update", "…and 1 more"],
        )


if __name__ == "__main__":
    unittest.main()
