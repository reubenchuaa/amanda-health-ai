#!/usr/bin/env python3
"""Generate docs/index.html from health/data.json and context.json."""

import json
import re
from datetime import date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_FILE  = SCRIPT_DIR / "health" / "data.json"
CONTEXT_FILE = SCRIPT_DIR / "context.json"
DOCS_DIR   = SCRIPT_DIR / "docs"
OUTPUT_FILE = DOCS_DIR / "index.html"


def load_data():
    if not DATA_FILE.exists():
        return {"workouts": [], "daily": []}
    return json.loads(DATA_FILE.read_text())


def load_context():
    if not CONTEXT_FILE.exists():
        return {}
    return json.loads(CONTEXT_FILE.read_text())


def g(d, *keys):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k)
        else:
            return None
    return d if d is not None else None


def is_run(w):
    return (w.get("type") or "").lower() in ("running", "run", "outdoor run", "indoor run", "treadmill")


def pace_str(km, mins):
    if not km or not mins or km <= 0:
        return "—"
    spm = mins / km
    m, s = divmod(int(spm * 60), 60)
    return f"{m}:{s:02d}/km"


def dur_str(mins):
    if not mins:
        return "—"
    h, m = divmod(int(mins), 60)
    return f"{h}h {m}m" if h else f"{m}m"


def get_daily_range(data, days=14):
    today = date.today()
    dates = {(today - timedelta(days=i)).isoformat() for i in range(days)}
    items = [d for d in data.get("daily", []) if d.get("date") in dates]
    return sorted(items, key=lambda x: x["date"])


def get_recent_runs(data, n=10):
    runs = [w for w in data.get("workouts", []) if is_run(w)]
    runs.sort(key=lambda w: w.get("start", ""), reverse=True)
    return runs[:n]


def get_weekly_volumes(data, weeks=10):
    today = date.today()
    result = []
    for i in range(weeks - 1, -1, -1):
        ws = today - timedelta(days=today.weekday()) - timedelta(weeks=i)
        we = ws + timedelta(days=6)
        km = sum(
            (w.get("distance_km") or 0)
            for w in data.get("workouts", [])
            if is_run(w) and ws.isoformat() <= (w.get("start") or "")[:10] <= we.isoformat()
        )
        result.append((ws.strftime("%b %d"), round(km, 1)))
    return result


