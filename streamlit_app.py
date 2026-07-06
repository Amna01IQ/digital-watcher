"""
Digital Watcher - Setup page.

Multi-user: anyone can create their own monitoring profile here (contact
details, websites to watch, notification preferences). There are no
accounts or passwords - creating a profile generates a short code, and
that code is the only way to come back later and view or edit it.

Saving a profile:
  1. Writes it into profiles.json in the GitHub repo (alongside everyone
     else's profiles).
  2. Makes sure the one shared cron-job.org job exists, firing the
     GitHub Actions workflow every 15 minutes for all profiles.

The agent itself (the part that visits websites and sends notifications)
runs separately, on GitHub Actions - see agent/check_sites.py. It loops
through every profile and decides per-profile whether a check is due.
"""
import datetime
import random
import string

import streamlit as st

from services import (
    ensure_shared_cronjob,
    load_profiles_from_github,
    save_profiles_to_github,
    trigger_workflow_now,
)

st.set_page_config(page_title="Digital Watcher - Setup", page_icon="\U0001F441", layout="centered")

BLANK_PROFILE = {
    "profile_id": None,
    "user": {"name": "", "email": ""},
    "telegram_chat_id": "",
    "websites": [],
    "notifications": {"email": True, "telegram": True},
    "mode": "daily",
    "daily_time": "08:00",
    "timezone": "Asia/Amman",
    "last_daily_run_date": None,
}


def get_secret(name):
    return st.secrets.get(name, "")


def generate_profile_id(existing_ids):
    chars = string.ascii_uppercase + string.digits
    while True:
        candidate = "".join(random.choices(chars, k=6))
        if candidate not in existing_ids:
            return candidate


def find_profile(profiles_doc, code):
    for profile in profiles_doc.get("profiles", []):
        if profile.get("profile_id") == code:
            return profile
    return None


st.title("\U0001F441 Digital Watcher")
st.write(
    "Digital Watcher is an AI agent that keeps an eye on websites for you. "
    "It periodically **senses** each page, **compares** it with what it saw "
    "last time, and **acts** by notifying you the moment something changes. "
    "Anyone can create their own monitoring profile below - no account "
    "needed, just a short code you keep to come back and edit your settings."
)

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

repo = get_secret("GITHUB_REPO")
gh_token = get_secret("GH_TOKEN")
branch = get_secret("GITHUB_BRANCH") or "main"
cronjob_key = get_secret("CRONJOB_API_KEY")

if "profiles_doc" not in st.session_state:
    try:
        profiles_doc, sha = load_profiles_from_github(repo, gh_token, branch)
    except Exception as exc:
        st.error(f"Could not load profiles from GitHub: {exc}")
        profiles_doc, sha = {"cronjob_id": None, "profiles": []}, None
    st.session_state.profiles_doc = profiles_doc
    st.session_state.sha = sha

if "loaded_profile_id" not in st.session_state:
    st.session_state.loaded_profile_id = None  # None = creating a new profile

profiles_doc = st.session_state.profiles_doc

st.header("Returning? Load your profile")
code_input = st.text_input(
    "Enter your profile code",
    value="",
    max_chars=6,
    help="Leave this blank to create a brand-new profile instead.",
).strip().upper()

col_load, col_new = st.columns(2)
with col_load:
    if st.button("Load my profile", disabled=not code_input):
        match = find_profile(profiles_doc, code_input)
        if match:
            st.session_state.loaded_profile_id = code_input
            st.rerun()
        else:
            st.error("No profile found with that code.")
with col_new:
    if st.button("Start a new profile"):
        st.session_state.loaded_profile_id = None
        st.rerun()

st.divider()

current = (
    find_profile(profiles_doc, st.session_state.loaded_profile_id)
    if st.session_state.loaded_profile_id
    else None
)
active_key = current["profile_id"] if current else "new"

if current:
    st.success(f"Editing profile **{current['profile_id']}**")
    profile_data = current
else:
    st.info("Creating a new profile.")
    profile_data = BLANK_PROFILE

st.header("1. Your details")
name = st.text_input(
    "Your name", value=profile_data["user"]["name"], key=f"name_{active_key}"
)
email = st.text_input(
    "Your email address", value=profile_data["user"]["email"], key=f"email_{active_key}"
)

telegram_chat_id = st.text_input(
    "Telegram Chat ID (optional if you only use Email)",
    value=profile_data["telegram_chat_id"],
    key=f"telegram_{active_key}",
    help=(
        "1. Open Telegram and search for our bot, then press **Start**.\n"
        "2. Message **@userinfobot** (press Start there too) - it will reply "
        "with your numeric Chat ID.\n"
        "3. Paste that number here."
    ),
)

