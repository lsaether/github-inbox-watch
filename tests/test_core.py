import unittest

from github_inbox_watch.core import (
    item_from_notification,
    item_from_search_result,
    parse_gh_json,
    sort_items_newest_first,
)


class CoreTests(unittest.TestCase):
    def notification(self, subject_type="Issue"):
        return {
            "id": "thread-1",
            "updated_at": "2026-05-18T13:00:00Z",
            "subject": {
                "type": subject_type,
                "url": "https://api.github.com/repos/owner/repo/issues/123",
                "title": "Fallback title",
            },
        }

    def subject(self, *, author="example-user", state="open", html_url=None):
        return {
            "user": {"login": author},
            "state": state,
            "number": 123,
            "title": "Real title",
            "html_url": html_url or "https://github.com/owner/repo/issues/123",
        }

    def test_item_from_notification_keeps_open_authored_issue(self):
        item = item_from_notification(self.notification(), self.subject(), owner="example-user")

        self.assertIsNotNone(item)
        self.assertEqual(item.thread_id, "thread-1")
        self.assertEqual(item.repo, "owner/repo")
        self.assertEqual(item.number, 123)
        self.assertEqual(item.title, "Real title")
        self.assertEqual(item.kind, "issue")

    def test_item_from_notification_preserves_remote_read_state(self):
        item = item_from_notification(
            {
                **self.notification(),
                "unread": False,
                "last_read_at": "2026-05-19T00:07:15Z",
            },
            self.subject(),
            owner="example-user",
        )

        self.assertIsNotNone(item)
        self.assertFalse(item.github_unread)
        self.assertEqual(item.github_last_read_at, "2026-05-19T00:07:15Z")

    def test_item_from_notification_keeps_open_authored_pr(self):
        item = item_from_notification(
            self.notification(subject_type="PullRequest"),
            self.subject(html_url="https://github.com/owner/repo/pull/123"),
            owner="example-user",
        )

        self.assertIsNotNone(item)
        self.assertEqual(item.kind, "pr")
        self.assertEqual(item.url, "https://github.com/owner/repo/pull/123")

    def test_item_from_notification_ignores_closed_or_non_authored_or_non_issue_subjects(self):
        self.assertIsNone(item_from_notification(self.notification(), self.subject(state="closed"), owner="example-user"))
        self.assertIsNone(item_from_notification(self.notification(), self.subject(author="someoneelse"), owner="example-user"))
        self.assertIsNone(item_from_notification(self.notification(subject_type="Commit"), self.subject(), owner="example-user"))

    def test_item_from_search_result_normalizes_self_authored_issue(self):
        item = item_from_search_result(
            {
                "number": 22,
                "title": "smoke test",
                "html_url": "https://github.com/example-user/example-repo/issues/22",
                "repository_url": "https://api.github.com/repos/example-user/example-repo",
                "updated_at": "2026-05-18T16:00:56Z",
                "state": "open",
                "user": {"login": "example-user"},
            },
            owner="example-user",
        )

        self.assertIsNotNone(item)
        self.assertEqual(item.thread_id, "search:issue:example-user/example-repo#22")
        self.assertEqual(item.repo, "example-user/example-repo")
        self.assertEqual(item.kind, "issue")

    def test_item_from_search_result_marks_prs_and_filters_irrelevant_items(self):
        result = {
            "number": 7,
            "title": "PR smoke",
            "html_url": "https://github.com/owner/repo/pull/7",
            "repository_url": "https://api.github.com/repos/owner/repo",
            "updated_at": "2026-05-18T16:00:56Z",
            "state": "open",
            "user": {"login": "example-user"},
            "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/7"},
        }

        self.assertEqual(item_from_search_result(result, owner="example-user").kind, "pr")
        self.assertIsNone(item_from_search_result({**result, "state": "closed"}, owner="example-user"))
        self.assertIsNone(item_from_search_result({**result, "user": {"login": "someoneelse"}}, owner="example-user"))

    def test_parse_gh_json_accepts_slurped_paginated_arrays(self):
        parsed = parse_gh_json('[[{"id": "1"}], [{"id": "2"}]]')
        self.assertEqual(parsed, [{"id": "1"}, {"id": "2"}])

    def test_sort_items_newest_first(self):
        newer = item_from_notification(self.notification(), self.subject(), owner="example-user")
        older = item_from_notification(
            {**self.notification(), "id": "thread-2", "updated_at": "2026-05-17T13:00:00Z"},
            {**self.subject(), "number": 124, "html_url": "https://github.com/owner/repo/issues/124"},
            owner="example-user",
        )

        self.assertEqual([item.thread_id for item in sort_items_newest_first([older, newer])], ["thread-1", "thread-2"])


if __name__ == "__main__":
    unittest.main()
