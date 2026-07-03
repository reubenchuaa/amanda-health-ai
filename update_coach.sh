#!/bin/bash
# Runs on Mac wake/login — pulls latest run data and updates coach note via Claude AI

cd /Users/amandakoh/Desktop/strava-ai

# Pull latest data from GitHub
git pull --quiet

# Run Claude to reason about the data and write coach_note.md
/opt/homebrew/bin/claude --dangerously-skip-permissions -p "
You are an expert running coach for Amanda. Read health/data.json and context.json in the current directory.

From data.json, extract and reason about:
- Recent runs: distance, pace, avg HR, max HR, cadence, elevation, calories
- This week's volume (km) vs last week
- Gaps in training (missed runs, rest days)
- HR trends: is she running too hard or keeping it aerobic?
- Long run progression over the past 4 weeks
- context.json: current training phase, race goal (sub 2:30 Kiprun Singapore Half Marathon 27 Sep 2026), HR zones (easy max 145 bpm, tempo 160-170 bpm)

Write a coach note to health/coach_note.md with:

**[Bold headline: one sharp sentence on today's status]**

**What your data says**
2-3 sentences using actual numbers from her recent runs. Comment on whether she is running aerobically (HR under 145), volume trend this week, and any patterns worth noting.

**Today's session**
Specific: session type, exact distance, pace range, HR cap. Adapt to training phase and how recently she ran.

**3-Day Plan**
- Today (weekday): specific session
- Tomorrow (weekday): specific session
- Day after (weekday): specific session

**This week's focus**
One sentence on the phase goal and one key thing to watch (e.g. HR discipline in the Singapore heat, cadence, long run fuelling).

Be direct, use real numbers from her data, adapt to what actually happened. Under 280 words.
Write ONLY the markdown to health/coach_note.md.
" 2>/dev/null

# Prepend timestamp to coach note
if [ -f health/coach_note.md ]; then
  TIMESTAMP="_Updated: $(date '+%a, %d %b %Y at %I:%M %p SGT')_"
  echo -e "$TIMESTAMP\n\n$(cat health/coach_note.md)" > health/coach_note.md
fi

# Regenerate dashboard with new coach note
python3 generate_dashboard.py 2>/dev/null

# Push everything back to GitHub
git add health/coach_note.md docs/index.html health/data.json
git diff --cached --quiet || git commit -m "coach: $(date '+%Y-%m-%d %H:%M')"
git push --quiet
