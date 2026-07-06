# Digital Watcher

Digital Watcher is a multi-user AI agent that monitors websites for changes
and notifies each user by Email and/or Telegram the moment something
changes. It was built as a university assignment to demonstrate a complete,
autonomous **agent loop** — **Sense → Compare → Act** — running entirely on
free infrastructure, with no paid services and no credit card anywhere.

**Live app:** _add your deployed Streamlit app link here_

---

## 1. The Agent Concept: Sense → Compare → Act

An AI agent is a program that perceives its environment, reasons about what
it perceives, and acts on that reasoning — on its own, on a schedule,
without a human driving each step. Digital Watcher implements this as a
loop that repeats for every website a user monitors:

1. **Sense** — the agent downloads a website's page and extracts its
   visible text content.
2. **Compare** — it compares that content against a snapshot saved from
   roughly 24 hours earlier, to decide whether anything meaningful changed.
3. **Act** — if something changed, it notifies the user through whichever
   channels they chose (Email, Telegram, or both), describing what
   changed. If nothing changed, it usually stays quiet — except once a day
   in "Daily digest" mode, when it sends a short confirmation that it's
   still watching.

This loop runs independently for every user who has created a profile, on
a shared automatic schedule, with no manual intervention required after
initial setup.

## 2. The Multi-User Profile System

Digital Watcher supports any number of independent users through a simple
**profile code** system — no accounts, no passwords, no login screen.

| Action | What happens |
|---|---|
| **Create a profile** | Open the app -> the form is blank by default -> fill in your name, email, Telegram Chat ID, up to 5 websites, and notification preferences -> click **Save settings**. A unique 6-character **profile code** (e.g. `K7X2QP`) is generated and shown prominently. **Save this code** — it's the only way to come back later. |
| **Return to a profile** | Open the app -> under "Returning? Load your profile", enter your code -> click **Load my profile** -> your settings load, ready to edit -> change anything and click **Save settings** again. |
| **Wrong or empty code** | Always shows the blank creation form. A profile's data is never shown unless its exact code is entered — this is the only access control the app needs. |

Every profile is checked and notified **independently** — different
people can watch completely different websites, on different schedules,
with different contact details — but all profiles share the same
underlying sending credentials (one Gmail account, one Telegram bot) and
the same 15-minute check cycle (explained below).

## 3. Architecture

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
under load, which isn't precise enough for time-sensitive checks.
cron-job.org is a free, minute-accurate external scheduler. It doesn't run
any code itself — it just fires an HTTP request (`repository_dispatch`) to
GitHub every 15 minutes, which is what actually starts the GitHub Actions
workflow.

