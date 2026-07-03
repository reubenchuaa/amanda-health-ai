#!/usr/bin/env python3
"""Parse Strava bulk export activities.csv into health/data.json.
Also extracts GPS routes from .fit.gz files for map rendering."""

import csv
import gzip
import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_FILE  = SCRIPT_DIR / "health" / "data.json"

RUN_TYPES = {"run", "virtualrun", "treadmill"}

# How many GPS points to keep per run (sampled evenly)
MAX_GPS_POINTS = 250


def parse_float(v):
    try:
        f = float(v)
        return f if f else None
    except (ValueError, TypeError):
        return None


def parse_int(v):
    try:
        f = float(v)
        return int(f) if f else None
    except (ValueError, TypeError):
        return None


def extract_route(fit_gz_path, max_points=MAX_GPS_POINTS):
    """Extract GPS polyline from a .fit.gz file. Returns [[lat, lon], ...]."""
    try:
        from fitparse import FitFile
        with gzip.open(fit_gz_path) as f:
            ff = FitFile(f)
            coords = []
            for record in ff.get_messages("record"):
                d = {m.name: m.value for m in record}
                lat = d.get("position_lat")
                lon = d.get("position_long")
                if lat and lon:
                    coords.append([
                        round(lat * 180 / 2**31, 6),
                        round(lon * 180 / 2**31, 6)
                    ])
        if not coords:
            return None
        # Sample evenly to keep payload small
        step = max(1, len(coords) // max_points)
        sampled = coords[::step][:max_points]
        return sampled
    except Exception as e:
        print(f"  Warning: could not parse GPS from {fit_gz_path.name}: {e}")
        return None


def parse_export(csv_path, extract_gps=True):
    export_dir = csv_path.parent
    workouts = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            activity_type = (row.get("Activity Type") or "").strip().lower()
            if activity_type not in RUN_TYPES:
                continue

            # Parse date
            date_str = row.get("Activity Date") or ""
            try:
                dt = datetime.strptime(date_str, "%b %d, %Y, %I:%M:%S %p")
                start = dt.strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                try:
                    dt = datetime.strptime(date_str[:20], "%b %d, %Y, %I:%M:%S")
                    start = dt.strftime("%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    continue

            name     = (row.get("Activity Name") or "Run").strip()
            dist_m   = parse_float(row.get("Distance") or row.get("Distance.1"))
            move_s   = parse_float(row.get("Moving Time") or row.get("Elapsed Time"))
            avg_spd  = parse_float(row.get("Average Speed"))
            avg_hr   = parse_float(row.get("Average Heart Rate"))
            max_hr   = parse_float(row.get("Max Heart Rate"))
            elev     = parse_float(row.get("Elevation Gain"))
            cal      = parse_float(row.get("Calories"))
            cadence  = parse_float(row.get("Average Cadence"))
            filename = (row.get("Filename") or "").strip()

            # Distance: Strava exports in metres when >100, or km when small
            if dist_m and dist_m > 100:
                dist_km = dist_m / 1000
            elif dist_m:
                dist_km = dist_m
            else:
                dist_km = 0

            # GPS route from FIT file
            route = None
            if extract_gps and filename:
                fit_path = export_dir / filename
                if fit_path.exists():
                    route = extract_route(fit_path)

            entry = {
                "type":          "Run",
                "name":          name,
                "start":         start,
                "distance_km":   round(dist_km, 3),
                "duration_mins": round(move_s / 60, 1) if move_s else None,
                "avg_hr":        round(avg_hr, 1) if avg_hr else None,
                "max_hr":        int(max_hr) if max_hr else None,
                "elevation_m":   round(elev, 1) if elev else 0,
                "calories":      int(cal) if cal else None,
                "avg_cadence":   round(cadence, 1) if cadence else None,
            }
            if route:
                entry["route"] = route

            workouts.append(entry)

    return workouts


def merge(existing_workouts, new_workouts):
    existing_starts = {w["start"] for w in existing_workouts}
    added = 0
    for w in new_workouts:
        if w["start"] not in existing_starts:
            existing_workouts.append(w)
            existing_starts.add(w["start"])
            added += 1
        else:
            # Update existing with richer data (prefer new GPS if present)
            for i, ew in enumerate(existing_workouts):
                if ew["start"] == w["start"]:
                    existing_workouts[i] = {**ew, **{k: v for k, v in w.items() if v is not None}}
                    break
    return existing_workouts, added


if __name__ == "__main__":
    if len(sys.argv) < 2:
        candidates = list(Path.home().glob("Desktop/export_*/activities.csv"))
        if not candidates:
            print("Usage: python3 parse_strava_export.py /path/to/activities.csv")
            sys.exit(1)
        csv_path = candidates[0]
    else:
        csv_path = Path(sys.argv[1])

    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        sys.exit(1)

    print(f"Parsing {csv_path}...")
    new_workouts = parse_export(csv_path)
    print(f"Found {len(new_workouts)} runs")

    existing = {"workouts": [], "daily": []}
    if DATA_FILE.exists():
        try:
            existing = json.loads(DATA_FILE.read_text())
        except Exception:
            pass

    merged, added = merge(existing.get("workouts", []), new_workouts)
    existing["workouts"] = sorted(merged, key=lambda w: w.get("start", ""), reverse=True)

    DATA_FILE.write_text(json.dumps(existing, indent=2, default=str))
    routes_count = sum(1 for w in existing["workouts"] if w.get("route"))
    print(f"Done — {added} new runs added, {len(existing['workouts'])} total, {routes_count} with GPS routes")
    print(f"Saved → {DATA_FILE}")
