import json
import unittest

from github_inbox_watch.state import empty_state
from github_inbox_watch.waybar import build_waybar_payload


class WaybarTests(unittest.TestCase):
    def test_waybar_normal_payload(self):
        payload = build_waybar_payload(empty_state())

        self.assertEqual(payload["text"], "")
        self.assertEqual(payload["class"], "clean")
        self.assertIn("No new", payload["tooltip"])

    def test_waybar_unseen_payload_lists_newest_threads(self):
        state = empty_state()
        state["threads"] = {
            "t1": {
                "thread_id": "t1",
                "repo": "owner/repo",
                "number": 1,
                "title": "First item",
                "url": "https://github.com/owner/repo/issues/1",
                "kind": "issue",
                "updated_at": "2026-05-18T12:00:00Z",
                "seen_at": "2026-05-18T11:00:00Z",
                "unseen": True,
            },
            "t2": {
                "thread_id": "t2",
                "repo": "owner/repo",
                "number": 2,
                "title": "Second item",
                "url": "https://github.com/owner/repo/pull/2",
                "kind": "pr",
                "updated_at": "2026-05-18T13:00:00Z",
                "seen_at": "2026-05-18T11:00:00Z",
                "unseen": True,
            },
        }
        state["unseen_count"] = 2

        payload = build_waybar_payload(state)

        self.assertEqual(payload["text"], " 2")
        self.assertEqual(payload["class"], "unseen")
        self.assertTrue(payload["tooltip"].splitlines()[0].startswith("owner/repo#2"))
        json.dumps(payload)

    def test_waybar_tooltip_item_limit_is_configurable(self):
        state = empty_state()
        state["threads"] = {
            f"t{idx}": {
                "thread_id": f"t{idx}",
                "repo": "owner/repo",
                "number": idx,
                "title": f"Item {idx}",
                "url": f"https://github.com/owner/repo/issues/{idx}",
                "kind": "issue",
                "updated_at": f"2026-05-18T1{idx}:00:00Z",
                "seen_at": "2026-05-18T10:00:00Z",
                "unseen": True,
            }
            for idx in range(1, 4)
        }
        state["unseen_count"] = 3

        payload = build_waybar_payload(state, max_tooltip_items=1)

        self.assertEqual(payload["text"], " 3")
        self.assertEqual(payload["tooltip"].splitlines(), ["owner/repo#3 — Item 3", "…and 2 more"])

    def test_waybar_error_payload_preserves_error_signal(self):
        state = empty_state()
        state["last_error"] = "gh failed"

        payload = build_waybar_payload(state)

        self.assertEqual(payload["text"], " !")
        self.assertEqual(payload["class"], "error")
        self.assertIn("gh failed", payload["tooltip"])


if __name__ == "__main__":
    unittest.main()