**Why one shared 15-minute schedule instead of a schedule per profile?**
With many independent users potentially wanting different daily check
times, a single external trigger can't hit everyone's exact minute.
Instead, one shared cron-job.org job fires every 15 minutes for everyone,
and the agent decides *per profile* whether a check is actually due right
now (see [How a Check Works](#5-how-a-check-works)) — this scales to any
number of users without creating and managing a separate cron-job.org job
per person.

### Components

| Component | What it does | Where it runs |
|---|---|---|
| `streamlit_app.py` | Setup web form: create/load a profile, edit contact details, websites, notification preferences | Streamlit Community Cloud |
| `services.py` | Talks to the GitHub API (save `profiles.json`) and the cron-job.org API (the one shared schedule) | Same Streamlit app |
| `.github/workflows/check.yml` | Workflow triggered by `repository_dispatch` / `workflow_dispatch` | GitHub Actions |
| `agent/check_sites.py` + `agent/fetcher.py` + `agent/messages.py` + `agent/notifier.py` | The actual monitoring agent: loops over all profiles, sense/compare/act per profile | GitHub Actions |
| `profiles.json` | Every user's profile (source of truth) plus the shared `cronjob_id` | Committed in this repo |
| `snapshots/` | Last-seen text content per profile per website, used to detect changes | Committed in this repo |

## 4. Tech Stack

- **Streamlit** — the setup web app (Python, no HTML/CSS/JS needed)
- **GitHub Actions** — free compute to run the agent
- **GitHub REST API** — to read/write `profiles.json` and to fire manual/scheduled checks
- **cron-job.org** — free, minute-accurate external scheduler
- **Python** (`requests`, `beautifulsoup4`) — fetching and parsing web pages
- **Gmail SMTP** — sending email notifications (via an App Password, not the real account password)
- **Telegram Bot API** — sending Telegram notifications
- Everything above is **100% free** — no paid tiers, no credit card, anywhere in this stack.

## 5. How a Check Works (`agent/check_sites.py`)

1. Load `profiles.json`.
2. For each profile, decide if it's due right now:
   - **Instant mode** profiles: always due (checked every 15 minutes).
   - **Daily digest** profiles: due on the first run at-or-after their
     chosen time each day, tracked via a `last_daily_run_date` field on
     the profile — so a profile set for 16:30 fires within the same
     15-minute cycle, by 16:45 at the latest.
3. For each due profile, and for each of its websites:
   - Download the page and extract its visible text (**Sense**).
   - If there's no snapshot history yet, save one and treat it as the
     first run for that site.
   - Otherwise, compare the current content against the snapshot closest
     to **24 hours ago** (falling back to the oldest snapshot available
     if the site hasn't been monitored for a full 24 hours yet) and
     collect any new/changed lines (**Compare**).
   - If the site can't be reached, record an error instead of crashing.
   - Save the current content as a new timestamped snapshot, and delete
     any snapshots older than 48 hours so the repo stays small.
4. Decide what to send *to that profile*:
   - First-ever run for that profile: a "monitoring started" welcome message.
   - Anything changed or a new site was added: "Here's what changed in the
     last 24 hours" followed by a summary of the differences.
   - Nothing changed, but mode is "Daily digest": a short "checked N sites, no changes" message.
   - Nothing changed, mode is "Instant mode": no message at all.
5. Send the message through that profile's enabled channels (Email,
   Telegram), using its own email address / Telegram Chat ID (**Act**).
6. Commit the updated snapshots and any updated `last_daily_run_date`
   values back to the repo. One profile failing unexpectedly doesn't stop
   the others from being checked.

### Snapshot storage

Snapshots are kept per profile, per site, in
`snapshots/<profile_id>/<site-hash>/<unix-timestamp>.txt`, one file per
check, covering at least the last 48 hours. This rolling history is what
lets every check always compare against "24 hours ago" instead of just
"the previous run".

## 6. Getting Started

### As an end user (using the already-deployed app)

1. Open the live app link at the top of this README.
2. Fill in the blank form: your name, email, optional Telegram Chat ID, up
   to 5 websites to watch, and how you want to be notified.
3. Click **Save settings** and copy the profile code shown — that's your
   only way back in.
4. That's it. The agent checks your sites automatically from then on.
5. To change anything later, come back to the same link, enter your code
   under "Returning? Load your profile", and save again.

### As a developer (deploying your own copy)

1. A GitHub account and a **public** repository containing this project (public = free Actions minutes).
2. GitHub **repository secrets**: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `TELEGRAM_BOT_TOKEN`.
3. A [Streamlit Community Cloud](https://streamlit.io/cloud) account to deploy `streamlit_app.py`, with **app secrets**: `GH_TOKEN`, `GITHUB_REPO`, `GITHUB_BRANCH`, `CRONJOB_API_KEY` (see `.streamlit/secrets.toml.example`).
4. A free [cron-job.org](https://cron-job.org) account and API key.
5. A Telegram bot (via [@BotFather](https://t.me/BotFather)) if you want Telegram notifications.

Once deployed, open the Streamlit app link. The first profile ever saved
(by anyone) automatically creates the one shared cron-job.org schedule —
after that, the agent runs fully automatically for every profile, with no
further manual steps.

## 7. Project Structure

```
digital-watcher/
├── streamlit_app.py          # Setup web form (Streamlit): create/load profiles
├── services.py                # GitHub API + cron-job.org API helpers
├── profiles.json               # Every user's profile + shared cronjob_id
├── requirements.txt            # Python deps for the Streamlit app
├── agent/
│   ├── check_sites.py          # Main agent script: loops over profiles, sense -> compare -> act
│   ├── fetcher.py               # Downloads + extracts page text
│   ├── messages.py               # Builds subject/plain/HTML notification content
│   ├── notifier.py                # Sends Email / Telegram messages
│   └── requirements.txt            # Python deps for the agent
├── snapshots/                      # Last-seen content per profile per website
└── .github/workflows/check.yml     # GitHub Actions workflow definition
```