def get_coaching(data, context):
    today = date.today()
    race_date = date.fromisoformat(context.get("race_date", "2026-09-27"))
    days_to_race = (race_date - today).days
    easy_hr_cap  = context.get("hr_zones", {}).get("easy_max", 145)
    tempo_range  = context.get("hr_zones", {}).get("tempo_range", "160–170")

    current_phase = None
    for phase in context.get("training_phases", []):
        if phase["start"] <= today.isoformat() <= phase["end"]:
            current_phase = phase
            break
    phase_name = current_phase["name"] if current_phase else "Training"

    daily_14 = get_daily_range(data, 14)
    today_d  = next((d for d in daily_14 if d["date"] == today.isoformat()), None)

    rhr       = g(today_d, "resting_hr")
    hrv       = g(today_d, "hrv")
    sleep_h   = g(today_d, "sleep_hours")
    steps     = g(today_d, "steps")

    # Baseline RHR from last 14 days
    rhr_vals = [d["resting_hr"] for d in daily_14 if d.get("resting_hr")]
    baseline_rhr = round(sum(rhr_vals) / len(rhr_vals)) if rhr_vals else None

    # Recovery score estimate (0–100)
    recovery_score = None
    if hrv is not None:
        hrv_vals = [d["hrv"] for d in daily_14 if d.get("hrv")]
        baseline_hrv = sum(hrv_vals) / len(hrv_vals) if hrv_vals else hrv
        hrv_score = min(100, max(0, int(50 + (hrv - baseline_hrv) / max(baseline_hrv, 1) * 100)))
        recovery_score = hrv_score
    if rhr is not None and baseline_rhr is not None:
        rhr_score = min(100, max(0, int(75 - (rhr - baseline_rhr) * 5)))
        recovery_score = ((recovery_score or 75) + rhr_score) // 2
    if sleep_h is not None:
        sleep_score = min(100, max(0, int((sleep_h / 8) * 100)))
        recovery_score = ((recovery_score or 75) + sleep_score) // 2

    # Last run
    last_run = get_recent_runs(data, 1)
    last_run = last_run[0] if last_run else None
    days_since_run = None
    if last_run:
        lr_date = date.fromisoformat((last_run.get("start") or today.isoformat())[:10])
        days_since_run = (today - lr_date).days

    # --- Headline ---
    if recovery_score is not None:
        if recovery_score >= 75:
            headline = "Recovery looks good — green light to run today."
        elif recovery_score >= 50:
            headline = "Moderate recovery — keep it easy today."
        else:
            headline = "Low recovery — rest or a gentle walk is the smart call."
    elif days_since_run is None:
        headline = "No runs logged yet — time to start!"
    elif days_since_run <= 1:
        headline = "You ran recently — check how your legs feel before heading out."
    elif days_since_run >= 4:
        headline = f"{days_since_run} days since your last run — let's get moving!"
    else:
        headline = "Good time to lace up — a run today will keep the momentum going."

    lines = [f"**{headline}**", ""]

    # Recovery metrics paragraph
    metrics = []
    if rhr is not None:
        if baseline_rhr and rhr > baseline_rhr + 3:
            metrics.append(f"resting HR is {rhr} bpm (above your {baseline_rhr} bpm baseline — body is working harder than usual)")
        else:
            metrics.append(f"resting HR is {rhr} bpm")
    if hrv is not None:
        metrics.append(f"HRV is {hrv} ms")
    if sleep_h is not None:
        sl = "good" if sleep_h >= 7.5 else ("okay" if sleep_h >= 6.5 else "short")
        metrics.append(f"sleep was {sleep_h:.1f} hours ({sl})")
    if metrics:
        lines.append("Your numbers today: " + ", ".join(metrics) + ".")
        lines.append("")

    # Last run insight
    if last_run:
        lr_hr = last_run.get("avg_hr")
        lr_km = last_run.get("distance_km") or 0
        lr_mins = last_run.get("duration_mins") or 0
        if lr_hr:
            if lr_hr <= easy_hr_cap:
                lines.append(f"Last run avg HR was {lr_hr:.0f} bpm — nicely controlled, well within easy zone.")
            elif lr_hr <= easy_hr_cap + 8:
                lines.append(f"Last run avg HR {lr_hr:.0f} bpm — slightly above {easy_hr_cap} bpm cap, likely the Singapore heat. Try starting slower next time.")
            else:
                lines.append(f"Last run avg HR {lr_hr:.0f} bpm — too high for easy running (cap: {easy_hr_cap} bpm). Slow down: if you can't hold a conversation, you're going too fast.")
            lines.append("")

    # Phase-specific advice
    if phase_name == "Norway Hiking":
        lines.append(
            "You're in Norway — the hiking IS your training. Every step counts. "
            "Focus on fuelling well, staying hydrated, and looking after your knees on the descents. No pressure to run."
        )
    elif phase_name == "RACE DAY":
        lines.append(
            f"**Race day!** Target {context.get('target_time','2:30')} — that's {context.get('target_pace_per_km','7:06')}/km. "
            "Start 10–15 sec/km slower than target for the first 5 km. The Singapore heat bites early — go out controlled. "
            "Drink at every station. You've put in the work. Go get it!"
        )
    elif phase_name == "Race Taper":
        lines.append(
            "Taper time — trust the training you've banked. Keep runs short (3–4 km) and easy. "
            "Sleep as much as you can, eat well, and stay off your feet when you don't need to be on them."
        )
    elif phase_name == "Shake Out":
        lines.append(
            "Welcome back from Norway! Your legs have done serious elevation work. "
            "Two easy 4–5 km runs this week is all you need — just remind your body what road running feels like."
        )
    elif phase_name == "Taper":
        lines.append(
            "Pre-Norway taper. Cut volume by about 30% and keep all runs easy. "
            "Arrive in Norway feeling fresh, not carrying accumulated fatigue."
        )
    elif phase_name == "Base Building":
        if recovery_score is not None and recovery_score >= 75:
            lines.append(
                f"Good day to get a run in. Aim for 5–6 km at a conversational pace, HR under {easy_hr_cap} bpm. "
                "In Singapore heat that means going slower than feels right — that's correct. "
                "The aerobic base you build now pays off in September."
            )
        elif recovery_score is not None and recovery_score >= 50:
            lines.append(
                f"Moderate recovery today — keep it to 4–5 km, very easy, HR under {easy_hr_cap} bpm. "
                "If you feel flat after 10 minutes, turn around. No hero miles."
            )
        else:
            lines.append(
                "Low recovery today — skip the run and rest. One rest day now protects the whole block. "
                "A short walk is fine if you need to move."
            )
    elif phase_name == "Build":
        if recovery_score is not None and recovery_score >= 75:
            lines.append(
                f"Good readiness — this week's long run can stretch to 10–12 km. "
                f"Keep it easy (HR under {easy_hr_cap} bpm), and add one short tempo effort: "
                f"15–20 min at {tempo_range} bpm in the middle of a 6 km run."
            )
        else:
            lines.append(
                f"Take it easy today: 5–6 km at a relaxed pace, HR under {easy_hr_cap} bpm. "
                "Save the tempo work for when your body is fresh."
            )
    elif phase_name == "Peak Block":
        if recovery_score is not None and recovery_score >= 75:
            lines.append(
                f"Readiness supports quality work. Consider a tempo run: 8–10 km with 20 min at race pace "
                f"({context.get('target_pace_per_km','7:06')}/km) in the middle. Warm up and cool down easy."
            )
        else:
            lines.append(
                f"Keep today easy: 5–6 km at a relaxed pace, HR under {easy_hr_cap} bpm. "
                "Quality sessions only work when you're recovered enough to execute them."
            )
    else:
        lines.append(
            f"Keep the consistency going: easy 5 km, HR under {easy_hr_cap} bpm. "
            "Show up, keep it relaxed, and trust the process."
        )

    lines.append("")

    # 3-day plan
    def day_plan(offset):
        target_date = today + timedelta(days=offset)
        label = ["Today", "Tomorrow", "Day after"][offset]
        dow = target_date.strftime("%a")
        p = next(
            (ph for ph in context.get("training_phases", [])
             if ph["start"] <= target_date.isoformat() <= ph["end"]), None
        )
        pname = p["name"] if p else phase_name

        if pname == "Norway Hiking":
            return f"**{label} ({dow}):** Hiking — active adventure, mind the knees on descents."
        elif pname == "RACE DAY":
            return f"**{label} ({dow}):** RACE DAY — Kiprun Singapore Half Marathon. Sub 2:30!"
        elif pname == "Race Taper":
            return f"**{label} ({dow}):** Easy 3–4 km or full rest. Stay fresh."
        elif pname == "Shake Out":
            return f"**{label} ({dow}):** Easy 4–5 km, very relaxed, no pace target."
        elif pname == "Taper":
            return f"**{label} ({dow}):** {'Easy 4–5 km, light.' if offset % 2 == 0 else 'Rest or short walk.'}"
        elif pname == "Base Building":
            return f"**{label} ({dow}):** {'Easy 5–6 km, HR under ' + str(easy_hr_cap) + ' bpm.' if offset % 2 == 0 else 'Rest or light walk.'}"
        elif pname == "Build":
            if offset == 2:
                return f"**{label} ({dow}):** Long run — 10–12 km easy, time on feet over pace."
            elif offset == 1:
                return f"**{label} ({dow}):** Rest or easy 4 km."
            return f"**{label} ({dow}):** Easy 6 km or short tempo (15 min at {tempo_range} bpm)."
        elif pname == "Peak Block":
            if offset == 2:
                return f"**{label} ({dow}):** Long run — 14–16 km easy, practice fuelling."
            elif offset == 1:
                return f"**{label} ({dow}):** Rest or easy 5 km."
            return f"**{label} ({dow}):** Tempo run — 8 km with 20 min at {context.get('target_pace_per_km','7:06')}/km."
        else:
            return f"**{label} ({dow}):** {'Easy 5 km, HR under ' + str(easy_hr_cap) + ' bpm.' if offset % 2 == 0 else 'Rest.'}"

    lines.append("**3-Day Plan:**")
    lines.append("")
    for i in range(3):
        lines.append(day_plan(i))
    lines.append("")
    lines.append(f"*{days_to_race} days to race · Phase: {phase_name}*")

    return "\n".join(lines)


