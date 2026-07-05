#!/usr/bin/env python3
"""Generate docs/index.html from health/data.json and context.json."""

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

def parse_dt(dt_str):
    """Parse an ISO timestamp string (already in local/SGT time from Intervals.icu)."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str[:19])
    except Exception:
        return None

def dt_display(dt_str):
    """Return 'DD Mon HH:MM' from a local timestamp string."""
    dt = parse_dt(dt_str)
    return dt.strftime("%d %b %H:%M") if dt else "—"

SCRIPT_DIR   = Path(__file__).parent
DATA_FILE    = SCRIPT_DIR / "health" / "data.json"
CONTEXT_FILE = SCRIPT_DIR / "context.json"
COACH_FILE   = SCRIPT_DIR / "health" / "coach_note.md"
DOCS_DIR     = SCRIPT_DIR / "docs"
OUTPUT_FILE  = DOCS_DIR / "index.html"


# ── helpers ──────────────────────────────────────────────────────────────────

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
    return (w.get("type") or "").lower() in ("run", "virtualrun", "treadmill", "running")


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


def js_arr(lst):
    return "[" + ",".join("null" if v is None else str(v) for v in lst) + "]"


def get_recent_runs(data, n=10):
    runs = [w for w in data.get("workouts", []) if is_run(w)]
    runs.sort(key=lambda w: w.get("start", ""), reverse=True)
    return runs[:n]


def get_weekly_volumes(data, weeks=14):
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


# ── AI / rule-based coach ─────────────────────────────────────────────────────

def get_coaching(data, context):
    today        = date.today()
    race_date    = date.fromisoformat(context.get("race_date", "2026-09-27"))
    days_to_race = (race_date - today).days
    easy_cap     = context.get("hr_zones", {}).get("easy_max", 145)
    tempo_range  = context.get("hr_zones", {}).get("tempo_range", "160–170")

    current_phase = None
    for phase in context.get("training_phases", []):
        if phase["start"] <= today.isoformat() <= phase["end"]:
            current_phase = phase
            break
    phase_name = current_phase["name"] if current_phase else "Training"

    runs_7d  = [w for w in data.get("workouts", []) if is_run(w) and (w.get("start") or "")[:10] >= (today - timedelta(days=6)).isoformat()]
    runs_14d = [w for w in data.get("workouts", []) if is_run(w) and (w.get("start") or "")[:10] >= (today - timedelta(days=13)).isoformat()]
    km_7d    = sum((w.get("distance_km") or 0) for w in runs_7d)
    km_14d   = sum((w.get("distance_km") or 0) for w in runs_14d)
    km_prev  = km_14d - km_7d

    last_run = get_recent_runs(data, 1)
    last_run = last_run[0] if last_run else None
    days_since_run = None
    if last_run:
        lr_date = date.fromisoformat((last_run.get("start") or today.isoformat())[:10])
        days_since_run = (today - lr_date).days

    if days_since_run is None:
        headline = "No runs logged yet — time to get started!"
    elif days_since_run == 0:
        headline = "You ran today — great work! Rest up and recover well."
    elif days_since_run <= 2:
        headline = "Good rhythm — you ran recently. Check how your legs feel today."
    elif days_since_run <= 4:
        headline = "A few days since your last run — good time to get out there."
    else:
        headline = f"{days_since_run} days since your last run — let's get moving again!"

    lines = [f"**{headline}**", ""]

    if km_7d > 0 or km_prev > 0:
        vol = f"This week: {km_7d:.1f} km"
        if km_prev > 0:
            diff = km_7d - km_prev
            trend = f"+{diff:.1f} km" if diff >= 0 else f"{diff:.1f} km"
            vol += f" (last week: {km_prev:.1f} km, {trend})"
        lines.append(vol + ".")
        if km_7d > 0 and km_prev > 0 and km_7d > km_prev * 1.3:
            lines.append("Volume jumped more than 30% this week — ease back a little to protect against injury.")
        lines.append("")

    if last_run:
        lr_hr = last_run.get("avg_hr")
        if lr_hr:
            if lr_hr <= easy_cap:
                lines.append(f"Last run avg HR was {lr_hr:.0f} bpm — nicely controlled, well within easy zone.")
            elif lr_hr <= easy_cap + 8:
                lines.append(f"Last run avg HR {lr_hr:.0f} bpm — slightly above {easy_cap} bpm cap, likely the Singapore heat. Try starting slower next time.")
            else:
                lines.append(f"Last run avg HR {lr_hr:.0f} bpm — above easy zone (cap: {easy_cap} bpm). Slow down: if you can't hold a conversation, you're going too fast.")
            lines.append("")

    if phase_name == "Norway Hiking":
        lines.append("You're in Norway — the hiking IS your training. Every step counts. Focus on fuelling well and looking after your knees on the descents.")
    elif phase_name == "RACE DAY":
        lines.append(f"**Race day!** Target {context.get('target_time','2:30')} — that's {context.get('target_pace_per_km','7:06')}/km. Start 10–15 sec/km slower for the first 5 km. Drink at every station. You've got this!")
    elif phase_name == "Race Taper":
        lines.append("Taper time — trust the training you've banked. Keep runs short (3–4 km) and easy. Sleep well, eat well, stay off your feet.")
    elif phase_name == "Shake Out":
        lines.append("Welcome back from Norway! Two easy 4–5 km runs this week is all you need — just remind your body what road running feels like.")
    elif phase_name == "Base Building":
        lines.append(f"Focus: keep it easy and consistent. Aim for 3 runs of 5–6 km, HR under {easy_cap} bpm. In Singapore heat that means going slower than feels right — that's fine. The aerobic base you build now pays off in September.")
    elif phase_name == "Build":
        lines.append(f"Time to build! Long run can stretch to 10–12 km. Keep it easy (HR under {easy_cap} bpm) and add one short tempo: 15–20 min at {tempo_range} bpm in the middle of a 6 km run.")
    elif phase_name == "Peak Block":
        lines.append(f"Peak block. Long runs up to 16–17 km, one tempo per week at race pace ({context.get('target_pace_per_km','7:06')}/km). Everything else easy (HR under {easy_cap} bpm).")
    elif phase_name == "Taper":
        lines.append("Pre-Norway taper. Cut volume by ~30%, keep all runs easy. Arrive in Norway feeling fresh.")
    else:
        lines.append(f"Keep the consistency going: 3 runs this week, mostly easy (HR under {easy_cap} bpm).")

    lines.append("")

    def day_plan(offset):
        target_date = today + timedelta(days=offset)
        label = ["Today", "Tomorrow", "Day after"][offset]
        dow   = target_date.strftime("%a")
        p = next((ph for ph in context.get("training_phases", []) if ph["start"] <= target_date.isoformat() <= ph["end"]), None)
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
            return f"**{label} ({dow}):** {'Easy 4–5 km, keep it light.' if offset % 2 == 0 else 'Rest or short walk.'}"
        elif pname == "Base Building":
            return f"**{label} ({dow}):** {'Easy 5–6 km, HR under ' + str(easy_cap) + ' bpm.' if offset % 2 == 0 else 'Rest or light walk.'}"
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
            return f"**{label} ({dow}):** Tempo — 8 km with 20 min at {context.get('target_pace_per_km','7:06')}/km."
        else:
            return f"**{label} ({dow}):** {'Easy 5 km, HR under ' + str(easy_cap) + ' bpm.' if offset % 2 == 0 else 'Rest.'}"

    lines.append("**3-Day Plan:**")
    lines.append("")
    for i in range(3):
        lines.append(day_plan(i))
    lines.append("")
    lines.append(f"*{days_to_race} days to race · Phase: {phase_name}*")
    return "\n".join(lines)


# ── HTML generator ────────────────────────────────────────────────────────────

def generate_html(data, context, coaching_text):
    today        = date.today()
    race_date    = date.fromisoformat(context.get("race_date", "2026-09-27"))
    days_to_race = (race_date - today).days

    # ── wellness stats — most recent day with data ──
    daily_sorted = sorted(data.get("daily", []), key=lambda x: x.get("date",""), reverse=True)
    wellness = next((d for d in daily_sorted if any(d.get(k) is not None for k in ("resting_hr","hrv","steps","sleep_hours"))), None)
    w_date      = wellness.get("date","") if wellness else ""
    w_rhr       = wellness.get("resting_hr") if wellness else None
    w_hrv       = wellness.get("hrv") if wellness else None
    w_steps     = wellness.get("steps") if wellness else None
    w_sleep     = wellness.get("sleep_hours") if wellness else None
    w_rhr_s     = f"{w_rhr} bpm" if w_rhr else "—"
    w_steps_s   = f"{w_steps:,}" if w_steps else "—"
    w_label     = f"as of {w_date[5:]}" if w_date else ""
    # RHR colour
    rhr_color   = "#64748b"
    if w_rhr:
        rhr_color = "#10b981" if w_rhr <= 60 else ("#f59e0b" if w_rhr <= 70 else "#ef4444")

    # ── weekly stats ──
    weekly_vols = get_weekly_volumes(data, 14)
    week_labels = json.dumps([w[0] for w in weekly_vols])
    week_kms    = js_arr([w[1] for w in weekly_vols])

    runs_7d  = [w for w in data.get("workouts", []) if is_run(w) and (w.get("start") or "")[:10] >= (today - timedelta(days=6)).isoformat()]
    runs_14d = [w for w in data.get("workouts", []) if is_run(w) and (w.get("start") or "")[:10] >= (today - timedelta(days=13)).isoformat()]
    km_7d    = sum((w.get("distance_km") or 0) for w in runs_7d)
    km_prev  = sum((w.get("distance_km") or 0) for w in runs_14d) - km_7d
    elev_7d  = sum((w.get("elevation_m") or 0) for w in runs_7d)
    count_7d = len(runs_7d)
    all_runs = [w for w in data.get("workouts", []) if is_run(w)]

    # Compute ACWR (acute:chronic workload ratio) — 7-day / 28-day average
    km_28d = sum((w.get("distance_km") or 0) for w in data.get("workouts", [])
                 if is_run(w) and (w.get("start") or "")[:10] >= (today - timedelta(days=27)).isoformat())
    chronic = km_28d / 4 if km_28d else 0
    acwr    = round(km_7d / chronic, 2) if chronic else None
    if acwr is None:
        acwr_s, acwr_status, acwr_color = "—", "", "#64748b"
    elif acwr < 0.8:
        acwr_s, acwr_status, acwr_color = str(acwr), "Low load", "#64748b"
    elif acwr < 1.3:
        acwr_s, acwr_status, acwr_color = str(acwr), "Optimal", "#10b981"
    else:
        acwr_s, acwr_status, acwr_color = str(acwr), "High load", "#ef4444"

    # ── pace/HR trend (last 10 runs) ──
    recent10   = get_recent_runs(data, 10)[::-1]
    run_labels = json.dumps([dt_display(r.get("start") or "")[:6] for r in recent10])
    run_pace   = js_arr([
        round(r.get("duration_mins") / r.get("distance_km"), 2)
        if r.get("distance_km") and r.get("duration_mins") and r.get("distance_km") > 0 else None
        for r in recent10
    ])
    run_hr = js_arr([r.get("avg_hr") for r in recent10])

    # ── latest run review ──
    latest_run = get_recent_runs(data, 1)
    latest_run = latest_run[0] if latest_run else None
    run_review_html = ""
    map_js = ""

    if latest_run:
        lr       = latest_run
        lr_dt    = parse_dt(lr.get("start") or "")
        lr_date  = lr_dt.strftime("%d %b %Y") if lr_dt else "—"
        lr_time  = lr_dt.strftime("%d %b %Y, %I:%M %p SGT") if lr_dt else "—"
        lr_name  = lr.get("name") or "Run"
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
        # Use route from latest run; if missing, fall back to most recent run with a route
        route = lr.get("route")
        if not route:
            all_runs = get_recent_runs(data, 50)
            for r in all_runs:
                if r.get("route"):
                    route = r.get("route")
                    break


        easy_cap = context.get("hr_zones", {}).get("easy_max", 145)
        verdict_parts = []
        if isinstance(lr_hr, (int, float)):
            if lr_hr <= easy_cap:
                verdict_parts.append(f"HR well controlled at {lr_hr:.0f} bpm — great aerobic discipline.")
            elif lr_hr <= easy_cap + 8:
                verdict_parts.append(f"HR at {lr_hr:.0f} bpm — slightly above {easy_cap} bpm cap, likely the Singapore heat. Try starting slower.")
            else:
                verdict_parts.append(f"HR at {lr_hr:.0f} bpm — above easy zone (cap: {easy_cap} bpm). Slow down next time.")
        if lr_cad_raw:
            spm = lr_cad_raw * 2
            if spm < 160:
                verdict_parts.append(f"Cadence {spm:.0f} spm — try shorter, quicker steps toward 170+.")
            elif spm < 170:
                verdict_parts.append(f"Cadence {spm:.0f} spm — closing in on 170+, keep it up.")
            else:
                verdict_parts.append(f"Cadence {spm:.0f} spm — excellent running economy.")
        verdict = " ".join(verdict_parts) if verdict_parts else "Solid effort — keep the consistency going!"

        map_section = ""
        if route:
            route_json = json.dumps(route)
            map_section = """<div id="runmap" style="height:220px;border-radius:8px;margin-top:12px;overflow:hidden"></div>"""
            map_js = f"""
