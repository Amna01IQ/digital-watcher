"""
Digital Watcher agent.

Sense  -> download each configured website's text.
Decide -> compare it with the last saved snapshot.
Act    -> notify the user by Email / Telegram if something changed.

Run with: python agent/check_sites.py
(from the repository root, as GitHub Actions does).
"""
import hashlib
import json
import os
from pathlib import Path

from fetcher import fetch_text
from notifier import send_email, send_telegram

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
SNAPSHOTS_DIR = ROOT / "snapshots"

MAX_CHANGED_LINES = 15


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def snapshot_path(url):
    # Hash the URL so it's always a safe, unique file name.
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return SNAPSHOTS_DIR / f"{digest}.txt"


def read_snapshot(path):
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").splitlines()


def write_snapshot(path, lines):
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def check_site(site):
    label = site.get("label") or site["url"]
    url = site["url"]
    path = snapshot_path(url)
    old_lines = read_snapshot(path)

    try:
        new_lines = fetch_text(url)
    except Exception as exc:
        return {"label": label, "url": url, "status": "error", "error": str(exc)}

    if old_lines is None:
        write_snapshot(path, new_lines)
        return {"label": label, "url": url, "status": "new"}

    added = [line for line in new_lines if line not in old_lines]
    if added:
        write_snapshot(path, new_lines)
        return {
            "label": label,
            "url": url,
            "status": "changed",
            "changed_lines": added[:MAX_CHANGED_LINES],
            "changed_count": len(added),
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
            lines.append(f"Digital Watcher detected changes on {len(changed)} site(s):")
            lines.append("")
            for r in changed:
                lines.append(f"=== {r['label']} ===")
                lines.append(r["url"])
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
        return f"Digital Watcher: {total} update(s)", "\n".join(lines)

    if mode == "daily":
        lines = [f"Checked {len(results)} site(s) - no changes today."]
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

    results = [check_site(site) for site in websites]
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