def js_arr(lst):
    return "[" + ",".join("null" if v is None else str(v) for v in lst) + "]"


def generate_html(data, context, coaching_text):
    today = date.today()
    race_date = date.fromisoformat(context.get("race_date", "2026-09-27"))
    days_to_race = (race_date - today).days

    daily_14 = get_daily_range(data, 14)
    today_d  = next((d for d in daily_14 if d["date"] == today.isoformat()), None)

    # Today's metrics
    rhr      = g(today_d, "resting_hr") or "—"
    hrv      = g(today_d, "hrv") or "—"
    sleep_h  = g(today_d, "sleep_hours")
    steps_r  = g(today_d, "steps")
    active_e = g(today_d, "active_energy") or "—"

    sleep_s  = f"{sleep_h:.1f} hrs" if sleep_h else "—"
    steps_s  = f"{steps_r:,}" if isinstance(steps_r, int) else (f"{int(steps_r):,}" if steps_r else "—")

    # Recovery colour
    rhr_vals = [d["resting_hr"] for d in daily_14 if d.get("resting_hr")]
    baseline_rhr = round(sum(rhr_vals) / len(rhr_vals)) if rhr_vals else None
    hrv_vals = [d["hrv"] for d in daily_14 if d.get("hrv")]
    baseline_hrv = round(sum(hrv_vals) / len(hrv_vals)) if hrv_vals else None

    recovery_color = "#6b7280"
    if isinstance(hrv, (int, float)) and baseline_hrv:
        ratio = hrv / baseline_hrv
        if ratio >= 0.97:   recovery_color = "#10b981"
        elif ratio >= 0.90: recovery_color = "#f59e0b"
        else:               recovery_color = "#ef4444"

    # Chart data
    chart_labels = json.dumps([d["date"][5:] for d in daily_14])
    chart_rhr    = js_arr([d.get("resting_hr") for d in daily_14])
    chart_hrv    = js_arr([d.get("hrv") for d in daily_14])
    chart_sleep  = js_arr([d.get("sleep_hours") for d in daily_14])
    chart_steps  = js_arr([d.get("steps") for d in daily_14])

    weekly_vols  = get_weekly_volumes(data, 10)
    week_labels  = json.dumps([w[0] for w in weekly_vols])
    week_kms     = js_arr([w[1] for w in weekly_vols])

    # Recent runs for pace/HR trend
    recent10   = get_recent_runs(data, 10)[::-1]
    run_labels = json.dumps([(r.get("start") or "")[:10][5:] for r in recent10])
    run_pace   = js_arr([
        round((r["duration_mins"] / r["distance_km"]), 2) if r.get("distance_km") and r.get("duration_mins") else None
        for r in recent10
    ])
    run_hr     = js_arr([r.get("avg_hr") for r in recent10])

    # Latest run review
    latest_run = get_recent_runs(data, 1)
    latest_run = latest_run[0] if latest_run else None
    run_review_html = ""

    if latest_run:
        lr = latest_run
        lr_date  = (lr.get("start") or "")[:10]
        lr_name  = lr.get("name") or lr.get("type") or "Run"
        lr_km    = lr.get("distance_km") or 0
        lr_mins  = lr.get("duration_mins") or 0
        lr_pace  = pace_str(lr_km, lr_mins)
        lr_dur   = dur_str(lr_mins)
        lr_hr    = lr.get("avg_hr") or "—"
        lr_hr_max = lr.get("max_hr") or "—"
        lr_elev  = lr.get("elevation_m") or 0
        lr_cal   = lr.get("calories") or "—"
        lr_cad_raw = lr.get("avg_cadence")
        lr_cad   = f"{lr_cad_raw * 2:.0f} spm" if lr_cad_raw else "—"

        easy_cap = context.get("hr_zones", {}).get("easy_max", 145)
        verdict_parts = []
        if isinstance(lr_hr, (int, float)):
            if lr_hr <= easy_cap:
                verdict_parts.append(f"HR well controlled at {lr_hr:.0f} bpm — great aerobic discipline.")
            elif lr_hr <= easy_cap + 8:
                verdict_parts.append(f"HR at {lr_hr:.0f} bpm — slightly above {easy_cap} bpm, likely the heat. Try starting slower.")
            else:
                verdict_parts.append(f"HR at {lr_hr:.0f} bpm — above easy zone. Slow right down: if you can't chat, you're going too hard.")
        if lr_cad_raw:
            spm = lr_cad_raw * 2
            if spm < 160:
                verdict_parts.append(f"Cadence {spm:.0f} spm — try shorter, quicker steps toward 170+.")
            elif spm < 170:
                verdict_parts.append(f"Cadence {spm:.0f} spm — closing in on 170+, keep it up.")
            else:
                verdict_parts.append(f"Cadence {spm:.0f} spm — excellent running economy.")
        verdict = " ".join(verdict_parts) if verdict_parts else "Solid effort — keep the consistency going!"

        run_review_html = f"""<div class="run-review">
  <div class="run-header">
    <div>
      <div class="run-title">{lr_name}</div>
      <div class="run-date">{lr_date}</div>
    </div>
    <div class="run-stat-row">
      <div class="run-stat"><span class="rs-val">{lr_km:.2f} km</span><span class="rs-lbl">Distance</span></div>
      <div class="run-stat"><span class="rs-val">{lr_pace}</span><span class="rs-lbl">Avg Pace</span></div>
      <div class="run-stat"><span class="rs-val">{lr_dur}</span><span class="rs-lbl">Time</span></div>
      <div class="run-stat"><span class="rs-val">{lr_hr}</span><span class="rs-lbl">Avg HR</span></div>
      <div class="run-stat"><span class="rs-val">{lr_hr_max}</span><span class="rs-lbl">Max HR</span></div>
      <div class="run-stat"><span class="rs-val">{lr_cad}</span><span class="rs-lbl">Cadence</span></div>
      <div class="run-stat"><span class="rs-val">{lr_elev:.0f} m</span><span class="rs-lbl">Elevation</span></div>
      <div class="run-stat"><span class="rs-val">{lr_cal}</span><span class="rs-lbl">Calories</span></div>
    </div>
  </div>
  <div class="run-verdict">💬 {verdict}</div>
</div>"""

    # Activities table
    acts_rows = ""
    for act in sorted(data.get("workouts", []), key=lambda w: w.get("start",""), reverse=True)[:8]:
        d     = (act.get("start") or "")[:10]
        name  = act.get("name") or act.get("type") or "Workout"
        km    = act.get("distance_km") or 0
        mins  = act.get("duration_mins") or 0
        p     = pace_str(km, mins) if is_run(act) else "—"
        hr    = act.get("avg_hr") or "—"
        hr_s  = f"{hr:.0f}" if isinstance(hr, float) else str(hr)
        elev  = act.get("elevation_m") or 0
        cal   = act.get("calories") or "—"
        acts_rows += f"<tr><td>{d[5:]}</td><td>{name}</td><td>{km:.1f} km</td><td>{p}</td><td>{hr_s}</td><td>{dur_str(mins)}</td><td>{elev:.0f} m</td><td>{cal}</td></tr>\n"

    # Training phases
    phase_html = ""
    for phase in context.get("training_phases", []):
        ps, pe = phase["start"], phase["end"]
        is_current = ps <= today.isoformat() <= pe
        is_past    = pe < today.isoformat()
        cls  = "phase-current" if is_current else ("phase-past" if is_past else "phase-future")
        tag  = '<span class="now-tag">NOW</span>' if is_current else ""
        phase_html += f"""<div class="phase {cls}">
          <div class="phase-left">{tag}<span class="phase-name">{phase['name']}</span></div>
          <div class="phase-right"><span class="phase-dates">{ps[5:]} – {pe[5:]}</span><span class="phase-focus">{phase['focus']}</span></div>
        </div>\n"""

    # Coach HTML
    coach_html = ""
    for para in coaching_text.strip().split("\n"):
        para = para.strip()
        if not para:
            continue
        para = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', para)
        coach_html += f"<p>{para}</p>\n"

    synced_at = data.get("synced_at", "")[:16].replace("T", " ") or today.isoformat()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{context.get('athlete_name','Amanda')} · Training Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}}
