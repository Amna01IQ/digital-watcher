"""
Digital Watcher agent.

Sense  -> download each configured website's text.
Decide -> compare it with the snapshot taken closest to 24 hours ago.
Act    -> notify the user by Email / Telegram with what changed.

Each site keeps a rolling history of snapshots (one per run) under
snapshots/<site>/<unix-timestamp>.txt, covering at least the last 48
hours. This lets every run - daily, instant, or manually triggered -
report "what changed in the last 24 hours" instead of just "what
changed since the last run".

Run with: python agent/check_sites.py
(from the repository root, as GitHub Actions does).
"""
import hashlib
import json
import os
import time
from pathlib import Path

from fetcher import fetch_text
from notifier import send_email, send_telegram

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
SNAPSHOTS_DIR = ROOT / "snapshots"

MAX_CHANGED_LINES = 15
TARGET_AGE_HOURS = 24
SNAPSHOT_RETENTION_HOURS = 48


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def site_dir(url):
    # Hash the URL so it's always a safe, unique folder name.
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    path = SNAPSHOTS_DIR / digest
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_snapshots(directory):
    """Return (timestamp, path) pairs for this site, oldest first."""
    snapshots = []
    for file in directory.glob("*.txt"):
        try:
            snapshots.append((int(file.stem), file))
        except ValueError:
            continue
    snapshots.sort(key=lambda pair: pair[0])
    return snapshots


def pick_reference_snapshot(snapshots, now_ts):
    """Pick the snapshot closest to 24h ago. Falls back to the oldest one
    available if we don't have 24 hours of history yet."""
    target_ts = now_ts - TARGET_AGE_HOURS * 3600
    oldest_ts, oldest_path = snapshots[0]
    if oldest_ts > target_ts:
        return oldest_path, True  # not enough history yet - fall back to oldest
    closest = min(snapshots, key=lambda pair: abs(pair[0] - target_ts))
    return closest[1], False


def save_snapshot(directory, now_ts, lines):
    (directory / f"{now_ts}.txt").write_text("\n".join(lines), encoding="utf-8")


def prune_old_snapshots(directory, now_ts):
    cutoff = now_ts - SNAPSHOT_RETENTION_HOURS * 3600
    for ts, path in list_snapshots(directory):
        if ts < cutoff:
            path.unlink()


def check_site(site, now_ts):
    label = site.get("label") or site["url"]
    url = site["url"]
    directory = site_dir(url)
    existing_snapshots = list_snapshots(directory)

    try:
        new_lines = fetch_text(url)
    except Exception as exc:
        return {"label": label, "url": url, "status": "error", "error": str(exc)}

    if not existing_snapshots:
        save_snapshot(directory, now_ts, new_lines)
        return {"label": label, "url": url, "status": "new"}

    reference_path, is_fallback = pick_reference_snapshot(existing_snapshots, now_ts)
    reference_lines = reference_path.read_text(encoding="utf-8").splitlines()

    save_snapshot(directory, now_ts, new_lines)
    prune_old_snapshots(directory, now_ts)

    added = [line for line in new_lines if line not in reference_lines]
    if added:
        return {
            "label": label,
            "url": url,
            "status": "changed",
            "changed_lines": added[:MAX_CHANGED_LINES],
            "changed_count": len(added),
            "fallback": is_fallback,
        }

    return {"label": label, "url": url, "status": "unchanged"}


def build_message(config, results):
    """Decide whether a notification is needed, and build its subject/body."""
    changed = [r for r in results if r["status"] == "changed"]
    new_sites = [r for r in results if r["status"] == "new"]
    errors = [r for r in results if r["status"] == "error"]
    mode = config.get("mode", "daily")

    # Every site is brand new -> this is the very first check ever.
    if new_sites and len(new_sites) == len(results):
        lines = ["Digital Watcher is now monitoring your websites.", ""]
        for r in new_sites:
            lines.append(f"- {r['label']} ({r['url']})")
        if errors:
            lines.append("")
            lines.append("Could not reach these sites (will retry next check):")
            for r in errors:
                lines.append(f"- {r['label']} ({r['url']}): {r['error']}")
        return "Digital Watcher: monitoring started", "\n".join(lines)

    if changed or new_sites:
        lines = []
        if changed:
            lines.append(f"Here's what changed in the last 24 hours on {len(changed)} site(s):")
            lines.append("")
            for r in changed:
                lines.append(f"=== {r['label']} ===")
                lines.append(r["url"])
                if r.get("fallback"):
                    lines.append(
                        "(showing changes since monitoring started - not yet 24 hours of history)"
                    )
                lines.append(
                    f"{r['changed_count']} new/changed line(s), showing up to {MAX_CHANGED_LINES}:"
                )
                for line in r["changed_lines"]:
                    lines.append(f"  + {line}")
                lines.append("")
        if new_sites:
            lines.append("Newly added and now being monitored:")
            for r in new_sites:
                lines.append(f"- {r['label']} ({r['url']})")
            lines.append("")
        if errors:
            lines.append("Could not reach these sites:")
            for r in errors:
                lines.append(f"- {r['label']} ({r['url']}): {r['error']}")
        total = len(changed) + len(new_sites)
        return f"Digital Watcher: {total} update(s) in the last 24 hours", "\n".join(lines)

    if mode == "daily":
        lines = [f"Checked {len(results)} site(s) - no changes in the last 24 hours."]
        if errors:
            lines.append("")
            lines.append("Could not reach these sites:")
            for r in errors:
                lines.append(f"- {r['label']} ({r['url']}): {r['error']}")
        return "Digital Watcher: daily check - no changes", "\n".join(lines)

    # Instant mode, nothing changed: stay quiet.
    return None, None


def main():
    config = load_config()
    websites = config.get("websites", [])[:5]

    if not websites:
        print("No websites configured yet. Nothing to check.")
        return

    now_ts = int(time.time())
    results = [check_site(site, now_ts) for site in websites]
    for r in results:
        print(r)

    subject, body = build_message(config, results)
    if subject is None:
        print("No notification needed this run.")
        return

    notifications = config.get("notifications", {})
    user = config.get("user", {})

    if notifications.get("email"):
        ok, info = send_email(
            subject=subject,
            body=body,
            to_address=user.get("email", ""),
            gmail_address=os.environ.get("GMAIL_ADDRESS", ""),
            gmail_app_password=os.environ.get("GMAIL_APP_PASSWORD", ""),
        )
        print(info)

    if notifications.get("telegram"):
        telegram_text = f"<b>{subject}</b>\n\n{body}"
        ok, info = send_telegram(
            text=telegram_text,
            chat_id=config.get("telegram_chat_id", ""),
            bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        )
        print(info)


if __name__ == "__main__":
    main()
