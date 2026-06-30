#!/usr/bin/env python3
"""Generate docs/index.html from strava/data.json and context.json."""

import json
import re
from datetime import date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_FILE = SCRIPT_DIR / "strava" / "data.json"
CONTEXT_FILE = SCRIPT_DIR / "context.json"
DOCS_DIR = SCRIPT_DIR / "docs"
OUTPUT_FILE = DOCS_DIR / "index.html"


def load_data():
    if not DATA_FILE.exists():
        return []
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


def is_run(act):
    return (act.get("type") or act.get("sport_type") or "").lower() in ("run", "virtualrun", "treadmill")


def pace_str(mps):
    if not mps or mps <= 0:
        return "—"
    spm = (1 / mps) * 1000
    m, s = divmod(int(spm), 60)
    return f"{m}:{s:02d}/km"


def dur_str(secs):
    if not secs:
        return "—"
    h, m = divmod(int(secs) // 60, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def week_start(d):
    """Monday of the week containing date d."""
    return d - timedelta(days=d.weekday())


def get_weekly_volumes(data, weeks=10):
    """Returns list of (week_label, km) for last N weeks, oldest first."""
    today = date.today()
    result = []
    for i in range(weeks - 1, -1, -1):
        ws = week_start(today) - timedelta(weeks=i)
        we = ws + timedelta(days=6)
        km = 0.0
        for act in data:
            if not is_run(act):
                continue
            d = (act.get("start_date_local") or "")[:10]
            if ws.isoformat() <= d <= we.isoformat():
                km += (act.get("distance") or 0) / 1000
        result.append((ws.strftime("%b %d"), round(km, 1)))
    return result


def get_recent_runs(data, n=10):
    runs = [a for a in data if is_run(a)]
    runs.sort(key=lambda a: a.get("start_date_local", ""), reverse=True)
    return runs[:n]


def get_recent_activities(data, n=8):
    acts = sorted(data, key=lambda a: a.get("start_date_local", ""), reverse=True)
    return acts[:n]


def get_coaching(data, context):
    today = date.today()
    race_date = date.fromisoformat(context.get("race_date", "2026-09-27"))
    days_to_race = (race_date - today).days
    easy_hr_cap = context.get("hr_zones", {}).get("easy_max", 145)
    tempo_range = context.get("hr_zones", {}).get("tempo_range", "160–170")

    # Current phase
    current_phase = None
    for phase in context.get("training_phases", []):
        if phase["start"] <= today.isoformat() <= phase["end"]:
            current_phase = phase
            break
    phase_name = current_phase["name"] if current_phase else "Training"

    # Activity stats
    runs_14d = [a for a in data if is_run(a) and (a.get("start_date_local") or "")[:10] >= (today - timedelta(days=14)).isoformat()]
    runs_7d  = [a for a in data if is_run(a) and (a.get("start_date_local") or "")[:10] >= (today - timedelta(days=7)).isoformat()]
    km_7d  = sum((a.get("distance") or 0) for a in runs_7d)  / 1000
    km_14d = sum((a.get("distance") or 0) for a in runs_14d) / 1000
    km_prev_week = km_14d - km_7d

    last_run = get_recent_runs(data, 1)
    last_run = last_run[0] if last_run else None
    days_since_run = None
    last_hr_avg = None
    last_pace = None
    last_dist = None
    if last_run:
        lr_date = date.fromisoformat((last_run.get("start_date_local") or today.isoformat())[:10])
        days_since_run = (today - lr_date).days
        last_hr_avg = last_run.get("average_heartrate")
        spd = last_run.get("average_speed")
        last_pace = pace_str(spd) if spd else None
        last_dist = (last_run.get("distance") or 0) / 1000

    # --- Headline ---
    if days_since_run is None:
        headline = "No recent runs found — lace up and log your first one!"
    elif days_since_run == 0:
        headline = "You ran today — great work! Rest up and recover well."
    elif days_since_run <= 2:
        headline = "Good rhythm — you ran recently. Check how your legs feel today."
    elif days_since_run <= 4:
        headline = "A few days since your last run — good time to get out there."
    else:
        headline = f"{days_since_run} days since your last run — let's get moving again!"

    lines = [f"**{headline}**", ""]

    # Volume context
    if km_7d > 0 or km_prev_week > 0:
        vol_note = f"This week: {km_7d:.1f} km"
        if km_prev_week > 0:
            diff = km_7d - km_prev_week
            trend = f"+{diff:.1f} km" if diff >= 0 else f"{diff:.1f} km"
            vol_note += f" (last week: {km_prev_week:.1f} km, {trend})"
        lines.append(vol_note + ".")
        if km_7d > 0 and km_prev_week > 0 and km_7d > km_prev_week * 1.3:
            lines.append("Volume jumped more than 30% this week — ease back a little to protect against injury.")
        lines.append("")

    # Last run insight
    if last_run and last_hr_avg:
        if last_hr_avg <= easy_hr_cap:
            lines.append(f"Last run avg HR {last_hr_avg:.0f} bpm — nicely controlled, well under the {easy_hr_cap} bpm easy cap.")
        elif last_hr_avg <= easy_hr_cap + 8:
            lines.append(f"Last run avg HR {last_hr_avg:.0f} bpm — a touch above {easy_hr_cap} bpm, likely the Singapore heat. Slow down a bit earlier next time.")
        else:
            lines.append(f"Last run avg HR {last_hr_avg:.0f} bpm — too high for an easy run (cap: {easy_hr_cap} bpm). Focus on slowing down: if you can't hold a conversation, you're going too fast.")
        lines.append("")

    # Phase-specific advice
    if phase_name == "Norway Hiking":
        lines.append(
            "You're in Norway — the hiking IS your training. Enjoy every step. "
            "Focus on fuelling well, staying hydrated, and managing your knees on the descents. "
            "No pressure to run."
        )
    elif phase_name == "Race Taper":
        lines.append(
            "Taper week — trust the training you've banked. Keep runs short (3–4 km) and easy. "
            "Sleep as much as you can, eat well, and stay off your feet when you don't need to be on them."
        )
    elif phase_name == "RACE DAY":
        lines.append(
            f"**It's race day!** Target {context.get('target_time', '2:30')} — that's {context.get('target_pace_per_km', '7:06')}/km. "
            "Start 10–15 sec/km slower than target for the first 5 km — the Singapore heat will make you pay if you go out too fast. "
            "Drink at every station. You've done the work. Go get it!"
        )
    elif phase_name in ("Base Building",):
        lines.append(
            f"Focus this week: keep it easy and consistent. Aim for 3 runs of 5–6 km, "
            f"HR under {easy_hr_cap} bpm. In Singapore heat that might mean running slower than feels right — "
            "that's totally fine. The aerobic base you build now pays off in September."
        )
    elif phase_name == "Build":
        lines.append(
            f"Time to build! Your long run can stretch to 10–12 km this block. "
            f"Keep it easy (HR under {easy_hr_cap} bpm) and add one short tempo effort per week: "
            f"15–20 min at {tempo_range} bpm in the middle of a 6 km run. "
            "Everything else stays easy."
        )
    elif phase_name in ("Peak Block",):
        lines.append(
            f"Peak training block. Long runs up to 16–17 km, one tempo session per week at race pace ({context.get('target_pace_per_km', '7:06')}/km). "
            f"Keep all other runs easy (HR under {easy_hr_cap} bpm). "
            "If you feel tired, rest — don't push through fatigue in this phase."
        )
    elif phase_name == "Shake Out":
        lines.append(
            "Welcome back from Norway! Your legs have done serious work. "
            "Two easy 4–5 km runs this week is all you need. No pace pressure — just remind your body what road running feels like."
        )
    elif phase_name == "Taper":
        lines.append(
            "Pre-Norway taper. Cut volume by about 30% and keep all runs easy. "
            "You want to arrive in Norway feeling fresh, not accumulated fatigue."
        )
    else:
        lines.append(
            f"Keep the consistency going: 3 runs this week, mostly easy (HR under {easy_hr_cap} bpm). "
            "One run can have a short faster segment if you're feeling good."
        )

    lines.append("")

    # 3-day plan
    def day_plan(offset):
        target_date = today + timedelta(days=offset)
        label = ["Today", "Tomorrow", "Day after"][offset]
        dow = target_date.strftime("%a")

        p = None
        for phase in context.get("training_phases", []):
            if phase["start"] <= target_date.isoformat() <= phase["end"]:
                p = phase
                break
        pname = p["name"] if p else phase_name

        if pname == "Norway Hiking":
            return f"**{label} ({dow}):** Hiking — active adventure, watch the knees on descents."
        elif pname == "RACE DAY":
            return f"**{label} ({dow}):** RACE DAY — Kiprun Singapore Half Marathon. Sub 2:30!"
        elif pname == "Race Taper":
            return f"**{label} ({dow}):** Easy 3–4 km shakeout or full rest. Stay fresh."
        elif pname == "Shake Out":
            return f"**{label} ({dow}):** Easy 4–5 km, very relaxed, no pace target."
        elif pname == "Taper":
            is_run_day = offset % 2 == 0
            if is_run_day:
                return f"**{label} ({dow}):** Easy 4–5 km, keep it light before Norway."
            return f"**{label} ({dow}):** Rest or short walk."
        elif pname == "Base Building":
            is_run_day = offset % 2 == 0
            if is_run_day:
                return f"**{label} ({dow}):** Easy 5–6 km, HR under {easy_hr_cap} bpm, conversational pace."
            return f"**{label} ({dow}):** Rest or light cross-training."
        elif pname == "Build":
            if offset == 2:
                return f"**{label} ({dow}):** Long run — 8–10 km easy, time on feet matters more than pace."
            elif offset == 1:
                return f"**{label} ({dow}):** Rest or short easy 4 km."
            return f"**{label} ({dow}):** Easy 6 km or tempo run (15 min at {tempo_range} bpm)."
        elif pname == "Peak Block":
            if offset == 2:
                return f"**{label} ({dow}):** Long run — 14–16 km easy, fuelling practice."
            elif offset == 1:
                return f"**{label} ({dow}):** Rest or easy 5 km."
            return f"**{label} ({dow}):** Tempo run — 8 km with 20 min at race pace ({context.get('target_pace_per_km', '7:06')}/km)."
        else:
            is_run_day = offset % 2 == 0
            if is_run_day:
                return f"**{label} ({dow}):** Easy run — 5 km, HR under {easy_hr_cap} bpm."
            return f"**{label} ({dow}):** Rest."

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

    # Current phase
    current_phase = None
    for phase in context.get("training_phases", []):
        if phase["start"] <= today.isoformat() <= phase["end"]:
            current_phase = phase
            break

    # Weekly volumes for chart
    weekly_vols = get_weekly_volumes(data, 10)
    week_labels = json.dumps([w[0] for w in weekly_vols])
    week_kms    = js_arr([w[1] for w in weekly_vols])

    # This week stats
    runs_7d = [a for a in data if is_run(a) and (a.get("start_date_local") or "")[:10] >= (today - timedelta(days=6)).isoformat()]
    km_7d   = sum((a.get("distance") or 0) for a in runs_7d) / 1000
    elev_7d = sum((a.get("total_elevation_gain") or 0) for a in runs_7d)
    runs_this_week = len(runs_7d)
    effort_7d = sum((a.get("suffer_score") or 0) for a in runs_7d)

    # Longest run ever
    all_runs = [a for a in data if is_run(a)]
    longest = max((a.get("distance") or 0) for a in all_runs) / 1000 if all_runs else 0

    # Recent pace chart (last 10 runs, oldest first)
    recent10 = get_recent_runs(data, 10)[::-1]
    pace_labels = json.dumps([(r.get("start_date_local") or "")[:10][5:] for r in recent10])
    pace_vals = js_arr([
        round((1 / r["average_speed"]) * 1000 / 60, 2) if r.get("average_speed") else None
        for r in recent10
    ])
    hr_vals = js_arr([r.get("average_heartrate") for r in recent10])

    # Latest run detail
    latest_run = get_recent_runs(data, 1)
    latest_run = latest_run[0] if latest_run else None
    run_review_html = ""

    if latest_run:
        lr = latest_run
        lr_date = (lr.get("start_date_local") or "")[:10]
        lr_name = lr.get("name", "Run")
        lr_dist = (lr.get("distance") or 0) / 1000
        lr_dist_s = f"{lr_dist:.2f} km"
        lr_spd = lr.get("average_speed")
        lr_pace = pace_str(lr_spd)
        lr_dur = dur_str(lr.get("moving_time"))
        lr_hr_avg = lr.get("average_heartrate") or "—"
        lr_hr_max = lr.get("max_heartrate") or "—"
        lr_elev = lr.get("total_elevation_gain") or 0
        lr_cad_raw = lr.get("average_cadence")
        lr_cad = f"{lr_cad_raw * 2:.0f} spm" if lr_cad_raw else "—"  # Strava reports one-foot cadence
        lr_effort = lr.get("suffer_score") or "—"
        lr_pr = lr.get("pr_count") or 0

        # HR zones from _zones
        zones_data = lr.get("_zones") or {}
        hr_zone_data = zones_data.get("heart_rate", {}) if isinstance(zones_data, dict) else {}
        buckets = hr_zone_data.get("distribution_buckets", []) if isinstance(hr_zone_data, dict) else []
        lr_zones_html = ""
        if buckets:
            z_names  = ["Z1 Recovery", "Z2 Aerobic", "Z3 Tempo", "Z4 Threshold", "Z5 Max"]
            z_colors = ["#64748b", "#10b981", "#f59e0b", "#f97316", "#ef4444"]
            total_secs = sum(b.get("time", 0) for b in buckets)
            for i, b in enumerate(buckets[:5]):
                secs = b.get("time", 0)
                pct = round(secs / total_secs * 100) if total_secs else 0
                m, s = divmod(int(secs), 60)
                zn = z_names[i] if i < len(z_names) else f"Z{i+1}"
                zc = z_colors[i]
                lr_zones_html += f"""<div style="margin-bottom:6px">
                  <div style="display:flex;justify-content:space-between;font-size:0.75rem;margin-bottom:2px">
                    <span style="color:{zc};font-weight:600">{zn}</span>
                    <span style="color:#94a3b8">{m}m {s}s &nbsp;{pct}%</span>
                  </div>
                  <div style="background:#0f172a;border-radius:4px;height:6px">
                    <div style="background:{zc};width:{pct}%;height:6px;border-radius:4px"></div>
                  </div>
                </div>\n"""

        # Km splits
        splits = lr.get("splits_metric") or []
        splits_html = ""
        if splits:
            splits_html = "<div class='splits'><div class='splits-title'>KM Splits</div>"
            for i, sp in enumerate(splits[:25], 1):
                sp_spd = sp.get("average_speed")
                sp_pace = pace_str(sp_spd)
                sp_hr = sp.get("average_heartrate")
                sp_hr_s = f"{sp_hr:.0f}" if sp_hr else "—"
                sp_dist = sp.get("distance", 0)
                sp_dist_s = f"{sp_dist/1000:.2f} km"
                splits_html += f"<div class='split-row'><span class='sp-num'>KM {i}</span><span class='sp-dist'>{sp_dist_s}</span><span class='sp-pace'>{sp_pace}</span><span class='sp-hr'>{sp_hr_s} bpm</span></div>\n"
            splits_html += "</div>"

        # Coaching verdict on this run
        easy_cap = context.get("hr_zones", {}).get("easy_max", 145)
        verdict_parts = []
        if isinstance(lr_hr_avg, (int, float)):
            if lr_hr_avg <= easy_cap:
                verdict_parts.append(f"HR well controlled at {lr_hr_avg:.0f} bpm — great aerobic discipline.")
            elif lr_hr_avg <= easy_cap + 8:
                verdict_parts.append(f"HR at {lr_hr_avg:.0f} bpm — slightly above the {easy_cap} easy cap, likely heat. Try starting slower.")
            else:
                verdict_parts.append(f"HR at {lr_hr_avg:.0f} bpm — that's above easy zone. Slow down: if you can't chat, you're going too hard.")
        if lr_cad_raw:
            actual_spm = lr_cad_raw * 2
            if actual_spm < 160:
                verdict_parts.append(f"Cadence {actual_spm:.0f} spm — try to shorten your stride and quicken turnover toward 170+.")
            elif actual_spm < 170:
                verdict_parts.append(f"Cadence {actual_spm:.0f} spm — getting close to the 170+ efficiency sweet spot.")
            else:
                verdict_parts.append(f"Cadence {actual_spm:.0f} spm — excellent running economy.")
        if lr_pr > 0:
            verdict_parts.append(f"{'1 new PR' if lr_pr == 1 else f'{lr_pr} new PRs'} on this run!")
        verdict = " ".join(verdict_parts) if verdict_parts else "Solid effort — keep the consistency going!"

        run_review_html = f"""<div class="run-review">
  <div class="run-header">
    <div>
      <div class="run-title">{lr_name}</div>
      <div class="run-date">{lr_date}</div>
    </div>
    <div class="run-stat-row">
      <div class="run-stat"><span class="rs-val">{lr_dist_s}</span><span class="rs-lbl">Distance</span></div>
      <div class="run-stat"><span class="rs-val">{lr_pace}</span><span class="rs-lbl">Avg Pace</span></div>
      <div class="run-stat"><span class="rs-val">{lr_dur}</span><span class="rs-lbl">Time</span></div>
      <div class="run-stat"><span class="rs-val">{lr_hr_avg}</span><span class="rs-lbl">Avg HR</span></div>
      <div class="run-stat"><span class="rs-val">{lr_hr_max}</span><span class="rs-lbl">Max HR</span></div>
      <div class="run-stat"><span class="rs-val">{lr_cad}</span><span class="rs-lbl">Cadence</span></div>
      <div class="run-stat"><span class="rs-val">{lr_elev:.0f} m</span><span class="rs-lbl">Elevation</span></div>
      <div class="run-stat"><span class="rs-val">{lr_effort}</span><span class="rs-lbl">Relative Effort</span></div>
    </div>
  </div>
  {"<div class='run-zones'><div class='run-zones-title'>HR Zones</div>" + lr_zones_html + "</div>" if lr_zones_html else ""}
  {splits_html}
  <div class="run-verdict">💬 {verdict}</div>
</div>"""

    # Activities table
    acts_rows = ""
    for act in get_recent_activities(data, 8):
        d = (act.get("start_date_local") or "")[:10]
        name = act.get("name", "Activity")
        sport = (act.get("type") or act.get("sport_type") or "").replace("Run", "🏃").replace("Ride", "🚴").replace("Swim", "🏊")
        dist = (act.get("distance") or 0) / 1000
        dist_s = f"{dist:.2f} km" if dist else "—"
        spd = act.get("average_speed")
        pace_s = pace_str(spd) if is_run(act) else "—"
        hr = act.get("average_heartrate") or "—"
        hr_s = f"{hr:.0f}" if isinstance(hr, float) else str(hr)
        dur = dur_str(act.get("moving_time"))
        elev = act.get("total_elevation_gain") or 0
        effort = act.get("suffer_score") or "—"
        acts_rows += f"<tr><td>{d[5:]}</td><td>{sport} {name}</td><td>{dist_s}</td><td>{pace_s}</td><td>{hr_s}</td><td>{dur}</td><td>{elev:.0f} m</td><td>{effort}</td></tr>\n"

    # Training phases
    phase_html = ""
    for phase in context.get("training_phases", []):
        ps, pe = phase["start"], phase["end"]
        is_current = ps <= today.isoformat() <= pe
        is_past = pe < today.isoformat()
        cls = "phase-current" if is_current else ("phase-past" if is_past else "phase-future")
        tag = '<span class="now-tag">NOW</span>' if is_current else ""
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

    # Stats
    km_7d_s   = f"{km_7d:.1f} km"
    elev_7d_s = f"{elev_7d:.0f} m"
    longest_s = f"{longest:.1f} km" if longest else "—"
    effort_s  = str(effort_7d) if effort_7d else "—"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{context.get('athlete_name', 'Amanda')} · Strava Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}}
