#!/usr/bin/env python3
"""Strava sync script — pulls recent activities and saves to strava/data.json."""

import json
import os
import sys
import webbrowser
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

SCRIPT_DIR = Path(__file__).parent
STRAVA_DIR = SCRIPT_DIR / "strava"
TOKEN_FILE = SCRIPT_DIR / ".strava_token.json"
DATA_FILE = STRAVA_DIR / "data.json"

STRAVA_DIR.mkdir(exist_ok=True)

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
API_BASE = "https://www.strava.com/api/v3"


def get_credentials():
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    if client_id and client_secret:
        return client_id, client_secret
    print("\nNo STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET found in environment.")
    print("Create a Strava API app at: https://www.strava.com/settings/api")
    client_id = input("Client ID: ").strip()
    client_secret = input("Client Secret: ").strip()
    return client_id, client_secret


def refresh_token(client_id, client_secret, refresh):
    resp = requests.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    return resp.json()


def save_token(data):
    TOKEN_FILE.write_text(json.dumps(data, indent=2))
    TOKEN_FILE.chmod(0o600)


def load_token():
    client_id, client_secret = get_credentials()
    now_ts = datetime.now(timezone.utc).timestamp()

    # GitHub Actions: refresh_token supplied as secret
    env_refresh = os.environ.get("STRAVA_REFRESH_TOKEN")
    if env_refresh:
        tok = refresh_token(client_id, client_secret, env_refresh)
        tok["client_id"] = client_id
        tok["client_secret"] = client_secret
        return tok

    # Local: try saved token file
    if TOKEN_FILE.exists():
        tok = json.loads(TOKEN_FILE.read_text())
        if tok.get("expires_at", 0) > now_ts + 60:
            tok["client_id"] = client_id
            tok["client_secret"] = client_secret
            return tok
        tok = refresh_token(client_id, client_secret, tok["refresh_token"])
        save_token(tok)
        tok["client_id"] = client_id
        tok["client_secret"] = client_secret
        return tok

    # Fresh OAuth
    params = {
        "client_id": client_id,
        "redirect_uri": "http://localhost",
        "response_type": "code",
        "approval_prompt": "force",
        "scope": "read,activity:read_all",
    }
    auth_url = AUTH_URL + "?" + urlencode(params)
    print(f"\nOpen this URL in your browser:\n\n{auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass
    redirect = input("Paste the full redirect URL (http://localhost?code=...&...): ").strip()
    code = redirect.split("code=")[1].split("&")[0]

    resp = requests.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
    })
    resp.raise_for_status()
    tok = resp.json()
    save_token(tok)
    print("Authorisation successful — token saved to .strava_token.json")
    tok["client_id"] = client_id
    tok["client_secret"] = client_secret
    return tok


def api_get(tok, path, **params):
    headers = {"Authorization": f"Bearer {tok['access_token']}"}
    resp = requests.get(f"{API_BASE}{path}", headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def fetch_activities(tok, days=7):
    after = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    activities = []
    page = 1
    while True:
        batch = api_get(tok, "/athlete/activities", after=after, per_page=50, page=page)
        if not batch:
            break
        activities.extend(batch)
        if len(batch) < 50:
            break
        page += 1
    return activities


def fetch_detail(tok, activity_id):
    try:
        detail = api_get(tok, f"/activities/{activity_id}")
        try:
            detail["_zones"] = api_get(tok, f"/activities/{activity_id}/zones")
        except Exception:
            detail["_zones"] = {}
        return detail
    except Exception as e:
        print(f"    Warning: detail for {activity_id} — {e}")
        return None


def merge(existing, new_acts):
    existing_ids = {a["id"] for a in existing}
    added = 0
    for act in new_acts:
        if act["id"] not in existing_ids:
            existing.append(act)
            existing_ids.add(act["id"])
            added += 1
    return existing, added


def sync(days=7):
    tok = load_token()

    print(f"\nFetching activities for last {days} days...\n")
    new_acts = fetch_activities(tok, days)
    print(f"  Found {len(new_acts)} activities in window\n")

    enriched = []
    for act in new_acts:
        label = act.get("name", "?")
        date_s = (act.get("start_date_local") or "")[:10]
        print(f"  {date_s} · {label}")
        detail = fetch_detail(tok, act["id"])
        if detail:
            act.update(detail)
        enriched.append(act)

    existing = []
    if DATA_FILE.exists():
        try:
            existing = json.loads(DATA_FILE.read_text())
        except Exception:
            existing = []

    merged, added = merge(existing, enriched)
    merged.sort(key=lambda a: a.get("start_date_local", ""), reverse=True)
    DATA_FILE.write_text(json.dumps(merged, indent=2, default=str))
    print(f"\n  +{added} new · {len(merged)} total saved → strava/data.json")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    sync(days)
