#!/usr/bin/env node
// Sends the news / reports that just changed to the Savage Tracker alerts Worker (POST /push/news) so alerts queue until exact public availability is verified
// Public data only: original bilingual news records and changed report rows.
// No secrets in this file: the shared key comes from the env var PUSH_NEWS_KEY (GitHub Actions secret, or a local file outside the repo).
// Usage: node scripts/push-news.cjs [--before <sha>] [--after <sha=HEAD>] [--test "title"]
// Fails loudly if queue acknowledgement is unavailable. Durable Object alarms own readiness/delivery retries.
const { execFileSync } = require('child_process');
const fs = require('fs');
require('../alerts-core.js');
const URL_ = process.env.PUSH_NEWS_URL || 'https://savage-orderbook.oriboyianjo.workers.dev/push/v2/news';
const arg = (n) => { const i = process.argv.indexOf('--' + n); return i > 0 ? process.argv[i + 1] : ''; };
const warn = (m) => console.log('::warning::push-news: ' + m);
let key = process.env.PUSH_NEWS_KEY || '';
if (!key && process.env.PUSH_NEWS_KEY_FILE) { try { key = fs.readFileSync(process.env.PUSH_NEWS_KEY_FILE, 'utf8').trim(); } catch (e) {} }
const git = (...a) => { try { return execFileSync('git', a, { encoding: 'utf8', maxBuffer: 64e6, stdio: ['ignore', 'pipe', 'ignore'] }); } catch (e) { return null; } };
const show = (sha, f) => { if (!sha || /^0+$/.test(sha)) return null; const t = git('show', sha + ':' + f); if (t == null) return null; try { return JSON.parse(t); } catch (e) { return null; } };

// Every queued report row costs the Worker KV list/read operations (free plan: 1,000 lists/day), so only rows that can raise a
// NEW alert are sent: results that just appeared (released today or in the last 3 days, as detect() alerts on), and an existing
// row without results whose date moved onto today/tomorrow. Brand-new calendar rows are not queued (the app shows them). Estimate tweaks, SEC time/link
// confirmations, notes and backfills of older rows are published on the site but not queued. Biggest companies first, capped.
const has_ = (v) => v != null && String(v).trim() !== '';
const pubOf = (x) => has_(x['בפועל_EPS']) || has_(x['הכנסות_בפועל']);
function alertReports(r0, r1, now = Date.now(), cap = 120) {
  const ilDay = (off) => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jerusalem' }).format(new Date(now + off * 864e5));
  const today = ilDay(0), tmr = ilDay(1), old = ilDay(-3);
  const byId = new Map(), byKey = new Map(), k = (x) => x['סימול'] + '|' + x['תאריך'];
  for (const x of r0) { if (x['מזהה']) byId.set(x['מזהה'], x); byKey.set(k(x), x); }
  let rank = {}; try { (JSON.parse(fs.readFileSync(require('path').join(__dirname, '..', 'mcap-rank.json'), 'utf8')).ranked || []).forEach((z, i) => { rank[z[0]] = i + 1; }); } catch (e) {}
  const out = r1.filter((x) => {
    const p = (x['מזהה'] && byId.get(x['מזהה'])) || byKey.get(k(x));
    if (p && JSON.stringify(p) === JSON.stringify(x)) return false;
    const d = String(x['תאריך'] || '').slice(0, 10);
    if (pubOf(x)) return !(p && pubOf(p)) && d >= old && d <= today;
    return (d === today || d === tmr) && !!p && String(p['תאריך'] || '').slice(0, 10) !== d;   // an existing row moved onto today/tomorrow
  });
  out.sort((a, b) => (rank[a['סימול']] || 1e9) - (rank[b['סימול']] || 1e9));
  if (out.length > cap) warn('reports: ' + out.length + ' alert-worthy rows, sending the ' + cap + ' biggest companies');
  return out.slice(0, cap);
}
module.exports = { alertReports };

if (require.main === module) (async () => {
  if (!key)throw new Error('PUSH_NEWS_KEY missing; nothing queued');
  const after = arg('after') || 'HEAD', before = arg('before');
  let news = [], reports = [];
  if(arg('test'))throw new Error('Test sends disabled; use local queue tests');
  {
    const n = show(after, 'news.json'); if(!Array.isArray(n))throw new Error('Exact triggering news version unavailable; refusing moving-main fallback');
    // Full original records preserve IDs, versions and verified translations. Accepted intents persist beyond the newest-80 ingestion window.
    if (Array.isArray(n)) news = globalThis.AlertsCore.newestNews(n);
    const r1 = show(after, 'reports.json'), r0 = show(before, 'reports.json');
    if (Array.isArray(r1) && Array.isArray(r0)) reports = alertReports(r0, r1);   // only rows whose change can raise a new alert

  }
  if (!news.length && !reports.length) { console.log('push-news: nothing to send'); return; }
  const commit=git('rev-parse',after)?.trim();if(!commit)throw new Error('Exact commit unavailable');
  const commitTime=Number(git('show','-s','--format=%ct',after)?.trim())*1000;
  const body = JSON.stringify({ schema:2, commit, commitTime, news, reports });
  if(Buffer.byteLength(body)>1000000)throw new Error('Publication intent exceeds safe request size');
  // Retry transient failures (network, 429, 5xx such as a Cloudflare daily-limit 500) with backoff: ~3.5 min in total.
  // Fail fast only on a definite configuration answer from the Worker (401 key, 404 route, JSON 503 "not configured").
  const waits = [5, 15, 30, 60, 90];
  for (let i = 1; i <= waits.length + 1; i++) {
    try {
      const r = await fetch(URL_, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Push-Key': key }, body, signal: AbortSignal.timeout(25000) });
      const t = await r.text();
      if (r.ok) { console.log('push-news: ok ' + t.slice(0, 300)); return; }
      let cfg = r.status === 401 || r.status === 404;
      if (r.status === 503) { try { cfg = !!JSON.parse(t).error; } catch (e) {} }
      if (cfg) throw Object.assign(new Error('Worker rejected queue ingest: '+r.status+' '+t.slice(0,120)), { fatal: true });
      console.log('push-news: attempt ' + i + ' HTTP ' + r.status + ' ' + t.replace(/\s+/g, ' ').slice(0, 120));
    } catch (e) { if (e.fatal) throw e; console.log('push-news: attempt ' + i + ' ' + e.message); }
    if (i <= waits.length) await new Promise((x) => setTimeout(x, waits[i - 1] * 1000));
  }
  throw new Error('Durable queue ingest failed after ' + (waits.length + 1) + ' attempts; event not confirmed queued (the next successful run re-sends the newest 80 items)');
})().catch((e) => { warn(e.message); process.exitCode=1; });