.header{{background:linear-gradient(135deg,#4a1d96,#0f172a);padding:20px 16px 16px;border-bottom:1px solid #1e293b}}
.header h1{{font-size:1.25rem;font-weight:700;color:#f1f5f9}}
.header .sub{{font-size:0.8rem;color:#94a3b8;margin-top:3px}}
.pills{{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}}
.pill{{display:inline-block;padding:4px 12px;border-radius:20px;font-size:0.75rem;font-weight:600}}
.pill-purple{{background:#2e1065;border:1px solid #a855f7;color:#d8b4fe}}
.pill-green{{background:#052e16;border:1px solid #22c55e;color:#86efac}}
.wrap{{max-width:900px;margin:0 auto;padding:14px}}
.sec{{font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#475569;margin:22px 0 8px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px}}
.card{{background:#1e293b;border-radius:10px;padding:12px;border:1px solid #334155}}
.card .lbl{{font-size:0.65rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px}}
.card .val{{font-size:1.5rem;font-weight:700;color:#f1f5f9;line-height:1}}
.card .sub2{{font-size:0.7rem;color:#94a3b8;margin-top:2px}}
.rec-wrap{{display:grid;grid-template-columns:auto 1fr;gap:8px;align-items:start}}
.rec-card{{background:#1e293b;border-radius:10px;padding:14px 16px;border:2px solid {recovery_color};min-width:110px;text-align:center}}
.rec-card .lbl{{font-size:0.65rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}}
.rec-val{{font-size:2rem;font-weight:800;color:{recovery_color};line-height:1}}
.rec-sub{{font-size:0.75rem;color:{recovery_color};font-weight:600;margin-top:4px}}
.coach-card{{background:#1e293b;border-radius:10px;padding:16px;border-left:3px solid #a855f7}}
.coach-card p{{font-size:0.88rem;line-height:1.65;color:#cbd5e1}}
.coach-card p+p{{margin-top:8px}}
.coach-card strong{{color:#f1f5f9}}
.box{{background:#1e293b;border-radius:10px;padding:14px;border:1px solid #334155;margin-bottom:8px}}
.box h3{{font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#475569;margin-bottom:10px}}
table{{width:100%;border-collapse:collapse;font-size:0.78rem}}
th{{text-align:left;color:#475569;font-weight:600;font-size:0.65rem;text-transform:uppercase;letter-spacing:.04em;padding:5px 6px;border-bottom:1px solid #334155}}
td{{padding:7px 6px;border-bottom:1px solid #1e293b;color:#cbd5e1}}
tr:last-child td{{border-bottom:none}}
.phase{{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-radius:8px;margin-bottom:5px;gap:12px}}
.phase-past{{background:#0f172a;opacity:.5}}
.phase-current{{background:#2e1065;border:1px solid #a855f7}}
.phase-future{{background:#1e293b}}
.phase-left{{display:flex;align-items:center;gap:8px;min-width:130px}}
.phase-name{{font-size:0.82rem;font-weight:600;color:#e2e8f0}}
.phase-past .phase-name{{color:#475569}}
.phase-right{{display:flex;flex-direction:column;align-items:flex-end;gap:2px}}
.phase-dates{{font-size:0.68rem;color:#64748b}}
.phase-focus{{font-size:0.73rem;color:#94a3b8;text-align:right}}
.phase-current .phase-focus{{color:#d8b4fe}}
.now-tag{{background:#a855f7;color:#fff;font-size:0.6rem;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase}}
.run-review{{background:#1e293b;border-radius:10px;padding:14px;border:1px solid #334155;margin-bottom:8px}}
.run-header{{margin-bottom:12px}}
.run-title{{font-size:1rem;font-weight:700;color:#f1f5f9}}
.run-date{{font-size:0.72rem;color:#64748b;margin-top:2px}}
.run-stat-row{{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px}}
.run-stat{{display:flex;flex-direction:column;min-width:60px}}
.rs-val{{font-size:0.95rem;font-weight:700;color:#f1f5f9}}
.rs-lbl{{font-size:0.62rem;color:#64748b;text-transform:uppercase;letter-spacing:.04em;margin-top:1px}}
.run-verdict{{background:#0f172a;border-radius:8px;padding:10px 12px;font-size:0.82rem;color:#94a3b8;margin-top:10px;line-height:1.5}}
.footer{{font-size:0.65rem;color:#334155;text-align:center;padding:20px 0 12px}}
@media(max-width:520px){{
  .rec-wrap{{grid-template-columns:1fr}}
  .cards{{grid-template-columns:repeat(2,1fr)}}
  .phase-right{{display:none}}
}}
</style>
</head>
<body>
<div class="header">
<div style="max-width:900px;margin:0 auto">
  <h1>🏃‍♀️ {context.get('athlete_name','Amanda')} · Training Dashboard</h1>
  <div class="sub">{context.get('race_name','Race')} · Target {context.get('target_time','')}</div>
  <div class="pills">
    <span class="pill pill-purple">🏁 {days_to_race} days to race</span>
    <span class="pill pill-green">Synced {synced_at}</span>
  </div>
</div>
</div>

<div class="wrap">

<div class="sec">Today's Recovery</div>
<div class="rec-wrap">
  <div class="rec-card">
    <div class="lbl">HRV</div>
    <div class="rec-val">{hrv}</div>
    <div class="rec-sub">ms</div>
  </div>
  <div class="cards" style="margin:0">
    <div class="card"><div class="lbl">Resting HR</div><div class="val">{rhr}</div><div class="sub2">bpm{(' · baseline ' + str(baseline_rhr)) if baseline_rhr else ''}</div></div>
    <div class="card"><div class="lbl">Sleep</div><div class="val" style="font-size:1.2rem">{sleep_s}</div><div class="sub2">last night</div></div>
    <div class="card"><div class="lbl">Steps</div><div class="val" style="font-size:1.1rem">{steps_s}</div><div class="sub2">today</div></div>
    <div class="card"><div class="lbl">Active Energy</div><div class="val" style="font-size:1.1rem">{active_e}</div><div class="sub2">kcal</div></div>
  </div>
</div>

<div class="sec">Daily Coach</div>
<div class="coach-card">
  {coach_html}
</div>

<div class="sec">Latest Run Review</div>
{run_review_html if run_review_html else '<div class="box" style="color:#475569;font-size:0.85rem">No runs yet — go log one!</div>'}

<div class="sec">14-Day Trends</div>
<div class="box"><h3>Resting Heart Rate (bpm)</h3><canvas id="rhr" height="75"></canvas></div>
<div class="box"><h3>HRV (ms)</h3><canvas id="hrv" height="75"></canvas></div>
<div class="box"><h3>Sleep (hours)</h3><canvas id="sleep" height="75"></canvas></div>
<div class="box"><h3>Steps</h3><canvas id="steps" height="75"></canvas></div>

<div class="sec">10-Week Running Volume</div>
<div class="box"><h3>Weekly Distance (km)</h3><canvas id="vol" height="80"></canvas></div>

<div class="sec">Pace &amp; HR Trends</div>
<div class="box"><h3>Avg Pace — last 10 runs (min/km)</h3><canvas id="pace" height="75"></canvas></div>
<div class="box"><h3>Avg Heart Rate — last 10 runs</h3><canvas id="runhr" height="75"></canvas></div>

<div class="sec">Recent Activities</div>
<div class="box" style="overflow-x:auto">
  <table>
    <thead><tr><th>Date</th><th>Activity</th><th>Dist</th><th>Pace</th><th>Avg HR</th><th>Time</th><th>Elev</th><th>Cal</th></tr></thead>
    <tbody>{acts_rows}</tbody>
  </table>
</div>

<div class="sec">Training Plan</div>
<div class="box">
  {phase_html}
</div>

<div class="footer">Apple Health · auto-synced daily via iPhone Shortcut</div>
</div>

<script>
const opt = (ymin, ymax, dec) => ({{
  responsive: true,
  plugins: {{ legend: {{ labels: {{ color: '#64748b', font: {{ size: 10 }} }} }} }},
  scales: {{
    x: {{ ticks: {{ color: '#475569', font: {{ size: 10 }} }}, grid: {{ color: '#1e293b' }} }},
    y: {{ ticks: {{ color: '#475569', font: {{ size: 10 }}, callback: v => dec ? v.toFixed(dec) : v }}, grid: {{ color: '#334155' }}, min: ymin, max: ymax }}
  }}
}});
const L = {chart_labels};
new Chart(document.getElementById('rhr'), {{ type:'line', data:{{ labels:L, datasets:[{{ label:'bpm', data:{chart_rhr}, borderColor:'#ef4444', backgroundColor:'rgba(239,68,68,.1)', fill:true, tension:.35, pointRadius:3 }}] }}, options:opt() }});
new Chart(document.getElementById('hrv'), {{ type:'line', data:{{ labels:L, datasets:[{{ label:'ms', data:{chart_hrv}, borderColor:'#a855f7', backgroundColor:'rgba(168,85,247,.1)', fill:true, tension:.35, pointRadius:3 }}] }}, options:opt() }});
new Chart(document.getElementById('sleep'), {{ type:'bar', data:{{ labels:L, datasets:[{{ label:'hrs', data:{chart_sleep}, backgroundColor:'rgba(59,130,246,.6)', borderColor:'#3b82f6', borderWidth:1, borderRadius:3 }}] }}, options:opt(0, 10, 1) }});
new Chart(document.getElementById('steps'), {{ type:'bar', data:{{ labels:L, datasets:[{{ label:'steps', data:{chart_steps}, backgroundColor:'rgba(16,185,129,.5)', borderColor:'#10b981', borderWidth:1, borderRadius:3 }}] }}, options:opt() }});
new Chart(document.getElementById('vol'), {{ type:'bar', data:{{ labels:{week_labels}, datasets:[{{ label:'km', data:{week_kms}, backgroundColor:'rgba(168,85,247,.6)', borderColor:'#a855f7', borderWidth:1, borderRadius:4 }}] }}, options:opt(0) }});
new Chart(document.getElementById('pace'), {{ type:'line', data:{{ labels:{run_labels}, datasets:[{{ label:'min/km', data:{run_pace}, borderColor:'#f97316', backgroundColor:'rgba(249,115,22,.1)', fill:true, tension:.35, pointRadius:4 }}] }}, options:opt(undefined, undefined, 2) }});
new Chart(document.getElementById('runhr'), {{ type:'line', data:{{ labels:{run_labels}, datasets:[{{ label:'bpm', data:{run_hr}, borderColor:'#ef4444', backgroundColor:'rgba(239,68,68,.1)', fill:true, tension:.35, pointRadius:4 }}] }}, options:opt() }});
</script>
</body>
</html>"""

    return html


if __name__ == "__main__":
    DOCS_DIR.mkdir(exist_ok=True)
    data     = load_data()
    context  = load_context()
    coaching = get_coaching(data, context)
    html     = generate_html(data, context, coaching)
    OUTPUT_FILE.write_text(html)
    print(f"Dashboard written → {OUTPUT_FILE}")
