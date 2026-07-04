#!/usr/bin/env python3
"""Generate AI coach note via Anthropic API and write to health/coach_note.md.
Works in GitHub Actions (ANTHROPIC_API_KEY secret) and locally."""

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
DATA_FILE    = SCRIPT_DIR / "health" / "data.json"
CONTEXT_FILE = SCRIPT_DIR / "context.json"
COACH_FILE   = SCRIPT_DIR / "health" / "coach_note.md"

SGT = timedelta(hours=8)


def load_json(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def summarise_for_claude(data, context):
    """Build a compact text summary of recent runs + context for the prompt."""
    today_sgt = (datetime.utcnow() + SGT).date()

    runs = sorted(
        [w for w in data.get("workouts", []) if (w.get("type") or "").lower() in ("run", "virtualrun", "treadmill", "running") and (w.get("distance_km") or 0) > 0],
        key=lambda w: w.get("start", ""),
        reverse=True
    )

    lines = []
    lines.append(f"Today (SGT): {today_sgt.isoformat()} ({today_sgt.strftime('%A')})")
    lines.append(f"Athlete: {context.get('athlete_name', 'Amanda')}")
    lines.append(f"Goal: {context.get('goal', 'Sub 2:30 Kiprun Singapore Half Marathon 27 Sep 2026')}")
    lines.append(f"Race date: {context.get('race_date', '2026-09-27')} ({(date.fromisoformat(context.get('race_date','2026-09-27')) - today_sgt).days} days away)")
    lines.append(f"Target pace: {context.get('target_pace_per_km', '7:06')}/km")
    lines.append(f"HR zones: easy max {context.get('hr_zones', {}).get('easy_max', 145)} bpm, tempo {context.get('hr_zones', {}).get('tempo_range', '160-170')} bpm")

    # Current phase
    current_phase = None
    for phase in context.get("training_phases", []):
        if phase["start"] <= today_sgt.isoformat() <= phase["end"]:
            current_phase = phase
            break
    if current_phase:
        lines.append(f"Current phase: {current_phase['name']} ({current_phase['start']} to {current_phase['end']}) — {current_phase['focus']}")

    # Recent runs
    lines.append(f"\nRecent runs ({len(runs[:8])} shown):")
    for r in runs[:8]:
        start_sgt = (datetime.fromisoformat(r["start"]) + SGT).strftime("%d %b %I:%M %p") if r.get("start") else "?"
        km = r.get("distance_km", 0)
        mins = r.get("duration_mins") or 0
        pace = f"{int(mins/km)}:{int((mins/km*60)%60):02d}/km" if km and mins else "?"
        hr = r.get("avg_hr")
        max_hr = r.get("max_hr")
        elev = r.get("elevation_m", 0)
        cal = r.get("calories")
        lines.append(
            f"  {start_sgt} — {r.get('name','Run')}: {km:.1f} km, {pace}, "
            f"avg HR {hr:.0f} bpm, max HR {max_hr} bpm, elev {elev:.0f} m"
            + (f", {cal} cal" if cal else "")
        )

    # This week volume
    week_start = today_sgt - timedelta(days=today_sgt.weekday())
    km_this_week = sum(
        (w.get("distance_km") or 0) for w in runs
        if (w.get("start") or "")[:10] >= week_start.isoformat()
    )
    km_last_week = sum(
        (w.get("distance_km") or 0) for w in runs
        if (week_start - timedelta(weeks=1)).isoformat() <= (w.get("start") or "")[:10] < week_start.isoformat()
    )
    lines.append(f"\nThis week so far: {km_this_week:.1f} km | Last week: {km_last_week:.1f} km")

    # Days since last run
    if runs:
        last_run_date = date.fromisoformat((runs[0].get("start") or "")[:10])
        # Adjust for UTC→SGT date shift
        last_run_date_sgt = (datetime.fromisoformat(runs[0]["start"]) + SGT).date()
        days_since = (today_sgt - last_run_date_sgt).days
        lines.append(f"Days since last run: {days_since}")

    # Wellness
    daily = sorted(data.get("daily", []), key=lambda x: x.get("date", ""), reverse=True)
    wellness = next((d for d in daily if any(d.get(k) is not None for k in ("resting_hr", "steps"))), None)
    if wellness:
        lines.append(f"\nLatest Apple Watch data ({wellness.get('date','')}):")
        if wellness.get("resting_hr"):
            lines.append(f"  Resting HR: {wellness['resting_hr']} bpm")
        if wellness.get("steps"):
            lines.append(f"  Steps: {wellness['steps']:,}")

    return "\n".join(lines)


def generate_coach_note(data, context):
    try:
        import anthropic
    except ImportError:
        print("anthropic package not installed — run: pip install anthropic")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set")
        sys.exit(1)

    summary = summarise_for_claude(data, context)

    prompt = f"""You are a warm, encouraging running coach writing a daily note for Amanda. She is training for her first half marathon and can get easily discouraged — so your tone must always be positive, supportive and motivating, even when correcting something. Celebrate every run, no matter how short or slow. Frame challenges as opportunities, not failures.

Here is her current training data:

{summary}

Write a coach note with these exact sections:

**[Warm, upbeat headline — celebrate something specific she did, or hype up what's ahead]**

**How you're doing**
2-3 sentences using real numbers. Lead with a positive observation first. If HR is above the easy cap, frame it gently — e.g. 'The Singapore heat makes everyone's HR spike, so don't worry — just slowing down a touch will make a big difference.' Never say she is doing something wrong; say what to try instead.

**Today's session**
Specific and encouraging: session type, distance, pace/HR guidance. Use phrases like 'You've got this!', 'This is going to feel great', 'Keep it fun'. Always end with a motivating line.

**3-Day Plan**
- Today ({(datetime.utcnow() + timedelta(hours=8)).strftime('%a, %-d %b')}): session
- Tomorrow: session
- Day after: session

**This week's focus**
One encouraging sentence on the phase goal. End with something like 'Every km gets you closer to that finish line!'

Tone: warm, friendly, like a supportive friend who happens to be a running coach. Use real numbers but keep the mood upbeat. Under 280 words. Output ONLY the markdown, no preamble."""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()


if __name__ == "__main__":
    data    = load_json(DATA_FILE)
    context = load_json(CONTEXT_FILE)

    print("Generating AI coach note via Anthropic API...")
    note = generate_coach_note(data, context)

    today_sgt = (datetime.utcnow() + SGT).strftime("%a, %d %b %Y at %I:%M %p SGT")
    full_note = f"_Updated: {today_sgt}_\n\n{note}"

    COACH_FILE.write_text(full_note)
    print(f"Coach note written → {COACH_FILE}")
    print()
    print(note[:300] + "..." if len(note) > 300 else note)
