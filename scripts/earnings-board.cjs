#!/usr/bin/env node
// Automatic updater for the News-tab earnings board (reports.json).
// Sources (public data only, no portfolio data):
//  - Alpha Vantage (personal free key, repo secret ALPHAVANTAGE_KEY, <=25 calls/day): EARNINGS_CALENDAR (dates, timing, EPS estimate),
//    EARNINGS (reported EPS, same street basis as its estimate), EARNINGS_ESTIMATES (revenue consensus) for a short priority list.
//  - SEC EDGAR (official data.sec.gov / sec.gov only): 8-K Item 2.02 detection -> release confirmed, time, report link.
//    Fair access: User-Agent "SavageTracker Savtra12@gmail.com", <=2 req/s, stop on 403/429 (no retry, no circumvention).
//  - financials/<SYM>.json shards already in the repo (built from SEC XBRL / 8-K) -> GAAP revenue actuals.
// Never writes or changes הערה / הערה_en (Ori writes notes). Never deletes manual rows.
// Usage: node scripts/earnings-board.cjs [--av] [--sec] [--apply-only] [--state DIR] [--today YYYY-MM-DD]
'use strict';
const fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..');
globalThis.self = globalThis;
require(path.join(ROOT, 'content-language.js'));
const CL = globalThis.ContentLanguage;

const UA = 'SavageTracker Savtra12@gmail.com';
const SEC_INTERVAL_MS = 1000;           // 1 req/s: financials-fast may use the other 1 req/s of the 2 req/s project budget
const AV_INTERVAL_MS = 1500;            // AV free key: max 1 request per second
const AV_PER_RUN = 12;                  // 2 scheduled runs/day x 12 = 24 <= 25/day
const AV_ACTUALS_MAX = 8;
const AUTO = 'alphavantage-calendar';
const NOTE_KEYS = ['הערה', 'הערה_en'];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const has = (v) => v != null && String(v).trim() !== '';
const log = (...a) => console.log('[earnings-board]', ...a);