.header{{background:linear-gradient(135deg,#7c2d12,#0f172a);padding:20px 16px 16px;border-bottom:1px solid #1e293b}}
.header h1{{font-size:1.25rem;font-weight:700;color:#f1f5f9}}
.header .sub{{font-size:0.8rem;color:#94a3b8;margin-top:3px}}
.pills{{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}}
.pill{{display:inline-block;padding:4px 12px;border-radius:20px;font-size:0.75rem;font-weight:600}}
.pill-orange{{background:#431407;border:1px solid #f97316;color:#fdba74}}
.pill-green{{background:#052e16;border:1px solid #22c55e;color:#86efac}}
.wrap{{max-width:900px;margin:0 auto;padding:14px}}
.sec{{font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#475569;margin:22px 0 8px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px}}
.card{{background:#1e293b;border-radius:10px;padding:12px;border:1px solid #334155}}
.card .lbl{{font-size:0.65rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px}}
.card .val{{font-size:1.5rem;font-weight:700;color:#f1f5f9;line-height:1}}
.card .sub2{{font-size:0.7rem;color:#94a3b8;margin-top:2px}}
.coach-card{{background:#1e293b;border-radius:10px;padding:16px;border-left:3px solid #f97316}}
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
.phase-current{{background:#431407;border:1px solid #f97316}}
.phase-future{{background:#1e293b}}
.phase-left{{display:flex;align-items:center;gap:8px;min-width:130px}}
.phase-name{{font-size:0.82rem;font-weight:600;color:#e2e8f0}}
.phase-past .phase-name{{color:#475569}}
.phase-right{{display:flex;flex-direction:column;align-items:flex-end;gap:2px}}
.phase-dates{{font-size:0.68rem;color:#64748b}}
.phase-focus{{font-size:0.73rem;color:#94a3b8;text-align:right}}
.phase-current .phase-focus{{color:#fdba74}}
.now-tag{{background:#f97316;color:#fff;font-size:0.6rem;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase}}
.run-review{{background:#1e293b;border-radius:10px;padding:14px;border:1px solid #334155;margin-bottom:8px}}
.run-header{{margin-bottom:12px}}
.run-title{{font-size:1rem;font-weight:700;color:#f1f5f9}}
.run-date{{font-size:0.72rem;color:#64748b;margin-top:2px}}
.run-stat-row{{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px}}
.run-stat{{display:flex;flex-direction:column;min-width:60px}}
.rs-val{{font-size:0.95rem;font-weight:700;color:#f1f5f9}}
.rs-lbl{{font-size:0.62rem;color:#64748b;text-transform:uppercase;letter-spacing:.04em;margin-top:1px}}
.run-zones{{margin:10px 0}}
.run-zones-title{{font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#475569;margin-bottom:8px}}
.splits{{margin:10px 0}}
.splits-title{{font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#475569;margin-bottom:8px}}
.split-row{{display:grid;grid-template-columns:50px 70px 90px 1fr;gap:4px;padding:4px 0;border-bottom:1px solid #0f172a;font-size:0.75rem}}
.sp-num{{color:#475569;font-weight:600}}
.sp-dist{{color:#64748b}}
.sp-pace{{color:#f1f5f9;font-weight:600}}
.sp-hr{{color:#94a3b8}}
.run-verdict{{background:#0f172a;border-radius:8px;padding:10px 12px;font-size:0.82rem;color:#94a3b8;margin-top:10px;line-height:1.5}}
.footer{{font-size:0.65rem;color:#334155;text-align:center;padding:20px 0 12px}}
@media(max-width:520px){{
  .cards{{grid-template-columns:repeat(2,1fr)}}
  .phase-right{{display:none}}
  .split-row{{grid-template-columns:40px 60px 80px 1fr}}
}}
</style>
</head>
<body>
<div class="header">
<div style="max-width:900px;margin:0 auto">
  <h1>🏃‍♀️ {context.get('athlete_name','Amanda')} · Strava Dashboard</h1>
  <div class="sub">{context.get('race_name','Race')} · Target {context.get('target_time','')}</div>
  <div class="pills">
    <span class="pill pill-orange">🏁 {days_to_race} days to race</span>
    <span class="pill pill-green">Updated {today.isoformat()}</span>
  </div>
</div>
</div>

<div class="wrap">

<div class="sec">This Week</div>
<div class="cards">
  <div class="card"><div class="lbl">Weekly km</div><div class="val" style="font-size:1.3rem">{km_7d_s}</div><div class="sub2">{runs_this_week} run{'s' if runs_this_week != 1 else ''}</div></div>
  <div class="card"><div class="lbl">Elevation</div><div class="val" style="font-size:1.3rem">{elev_7d_s}</div><div class="sub2">gain this week</div></div>
  <div class="card"><div class="lbl">Relative Effort</div><div class="val" style="font-size:1.3rem">{effort_s}</div><div class="sub2">suffer score</div></div>
  <div class="card"><div class="lbl">Longest Run</div><div class="val" style="font-size:1.3rem">{longest_s}</div><div class="sub2">all time</div></div>
</div>

<div class="sec">Daily Coach</div>
<div class="coach-card">
  {coach_html}
</div>

<div class="sec">Latest Run Review</div>
{run_review_html if run_review_html else '<div class="box" style="color:#475569;font-size:0.85rem">No run data yet — go log one on Strava!</div>'}

<div class="sec">10-Week Volume</div>
<div class="box"><h3>Weekly Distance (km)</h3><canvas id="vol" height="80"></canvas></div>

<div class="sec">Pace &amp; HR Trends</div>
<div class="box"><h3>Avg Pace — last 10 runs (min/km)</h3><canvas id="pace" height="75"></canvas></div>
<div class="box"><h3>Avg Heart Rate — last 10 runs</h3><canvas id="hr" height="75"></canvas></div>

<div class="sec">Recent Activities</div>
<div class="box" style="overflow-x:auto">
  <table>
    <thead><tr><th>Date</th><th>Activity</th><th>Dist</th><th>Pace</th><th>Avg HR</th><th>Time</th><th>Elev</th><th>Effort</th></tr></thead>
    <tbody>{acts_rows}</tbody>
  </table>
</div>

<div class="sec">Training Plan</div>
<div class="box">
  {phase_html}
</div>

<div class="footer">Strava · auto-synced daily · powered by strava-ai</div>
</div>

<script>
const optLine = (ymin, ymax, decimals) => ({{
  responsive: true,
  plugins: {{ legend: {{ labels: {{ color: '#64748b', font: {{ size: 10 }} }} }} }},
  scales: {{
    x: {{ ticks: {{ color: '#475569', font: {{ size: 10 }} }}, grid: {{ color: '#1e293b' }} }},
    y: {{ ticks: {{ color: '#475569', font: {{ size: 10 }}, callback: v => decimals ? v.toFixed(decimals) : v }}, grid: {{ color: '#334155' }}, min: ymin, max: ymax }}
  }}
}});
new Chart(document.getElementById('vol'), {{
  type: 'bar',
  data: {{ labels: {week_labels}, datasets: [{{ label: 'km', data: {week_kms}, backgroundColor: 'rgba(249,115,22,.7)', borderColor: '#f97316', borderWidth: 1, borderRadius: 4 }}] }},
  options: optLine(0, undefined, 0)
}});
new Chart(document.getElementById('pace'), {{
  type: 'line',
  data: {{ labels: {pace_labels}, datasets: [{{ label: 'min/km', data: {pace_vals}, borderColor: '#f97316', backgroundColor: 'rgba(249,115,22,.1)', fill: true, tension: .35, pointRadius: 3 }}] }},
  options: optLine(undefined, undefined, 2)
}});
new Chart(document.getElementById('hr'), {{
  type: 'line',
  data: {{ labels: {pace_labels}, datasets: [{{ label: 'bpm', data: {hr_vals}, borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,.1)', fill: true, tension: .35, pointRadius: 3 }}] }},
  options: optLine(undefined, undefined, 0)
}});
</script>
</body>
</html>"""

    return html


if __name__ == "__main__":
    DOCS_DIR.mkdir(exist_ok=True)
    data = load_data()
    context = load_context()
    coaching = get_coaching(data, context)
    html = generate_html(data, context, coaching)
    OUTPUT_FILE.write_text(html)
    print(f"Dashboard written → {OUTPUT_FILE}")
