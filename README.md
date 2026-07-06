# Digital Watcher

Digital Watcher is a multi-user AI agent that monitors websites for changes
and notifies each user by Email and/or Telegram the moment something changes.

This project was built as a university assignment to demonstrate a simple
but complete **agent loop**: **Sense -> Decide -> Act**, running on free
infrastructure with no paid services.

## The agent concept

An AI agent is a program that repeatedly:

1. **Senses** its environment — here, it downloads the text content of each
   website a user is watching.
2. **Decides** — it compares the new content with a snapshot saved from
   around 24 hours ago to figure out if anything meaningfully changed.
3. **Acts** — if something changed, it notifies that user through the
   channels they chose (Email, Telegram, or both). If nothing changed, it
   usually stays quiet (except once a day in "Daily digest" mode, when it
   sends a short confirmation that it's still watching).

Digital Watcher repeats this loop on a shared schedule, independently for
every user who has created a profile — no coding required after setup.

## Multi-user model

Anyone can open the Streamlit app link and create their own monitoring
**profile** — their own contact details, up to 5 websites, and notification
preferences. There are no accounts or passwords: creating a profile
generates a short 6-character **profile code** (e.g. `K7X2QP`), and that
code is the only way to come back later and view or edit it.

- **Create:** open the app -> fill in the blank form -> save -> a profile
  code is shown prominently. Save it somewhere safe.
- **Return:** open the app -> enter your profile code under "Returning?
  Load your profile" -> your settings load for editing -> save again.
- A wrong or empty code always shows the blank creation form — it never
  reveals another profile's data.

All profiles are checked and notified independently, but they share the
same sending credentials (one Gmail account, one Telegram bot) and the
same 15-minute check cycle.

## Architecture

```
 ┌─────────────────┐        saves a profile via        ┌───────────────────┐
 │  Streamlit app   │ ─────────────────────────────────▶│  profiles.json     │
 │ (setup web form) │        GitHub Contents API         │  (all profiles,    │
 └─────────────────┘                                     │   in this repo)    │
         │                                               └───────────────────┘
         │ ensures ONE shared scheduled job exists (cron-job.org API)
         ▼
 ┌─────────────────┐   fires a repository_dispatch    ┌────────────────────┐
 │  cron-job.org    │ ──────────HTTP POST────────────▶ │  GitHub Actions    │
 │ (fires every     │   every 15 minutes, for everyone  │  workflow          │
 │  15 minutes)     │                                    │  (check.yml)      │
 └─────────────────┘                                     └────────────────────┘
                                                                    │
                                                                    ▼
                                                    reads profiles.json, loops
                                                    over every profile that is
                                                    due, checks its sites,
                                                    sends Email/Telegram to
                                                    that profile's own
                                                    contacts, commits updated
                                                    snapshots + profile state
```

**Why cron-job.org instead of GitHub's built-in `schedule:` cron?**
GitHub Actions' internal cron scheduler can be delayed by 5-15+ minutes
under load, which isn't precise enough. cron-job.org is a free,
minute-accurate external scheduler. It doesn't run any code itself — it
just fires an HTTP request (`repository_dispatch`) to GitHub every 15
minutes, which is what actually starts the GitHub Actions workflow.

**Why one shared 15-minute schedule instead of a schedule per profile?**
With many independent users potentially wanting different daily check
times, a single external trigger can't hit everyone's exact minute. Instead,
one shared cron-job.org job fires every 15 minutes, and the agent decides
per profile whether a check is actually due right now (see below) — this
scales to any number of users without creating/managing a cron-job.org job
per person.

### Components

| Component | What it does | Where it runs |
|---|---|---|
| `streamlit_app.py` | Setup web form: create/load a profile, edit contact details, websites, notification preferences | Streamlit Community Cloud |
| `services.py` | Talks to the GitHub API (save `profiles.json`) and the cron-job.org API (the one shared schedule) | Same Streamlit app |
| `.github/workflows/check.yml` | Workflow triggered by `repository_dispatch` / `workflow_dispatch` | GitHub Actions |
| `agent/check_sites.py` + `agent/fetcher.py` + `agent/messages.py` + `agent/notifier.py` | The actual monitoring agent: loops over all profiles, sense/decide/act per profile | GitHub Actions |
| `profiles.json` | Every user's profile (source of truth) plus the shared `cronjob_id` | Committed in this repo |
| `snapshots/` | Last-seen text content per profile per website, used to detect changes | Committed in this repo |

## Tech used

- **Streamlit** — the setup web app (Python, no HTML/CSS/JS needed)
- **GitHub Actions** — free compute to run the agent
- **GitHub REST API** — to read/write `profiles.json` and to fire manual/scheduled checks
- **cron-job.org** — free, minute-accurate external scheduler
- **Python** (`requests`, `beautifulsoup4`) — fetching and parsing web pages
- **Gmail SMTP** — sending email notifications (App Password, not your real password)
- **Telegram Bot API** — sending Telegram notifications
- Everything used here is **100% free** — no credit card required anywhere.

## How a check works (`agent/check_sites.py`)

1. Load `profiles.json`.
2. For each profile, decide if it's due right now:
   - "Instant mode" profiles: always due (checked every 15 minutes).
   - "Daily digest" profiles: due on the first run at-or-after their chosen
     time each day, tracked via a `last_daily_run_date` field on the
     profile — so a profile set for 16:30 fires within the same
     15-minute cycle, by 16:45 at the latest.
3. For each due profile, and for each of its websites:
   - Download the page and extract its visible text.
   - If there's no snapshot history yet, save one and treat it as the first run for that site.
   - Otherwise, compare the current content against the snapshot closest to
     **24 hours ago** (falling back to the oldest snapshot available if the
     site hasn't been monitored for a full 24 hours yet) and collect any
     new/changed lines.
   - If the site can't be reached, record an error instead of crashing.
   - Save the current content as a new timestamped snapshot, and delete any
     snapshots older than 48 hours so the repo stays small.
4. Decide what to send *to that profile*:
   - First-ever run for that profile: a "monitoring started" welcome message.
   - Anything changed or a new site was added: "Here's what changed in the
     last 24 hours" followed by a summary of the differences.
   - Nothing changed, but mode is "Daily digest": a short "checked N sites, no changes" message.
   - Nothing changed, mode is "Instant mode": no message at all.
5. Send the message through that profile's enabled channels (Email, Telegram),
   using its own email address / Telegram Chat ID.
6. Commit the updated snapshots and any updated `last_daily_run_date` values
   back to the repo. One profile failing unexpectedly doesn't stop the
   others from being checked.

### Snapshot storage

Snapshots are kept per profile, per site, in
`snapshots/<profile_id>/<site-hash>/<unix-timestamp>.txt`, one file per
check, covering at least the last 48 hours. This rolling history is what
lets every check always compare against "24 hours ago" instead of just
"the previous run".

## Initial setup (for anyone re-deploying this project)

See the step-by-step guide below. In short, you will need:

1. A GitHub account and a **public** repository containing this project (public = free Actions minutes).
2. GitHub **repository secrets**: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `TELEGRAM_BOT_TOKEN`.
3. A [Streamlit Community Cloud](https://streamlit.io/cloud) account to deploy `streamlit_app.py`, with **app secrets**: `GH_TOKEN`, `GITHUB_REPO`, `GITHUB_BRANCH`, `CRONJOB_API_KEY` (see `.streamlit/secrets.toml.example`).
4. A free [cron-job.org](https://cron-job.org) account and API key.
5. A Telegram bot (via [@BotFather](https://t.me/BotFather)) if you want Telegram notifications.

Once deployed, open the Streamlit app link. The first profile ever saved
(by anyone) automatically creates the one shared cron-job.org schedule —
after that, the agent runs fully automatically for every profile.

## Project structure

```
digital-watcher/
├── streamlit_app.py          # Setup web form (Streamlit): create/load profiles
├── services.py                # GitHub API + cron-job.org API helpers
├── profiles.json               # Every user's profile + shared cronjob_id
├── requirements.txt            # Python deps for the Streamlit app
├── agent/
│   ├── check_sites.py          # Main agent script: loops over profiles, sense -> decide -> act
│   ├── fetcher.py               # Downloads + extracts page text
│   ├── messages.py               # Builds subject/plain/HTML notification content
│   ├── notifier.py                # Sends Email / Telegram messages
│   └── requirements.txt            # Python deps for the agent
├── snapshots/                      # Last-seen content per profile per website
└── .github/workflows/check.yml     # GitHub Actions workflow definition
```