// ---------- dates ----------
const dayIn = (tz, d = new Date()) => new Intl.DateTimeFormat('en-CA', { timeZone: tz }).format(d);
const addDays = (ymd, n) => { const d = new Date(ymd + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const diffDays = (a, b) => Math.round((Date.parse(a + 'T12:00:00Z') - Date.parse(b + 'T12:00:00Z')) / 864e5);
const ilClock = (iso) => new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Jerusalem', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(iso));
const etParts = (iso) => { const p = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(new Date(iso)); const g = (t) => p.find((x) => x.type === t).value; return { date: `${g('year')}-${g('month')}-${g('day')}`, min: (+g('hour') % 24) * 60 + +g('minute') }; };

// ---------- formatting ----------
const money = (n) => { const a = Math.abs(n); const [d, s] = a >= 1e12 ? [1e12, 'T'] : a >= 1e9 ? [1e9, 'B'] : a >= 1e6 ? [1e6, 'M'] : [1e3, 'K']; return String(+(n / d).toFixed(3)) + s; };
const epsStr = (v) => { const x = Number(v); if (!isFinite(x)) return ''; return String(+x.toFixed(4)); };
function parseCsv(t) {
  const lines = String(t || '').trim().split(/\r?\n/); if (lines.length < 2) return [];
  const split = (l) => { const c = []; let cur = '', q = false; for (const ch of l) { if (ch === '"') q = !q; else if (ch === ',' && !q) { c.push(cur); cur = ''; } else cur += ch; } c.push(cur); return c; };
  const H = split(lines[0]);
  return lines.slice(1).map((l) => { const c = split(l); return Object.fromEntries(H.map((k, i) => [k, (c[i] ?? '').trim()])); });
}
const timing = (t) => (t === 'pre-market' ? 'before' : t === 'post-market' ? 'after' : '');
const symKey = (s) => String(s || '').toUpperCase().trim();

// ---------- hash / translation ----------
async function sealRow(row, wasFresh) {
  for (const k of NOTE_KEYS) if (k in row && row[k] === undefined) delete row[k];
  if (wasFresh === false) return row;   // a stale translation stays stale: never certify an outdated English text
  row._translation = { en: { source_hash: await CL.sourceHash('reports', row), schema_version: 1 } };
  return row;
}

// ---------- row helpers ----------
const isPublished = (r) => has(r['בפועל_EPS']) || has(r['הכנסות_בפועל']);
const secConfirmed = (r) => has(r['אימות_פרסום_SEC']);
const issuerTimed = (r) => /^issuer/.test(String(r.release_time_basis || '')) || has(r['מועד_פרסום_מאומת']);
const avEstimate = (r) => !has(r['צפי_EPS']) || /^Alpha Vantage/.test(String(r['מקור_צפי_EPS'] || ''));
function nextId(rows) { let m = 0; for (const r of rows) { const x = /^r-(\d+)$/.exec(r['מזהה'] || ''); if (x) m = Math.max(m, +x[1]); } return m; }

function indexBySymbol(rows) {
  const idx = {};
  for (const r of rows) if (Array.isArray(r['מדד']) && r['מדד'].length) { const s = symKey(r['סימול']); if (!idx[s] || String(r['תאריך']) >= idx[s].d) idx[s] = { d: String(r['תאריך']), v: r['מדד'].slice() }; }
  return Object.fromEntries(Object.entries(idx).map(([k, o]) => [k, o.v]));
}

// Applies one Alpha Vantage calendar pull. Pure (except time passed in): returns stats.
function applyCalendar(rows, cal, ctx) {
  const { today, names = {}, idx = indexBySymbol(rows) } = ctx;
  const st = { added: 0, moved: 0, estimate: 0, timing: 0, skippedReported: 0, skippedPast: 0 };
  const bySym = new Map();
  rows.forEach((r) => { const s = symKey(r['סימול']); if (!bySym.has(s)) bySym.set(s, []); bySym.get(s).push(r); });
  let id = nextId(rows);
  const seen = new Set();
  for (const x of cal) {
    const sym = symKey(x.symbol), rd = x.reportDate, fq = x.fiscalDateEnding;
    if (!sym || !/^\d{4}-\d{2}-\d{2}$/.test(rd || '') || seen.has(sym + '|' + fq)) continue;
    seen.add(sym + '|' + fq);
    const list = bySym.get(sym) || [];
    let row = list.find((r) => fq && r['רבעון_מסתיים'] === fq);
    if (!row) row = list.find((r) => !r['רבעון_מסתיים'] && !isPublished(r) && !secConfirmed(r) && Math.abs(diffDays(String(r['תאריך']), rd)) <= 21 && String(r['תאריך']) >= today);
    if (!row) {
      // A past row without results (board history) is never moved: the source often rolls unknown dates forward.
      if (list.some((r) => !isPublished(r) && String(r['תאריך']) < today && diffDays(rd, String(r['תאריך'])) <= 30 && diffDays(rd, String(r['תאריך'])) > 0)) { st.skippedPast++; continue; }
      const reported = list.find((r) => (isPublished(r) || secConfirmed(r)) && diffDays(rd, String(r['תאריך'])) >= -21 && diffDays(rd, String(r['תאריך'])) <= 40);
      if (reported) { st.skippedReported++; continue; }
      if (rd < today) continue;
      row = { 'חברה': names[sym] || x.name || sym, 'סימול': sym, 'תאריך': rd };
      const m = timing(x.timeOfTheDay); if (m) row['מועד'] = m;
      if (has(x.estimate)) { row['צפי_EPS'] = epsStr(x.estimate); row['מטבע_EPS'] = x.currency || 'USD'; row['בסיס_צפי_EPS'] = 'Analyst consensus (Alpha Vantage)'; row['מקור_צפי_EPS'] = 'Alpha Vantage EARNINGS_CALENDAR'; }
      if (idx[sym]) row['מדד'] = idx[sym].slice();
      row['רבעון_מסתיים'] = fq; row['מקור_מועד'] = 'Alpha Vantage EARNINGS_CALENDAR'; row.auto_source = AUTO;
      row['מזהה'] = 'r-' + String(++id).padStart(4, '0');
      rows.push(row); list.push(row); bySym.set(sym, list); st.added++;
      continue;
    }
    if (isPublished(row) || secConfirmed(row) || String(row['תאריך']) < today) continue;   // results are in / past row: the schedule is history
    if (!row['רבעון_מסתיים'] && fq) row['רבעון_מסתיים'] = fq;
    const old = String(row['תאריך']);
    if (old !== rd && !(issuerTimed(row) && old >= today)) {
      if (!has(row['תאריך_מקורי'])) row['תאריך_מקורי'] = old;
      const h = Array.isArray(row['היסטוריית_מועד']) ? row['היסטוריית_מועד'].slice() : [];
      if (!h.length) h.push({ scheduled_date: old, basis: 'Previous board date', preserved_on: today });
      h.push({ date: rd, basis: 'Alpha Vantage earnings calendar', verified_on: today });
      row['היסטוריית_מועד'] = h; row['תאריך'] = rd; row['שינוי_מועד'] = rd < old ? 'advanced' : 'delayed'; st.moved++;
    }
    const m = timing(x.timeOfTheDay);
    if (m && row['מועד'] !== m && !issuerTimed(row)) { row['מועד'] = m; st.timing++; }
    if (has(x.estimate) && avEstimate(row)) {
      const e = epsStr(x.estimate);
      if (row['צפי_EPS'] !== e) { row['צפי_EPS'] = e; row['מטבע_EPS'] = x.currency || row['מטבע_EPS'] || 'USD'; row['בסיס_צפי_EPS'] = 'Analyst consensus (Alpha Vantage)'; row['מקור_צפי_EPS'] = 'Alpha Vantage EARNINGS_CALENDAR'; st.estimate++; }
    }
  }
  return st;
}

// SEC 8-K Item 2.02 match for a row. recent = submissions.filings.recent
function find202(recent, rowDate) {
  if (!recent || !Array.isArray(recent.form)) return null;
  const hits = [];
  for (let i = 0; i < recent.form.length; i++) {
    if (!/^8-K(\/A)?$/.test(recent.form[i]) || !/(^|,)\s*2\.02(\s*,|$)/.test(String(recent.items[i] || ''))) continue;
    const iso = recent.acceptanceDateTime[i]; if (!iso) continue;
    const et = etParts(iso); const dd = diffDays(et.date, rowDate);
    if (dd < -1 || dd > 1) continue;
    hits.push({ acc: recent.accessionNumber[i], iso, et, dd, form: recent.form[i], doc: recent.primaryDocument && recent.primaryDocument[i] });
  }
  hits.sort((a, b) => (a.form === '8-K' ? 0 : 1) - (b.form === '8-K' ? 0 : 1) || Math.abs(a.dd) - Math.abs(b.dd) || a.iso.localeCompare(b.iso));
  return hits[0] || null;
}
function applySec(row, hit, ctx) {
  const { today, cik, link } = ctx; let changed = false;
  const index = `https://www.sec.gov/Archives/edgar/data/${+cik}/${hit.acc.replace(/-/g, '')}/${hit.acc}-index.htm`;
  const set = (k, v) => { if (row[k] !== v) { row[k] = v; changed = true; } };
  set('אימות_פרסום_SEC', hit.acc);
  // Release date per SEC acceptance (ET). A late 8-K filed the next morning for an evening release keeps the board date.
  const late = hit.dd === 1 && hit.et.min < 570 && row['מועד'] === 'after';
  if (!late && hit.et.date !== row['תאריך'] && !isPublished(row)) {
    if (!has(row['תאריך_מקורי'])) row['תאריך_מקורי'] = row['תאריך'];
    const h = Array.isArray(row['היסטוריית_מועד']) ? row['היסטוריית_מועד'].slice() : [];
    if (!h.length) h.push({ scheduled_date: row['תאריך'], basis: 'Previous board date', preserved_on: today });
    h.push({ date: hit.et.date, basis: 'SEC 8-K Item 2.02 acceptance', source: index, verified_on: today });
    row['היסטוריית_מועד'] = h; row['תאריך'] = hit.et.date; changed = true;
  }
  if (!late && !issuerTimed(row)) {
    const m = hit.et.min < 570 ? 'before' : hit.et.min >= 960 ? 'after' : '';
    if (m) set('מועד', m);
    if (!has(row.release_time_il) || /^(third-party|sec-8k)/.test(String(row.release_time_basis || ''))) {
      set('release_time_il', ilClock(hit.iso)); set('release_time_approx', true); set('release_time_basis', 'sec-8k-item-2.02-acceptance');
      set('release_time_source', index); set('release_time_verified_date', today);
    }
  }
  if (!has(row['קישור_לדוח'])) set('קישור_לדוח', link || index);
  return changed;
}

// Revenue actual from a financials shard: the quarter whose filing lands around the board date.
function shardRevenue(shard, rowDate) {
  if (!shard || !shard.p) return null;
  let best = null;
  for (const [y, qs] of Object.entries(shard.p)) for (const [q, v] of Object.entries(qs || {})) {
    if (q === 'FY' || !v || !isFinite(v.r) || !v.d || !v.e) continue;
    const filedOff = diffDays(v.d, rowDate), age = diffDays(rowDate, v.e);
    if (filedOff < -1 || filedOff > 45 || age < 0 || age > 120) continue;
    if (!best || v.e > best.e || (v.e === best.e && v.d < best.d)) best = { ...v, fy: y, q };
  }
  if (!best) return null;
  return { r: best.r, pr: best.f === '8-K' || best.src === 'pr', tag: (shard.tags || {}).r || '', cur: shard.cur || 'USD', acc: best.a, form: best.f, end: best.e, label: best.q + ' FY' + best.fy, cik: shard.cik };
}
// Money text ("3.45–3.60B", "$950M", "1.2 מיליארד") -> number; a range gives its midpoint.
function moneyNum(v) {
  const t = String(v || '').replace(/[,$]/g, ''); const re = /(-?\d+(?:\.\d+)?)\s*(T|B|bn|M|mn|K|טריליון|מיליארד\S*|מיליון\S*|אלף)?/gi;
  const mult = (u) => (/^(T|טריליון)/i.test(u || '') ? 1e12 : /^(B|bn|מיליארד)/i.test(u || '') ? 1e9 : /^(M|mn|מיליון)/i.test(u || '') ? 1e6 : /^(K|אלף)/i.test(u || '') ? 1e3 : 1);
  const xs = []; let m; while ((m = re.exec(t)) && xs.length < 2) xs.push({ x: +m[1], u: m[2] || '' });
  if (!xs.length) return null; const u = xs[xs.length - 1].u; const vals = xs.map((z) => z.x * mult(z.u || u));
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}
// SEC revenue is filled only when it is plausibly the same metric as the stored consensus: the board shows
// numbers people act on, and the XBRL revenue tag of banks / REITs / insurers is often only a component.
function revenuePlausible(row, rev) {
  const est = moneyNum(row['צפי_הכנסות']); if (!est || !(est > 0)) return false;
  if (String(row['מטבע_צפי_הכנסות'] || 'USD').toUpperCase() !== String(rev.cur || 'USD').toUpperCase()) return false;
  if (Math.abs(rev.r / est - 1) > 0.15) return false;
  if (/^(כן|yes|true)$/i.test(String(row['השוואה_הכנסות'] || '')) && rev.tag !== 'Revenues') return false;
  return true;
}
function applyRevenue(row, rev) {
  if (has(row['הכנסות_בפועל']) || !revenuePlausible(row, rev)) return false;
  row['הכנסות_בפועל'] = money(rev.r);
  row['מטבע_הכנסות'] = rev.cur;
  row['בסיס_בפועל_הכנסות'] = (rev.tag === 'Revenues' ? 'GAAP total revenue' : 'GAAP revenue (SEC tag ' + (rev.tag || 'unknown') + ')') + (rev.pr ? ' – SEC 8-K press release, ' : ' – SEC XBRL, ') + rev.label;
  if (rev.acc && rev.cik) row['מקור_הכנסות_בפועל'] = `https://www.sec.gov/Archives/edgar/data/${+rev.cik}/${rev.acc.replace(/-/g, '')}/${rev.acc}-index.htm`;
  if (!has(row['השוואה_הכנסות']) && rev.tag === 'Revenues' && /^Analyst consensus \(Alpha Vantage\)/.test(String(row['בסיס_צפי_הכנסות'] || ''))) { row['השוואה_הכנסות'] = 'כן'; row['השוואה_הכנסות_en'] = 'Yes'; }
  return true;
}

// Reported EPS from AV EARNINGS (street basis, same provider as the estimate).
function avQuarter(earn, rowDate, fq) {
  const q = (earn && earn.quarterlyEarnings) || [];
  return q.find((z) => (fq ? z.fiscalDateEnding === fq : false) && Math.abs(diffDays(z.reportedDate, rowDate)) <= 3)
    || q.find((z) => z.reportedDate && Math.abs(diffDays(z.reportedDate, rowDate)) <= 3) || null;
}
function applyAvActual(row, z) {
  if (!z || !has(z.reportedEPS) || z.reportedEPS === 'None' || has(row['בפועל_EPS'])) return false;
  row['בפועל_EPS'] = epsStr(z.reportedEPS);
  row['מטבע_EPS'] = row['מטבע_EPS'] || 'USD';
  row['בסיס_בפועל_EPS'] = 'Adjusted EPS, street basis (Alpha Vantage)';
  row['מקור_בפועל_EPS'] = 'Alpha Vantage EARNINGS';
  const avEst = has(z.estimatedEPS) && z.estimatedEPS !== 'None' ? Number(z.estimatedEPS) : NaN;
  if (avEstimate(row) && isFinite(avEst)) {     // our own AV estimate -> align to the estimate AV pairs with this actual
    row['צפי_EPS'] = epsStr(avEst); row['בסיס_צפי_EPS'] = 'Analyst consensus (Alpha Vantage)'; row['מקור_צפי_EPS'] = 'Alpha Vantage EARNINGS';
  }
  const est = Number(row['צפי_EPS']);
  const same = isFinite(est) && isFinite(avEst) && Math.abs(est - avEst) <= 0.02;
  if (!has(row['השוואה_EPS']) || /^Alpha Vantage/.test(String(row['מקור_צפי_EPS'] || ''))) {
    if (same) { row['השוואה_EPS'] = 'כן'; row['השוואה_EPS_en'] = 'Yes'; delete row['הסבר_EPS']; delete row['הסבר_EPS_en']; }
    else if (isFinite(est)) { row['השוואה_EPS'] = 'לא'; row['השוואה_EPS_en'] = 'No'; row['הסבר_EPS'] = 'הצפי והתוצאה ממקורות שונים; לא חושבה הפתעה.'; row['הסבר_EPS_en'] = 'Estimate and actual come from different sources; no surprise was calculated.'; }
  }
  return true;
}
function applyRevEstimate(row, est, fq) {
  if (has(row['צפי_הכנסות']) || !est || !Array.isArray(est.estimates)) return false;
  const z = est.estimates.find((e) => e.horizon === 'fiscal quarter' && e.date === fq);
  const v = z && Number(z.revenue_estimate_average); if (!isFinite(v) || v <= 0) return false;
  row['צפי_הכנסות'] = money(v); row['מטבע_צפי_הכנסות'] = 'USD'; row['בסיס_צפי_הכנסות'] = 'Analyst consensus (Alpha Vantage), total revenue';
  row['מקור_צפי_הכנסות'] = 'Alpha Vantage EARNINGS_ESTIMATES';
  if (has(z.revenue_estimate_analyst_count)) row['אנליסטים_צפי_הכנסות'] = String(Math.round(+z.revenue_estimate_analyst_count));
  return true;
}

// ---------- network ----------
class SecBlocked extends Error {}
function secClient(state) {
  let next = 0, count = 0;
  return {
    get count() { return count; },
    async json(url) {
      if (!/^https:\/\/(www\.sec\.gov|data\.sec\.gov)\//.test(url)) throw new Error('not an official SEC endpoint');
      const w = next - Date.now(); if (w > 0) await sleep(w);
      next = Date.now() + SEC_INTERVAL_MS; count++;
      const r = await fetch(url, { headers: { 'User-Agent': UA, 'Accept-Encoding': 'gzip, deflate' }, signal: AbortSignal.timeout(30000) });
      next = Date.now() + SEC_INTERVAL_MS;
      if (r.status === 403 || r.status === 429) { state.secBlockedUntil = Date.now() + 24 * 3600e3; throw new SecBlocked('SEC HTTP ' + r.status + ' - stopping all SEC requests, no retry'); }
      if (r.status === 404) return null;
      if (!r.ok) throw new Error('SEC HTTP ' + r.status);
      return r.json();
    },
  };
}
function avClient(key, state, today) {
  let calls = 0;
  const used = () => (state.avCalls && state.avCalls[today]) || 0;
  return {
    get calls() { return calls; },
    left: () => Math.max(0, Math.min(AV_PER_RUN - calls, 25 - used())),
    async get(fn, params) {
      if (!key) throw new Error('ALPHAVANTAGE_KEY missing');
      if (calls) await sleep(AV_INTERVAL_MS);
      calls++; state.avCalls = { [today]: used() + 1 };
      const u = 'https://www.alphavantage.co/query?function=' + fn + '&' + params + '&apikey=' + encodeURIComponent(key);
      const r = await fetch(u, { signal: AbortSignal.timeout(30000) });
      const t = await r.text();
      if (!r.ok) throw new Error('Alpha Vantage HTTP ' + r.status);
      if (/^\s*\{\s*"(Information|Note|Error Message)"/.test(t)) { const e = new Error('Alpha Vantage refused ' + fn + ' (limit or error)'); e.limit = true; throw e; }
      return t;
    },
  };
}

// The full financials build runs at 2 req/s outside our concurrency group: never send SEC requests next to it.
async function otherSecJobBusy() {
  const tok = process.env.GITHUB_TOKEN, repo = process.env.GITHUB_REPOSITORY; if (!tok || !repo) return false;
  try {
    const r = await fetch(`https://api.github.com/repos/${repo}/actions/runs?status=in_progress&per_page=50`, { headers: { Authorization: 'Bearer ' + tok, Accept: 'application/vnd.github+json' }, signal: AbortSignal.timeout(15000) });
    if (!r.ok) return false; const j = await r.json();
    return (j.workflow_runs || []).some((w) => String(w.id) !== String(process.env.GITHUB_RUN_ID) && /^financials$/i.test(w.name || ''));
  } catch (e) { return false; }
}

// ---------- main ----------
async function main() {
  const argv = process.argv.slice(2), flag = (f) => argv.includes('--' + f), opt = (f, d) => { const i = argv.indexOf('--' + f); return i >= 0 ? argv[i + 1] : d; };
  const stateDir = opt('state', '/tmp/earnings-board'); fs.mkdirSync(stateDir, { recursive: true });
  const stateFile = path.join(stateDir, 'state.json'), cacheFile = path.join(stateDir, 'fetched.json');
  const state = fs.existsSync(stateFile) ? JSON.parse(fs.readFileSync(stateFile, 'utf8')) : {};
  const today = opt('today', dayIn('America/New_York'));
  const applyOnly = flag('apply-only');
  const file = path.join(ROOT, 'reports.json');
  const raw = fs.readFileSync(file, 'utf8');
  const rows = JSON.parse(raw);
  const before = new Map(rows.map((r) => [r, JSON.stringify(r)]));
  const fresh = new Map(); await Promise.all(rows.map(async (r) => fresh.set(r, await CL.hashMatches('reports', r))));
  const secu = JSON.parse(fs.readFileSync(path.join(ROOT, 'securities-us.json'), 'utf8'));
  const names = Object.fromEntries((secu.d || []).map((x) => [symKey(x[0]), x[1]]));
  const mcap = JSON.parse(fs.readFileSync(path.join(ROOT, 'mcap-rank.json'), 'utf8'));
  const rank = Object.fromEntries((mcap.ranked || []).map((x, i) => [symKey(x[0]), i + 1]));
  const shard = (s) => { const f = path.join(ROOT, 'financials', s.replace(/[^A-Z0-9.\-]/g, '') + '.json'); try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { return null; } };
  const big = (r) => (Array.isArray(r['מדד']) && r['מדד'].some((x) => /S&P 500|Nasdaq 100|Dow/.test(x))) || (rank[symKey(r['סימול'])] || 1e9) <= 500;
  const byRank = (a, b) => (rank[symKey(a['סימול'])] || 1e9) - (rank[symKey(b['סימול'])] || 1e9);
  const fetched = applyOnly && fs.existsSync(cacheFile) ? JSON.parse(fs.readFileSync(cacheFile, 'utf8')) : { cal: null, earn: {}, est: {}, sec: {} };
  const stats = { today, av: 0, sec: 0 };
  const warnings = [];

  // 1) Alpha Vantage
  if (flag('av') && !applyOnly) {
    const av = avClient(process.env.ALPHAVANTAGE_KEY || '', state, today);
    try {
      fetched.cal = parseCsv(await av.get('EARNINGS_CALENDAR', 'horizon=3month'));
      if (!fetched.cal.length) warnings.push('empty Alpha Vantage calendar');
      // First apply the calendar so new/moved rows are visible to the priority lists.
      Object.assign(stats, { calendar: applyCalendar(rows, fetched.cal, { today, names }) });
      const tried = state.avTried || {};
      const released = (r) => { const d = String(r['תאריך']); return d < today || (d === today && (r['מועד'] === 'before' || secConfirmed(r))); };
      const needEps = rows.filter((r) => !has(r['בפועל_EPS']) && String(r['תאריך']) >= addDays(today, -3) && String(r['תאריך']) <= today && released(r) && big(r) && (tried[r['מזהה']] || 0) < 2).sort(byRank);
      for (const r of needEps.slice(0, AV_ACTUALS_MAX)) {
        if (av.left() <= 0) break;
        const s = symKey(r['סימול']); if (fetched.earn[s]) continue;
        try { fetched.earn[s] = JSON.parse(await av.get('EARNINGS', 'symbol=' + encodeURIComponent(s))); tried[r['מזהה']] = (tried[r['מזהה']] || 0) + 1; }
        catch (e) { if (e.limit) { warnings.push(e.message); break; } throw e; }
      }
      const needRev = rows.filter((r) => !has(r['צפי_הכנסות']) && has(r['רבעון_מסתיים']) && !isPublished(r) && String(r['תאריך']) >= today && String(r['תאריך']) <= addDays(today, 3) && big(r) && !(state.estTried || {})[r['מזהה']]).sort(byRank);
      state.estTried = state.estTried || {};
      for (const r of needRev) {
        if (av.left() <= 0) break;
        const s = symKey(r['סימול']); if (fetched.est[s]) continue;
        try { fetched.est[s] = JSON.parse(await av.get('EARNINGS_ESTIMATES', 'symbol=' + encodeURIComponent(s))); state.estTried[r['מזהה']] = today; }
        catch (e) { if (e.limit) { warnings.push(e.message); break; } throw e; }
      }
      state.avTried = Object.fromEntries(Object.entries(tried).slice(-500));
      state.estTried = Object.fromEntries(Object.entries(state.estTried).slice(-500));
    } catch (e) { if (e.limit) warnings.push(e.message); else throw e; }
    stats.av = av.calls;
  } else if (fetched.cal) stats.calendar = applyCalendar(rows, fetched.cal, { today, names });

  // 2) SEC 8-K Item 2.02 detector
  if (flag('sec') && !applyOnly) {
    if (state.secBlockedUntil && Date.now() < state.secBlockedUntil) warnings.push('SEC requests paused after a 403/429 until ' + new Date(state.secBlockedUntil).toISOString());
    else {
      const sec = secClient(state);
      const want = rows.filter((r) => { const d = String(r['תאריך']); return d >= addDays(today, -1) && d <= addDays(today, 1) && !secConfirmed(r); }).sort(byRank);
      let tickers = null, n = 0;
      try {
        for (const r of want) {
          if (n++ % 40 === 0 && await otherSecJobBusy()) { warnings.push('SEC step paused: the financials (2 req/s) job started'); break; }
          const s = symKey(r['סימול']); if (fetched.sec[s] !== undefined) continue;
          let cik = (shard(s) || {}).cik;
          if (!cik) {
            if (!tickers) { const t = await sec.json('https://www.sec.gov/files/company_tickers.json'); tickers = {}; for (const v of Object.values(t || {})) tickers[symKey(v.ticker)] = String(v.cik_str).padStart(10, '0'); }
            cik = tickers[s] || tickers[s.replace(/\./g, '-')];
          }
          if (!cik) { fetched.sec[s] = null; continue; }
          const sub = await sec.json(`https://data.sec.gov/submissions/CIK${String(cik).padStart(10, '0')}.json`);
          const hit = sub && find202(sub.filings && sub.filings.recent, String(r['תאריך']));
          if (!hit) { fetched.sec[s] = { cik, none: true }; continue; }
          let link = null;
          const ix = await sec.json(`https://www.sec.gov/Archives/edgar/data/${+cik}/${hit.acc.replace(/-/g, '')}/index.json`);
          const items = (ix && ix.directory && ix.directory.item) || [];
          const ex = items.find((it) => /ex-?99(?:[-_.]?0?1)?\b|ex99/i.test(it.name) && /\.html?$/i.test(it.name)) || items.find((it) => /99/.test(it.name) && /\.html?$/i.test(it.name));
          if (ex) link = `https://www.sec.gov/Archives/edgar/data/${+cik}/${hit.acc.replace(/-/g, '')}/${ex.name}`;
          fetched.sec[s] = { cik, hit, link };
        }
      } catch (e) { if (e instanceof SecBlocked) { warnings.push(e.message); stats.secBlocked = true; } else warnings.push('SEC: ' + e.message); }
      stats.sec = sec.count;
    }
  }
  let secApplied = 0;
  for (const r of rows) {
    const f = fetched.sec[symKey(r['סימול'])];
    if (!f || !f.hit || secConfirmed(r)) continue;
    const d = String(r['תאריך']); if (diffDays(f.hit.et.date, d) < -1 || diffDays(f.hit.et.date, d) > 1) continue;
    if (applySec(r, f.hit, { today, cik: f.cik, link: f.link })) secApplied++;
  }

  // 3) actuals
  let epsFilled = 0, revFilled = 0, revEst = 0;
  for (const r of rows) {
    const s = symKey(r['סימול']);
    if (fetched.earn[s] && applyAvActual(r, avQuarter(fetched.earn[s], String(r['תאריך']), r['רבעון_מסתיים']))) epsFilled++;
    if (fetched.est[s] && applyRevEstimate(r, fetched.est[s], r['רבעון_מסתיים'])) revEst++;
  }
  const revFrom = [addDays(today, -14), '2026-11-04'].sort()[1];
  for (const r of rows) {
    const d = String(r['תאריך']);
    if (has(r['הכנסות_בפועל']) || d < revFrom || d > today) continue;
    if (d === today && !(r['מועד'] === 'before' || secConfirmed(r))) continue;
    const rev = shardRevenue(shard(symKey(r['סימול'])), d);
    if (rev && applyRevenue(r, rev)) revFilled++;
  }

  // 4) rolling window: only automatic rows without notes and without results, long past
  const keep = rows.filter((r) => !(r.auto_source === AUTO && !has(r['הערה']) && !isPublished(r) && String(r['תאריך']) < addDays(today, -180)));
  const pruned = rows.length - keep.length;

  // 5) seal changed rows, guard notes, write
  let changed = 0, added = 0;
  for (const r of keep) {
    const b = before.get(r);
    if (b === JSON.stringify(r)) continue;
    if (b) { const o = JSON.parse(b); for (const k of NOTE_KEYS) { if (k in o) r[k] = o[k]; else delete r[k]; } } else { for (const k of NOTE_KEYS) delete r[k]; added++; }
    await sealRow(r, b ? fresh.get(r) : true); changed++;
  }
  Object.assign(stats, { secApplied, epsFilled, revFilled, revEst, pruned, changed, added, rows: keep.length, warnings });
  fs.writeFileSync(cacheFile, JSON.stringify(fetched));
  fs.writeFileSync(stateFile, JSON.stringify(state));
  if (changed || pruned) fs.writeFileSync(file, JSON.stringify(keep));
  log(JSON.stringify(stats));
  fs.writeFileSync(path.join(stateDir, 'summary.json'), JSON.stringify(stats));
  for (const w of warnings) console.log('::warning::earnings-board: ' + w);
}

module.exports = { moneyNum, revenuePlausible, applyCalendar, find202, applySec, shardRevenue, applyRevenue, avQuarter, applyAvActual, applyRevEstimate, sealRow, parseCsv, money, indexBySymbol, CL };
if (require.main === module) main().catch((e) => { console.log('::error::earnings-board: ' + e.message); process.exitCode = 1; });
