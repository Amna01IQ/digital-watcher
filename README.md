# Digital Watcher

Digital Watcher is an AI agent that monitors websites for changes and
notifies you by Email and/or Telegram the moment something changes.

This project was built as a university assignment to demonstrate a simple
but complete **agent loop**: **Sense -> Decide -> Act**, running on free
infrastructure with no paid services.

## The agent concept

An AI agent is a program that repeatedly:

1. **Senses** its environment — here, it downloads the text content of each
   website the user is watching.
2. **Decides** — it compares the new content with a snapshot saved from the
   previous check to figure out if anything meaningfully changed.
3. **Acts** — if something changed, it notifies the user through the
   channels they chose (Email, Telegram, or both). If nothing changed, it
   usually stays quiet (except once a day in "Daily digest" mode, when it
   sends a short confirmation that it's still watching).

Digital Watcher repeats this loop on a schedule the user controls entirely
through a web form — no coding required after setup.

## Architecture

```
 ┌─────────────────┐        saves settings via         ┌───────────────────┐
 │  Streamlit app   │ ─────────────────────────────────▶│  config.json      │
 │ (setup web form) │        GitHub Contents API         │  (in this repo)   │
 └─────────────────┘                                     └───────────────────┘
         │
         │ creates/updates a scheduled job via the cron-job.org API
         ▼
 ┌─────────────────┐   fires a repository_dispatch    ┌────────────────────┐
 │  cron-job.org    │ ──────────HTTP POST────────────▶ │  GitHub Actions    │
 │ (exact-time      │   at the exact minute chosen      │  workflow          │
 │  scheduler)      │                                    │  (check.yml)      │
 └─────────────────┘                                     └────────────────────┘
                                                                    │
                                                                    ▼
                                                    reads config.json, visits
                                                    each site, compares with
                                                    snapshots/, sends Email /
                                                    Telegram, commits new
                                                    snapshots back to the repo
```

**Why cron-job.org instead of GitHub's built-in `schedule:` cron?**
GitHub Actions' internal cron scheduler can be delayed by 5-15+ minutes
under load, which isn't good enough when the user picks an exact check
time. cron-job.org is a free, minute-accurate external scheduler. It
doesn't run any code itself — it just fires an HTTP request
(`repository_dispatch`) to GitHub at exactly the right moment, which is
what actually starts the GitHub Actions workflow.

### Components

| Component | What it does | Where it runs |
|---|---|---|
| `streamlit_app.py` | Setup web form: contact details, websites, notification preferences | Streamlit Community Cloud |
| `services.py` | Talks to the GitHub API (save `config.json`) and the cron-job.org API (schedule) | Same Streamlit app |
| `.github/workflows/check.yml` | Workflow triggered by `repository_dispatch` / `workflow_dispatch` | GitHub Actions |
| `agent/check_sites.py` + `agent/fetcher.py` + `agent/notifier.py` | The actual monitoring agent: sense, decide, act | GitHub Actions |
| `config.json` | User settings (single source of truth) | Committed in this repo |
| `snapshots/` | Last-seen text content per website, used to detect changes | Committed in this repo |

## Tech used

- **Streamlit** — the setup web app (Python, no HTML/CSS/JS needed)
- **GitHub Actions** — free compute to run the agent
- **GitHub REST API** — to read/write `config.json` and to fire manual/scheduled checks
- **cron-job.org** — free, minute-accurate external scheduler
- **Python** (`requests`, `beautifulsoup4`) — fetching and parsing web pages
- **Gmail SMTP** — sending email notifications (App Password, not your real password)
- **Telegram Bot API** — sending Telegram notifications
- Everything used here is **100% free** — no credit card required anywhere.

## How a check works (`agent/check_sites.py`)

1. Load `config.json`.
2. For each website:
   - Download the page and extract its visible text.
   - If there's no snapshot history yet, save one and treat it as the first run for that site.
   - Otherwise, compare the current content against the snapshot closest to
     **24 hours ago** (falling back to the oldest snapshot available if the
     site hasn't been monitored for a full 24 hours yet) and collect any
     new/changed lines.
   - If the site can't be reached, record an error instead of crashing.
   - Save the current content as a new timestamped snapshot, and delete any
     snapshots older than 48 hours so the repo stays small.
3. Decide what to send:
   - First-ever run: a "monitoring started" welcome message.
   - Anything changed or a new site was added: "Here's what changed in the
     last 24 hours" followed by a summary of the differences.
   - Nothing changed, but mode is "Daily digest": a short "checked N sites, no changes" message.
   - Nothing changed, mode is "Instant mode": no message at all.
4. Send the message through every enabled channel (Email, Telegram).
5. Commit the updated snapshots back to the repo.

### Snapshot storage

Snapshots are kept per site in `snapshots/<site-hash>/<unix-timestamp>.txt`,
one file per check, covering at least the last 48 hours. This rolling
history is what lets every run - daily, instant, or a manual test - always
compare against "24 hours ago" instead of just "the previous run".

## Initial setup (for anyone re-deploying this project)

See the step-by-step guide below. In short, you will need:

1. A GitHub account and a **public** repository containing this project (public = free Actions minutes).
2. GitHub **repository secrets**: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `TELEGRAM_BOT_TOKEN`.
3. A [Streamlit Community Cloud](https://streamlit.io/cloud) account to deploy `streamlit_app.py`, with **app secrets**: `GH_TOKEN`, `GITHUB_REPO`, `GITHUB_BRANCH`, `CRONJOB_API_KEY` (see `.streamlit/secrets.toml.example`).
4. A free [cron-job.org](https://cron-job.org) account and API key.
5. A Telegram bot (via [@BotFather](https://t.me/BotFather)) if you want Telegram notifications.

Once deployed, open the Streamlit app link, fill in the form, and click
**Save settings**. That's it — the schedule and the agent are now fully
automatic.

## Project structure

```
digital-watcher/
├── streamlit_app.py          # Setup web form (Streamlit)
├── services.py                # GitHub API + cron-job.org API helpers
├── config.json                 # User settings (written by the app)
├── requirements.txt            # Python deps for the Streamlit app
├── agent/
│   ├── check_sites.py          # Main agent script: sense -> decide -> act
│   ├── fetcher.py               # Downloads + extracts page text
│   ├── notifier.py               # Sends Email / Telegram messages
│   └── requirements.txt          # Python deps for the agent
├── snapshots/                    # Last-seen content per website
└── .github/workflows/check.yml   # GitHub Actions workflow definition
```
