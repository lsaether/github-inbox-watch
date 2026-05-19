# github-inbox-watch

A tiny local watcher for GitHub activity on **open issues and pull requests you authored**, designed for Waybar.

It runs a small daemon, polls GitHub through the GitHub CLI (`gh`), and writes a local Waybar JSON cache. The widget shows a clean GitHub icon when there is nothing new, or a count when matching notification threads have new activity.

It tracks:

- open GitHub issues and pull requests authored by the configured owner
- GitHub notification threads where you are participating or mentioned
- GitHub's remote read/unread state, so reading a notification clears the widget on the next poll
- local seen state, so you can clear the widget without changing GitHub notification state

The default mode behaves like a GitHub Inbox filter, not a synthetic "everything you authored" feed. An optional Search fallback can broaden tracking to open authored issues/PRs that GitHub did not create notification threads for.

## Why it was built

GitHub already has notifications, but they live in a browser tab and mix a lot of different kinds of attention. This was built for a narrower desktop signal: "did something new happen on an open issue or PR you opened?"

The goal is to keep that signal ambient. No new app, no local web server, no token handling, and no noisy desktop popups. Just a small Waybar count that can sit next to the rest of your system status.

## How it works

`github-inbox-watch daemon` polls GitHub notifications with:

```bash
gh api -X GET /notifications -F all=true -F participating=true -F per_page=100 --paginate --slurp
```

For each notification thread, it fetches the issue/PR subject and keeps only items where:

- subject type is `Issue` or `PullRequest`
- subject state is `open`
- subject author is the configured owner, defaulting to the authenticated `gh` user

The notification thread `updated_at` timestamp is the V1 "something new happened" signal.

By default, the watcher does **not** synthesize activity from authored-item search results. GitHub notifications/subscriptions are the source of truth, so actions you take yourself, such as opening your own issue, do not appear unless GitHub itself creates a notification thread. This keeps the widget closer to a real GitHub inbox instead of a "things you just did" feed.

If you explicitly want the broader authored-item search behavior, opt in with `--include-authored-search` or `GITHUB_INBOX_WATCH_INCLUDE_AUTHORED_SEARCH=1`. When the search fallback is enabled on an existing state file, old authored backlog is seeded as already seen while items updated inside the current poll overlap window can still surface as unseen.

## Requirements

- Python 3.11+
- GitHub CLI: `gh`
- Authenticated GitHub CLI: `gh auth login`
- Linux desktop if using the Waybar/systemd examples

No Python runtime dependencies are required.

## Install from a local clone

Option A: editable Python install:

```bash
git clone https://github.com/OWNER/github-inbox-watch.git
cd github-inbox-watch
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

Option B: no packaging step; symlink the repo wrapper:

```bash
mkdir -p ~/.local/bin
ln -sfn /path/to/github-inbox-watch/bin/github-inbox-watch ~/.local/bin/github-inbox-watch
```

After either option, the CLI should be available as:

```bash
github-inbox-watch --help
```

## Commands

```bash
github-inbox-watch daemon
github-inbox-watch poll-once
github-inbox-watch waybar
github-inbox-watch status
github-inbox-watch inbox
github-inbox-watch open
github-inbox-watch mark-seen
github-inbox-watch reset
```

Useful options:

```bash
github-inbox-watch --owner YOUR_GITHUB_LOGIN poll-once
github-inbox-watch --poll-interval 30 daemon
github-inbox-watch --include-authored-search poll-once
github-inbox-watch status --json
github-inbox-watch --owner YOUR_GITHUB_LOGIN inbox --print-only
github-inbox-watch open --print-only
```

You can also set:

```bash
export GITHUB_INBOX_WATCH_OWNER=YOUR_GITHUB_LOGIN
export GITHUB_INBOX_WATCH_INTERVAL=30
export GITHUB_INBOX_WATCH_INCLUDE_AUTHORED_SEARCH=1
```

## Local state

Durable state:

```text
~/.local/state/github-inbox-watch/state.json
```

Waybar cache:

```text
~/.cache/github-inbox-watch/waybar.json
```

First run bootstraps current matching notification threads as seen, so you do not get a giant initial backlog. Later updates become unseen until you run `mark-seen`. State also stores `search_baseline_at` when the optional authored-search fallback is enabled; that prevents the fallback from surfacing old backlog when it first starts tracking more items than the notifications API returned.

To inspect that local state without polling GitHub or opening a browser, run:

```bash
github-inbox-watch status
github-inbox-watch status --json
```

`status` prints the unseen/tracked counts, last poll/error metadata when present, and the current unseen item or latest tracked item. The JSON mode emits the same summary fields for scripts.

## Waybar

Example module:

```json
"custom/github-inbox": {
  "exec": "github-inbox-watch waybar",
  "return-type": "json",
  "interval": 5,
  "on-click": "github-inbox-watch inbox",
  "on-click-right": "github-inbox-watch mark-seen"
}
```

Display states:

```text
      no new activity
 3    three unseen updates
 !    last poll had an error
```

The tooltip lists the newest unseen items.

Left-clicking the Waybar module should usually open GitHub Notifications with
the closest native inbox filter for the watcher:

```text
is:issue-or-pull-request author:YOUR_GITHUB_LOGIN
```

GitHub's inbox filter syntax does not currently support the issue/PR open-state
filter that the daemon applies locally after fetching subject details, so the
browser view may include closed authored threads that the widget itself ignores.

## systemd user service

Copy or symlink the example unit:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/github-inbox-watch.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now github-inbox-watch.service
```

Check logs:

```bash
journalctl --user -u github-inbox-watch.service -f
```

## Development

Run tests without installing extra dependencies:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Run a local smoke poll:

```bash
PYTHONPATH=src python -m github_inbox_watch.cli poll-once
PYTHONPATH=src python -m github_inbox_watch.cli waybar
```

## Roadmap / alpha non-goals

The alpha keeps the moving parts small on purpose: no webhooks, no exposed local HTTP server, no desktop notifications, and no token storage. Waybar reads a local cache file; the daemon talks to GitHub through `gh`.

Possible future work:

- webhook or push-style delivery for lower latency, if there is a clean local setup
- optional desktop notifications for high-signal events
- richer click actions, such as open newest item and mark local state seen in one step
- a broader authored-activity mode built on GitHub Search
- multi-account support
- a config file for users who outgrow environment variables and CLI flags

For now, GitHub notifications stay the default source of truth. The optional authored-item Search fallback is rate-limited separately from notifications. Keep it disabled if you want the widget to behave like a GitHub inbox rather than a synthetic authored-item activity feed.