// Leaflet route map
(function(){{
  var coords = {route_json};
  var map = L.map('runmap', {{zoomControl:true, attributionControl:false}});
  L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',
    {{subdomains:'abcd',maxZoom:19}}).addTo(map);
  var poly = L.polyline(coords, {{color:'#a855f7',weight:3,opacity:.9}}).addTo(map);
  // start/end markers
  var startIcon = L.divIcon({{html:'<div style="width:10px;height:10px;border-radius:50%;background:#10b981;border:2px solid #fff"></div>',iconSize:[10,10],className:''}});
  var endIcon   = L.divIcon({{html:'<div style="width:10px;height:10px;border-radius:50%;background:#ef4444;border:2px solid #fff"></div>',iconSize:[10,10],className:''}});
  L.marker(coords[0], {{icon:startIcon}}).addTo(map);
  L.marker(coords[coords.length-1], {{icon:endIcon}}).addTo(map);
  map.fitBounds(poly.getBounds(), {{padding:[12,12]}});
}})();"""

        run_review_html = f"""<div class="run-review">
  <div class="run-header">
    <div>
      <div class="run-title">{lr_name}</div>
      <div class="run-date">🕐 {lr_time}</div>
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
  {map_section}
  <div class="run-verdict">💬 {verdict}</div>
