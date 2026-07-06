"""
Digital Watcher agent.

Sense  -> download each configured website's text.
Decide -> compare it with the snapshot taken closest to 24 hours ago.
Act    -> notify the user by Email / Telegram with what changed.

This is a multi-user agent: profiles.json holds every user's profile
(their own contact details, websites, and preferences). Every profile
is checked on the same shared schedule (the workflow runs every 15
minutes, see .github/workflows/check.yml), but each profile decides for
itself whether a check is actually due right now:
  - "instant" mode profiles: due on every run.
  - "daily" mode profiles: due on the first run at-or-after their chosen
    time each day (tracked via last_daily_run_date), so a profile set
    for 16:30 fires within the same 15-minute cycle, by 16:45 at the
    latest.

Each site keeps a rolling history of snapshots (one per run) under
snapshots/<profile_id>/<site-hash>/<unix-timestamp>.txt, covering at
least the last 48 hours. This lets every check report "what changed in
the last 24 hours" instead of just "what changed since the last run".

Run with: python agent/check_sites.py
(from the repository root, as GitHub Actions does).
"""
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - always available on Python 3.9+
    ZoneInfo = None

from fetcher import fetch_text
from messages import MAX_CHANGED_LINES, build_notification
from notifier import send_email, send_telegram

ROOT = Path(__file__).resolve().parent.parent
PROFILES_PATH = ROOT / "profiles.json"
SNAPSHOTS_DIR = ROOT / "snapshots"

TARGET_AGE_HOURS = 24
SNAPSHOT_RETENTION_HOURS = 48


def load_profiles():
    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_profiles(profiles_doc):
    with open(PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(profiles_doc, f, indent=2)
        f.write("\n")


def local_now(tz_name):
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


def is_profile_due(profile):
    if profile.get("mode", "daily") == "instant":
        return True

    now = local_now(profile.get("timezone", "Asia/Amman"))
    if profile.get("last_daily_run_date") == now.strftime("%Y-%m-%d"):
        return False  # already ran today

    hour, minute = (int(p) for p in profile.get("daily_time", "08:00").split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return now >= target


def site_dir(profile_id, url):
    # Hash the URL so it's always a safe, unique folder name.
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    path = SNAPSHOTS_DIR / profile_id / digest
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


def check_site(profile_id, site, now_ts):
    label = site.get("label") or site["url"]
    url = site["url"]
    directory = site_dir(profile_id, url)
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


def process_profile(profile, now_ts):
    profile_id = profile.get("profile_id", "unknown")
    websites = profile.get("websites", [])[:5]

    if not websites:
        print(f"[{profile_id}] No websites configured. Skipping.")
        return

    results = [check_site(profile_id, site, now_ts) for site in websites]
    for r in results:
        print(f"[{profile_id}] {r}")

    notification = build_notification(profile, results)
    if notification is None:
        print(f"[{profile_id}] No notification needed this run.")
        return
    subject, plain_body, html_body = notification

    notifications = profile.get("notifications", {})
    user = profile.get("user", {})

    if notifications.get("email"):
        ok, info = send_email(
            subject=subject,
            plain_body=plain_body,
            html_body=html_body,
            to_address=user.get("email", ""),
            gmail_address=os.environ.get("GMAIL_ADDRESS", ""),
            gmail_app_password=os.environ.get("GMAIL_APP_PASSWORD", ""),
        )
        print(f"[{profile_id}] {info}")

    if notifications.get("telegram"):
        telegram_text = f"<b>{subject}</b>\n\n{plain_body}"
        ok, info = send_telegram(
            text=telegram_text,
            chat_id=profile.get("telegram_chat_id", ""),
            bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        )
        print(f"[{profile_id}] {info}")


def main():
    profiles_doc = load_profiles()
    profiles = profiles_doc.get("profiles", [])

    if not profiles:
        print("No profiles yet. Nothing to check.")
        return

    # Manual triggers (the Streamlit "Run a test check now" button, or a
    # workflow_dispatch run from the Actions tab) force every profile to be
    # checked immediately, regardless of mode or today's gating - so a demo
    # always gets a real response instead of "not due yet". Real scheduled
    # runs (repository_dispatch from cron-job.org) are unaffected.
    force = os.environ.get("FORCE_CHECK", "false").lower() == "true"
    if force:
        print("Manual trigger detected - forcing a check for every profile.")

    now_ts = int(time.time())
    profiles_changed = False

    for profile in profiles:
        profile_id = profile.get("profile_id", "unknown")
        naturally_due = is_profile_due(profile)

        if not (naturally_due or force):
            print(f"[{profile_id}] Not due yet - skipping.")
            continue

        if naturally_due:
            print(f"[{profile_id}] Running check...")
        else:
            print(f"[{profile_id}] Forced check (manual trigger, not otherwise due yet)...")

        try:
            process_profile(profile, now_ts)
        except Exception as exc:
            # One profile's failure shouldn't stop everyone else's checks.
            print(f"[{profile_id}] Failed unexpectedly: {exc}")

        # Only advance the daily gate for a genuinely due scheduled run - a
        # forced manual/test run must not suppress today's real check.
        if naturally_due and profile.get("mode", "daily") == "daily":
            today = local_now(profile.get("timezone", "Asia/Amman")).strftime("%Y-%m-%d")
            profile["last_daily_run_date"] = today
            profiles_changed = True

    if profiles_changed:
        save_profiles(profiles_doc)


if __name__ == "__main__":
    main()
