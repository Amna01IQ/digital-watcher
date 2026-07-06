"""
Build the subject, plain-text body, and HTML body for a notification.

A specific, non-repeating subject line and a proper HTML + plain-text
multipart body both help these emails avoid Gmail's spam filter, which
tends to flag mail that reuses the exact same subject every time and is
a single wall of plain, repetitive text.
"""
import html
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - always available on Python 3.9+
    ZoneInfo = None

MAX_CHANGED_LINES = 15


def _local_date(config):
    now = datetime.now()
    if ZoneInfo is not None:
        try:
            now = datetime.now(ZoneInfo(config.get("timezone", "Asia/Amman")))
        except Exception:
            pass
    return now.strftime("%Y-%m-%d")


def _esc(text):
    return html.escape(str(text), quote=False)


def build_notification(config, results):
    """Return (subject, plain_body, html_body), or None if nothing should be sent."""
    changed = [r for r in results if r["status"] == "changed"]
    new_sites = [r for r in results if r["status"] == "new"]
    errors = [r for r in results if r["status"] == "error"]
    mode = config.get("mode", "daily")
    date = _local_date(config)
    user_name = config.get("user", {}).get("name", "").strip() or "there"

    # Every site is brand new -> this is the very first check ever.
    if new_sites and len(new_sites) == len(results):
        subject = f"Digital Watcher: monitoring started for {len(new_sites)} site(s) - {date}"
        intro = "Digital Watcher is now watching the following site(s) for changes:"
        listing = [(r["label"], r["url"]) for r in new_sites]
        plain = _render_plain(intro, listing=listing, errors=errors)
        rendered_html = _render_html(user_name, intro, listing=listing, errors=errors)
        return subject, plain, rendered_html

    updated = changed + new_sites
    if updated:
        if len(updated) == 1:
            subject = f"Digital Watcher: update on {updated[0]['label']} - {date}"
        else:
            names = ", ".join(r["label"] for r in updated[:3])
            if len(updated) > 3:
                names += ", ..."
            subject = f"Digital Watcher: {len(updated)} site update(s) ({names}) - {date}"

        intro = f"Here's what changed in the last 24 hours across {len(updated)} site(s):"
        plain = _render_plain(intro, changes=changed, new_sites=new_sites, errors=errors)
        rendered_html = _render_html(user_name, intro, changes=changed, new_sites=new_sites, errors=errors)
        return subject, plain, rendered_html

    if mode == "daily":
        subject = f"Digital Watcher: daily check for {date} - no changes"
        intro = f"Checked {len(results)} site(s) - nothing changed in the last 24 hours."
        plain = _render_plain(intro, errors=errors)
        rendered_html = _render_html(user_name, intro, errors=errors)
        return subject, plain, rendered_html

    # Instant mode, nothing changed: stay quiet.
    return None


def _render_plain(intro, changes=None, new_sites=None, listing=None, errors=None):
    lines = [intro, ""]

    if listing:
        for label, url in listing:
            lines.append(f"- {label} ({url})")
        lines.append("")

    if changes:
        for r in changes:
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
        lines.append("Could not reach these site(s):")
        for r in errors:
            lines.append(f"- {r['label']} ({r['url']}): {r['error']}")
        lines.append("")

    lines.append("- Digital Watcher")
    return "\n".join(lines).rstrip()


def _render_html(user_name, intro, changes=None, new_sites=None, listing=None, errors=None):
    parts = [
        '<div style="font-family: Arial, Helvetica, sans-serif; font-size: 15px; '
        'color: #222222; line-height: 1.5; max-width: 600px;">',
        f"<p>Hi {_esc(user_name)},</p>",
        f"<p>{_esc(intro)}</p>",
    ]

    if listing:
        parts.append('<ul style="padding-left: 20px; margin: 8px 0;">')
        for label, url in listing:
            parts.append(
                f'<li><strong>{_esc(label)}</strong> - '
                f'<a href="{_esc(url)}" style="color:#3B6FA0;">{_esc(url)}</a></li>'
            )
        parts.append("</ul>")

    if changes:
        for r in changes:
            parts.append(
                '<div style="margin: 16px 0; padding: 12px 16px; '
                'border-left: 3px solid #3B6FA0; background: #F4F7FA;">'
            )
            parts.append(f'<p style="margin: 0 0 4px 0;"><strong>{_esc(r["label"])}</strong></p>')
            parts.append(
                f'<p style="margin: 0 0 8px 0;">'
                f'<a href="{_esc(r["url"])}" style="color:#3B6FA0;">{_esc(r["url"])}</a></p>'
            )
            if r.get("fallback"):
                parts.append(
                    '<p style="margin: 0 0 8px 0; font-style: italic; color: #666;">'
                    "Showing changes since monitoring started - not yet 24 hours of history.</p>"
                )
            parts.append(
                f'<p style="margin: 0 0 4px 0;">{r["changed_count"]} new/changed line(s), '
                f"showing up to {MAX_CHANGED_LINES}:</p>"
            )
            parts.append('<ul style="margin: 0; padding-left: 20px;">')
            for line in r["changed_lines"]:
                parts.append(f"<li>{_esc(line)}</li>")
            parts.append("</ul></div>")

    if new_sites:
        parts.append(
            '<p style="margin: 16px 0 4px 0;"><strong>Newly added and now being monitored:</strong></p>'
        )
        parts.append('<ul style="padding-left: 20px; margin: 0 0 8px 0;">')
        for r in new_sites:
            parts.append(
                f'<li><strong>{_esc(r["label"])}</strong> - '
                f'<a href="{_esc(r["url"])}" style="color:#3B6FA0;">{_esc(r["url"])}</a></li>'
            )
        parts.append("</ul>")

    if errors:
        parts.append('<p style="margin: 16px 0 4px 0;"><strong>Could not reach these site(s):</strong></p>')
        parts.append('<ul style="padding-left: 20px; margin: 0 0 8px 0; color: #A33;">')
        for r in errors:
            parts.append(f'<li>{_esc(r["label"])} ({_esc(r["url"])}): {_esc(r["error"])}</li>')
        parts.append("</ul>")

    parts.append(
        '<p style="margin-top: 24px; color: #555;">Digital Watcher'
        '<br><span style="font-size: 12px; color: #999;">Automated website monitoring</span></p>'
    )
    parts.append("</div>")
    return "".join(parts)
