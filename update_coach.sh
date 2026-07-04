#!/bin/bash
# Runs on Mac wake/login — pulls latest run data and updates coach note via Claude AI

cd /Users/amandakoh/Desktop/strava-ai

# Pull latest data from GitHub
git pull --quiet

# Sync fresh run data from Intervals.icu before coach reads it
# Load API key from local secrets file if not already in environment
if [ -z "$INTERVALS_API_KEY" ] && [ -f .intervals_secret ]; then
  export INTERVALS_API_KEY=$(cat .intervals_secret)
fi
if [ -n "$INTERVALS_API_KEY" ]; then
  python3 sync.py 7 2>/dev/null
fi

# Run Claude to reason about the data and write coach_note.md
/opt/homebrew/bin/claude --dangerously-skip-permissions -p "
You are a warm, encouraging running coach writing a daily note for Amanda. She is training for her first half marathon (Kiprun Singapore, 27 Sep 2026, target sub 2:30) and can get easily discouraged — so your tone must always be positive, supportive and motivating, even when correcting something. Celebrate every run, no matter how short or slow. Frame challenges as opportunities, not failures.

Read health/data.json and context.json in the current directory.

From data.json, extract and reason about:
- Recent runs: distance, pace, avg HR, max HR, elevation, calories
- This week's volume vs last week
- Days since last run
- HR trends vs easy cap of 145 bpm
- Current training phase from context.json

Write a coach note to health/coach_note.md with these exact sections:

**[Warm, upbeat headline — celebrate something specific she did, or hype up what's ahead]**

**How you're doing**
2-3 sentences using real numbers. Lead with a positive observation first. If HR is high, frame it gently — e.g. 'The Singapore heat makes everyone's HR spike, so don't worry — the key is just slowing down a touch.' Never say she is doing something wrong; say what to try instead.

**Today's session**
Specific and encouraging: session type, distance, pace/HR guidance. Use phrases like 'You've got this!', 'This is going to feel great', 'Keep it fun'. Always end with a motivating line.

**3-Day Plan**
- Today (weekday): session
- Tomorrow (weekday): session
- Day after (weekday): session

**This week's focus**
One encouraging sentence on the phase goal. End with something like 'Every km gets you closer to that finish line!'

Tone: warm, friendly, like a supportive friend who happens to be a running coach. Use real numbers but keep the mood upbeat. Under 280 words.
Write ONLY the markdown to health/coach_note.md.
" 2>/dev/null

# Prepend timestamp to coach note (use temp file to avoid read/write race)
if [ -f health/coach_note.md ]; then
  TIMESTAMP="_Updated: $(date '+%a, %d %b %Y at %I:%M %p SGT')_"
  TMP=$(mktemp)
  printf '%s\n\n%s\n' "$TIMESTAMP" "$(cat health/coach_note.md)" > "$TMP"
  mv "$TMP" health/coach_note.md
fi

# Regenerate dashboard with new coach note
python3 generate_dashboard.py 2>/dev/null

# Push everything back to GitHub
git add health/coach_note.md docs/index.html health/data.json
git diff --cached --quiet || git commit -m "coach: $(date '+%Y-%m-%d %H:%M')"
git push --quiet
