#!/usr/bin/env python3
"""Intervals.icu sync — pulls activities and wellness data into health/data.json."""

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
import requests
from requests.auth import HTTPBasicAuth

SCRIPT_DIR = Path(__file__).parent
HEALTH_DIR = SCRIPT_DIR / "health"
DATA_FILE  = HEALTH_DIR / "data.json"

HEALTH_DIR.mkdir(exist_ok=True)

API_BASE    = "https://intervals.icu/api/v1"
ATHLETE_ID  = os.environ.get("INTERVALS_ATHLETE_ID", "i630647")
API_KEY     = os.environ.get("INTERVALS_API_KEY", "")


def auth():
    return HTTPBasicAuth("API_KEY", API_KEY)


def get(path, **params):
    resp = requests.get(f"{API_BASE}{path}", auth=auth(), params=params)
    resp.raise_for_status()
    return resp.json()


def pace_str(mps):
    if not mps or mps <= 0:
        return None
    spm = (1 / mps) * 1000
    m, s = divmod(int(spm), 60)
    return f"{m}:{s:02d}/km"


def is_run(act):
    t = (act.get("type") or act.get("sport_type") or "").lower()
    return t in ("run", "virtualrun", "treadmill", "running")


def sync(days=14):
    if not API_KEY:
        print("Warning: INTERVALS_API_KEY not set — skipping sync")
        return

    today     = date.today()
    date_from = (today - timedelta(days=days)).isoformat()
    date_to   = today.isoformat()

    print(f"\nFetching data for {date_from} → {date_to}\n")

    # --- Activities ---
    print("  Fetching activities...")
    try:
        acts_raw = get(
            f"/athlete/{ATHLETE_ID}/activities",
            oldest=date_from,
            newest=date_to
        )
    except Exception as e:
        print(f"  Warning: activities — {e}")
        acts_raw = []

    workouts = []
    for a in acts_raw:
        name     = a.get("name") or a.get("type") or "Activity"
        a_type   = a.get("type") or ""
        a_id     = a.get("id") or ""
        start    = (a.get("start_date_local") or a.get("date") or "")[:19]
        dist_m   = a.get("distance") or 0
        move_s   = a.get("moving_time") or a.get("elapsed_time") or 0
        avg_hr   = a.get("average_heartrate") or a.get("average_heart_rate")
        max_hr   = a.get("max_heartrate") or a.get("max_heart_rate")
        elev     = a.get("total_elevation_gain") or 0
        cal      = a.get("calories") or a.get("kilojoules")
        cadence  = a.get("average_cadence")

        # Fetch GPS route for runs
        route = None
        if a_id and is_run(a):
            try:
                streams = get(f"/activity/{a_id}/streams")
                latlng  = next((s for s in streams if s.get("type") == "latlng"), None)
                if latlng:
                    lats = latlng.get("data", [])
                    lngs = latlng.get("data2", [])
                    pairs = [[lats[i], lngs[i]] for i in range(len(lats)) if lats[i] and lngs[i]]
                    # Sample up to 250 points
                    step  = max(1, len(pairs) // 250)
                    route = pairs[::step][:250]
                    print(f"    GPS: {len(route)} points")
            except Exception as e:
                print(f"    GPS fetch skipped: {e}")

        workouts.append({
            "type":          a_type,
            "name":          name,
            "start":         start,
            "distance_km":   round(dist_m / 1000, 3) if dist_m else 0,
            "duration_mins": round(move_s / 60, 1) if move_s else 0,
            "avg_hr":        round(avg_hr, 1) if avg_hr else None,
            "max_hr":        int(max_hr) if max_hr else None,
            "elevation_m":   round(elev, 1) if elev else 0,
            "calories":      int(cal) if cal else None,
            "avg_cadence":   round(cadence, 1) if cadence else None,
            **({"route": route} if route else {}),
        })
        print(f"  Activity: {start[:10]} · {name}")

    # --- Wellness (RHR, HRV, sleep, steps) ---
    print("\n  Fetching wellness...")
    daily_map = {}
    try:
        well_raw = get(
            f"/athlete/{ATHLETE_ID}/wellness",
            oldest=date_from,
            newest=date_to
        )
        for w in well_raw:
            d = (w.get("id") or w.get("date") or "")[:10]
            if not d:
                continue
            daily_map[d] = {
                "date":          d,
                "resting_hr":    w.get("restingHR"),
                "hrv":           w.get("hrv") or w.get("hrvSDNN"),
                "sleep_hours":   round(w["sleepSecs"] / 3600, 2) if w.get("sleepSecs") else None,
                "steps":         w.get("steps"),
                "calories_burned": w.get("calories") or w.get("kcalBurned"),
            }
            print(f"  Wellness: {d}")
    except Exception as e:
        print(f"  Warning: wellness — {e}")

    daily = sorted(daily_map.values(), key=lambda x: x["date"])

    # --- Merge with existing data ---
    existing = {"workouts": [], "daily": []}
    if DATA_FILE.exists():
        try:
            existing = json.loads(DATA_FILE.read_text())
        except Exception:
            pass

    # Merge workouts — add new, update existing with richer data
    existing_starts = {w["start"] for w in existing.get("workouts", [])}
    for w in workouts:
        if w["start"] not in existing_starts:
            existing.setdefault("workouts", []).append(w)
            existing_starts.add(w["start"])
        else:
            existing["workouts"] = [
                {**e, **{k: v for k, v in w.items() if v is not None}}
                if e["start"] == w["start"] else e
                for e in existing["workouts"]
            ]

    # Merge daily
    existing_dates = {d["date"] for d in existing.get("daily", [])}
    for d in daily:
        if d["date"] in existing_dates:
            existing["daily"] = [
                {**e, **d} if e["date"] == d["date"] else e
                for e in existing["daily"]
            ]
        else:
            existing.setdefault("daily", []).append(d)

    sgt_now = datetime.utcnow() + timedelta(hours=8)
    existing["synced_at"] = sgt_now.strftime("%Y-%m-%dT%H:%M")

    DATA_FILE.write_text(json.dumps(existing, indent=2, default=str))
    print(f"\n  Saved → health/data.json")
    print(f"  {len(existing['workouts'])} total workouts · {len(existing['daily'])} wellness days")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    sync(days)