</div>"""

    # ── activities table — skip phantom zero-distance activities ──
    real_acts = [w for w in data.get("workouts", []) if (w.get("distance_km") or 0) > 0 or (w.get("duration_mins") or 0) > 0]
    acts_rows = ""
    for act in sorted(real_acts, key=lambda w: w.get("start", ""), reverse=True)[:10]:
        act_dt = parse_dt(act.get("start") or "")
        d     = act_dt.strftime("%d %b") if act_dt else "—"
        t     = act_dt.strftime("%I:%M %p") if act_dt else ""
        name  = act.get("name") or act.get("type") or "Activity"
        km    = act.get("distance_km") or 0
        mins  = act.get("duration_mins") or 0
        p     = pace_str(km, mins) if is_run(act) and km > 0 else "—"
        hr    = act.get("avg_hr") or "—"
        hr_s  = f"{hr:.0f}" if isinstance(hr, float) else str(hr)
        max_hr_s = str(act.get("max_hr") or "—")
        elev  = act.get("elevation_m") or 0
        cal   = act.get("calories") or "—"
        has_route = "🗺" if act.get("route") else ""
        acts_rows += f"<tr><td>{d}<br><span style='color:#475569;font-size:0.7rem'>{t}</span></td><td>{has_route} {name}</td><td>{km:.1f} km</td><td>{p}</td><td>{hr_s}</td><td>{max_hr_s}</td><td>{dur_str(mins)}</td><td>{elev:.0f} m</td><td>{cal}</td></tr>\n"

    # ── training phase timeline ──
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

    # ── coach HTML ──
    coach_html = ""
    for para in coaching_text.strip().split("\n"):
        para = para.strip()
        if not para:
            continue
        para = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', para)
        coach_html += f"<p>{para}</p>\n"

    _sat_raw  = data.get("synced_at") or today.isoformat()
    try:
        _sat_dt   = datetime.fromisoformat(_sat_raw[:16])
        synced_at = _sat_dt.strftime("%a, %d %b %Y at %I:%M %p")
    except Exception:
        synced_at = _sat_raw[:16].replace("T", " ")
    coach_updated = ""
    if COACH_FILE.exists():
        first_line = COACH_FILE.read_text().split("\n")[0].strip().strip("_")
        # first_line is like "Updated: Sat, 04 Jul 2026 at 01:59 AM SGT"
        coach_updated = first_line.replace("Updated: ", "")
    athlete   = context.get("athlete_name", "Amanda")
    leaflet   = '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9/dist/leaflet.css">\n<script src="https://unpkg.com/leaflet@1.9/dist/leaflet.js"></script>' if map_js else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{athlete} · Training Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
{leaflet}
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
.pill-blue{{background:#0c1a2e;border:1px solid #3b82f6;color:#93c5fd}}
.wrap{{max-width:900px;margin:0 auto;padding:14px}}
.sec{{font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#475569;margin:22px 0 8px}}
/* stat grid */
.stat-wrap{{display:grid;grid-template-columns:auto 1fr;gap:8px;align-items:start}}
.acwr-card{{background:#1e293b;border-radius:10px;padding:14px 16px;border:2px solid {acwr_color};min-width:110px;text-align:center}}
.acwr-card .lbl{{font-size:0.65rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}}
.acwr-card .score{{font-size:2.8rem;font-weight:800;color:{acwr_color};line-height:1}}
.acwr-card .level{{font-size:0.8rem;color:{acwr_color};font-weight:700;margin-top:3px;text-transform:uppercase}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px}}
.card{{background:#1e293b;border-radius:10px;padding:12px;border:1px solid #334155}}
.card .lbl{{font-size:0.65rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px}}
.card .val{{font-size:1.5rem;font-weight:700;color:#f1f5f9;line-height:1}}
.card .sub2{{font-size:0.7rem;color:#94a3b8;margin-top:2px}}
/* coach */
.coach-card{{background:#1e293b;border-radius:10px;padding:16px;border-left:3px solid #a855f7}}
.coach-card p{{font-size:0.88rem;line-height:1.65;color:#cbd5e1}}
.coach-card p+p{{margin-top:8px}}
.coach-card strong{{color:#f1f5f9}}
/* generic box */
.box{{background:#1e293b;border-radius:10px;padding:14px;border:1px solid #334155;margin-bottom:8px}}
.box h3{{font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#475569;margin-bottom:10px}}
/* table */
table{{width:100%;border-collapse:collapse;font-size:0.78rem}}
th{{text-align:left;color:#475569;font-weight:600;font-size:0.65rem;text-transform:uppercase;letter-spacing:.04em;padding:5px 6px;border-bottom:1px solid #334155}}
td{{padding:7px 6px;border-bottom:1px solid #1e293b;color:#cbd5e1}}
tr:last-child td{{border-bottom:none}}
/* phases */
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
/* run review */
.run-review{{background:#1e293b;border-radius:10px;padding:14px;border:1px solid #334155;margin-bottom:8px}}
.run-title{{font-size:1rem;font-weight:700;color:#f1f5f9}}
.run-date{{font-size:0.72rem;color:#64748b;margin-top:2px}}
.run-stat-row{{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px}}
.run-stat{{display:flex;flex-direction:column;min-width:62px}}
.rs-val{{font-size:0.95rem;font-weight:700;color:#f1f5f9}}
.rs-lbl{{font-size:0.62rem;color:#64748b;text-transform:uppercase;letter-spacing:.04em;margin-top:1px}}
.run-verdict{{background:#0f172a;border-radius:8px;padding:10px 12px;font-size:0.82rem;color:#94a3b8;margin-top:12px;line-height:1.5}}
.footer{{font-size:0.65rem;color:#334155;text-align:center;padding:20px 0 12px}}
@media(max-width:560px){{
  .stat-wrap{{grid-template-columns:1fr}}
  .cards{{grid-template-columns:repeat(2,1fr)}}
  .phase-right{{display:none}}
}}
</style>
</head>
<body>
<div class="header">
<div style="max-width:900px;margin:0 auto">
  <h1>🏃‍♀️ {athlete} · Training Dashboard</h1>
  <div class="sub">{context.get('race_name','Kiprun Singapore Half Marathon')} · Target {context.get('target_time','2:30')}</div>
  <div class="pills">
    <span class="pill pill-purple">🏁 {days_to_race} days to race</span>
    <span class="pill pill-green">🔄 Data synced {synced_at} SGT</span>
    {'<span class="pill pill-blue">🤖 AI coach ' + coach_updated + '</span>' if coach_updated else ''}
  </div>
</div>
</div>

<div class="wrap">

<div class="sec">This Week's Load</div>
<div class="stat-wrap">
  <div class="acwr-card">
    <div class="lbl">ACWR</div>
    <div class="score">{acwr_s}</div>
    <div class="level">{acwr_status}</div>
  </div>
  <div class="cards" style="margin:0">
    <div class="card"><div class="lbl">Distance</div><div class="val" style="font-size:1.2rem">{km_7d:.1f} km</div><div class="sub2">{count_7d} run{'s' if count_7d != 1 else ''} · prev {km_prev:.1f} km</div></div>
    <div class="card"><div class="lbl">Elevation</div><div class="val" style="font-size:1.2rem">{elev_7d:.0f} m</div><div class="sub2">gain this week</div></div>
    <div class="card"><div class="lbl">Race Target</div><div class="val" style="font-size:1.2rem">{context.get('target_time','2:30')}</div><div class="sub2">{context.get('target_pace_per_km','7:06')}/km</div></div>
  </div>
</div>

<div class="sec">Latest Health {f'<span style="font-size:0.6rem;color:#334155;font-weight:400;text-transform:none;letter-spacing:0">({w_label})</span>' if w_label else ''}</div>
<div class="cards">
  <div class="card"><div class="lbl">Resting HR</div><div class="val" style="color:{rhr_color}">{w_rhr_s}</div><div class="sub2">Apple Watch</div></div>
  <div class="card"><div class="lbl">Steps</div><div class="val" style="font-size:1.2rem">{w_steps_s}</div><div class="sub2">yesterday</div></div>
</div>

<div class="sec">Daily Coach</div>
<div class="coach-card">
  {coach_html}
</div>

<div class="sec">Latest Run Review</div>
{run_review_html if run_review_html else '<div class="box" style="color:#475569;font-size:0.85rem;padding:14px">No runs synced yet.</div>'}

<div class="sec">14-Week Volume</div>
<div class="box"><h3>Weekly Distance (km)</h3><canvas id="vol" height="80"></canvas></div>

<div class="sec">Pace &amp; HR Trends — last 10 runs</div>
<div class="box"><h3>Avg Pace (min/km)</h3><canvas id="pace" height="75"></canvas></div>
<div class="box"><h3>Avg Heart Rate (bpm)</h3><canvas id="hr" height="75"></canvas></div>

<div class="sec">Recent Activities</div>
<div class="box" style="overflow-x:auto">
  <table>
    <thead><tr><th>Date/Time</th><th>Name</th><th>Dist</th><th>Pace</th><th>Avg HR</th><th>Max HR</th><th>Time</th><th>Elev</th><th>Cal</th></tr></thead>
    <tbody>{acts_rows if acts_rows else '<tr><td colspan="9" style="color:#475569;text-align:center;padding:20px">No activities yet</td></tr>'}</tbody>
  </table>
</div>

<div class="sec">Training Plan</div>
<div class="box">
  {phase_html}
</div>

<div class="footer">Strava → Intervals.icu · auto-synced 4 AM &amp; 4 PM SGT · <a href="https://github.com/reubenchuaa/amanda-health-ai" style="color:#475569">reubenchuaa/amanda-health-ai</a></div>
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
new Chart(document.getElementById('vol'), {{
  type: 'bar',
  data: {{ labels: {week_labels}, datasets: [{{ label: 'km', data: {week_kms}, backgroundColor: 'rgba(168,85,247,.6)', borderColor: '#a855f7', borderWidth: 1, borderRadius: 4 }}] }},
  options: opt(0)
}});
new Chart(document.getElementById('pace'), {{
  type: 'line',
  data: {{ labels: {run_labels}, datasets: [{{ label: 'min/km', data: {run_pace}, borderColor: '#a855f7', backgroundColor: 'rgba(168,85,247,.1)', fill: true, tension: .35, pointRadius: 4 }}] }},
  options: opt(undefined, undefined, 2)
}});
new Chart(document.getElementById('hr'), {{
  type: 'line',
  data: {{ labels: {run_labels}, datasets: [{{ label: 'bpm', data: {run_hr}, borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,.1)', fill: true, tension: .35, pointRadius: 4 }}] }},
  options: opt()
}});
{map_js}
</script>
</body>
</html>"""
    return html


if __name__ == "__main__":
    DOCS_DIR.mkdir(exist_ok=True)
    data    = load_data()
    context = load_context()

    if COACH_FILE.exists():
        print("Using AI coach note...")
        raw = COACH_FILE.read_text()
        # Strip all _Updated: timestamp lines (may have stacked from previous runs)
        coaching = "\n".join(
            line for line in raw.splitlines() if not line.strip().startswith("_Updated:")
        ).strip()
    else:
        print("Generating rule-based coaching...")
        coaching = get_coaching(data, context)

    html = generate_html(data, context, coaching)
    OUTPUT_FILE.write_text(html)
    print(f"Dashboard written → {OUTPUT_FILE}")
