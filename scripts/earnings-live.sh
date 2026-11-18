#!/usr/bin/env bash
# Earnings board "live" loop (earnings-live workflow): every 10 minutes inside the US reporting windows
#   pre-market  03:00-10:30 New York time (about 10:00-17:30 Israel)
#   after-close 15:30-20:30 New York time (about 22:30-03:30 Israel)
# on US weekdays, one iteration =
#   1. sec-report-tool/financials/fast_layer.py: EDGAR "latest 8-K" feed -> Item 2.02 filings; the EX-99 press release of
#      covered companies is parsed (GAAP figures verified against the prior-year XBRL quarter) -> financials/<SYM>.json
#      and a feed file with acceptance time, revenue and EPS for the board.
#   2. scripts/earnings-board.cjs --live: release confirmed / time / link, EPS and revenue (sanity-checked against the estimate)
#      written to reports.json. Notes (הערה / הערה_en) are never written.
#   3. commit + push only on a change, then dispatch Pages publication and (only for rows with new results) push-news.
# SEC fair access: User-Agent "SavageTracker Savtra12@gmail.com", 1 request/second in this job (the universal EDGAR pass uses
# the other 1/s of the 2/s budget); no SEC request while the financials (2/s), financials-fast or earnings-board jobs run;
# official sec.gov endpoints only; HTTP 403/429 stops all SEC requests here for 24 hours, no retry.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); cd "$ROOT"
STATE=${EARNINGS_LIVE_STATE:-/tmp/earnings-live}; mkdir -p "$STATE/board"
FEED="$STATE/feed.json"
MAX_MIN=${MAX_MIN:-340}                 # stay inside the 6-hour job limit, then hand off to a fresh run
T0=$(date +%s)
log() { echo "[earnings-live] $(date -u +%H:%M:%SZ) $*"; }

