#!/usr/bin/env node
'use strict';
// Is a scheduled Alpha Vantage backup run of earnings-board due now? Usage: node scripts/av-slot.cjs "<cron>" [nowIso]
// Exit 0 when the cron's due time (today, UTC) is 14:00 or 02:00 Israel time (DST-correct) and it is <= 90 minutes late.
const SLOTS = [14, 2], MAX_LATE_MIN = 90;
const ilHour = (d) => +new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Jerusalem', hour: '2-digit', hourCycle: 'h23' }).format(d);
function check(cron, now = new Date()) {
  const [mi, hr] = String(cron).trim().split(/\s+/).map(Number);
  if (!Number.isInteger(mi) || !Number.isInteger(hr)) return { ok: false, reason: 'not an Alpha Vantage schedule' };
  let due = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), hr, mi);
  if (due > now.getTime()) due -= 864e5;                       // delivered after midnight UTC for a late-evening cron
  const late = Math.round((now.getTime() - due) / 6e4), h = ilHour(new Date(due));
  if (!SLOTS.includes(h)) return { ok: false, reason: `scheduled run due at ${String(h).padStart(2, '0')}:00 Israel time (other season's cron)` };
  if (late > MAX_LATE_MIN) return { ok: false, reason: `scheduled run ${late} minutes late` };
  return { ok: true, reason: `Alpha Vantage ${String(h).padStart(2, '0')}:00 slot, ${late} minutes late` };
}
module.exports = { check };
if (require.main === module) { const r = check(process.argv[2], process.argv[3] ? new Date(process.argv[3]) : new Date()); console.log(r.reason); process.exit(r.ok ? 0 : 1); }
