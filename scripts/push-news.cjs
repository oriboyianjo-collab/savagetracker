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

(async () => {
  if (!key)throw new Error('PUSH_NEWS_KEY missing; nothing queued');
  const after = arg('after') || 'HEAD', before = arg('before');
  let news = [], reports = [];
  if(arg('test'))throw new Error('Test sends disabled; use local queue tests');
  {
    const n = show(after, 'news.json'); if(!Array.isArray(n))throw new Error('Exact triggering news version unavailable; refusing moving-main fallback');
    // Full original records preserve IDs, versions and verified translations. Accepted intents persist beyond the newest-80 ingestion window.
    if (Array.isArray(n)) news = globalThis.AlertsCore.newestNews(n);
    const r1 = show(after, 'reports.json'), r0 = show(before, 'reports.json');
    if (Array.isArray(r1) && Array.isArray(r0)) {   // only rows that are new or changed since the previous commit
      const k = (x) => x['סימול'] + '|' + x['תאריך'], old = new Map(r0.map((x) => [k(x), JSON.stringify(x)]));
      reports = r1.filter((x) => old.get(k(x)) !== JSON.stringify(x)).slice(0, 400);
    }
  }
  if (!news.length && !reports.length) { console.log('push-news: nothing to send'); return; }
  const commit=git('rev-parse',after)?.trim();if(!commit)throw new Error('Exact commit unavailable');
  const commitTime=Number(git('show','-s','--format=%ct',after)?.trim())*1000;
  const body = JSON.stringify({ schema:2, commit, commitTime, news, reports });
  if(Buffer.byteLength(body)>1000000)throw new Error('Publication intent exceeds safe request size');
  for (let i = 1; i <= 3; i++) {
    try {
      const r = await fetch(URL_, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Push-Key': key }, body, signal: AbortSignal.timeout(25000) });
      const t = await r.text();
      if (r.ok) { console.log('push-news: ok ' + t.slice(0, 300)); return; }
      if (r.status === 404 || r.status === 401 || r.status === 503) { throw new Error('Worker rejected queue ingest: '+r.status+' '+t.slice(0,120)); }
      console.log('push-news: attempt ' + i + ' HTTP ' + r.status + ' ' + t.slice(0, 120));
    } catch (e) { console.log('push-news: attempt ' + i + ' ' + e.message); }
    await new Promise((x) => setTimeout(x, 2000 * i));
  }
  throw new Error('Durable queue ingest failed after 3 attempts; event not confirmed queued');
})().catch((e) => { warn(e.message); process.exitCode=1; });
