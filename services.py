"""
Helpers for talking to two external APIs:

1. GitHub Contents API   - read/write profiles.json in the project's repo.
2. cron-job.org REST API - keep the shared external scheduler in sync.

profiles.json holds every user's settings plus the one shared
cron-job.org job id: {"cronjob_id": ..., "profiles": [...]}. Every
profile is checked on the same schedule (every 15 minutes); the agent
decides per-profile whether a check is actually due (see agent/check_sites.py).

Keeping these calls in one place makes streamlit_app.py easier to read.
"""
import base64
import json

import requests

GITHUB_API = "https://api.github.com"
CRONJOB_API = "https://api.cron-job.org"
DISPATCH_EVENT_TYPE = "digital-watcher-check"
PROFILES_FILE_PATH = "profiles.json"


# ---------------------------------------------------------------------------
# GitHub: read/write profiles.json
# ---------------------------------------------------------------------------

def _github_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load_profiles_from_github(repo, token, branch):
    """Return (profiles_doc, sha). profiles_doc is {"cronjob_id": None, "profiles": []}
    if the file doesn't exist yet."""
    url = f"{GITHUB_API}/repos/{repo}/contents/{PROFILES_FILE_PATH}"
    response = requests.get(
        url, headers=_github_headers(token), params={"ref": branch}, timeout=20
    )
    if response.status_code == 404:
        return {"cronjob_id": None, "profiles": []}, None
    response.raise_for_status()
    data = response.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]


def save_profiles_to_github(repo, token, branch, profiles_doc, sha):
    """Create or update profiles.json in the repo. Returns the new file sha."""
    url = f"{GITHUB_API}/repos/{repo}/contents/{PROFILES_FILE_PATH}"
    content_b64 = base64.b64encode(
        json.dumps(profiles_doc, indent=2).encode("utf-8")
    ).decode("utf-8")
    payload = {
        "message": "Update Digital Watcher profiles",
        "content": content_b64,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    response = requests.put(
        url, headers=_github_headers(token), json=payload, timeout=20
    )
    response.raise_for_status()
    return response.json()["content"]["sha"]


def trigger_workflow_now(repo, token):
    """Fire a repository_dispatch immediately (used by the 'Run a test check now' button)."""
    url = f"{GITHUB_API}/repos/{repo}/dispatches"
    payload = {"event_type": DISPATCH_EVENT_TYPE}
    response = requests.post(
        url, headers=_github_headers(token), json=payload, timeout=20
    )
    response.raise_for_status()


# ---------------------------------------------------------------------------
# cron-job.org: one shared job, fired every 15 minutes for every profile
# ---------------------------------------------------------------------------

def _cronjob_headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _build_job_payload(repo, github_token):
    dispatch_url = f"{GITHUB_API}/repos/{repo}/dispatches"
    return {
        "job": {
            "url": dispatch_url,
            "enabled": True,
            "title": "Digital Watcher (shared, every 15 min)",
            "saveResponses": False,
            "requestMethod": 1,  # POST
            "schedule": {
                "timezone": "Asia/Amman",
                "hours": [-1],
                "minutes": [0, 15, 30, 45],
                "mdays": [-1],
                "months": [-1],
                "wdays": [-1],
            },
            "extendedData": {
                "headers": {
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "application/json",
                    "User-Agent": "digital-watcher-cronjob",
                },
                "body": json.dumps({"event_type": DISPATCH_EVENT_TYPE}),
            },
        }
    }


def ensure_shared_cronjob(api_key, job_id, repo, github_token):
    """Create the one shared cron-job.org job if needed, otherwise make sure
    the existing one still points at the right schedule/URL."""
    payload = _build_job_payload(repo, github_token)

    if job_id:
        url = f"{CRONJOB_API}/jobs/{job_id}"
        response = requests.patch(
            url, headers=_cronjob_headers(api_key), json=payload, timeout=20
        )
        if response.status_code == 404:
            job_id = None  # the job no longer exists on cron-job.org; create a fresh one below
        else:
            response.raise_for_status()
            return job_id

    url = f"{CRONJOB_API}/jobs"
    response = requests.put(
        url, headers=_cronjob_headers(api_key), json=payload, timeout=20
    )
    response.raise_for_status()
    return response.json()["jobId"]
