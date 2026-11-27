#!/usr/bin/env bash
# publish() in scripts/earnings-live.sh must commit reports.json even when report-links-live.json does not exist
# (always the case in the off and dry modes), and must include report-links-live.json when it does.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fail=0; ok() { echo "PASS $1"; }; bad() { echo "FAIL $1"; fail=1; }
mkdir -p "$T/bin"; printf '#!/bin/sh\nexit 0\n' > "$T/bin/gh"; chmod +x "$T/bin/gh"; export PATH="$T/bin:$PATH"
git init -q --bare "$T/origin.git"
git clone -q "$T/origin.git" "$T/w" 2>/dev/null; cd "$T/w"
git config user.email t@example.invalid; git config user.name t
mkdir financials; echo '[]' > reports.json; echo '{}' > financials/A.json; git add -A; git commit -q -m init; git push -q origin HEAD:main
STATE="$T/state"; mkdir -p "$STATE/board" "$STATE/live"; FEED="$STATE/feed.json"
log() { :; }
# load only the helper functions under test (the script itself runs its loop when sourced)
eval "$(sed -n '/^add_live_links() {/,/^iteration() {/p' "$ROOT/scripts/earnings-live.sh" | sed '$d')"

echo '[{"x":1}]' > reports.json
publish >/dev/null 2>&1
[ "$(git log -1 --format=%s)" != init ] && git diff --quiet HEAD origin/main 2>/dev/null; 
git fetch -q origin main
[ "$(git log -1 --format=%s origin/main)" != init ] && [ "$(git show origin/main:reports.json)" = '[{"x":1}]' ] && ok "reports.json committed and pushed without report-links-live.json" || bad "reports.json not committed when report-links-live.json is missing"

echo '[{"x":2}]' > reports.json; echo '{"symbols":{}}' > report-links-live.json
publish >/dev/null 2>&1
git fetch -q origin main
git show origin/main:report-links-live.json >/dev/null 2>&1 && [ "$(git show origin/main:reports.json)" = '[{"x":2}]' ] && ok "report-links-live.json is included when it exists" || bad "report-links-live.json not committed"

rm -f report-links-live.json; echo '[{"x":3}]' > reports.json
publish >/dev/null 2>&1
git fetch -q origin main
[ "$(git show origin/main:reports.json)" = '[{"x":3}]' ] && ! git cat-file -e origin/main:report-links-live.json 2>/dev/null && ok "deleted overlay is committed as a deletion" || bad "deletion of report-links-live.json not committed"
exit $fail
