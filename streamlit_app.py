"""
Digital Watcher - Setup page.

This Streamlit app lets you configure the monitoring agent: your contact
details, which websites to watch, how you want to be notified, and how
often the checks should run. When you click "Save settings" it:

  1. Writes your settings to config.json in the GitHub repo.
  2. Creates/updates a job on cron-job.org so the agent runs at exactly
     the time (or interval) you chose.

The agent itself (the part that visits websites and sends notifications)
runs separately, on GitHub Actions - see agent/check_sites.py.
"""
import datetime

import streamlit as st

from services import load_config_from_github, save_config_to_github, trigger_workflow_now, upsert_cronjob

st.set_page_config(page_title="Digital Watcher - Setup", page_icon="\U0001F441", layout="centered")

DEFAULT_CONFIG = {
    "user": {"name": "", "email": ""},
    "telegram_chat_id": "",
    "websites": [],
    "notifications": {"email": True, "telegram": True},
    "mode": "daily",
    "daily_time": "08:00",
    "timezone": "Asia/Amman",
    "cronjob_id": None,
}


def get_secret(name):
    return st.secrets.get(name, "")


def load_settings():
    repo = get_secret("GITHUB_REPO")
    token = get_secret("GH_TOKEN")
    branch = get_secret("GITHUB_BRANCH") or "main"
    config, sha = load_config_from_github(repo, token, branch)
    if config is None:
        return dict(DEFAULT_CONFIG), None
    return config, sha


st.title("\U0001F441 Digital Watcher")
st.write(
    "Digital Watcher is an AI agent that keeps an eye on websites for you. "
    "It periodically **senses** each page, **compares** it with what it saw "
    "last time, and **acts** by notifying you the moment something changes."
)


def passcode_gate():
    """Require a shared passcode before showing or editing any settings.

    This app's link is public (needed for free Streamlit Community Cloud
    hosting), so without this gate anyone who finds the URL could read or
    overwrite another person's contact details and monitored sites.
    """
    correct_passcode = get_secret("APP_PASSCODE")
    if not correct_passcode:
        st.warning(
            "No APP_PASSCODE secret is set, so this setup page is currently "
            "open to anyone with the link. Add an APP_PASSCODE secret to "
            "protect it (see .streamlit/secrets.toml.example)."
        )
        return True

    if st.session_state.get("passcode_ok"):
        return True

    st.info("This setup page is protected. Enter the access passcode to continue.")
    entered = st.text_input("Access passcode", type="password")
    if st.button("Unlock"):
        if entered == correct_passcode:
            st.session_state.passcode_ok = True
            st.rerun()
        else:
            st.error("Incorrect passcode.")
    return False


if not passcode_gate():
    st.stop()

missing_secrets = [
    name
    for name in ["GH_TOKEN", "GITHUB_REPO", "CRONJOB_API_KEY"]
    if not get_secret(name)
]
if missing_secrets:
    st.warning(
        "Missing Streamlit secret(s): "
        + ", ".join(missing_secrets)
        + ". Add them in Settings -> Secrets before saving settings. "
        "See .streamlit/secrets.toml.example in the repo."
    )

if "config" not in st.session_state:
    try:
        config, sha = load_settings()
    except Exception as exc:
        st.error(f"Could not load existing settings from GitHub: {exc}")
        config, sha = dict(DEFAULT_CONFIG), None
    st.session_state.config = config
    st.session_state.sha = sha

config = st.session_state.config

st.header("1. Your details")
name = st.text_input("Your name", value=config.get("user", {}).get("name", ""))
email = st.text_input("Your email address", value=config.get("user", {}).get("email", ""))

telegram_chat_id = st.text_input(
    "Telegram Chat ID (optional if you only use Email)",
    value=config.get("telegram_chat_id", ""),
    help=(
        "1. Open Telegram and search for your bot, then press **Start**.\n"
        "2. Message **@userinfobot** (press Start there too) - it will reply "
        "with your numeric Chat ID.\n"
        "3. Paste that number here."
    ),
)

st.header("2. Websites to monitor (up to 5)")
websites = []
existing_sites = config.get("websites", [])
for i in range(5):
    col1, col2 = st.columns([1, 2])
    existing = existing_sites[i] if i < len(existing_sites) else {"label": "", "url": ""}
    with col1:
        label = st.text_input(f"Label #{i + 1}", value=existing.get("label", ""), key=f"label_{i}")
    with col2:
        url = st.text_input(f"URL #{i + 1}", value=existing.get("url", ""), key=f"url_{i}")
    if url.strip():
        websites.append({"label": label.strip() or url.strip(), "url": url.strip()})