in_window() {   # US weekday and inside one of the two windows (New York clock, DST-aware)
  local dow hm; dow=$(TZ=America/New_York date +%u); hm=$(TZ=America/New_York date +%H%M); hm=$((10#$hm))
  [ "$dow" -le 5 ] || return 1
  { [ "$hm" -ge 300 ] && [ "$hm" -lt 1030 ]; } || { [ "$hm" -ge 1530 ] && [ "$hm" -lt 2030 ]; }
}
held() {        # a 403/429 in the last 24 hours
  [ -f "$STATE/sec-hold" ] || return 1
  local t; t=$(cat "$STATE/sec-hold" 2>/dev/null | head -1 | tr -cd 0-9); [ -n "$t" ] || t=0
  [ $(( $(date +%s) - t )) -lt 86400 ]
}
busy() {        # other SEC jobs: never overlap them (keeps the project total <= 2 requests/second)
  [ -n "${GITHUB_REPOSITORY:-}" ] || return 1
  gh run list -R "$GITHUB_REPOSITORY" --status in_progress --json workflowName,databaseId \
    --jq ".[] | select(.databaseId != ${GITHUB_RUN_ID:-0}) | .workflowName" 2>/dev/null | grep -Ex 'financials|financials-fast|earnings-board' || true
}

publish() {     # commit reports.json / financials shards on change; push without force; dispatch Pages + push-news
  git add reports.json financials/*.json 2>/dev/null
  if git diff --cached --quiet; then log "no change"; return 0; fi
  local msg; msg="earnings-live: $(node -e "const s=require('$STATE/board/summary.json');const l=s.live||{};console.log((l.secApplied||0)+' SEC confirmations, '+(s.epsFilled||0)+' EPS, '+(s.revFilled||0)+' revenue')" 2>/dev/null || echo update)"
  git commit -q -m "$msg"
  local base pushed="" i; base=$(git rev-parse HEAD~1)
  for i in 1 2 3 4 5; do
    if git push -q origin HEAD:main; then pushed=1; break; fi
    sleep $((i * 5)); git fetch -q origin main
    if git rebase -q origin/main; then continue; fi
    git rebase --abort 2>/dev/null
    # Same file changed upstream: keep our shard files where upstream did not touch them, re-apply the board offline.
    local keep="$STATE/keep"; rm -rf "$keep"; mkdir -p "$keep"
    for f in $(git diff --name-only HEAD~1 HEAD -- financials/); do cp "$f" "$keep/$(basename "$f")"; done
    git reset -q --hard origin/main
    for f in "$keep"/*.json; do [ -e "$f" ] || continue; b=financials/$(basename "$f"); git diff --quiet "$base" origin/main -- "$b" && cp "$f" "$b"; done
    node scripts/earnings-board.cjs --live "$FEED" --apply-only --state "$STATE/board" || return 1
    git add reports.json financials/*.json; if git diff --cached --quiet; then log "already up to date"; return 0; fi
    git commit -q -m "$msg"; base=$(git rev-parse HEAD~1)
  done
  [ -n "$pushed" ] || { echo "::warning::earnings-live: push failed after 5 attempts"; return 1; }
  log "pushed: $msg"
  local after before n; after=$(git rev-parse HEAD); before=$(git rev-parse HEAD~1)
  gh workflow run pages-queued.yml --ref main || echo "::warning::could not dispatch Pages publication"
  n=$(node -e "const {execFileSync}=require('child_process');const s=(c)=>JSON.parse(execFileSync('git',['show',c+':reports.json'],{maxBuffer:1e9}));console.log(require('./scripts/push-news.cjs').alertReports(s('$before'),s('$after')).length)")
  log "alert-worthy report rows: $n"
  if [ "${n:-0}" -gt 0 ]; then gh workflow run push-news.yml --ref main -f before="$before" -f after="$after" || echo "::warning::could not dispatch push-news"; fi
}

iteration() {   # $1 = extra fast_layer args (catch-up), $2 = accessions to (re)process first
  git fetch -q origin main && git reset -q --hard origin/main
  cp .fast-layer-state.json "$STATE/fl-backup.json" 2>/dev/null || rm -f "$STATE/fl-backup.json"
  local rc=0 a
  for a in $(echo "${2:-}" | tr ',' ' '); do
    python3 sec-report-tool/financials/fast_layer.py --board-out "$FEED" --accession "$a" || rc=$?
    [ "$rc" -eq 2 ] && break
    sleep 1
  done
  # shellcheck disable=SC2086
  [ "$rc" -eq 2 ] || python3 sec-report-tool/financials/fast_layer.py --board-out "$FEED" --budget-min 7 --max-filings 120 $1 || rc=$?
  if [ "$rc" -eq 2 ]; then date +%s > "$STATE/sec-hold"; echo "::warning::earnings-live: SEC access held (403/429) - no SEC requests from this job for 24 hours"; fi
  [ -f "$FEED" ] || { log "no feed file"; return 0; }
  node scripts/earnings-board.cjs --live "$FEED" --state "$STATE/board" || { echo "::warning::earnings-live: board update failed"; return 0; }
  [ -f "$STATE/board/sec-hold" ] && date +%s > "$STATE/sec-hold"
  if ! publish; then   # not pushed: forget this round's processed filings so the next round redoes them
    [ -f "$STATE/fl-backup.json" ] && cp "$STATE/fl-backup.json" .fast-layer-state.json
    git reset -q --hard origin/main
  fi
}

first=1
while :; do
  if [ "${FORCE_ONCE:-}" != "1" ] && ! in_window; then log "outside the reporting windows - done"; break; fi
  if held; then log "SEC access held after a 403/429 - stopping"; break; fi
  if [ $(( ($(date +%s) - T0) / 60 )) -ge "$MAX_MIN" ]; then echo "handoff=1" >> "${GITHUB_OUTPUT:-/dev/null}"; log "time limit - handing off to a new run"; break; fi
  b=$(busy)
  if [ -n "$b" ]; then log "skipping this round, busy: $(echo $b)"
  else
    extra=""; acc=""
    [ "$first" = 1 ] && acc="${ACCESSION:-}"
    if [ "$first" = 1 ] && [ "$(TZ=America/New_York date +%H)" -lt 11 ] && [ "$(cat "$STATE/catchup-day" 2>/dev/null)" != "$(TZ=America/New_York date +%F)" ]; then
      extra="--catchup 2 --budget-min 15 --max-filings 900"; TZ=America/New_York date +%F > "$STATE/catchup-day"    # previous days from the EDGAR daily index, once a day
    fi
    iteration "$extra" "$acc"; first=0
  fi
  [ "${FORCE_ONCE:-}" = "1" ] && break
  # next 10-minute mark (+1 minute so the minute's filings are in the feed)
  now=$(date +%s); next=$(( (now / 600 + 1) * 600 + 60 )); sleep $(( next - now ))
done
exit 0
