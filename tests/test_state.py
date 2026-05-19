import unittest

from github_inbox_watch.core import ActivityItem
from github_inbox_watch.state import (
    empty_state,
    mark_seen,
    reconcile_items,
)


class StateTests(unittest.TestCase):
    def item(self, thread_id="t1", updated_at="2026-05-18T12:00:00Z"):
        return ActivityItem(
            thread_id=thread_id,
            repo="owner/repo",
            number=123,
            title="Something changed",
            url="https://github.com/owner/repo/issues/123",
            kind="issue",
            updated_at=updated_at,
        )

    def test_first_run_bootstraps_current_items_as_seen(self):
        state = empty_state()

        result = reconcile_items(state, [self.item()], bootstrap=True)

        self.assertEqual(result.unseen_count, 0)
        self.assertEqual(result.state["threads"]["t1"]["seen_at"], "2026-05-18T12:00:00Z")
        self.assertFalse(result.state["threads"]["t1"]["unseen"])

    def test_newer_update_counts_unseen_without_marking_seen(self):
        state = empty_state()
        state["threads"]["t1"] = {
            "thread_id": "t1",
            "repo": "owner/repo",
            "number": 123,
            "title": "Something changed",
            "url": "https://github.com/owner/repo/issues/123",
            "kind": "issue",
            "updated_at": "2026-05-18T12:00:00Z",
            "seen_at": "2026-05-18T12:00:00Z",
            "unseen": False,
        }

        result = reconcile_items(
            state,
            [self.item(updated_at="2026-05-18T13:00:00Z")],
            bootstrap=False,
        )

        thread = result.state["threads"]["t1"]
        self.assertEqual(result.unseen_count, 1)
        self.assertEqual(thread["updated_at"], "2026-05-18T13:00:00Z")
        self.assertEqual(thread["seen_at"], "2026-05-18T12:00:00Z")
        self.assertTrue(thread["unseen"])

    def test_remote_read_notification_clears_local_unseen_even_if_last_read_is_old(self):
        state = empty_state()
        state["threads"]["t1"] = {
            "thread_id": "t1",
            "repo": "owner/repo",
            "number": 123,
            "title": "Something changed",
            "url": "https://github.com/owner/repo/issues/123",
            "kind": "issue",
            "updated_at": "2026-05-19T00:09:52Z",
            "seen_at": "2026-05-19T00:00:00Z",
            "unseen": True,
        }
        item = ActivityItem(
            thread_id="t1",
            repo="owner/repo",
            number=123,
            title="Something changed",
            url="https://github.com/owner/repo/issues/123",
            kind="issue",
            updated_at="2026-05-19T00:09:52Z",
            github_unread=False,
            github_last_read_at="2026-05-19T00:07:15Z",
        )

        result = reconcile_items(state, [item], bootstrap=False)

        thread = result.state["threads"]["t1"]
        self.assertEqual(result.unseen_count, 0)
        self.assertFalse(thread["unseen"])
        self.assertEqual(thread["seen_at"], "2026-05-19T00:09:52Z")
        self.assertFalse(thread["github_unread"])
        self.assertEqual(thread["github_last_read_at"], "2026-05-19T00:07:15Z")

    def test_new_items_at_or_before_baseline_are_seeded_seen(self):
        result = reconcile_items(
            empty_state(),
            [
                self.item(thread_id="old", updated_at="2026-05-18T11:59:59Z"),
                self.item(thread_id="new", updated_at="2026-05-18T12:00:01Z"),
            ],
            bootstrap=False,
            new_item_baseline_at="2026-05-18T12:00:00Z",
        )

        self.assertFalse(result.state["threads"]["old"]["unseen"])
        self.assertEqual(result.state["threads"]["old"]["seen_at"], "2026-05-18T11:59:59Z")
        self.assertTrue(result.state["threads"]["new"]["unseen"])
        self.assertEqual(result.unseen_count, 1)

    def test_seen_state_carries_over_by_url_when_source_id_changes(self):
        state = empty_state()
        state["threads"]["search:issue:owner/repo#123"] = {
            "thread_id": "search:issue:owner/repo#123",
            "repo": "owner/repo",
            "number": 123,
            "title": "Something changed",
            "url": "https://github.com/owner/repo/issues/123",
            "kind": "issue",
            "updated_at": "2026-05-18T12:00:00Z",
            "seen_at": "2026-05-18T12:00:00Z",
            "unseen": False,
        }

        result = reconcile_items(
            state,
            [self.item(thread_id="notification-1", updated_at="2026-05-18T12:00:00Z")],
            bootstrap=False,
        )

        self.assertEqual(result.state["threads"]["notification-1"]["seen_at"], "2026-05-18T12:00:00Z")
        self.assertFalse(result.state["threads"]["notification-1"]["unseen"])

    def test_mark_seen_advances_seen_at_for_unseen_threads(self):
        state = empty_state()
        state["threads"]["t1"] = {
            "thread_id": "t1",
            "repo": "owner/repo",
            "number": 123,
            "title": "Something changed",
            "url": "https://github.com/owner/repo/issues/123",
            "kind": "issue",
            "updated_at": "2026-05-18T13:00:00Z",
            "seen_at": "2026-05-18T12:00:00Z",
            "unseen": True,
        }

        marked = mark_seen(state)

        self.assertEqual(marked["threads"]["t1"]["seen_at"], "2026-05-18T13:00:00Z")
        self.assertFalse(marked["threads"]["t1"]["unseen"])
        self.assertEqual(marked["unseen_count"], 0)


if __name__ == "__main__":
    unittest.main()