st.header("2. Websites to monitor (up to 5)")
websites = []
existing_sites = profile_data.get("websites", [])
for i in range(5):
    col1, col2 = st.columns([1, 2])
    existing = existing_sites[i] if i < len(existing_sites) else {"label": "", "url": ""}
    with col1:
        label = st.text_input(
            f"Label #{i + 1}", value=existing.get("label", ""), key=f"label_{i}_{active_key}"
        )
    with col2:
        url = st.text_input(
            f"URL #{i + 1}", value=existing.get("url", ""), key=f"url_{i}_{active_key}"
        )
    if url.strip():
        websites.append({"label": label.strip() or url.strip(), "url": url.strip()})

st.header("3. Notification preferences")
col1, col2 = st.columns(2)
with col1:
    email_enabled = st.checkbox(
        "Email", value=profile_data["notifications"]["email"], key=f"email_on_{active_key}"
    )
with col2:
    telegram_enabled = st.checkbox(
        "Telegram", value=profile_data["notifications"]["telegram"], key=f"telegram_on_{active_key}"
    )

mode_label = st.radio(
    "How often should sites be checked?",
    ["Daily digest", "Instant mode"],
    index=0 if profile_data.get("mode", "daily") == "daily" else 1,
    key=f"mode_{active_key}",
    help=(
        "Daily digest: one check per day, within 15 minutes of the time you "
        "pick (all profiles share one 15-minute check cycle). Instant mode: "
        "checked every 15 minutes, notifies you right away when something "
        "changes."
    ),
)
mode = "daily" if mode_label == "Daily digest" else "instant"

daily_time_str = profile_data.get("daily_time") or "08:00"
default_hour, default_minute = (int(p) for p in daily_time_str.split(":"))
if mode == "daily":
    daily_time = st.time_input(
        "Daily check time (Asia/Amman)",
        value=datetime.time(default_hour, default_minute),
        key=f"time_{active_key}",
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
        is_new = current is None
        existing_ids = {p["profile_id"] for p in profiles_doc.get("profiles", [])}
        profile_id = current["profile_id"] if current else generate_profile_id(existing_ids)

        new_profile = {
            "profile_id": profile_id,
            "user": {"name": name.strip(), "email": email.strip()},
            "telegram_chat_id": telegram_chat_id.strip(),
            "websites": websites,
            "notifications": {"email": email_enabled, "telegram": telegram_enabled},
            "mode": mode,
            "daily_time": daily_time_str,
            "timezone": "Asia/Amman",
            "last_daily_run_date": current.get("last_daily_run_date") if current else None,
        }

        try:
            with st.spinner("Making sure the shared schedule is set up..."):
                job_id = ensure_shared_cronjob(
                    api_key=cronjob_key,
                    job_id=profiles_doc.get("cronjob_id"),
                    repo=repo,
                    github_token=gh_token,
                )
            profiles_doc["cronjob_id"] = job_id

            profiles_list = profiles_doc.get("profiles", [])
            if is_new:
                profiles_list.append(new_profile)
            else:
                for idx, p in enumerate(profiles_list):
                    if p["profile_id"] == profile_id:
                        profiles_list[idx] = new_profile
                        break
            profiles_doc["profiles"] = profiles_list

            with st.spinner("Saving your profile to GitHub..."):
                new_sha = save_profiles_to_github(
                    repo=repo,
                    token=gh_token,
                    branch=branch,
                    profiles_doc=profiles_doc,
                    sha=st.session_state.sha,
                )

            st.session_state.profiles_doc = profiles_doc
            st.session_state.sha = new_sha
            st.session_state.loaded_profile_id = profile_id

            channels = [c for c, on in [("Email", email_enabled), ("Telegram", telegram_enabled)] if on]
            if mode == "daily":
                next_run = f"once a day, within 15 minutes of {daily_time_str} (Asia/Amman)"
            else:
                next_run = "every 15 minutes, all day (Asia/Amman)"

            if is_new:
                st.success("Profile created!")
                st.markdown(
                    f"""
                    <div style="border: 2px solid #3B6FA0; border-radius: 8px; padding: 16px;
                                margin: 12px 0; text-align: center; background: #F4F7FA;">
                        <div style="font-size: 14px; color: #444;">
                            Save this code somewhere safe — you'll need it to view or edit
                            your settings later:
                        </div>
                        <div style="font-size: 32px; font-weight: bold; letter-spacing: 4px;
                                    color: #3B6FA0; margin-top: 8px;">
                            {profile_id}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.success(f"Settings updated for profile **{profile_id}**.")

            st.write(
                f"- **Channels enabled:** {', '.join(channels)}\n"
                f"- **Mode:** {mode_label}\n"
                f"- **Next run:** {next_run}"
            )
        except Exception as exc:
            st.error(f"Something went wrong while saving: {exc}")

st.divider()
st.subheader("Manual test")
st.write("Use this to trigger a check right now for every profile, without waiting for the schedule.")
if st.button("Run a test check now"):
    try:
        trigger_workflow_now(repo, gh_token)
        st.success("Triggered! Check the 'Actions' tab in your GitHub repo to watch it run.")
    except Exception as exc:
        st.error(f"Could not trigger the workflow: {exc}")