st.header("3. Notification preferences")
col1, col2 = st.columns(2)
with col1:
    email_enabled = st.checkbox(
        "Email", value=config.get("notifications", {}).get("email", True)
    )
with col2:
    telegram_enabled = st.checkbox(
        "Telegram", value=config.get("notifications", {}).get("telegram", True)
    )

mode_label = st.radio(
    "How often should sites be checked?",
    ["Daily digest", "Instant mode"],
    index=0 if config.get("mode", "daily") == "daily" else 1,
    help=(
        "Daily digest: one check per day at the exact time you pick. "
        "Instant mode: checks every 15 minutes and notifies you right away "
        "when something changes."
    ),
)
mode = "daily" if mode_label == "Daily digest" else "instant"

daily_time_str = config.get("daily_time", "08:00")
default_hour, default_minute = (int(p) for p in daily_time_str.split(":"))
if mode == "daily":
    daily_time = st.time_input(
        "Daily check time (Asia/Amman)",
        value=datetime.time(default_hour, default_minute),
    )
    daily_time_str = daily_time.strftime("%H:%M")
else:
    st.info("Instant mode checks every 15 minutes, all day, every day.")

st.divider()
save_clicked = st.button("Save settings", type="primary")

if save_clicked:
    errors = []
    if not name.strip():
        errors.append("Please enter your name.")
    if not email.strip():
        errors.append("Please enter your email address.")
    if not websites:
        errors.append("Please add at least one website to monitor.")
    if not email_enabled and not telegram_enabled:
        errors.append("Please enable at least one notification channel.")
    if telegram_enabled and not telegram_chat_id.strip():
        errors.append("Telegram is enabled - please enter your Telegram Chat ID.")
    for site in websites:
        if not (site["url"].startswith("http://") or site["url"].startswith("https://")):
            errors.append(f"'{site['url']}' is not a valid URL (must start with http:// or https://).")

    if errors:
        for err in errors:
            st.error(err)
    else:
        new_config = {
            "user": {"name": name.strip(), "email": email.strip()},
            "telegram_chat_id": telegram_chat_id.strip(),
            "websites": websites,
            "notifications": {"email": email_enabled, "telegram": telegram_enabled},
            "mode": mode,
            "daily_time": daily_time_str,
            "timezone": "Asia/Amman",
            "cronjob_id": config.get("cronjob_id"),
        }

        repo = get_secret("GITHUB_REPO")
        gh_token = get_secret("GH_TOKEN")
        branch = get_secret("GITHUB_BRANCH") or "main"
        cronjob_key = get_secret("CRONJOB_API_KEY")

        try:
            with st.spinner("Updating the cron-job.org schedule..."):
                job_id = upsert_cronjob(
                    api_key=cronjob_key,
                    job_id=new_config["cronjob_id"],
                    mode=mode,
                    daily_time=daily_time_str,
                    timezone="Asia/Amman",
                    repo=repo,
                    github_token=gh_token,
                )
            new_config["cronjob_id"] = job_id

            with st.spinner("Saving settings to GitHub..."):
                new_sha = save_config_to_github(
                    repo=repo, token=gh_token, branch=branch, config=new_config, sha=st.session_state.sha
                )

            st.session_state.config = new_config
            st.session_state.sha = new_sha

            channels = [c for c, on in [("Email", email_enabled), ("Telegram", telegram_enabled)] if on]
            if mode == "daily":
                next_run = f"once a day at {daily_time_str} (Asia/Amman)"
            else:
                next_run = "every 15 minutes, all day (Asia/Amman)"

            st.success(
                "Settings saved!\n\n"
                f"- **Channels enabled:** {', '.join(channels)}\n"
                f"- **Mode:** {mode_label}\n"
                f"- **Next run:** {next_run}\n\n"
                "The GitHub Actions agent will now run on this schedule automatically."
            )
        except Exception as exc:
            st.error(f"Something went wrong while saving: {exc}")

st.divider()
st.subheader("Manual test")
st.write("Use this to trigger a check right now, without waiting for the schedule.")
if st.button("Run a test check now"):
    try:
        repo = get_secret("GITHUB_REPO")
        gh_token = get_secret("GH_TOKEN")
        trigger_workflow_now(repo, gh_token)
        st.success("Triggered! Check the 'Actions' tab in your GitHub repo to watch it run.")
    except Exception as exc:
        st.error(f"Could not trigger the workflow: {exc}")
