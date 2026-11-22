'use strict';

const { parseIcs } = require('../ics.cjs');
const { matchSummary, CATALOG } = require('../catalog.cjs');
const { candidate, inRange } = require('./util.cjs');
const { periodMonthly } = require('../time.cjs');

const ICS = 'https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics';
const API = 'https://apps.bea.gov/api/data';
const PIO_URL = 'https://www.bea.gov/data/income-saving/personal-income';
const GDP_URL = 'https://www.bea.gov/data/gdp/gross-domestic-product';

/**
 * Official BEA NIPA series used for actuals (latest vintage; BEA revises, so the calendar follows).
 *  - PCE price m/m: Table 2.8.7 (published % change). y/y: from Table 2.8.4 index levels.
 *  - Personal income / spending m/m: Table 2.6 levels (current dollars).
 *  - Real GDP q/q SAAR: Table 1.1.1 line 1.
 */
const SERIES = {
  'bea-pce-mm': { table: 'T20807', code: 'DPCERGM', calc: 'value' },
  'bea-pce-core-mm': { table: 'T20807', code: 'DPCCRGM', calc: 'value' },
  'bea-pce-yy': { table: 'T20804', code: 'DPCERG', calc: 'yoy' },
  'bea-pce-core-yy': { table: 'T20804', code: 'DPCCRG', calc: 'yoy' },
  'bea-income': { table: 'T20600', code: 'A065RC', calc: 'mom' },
  'bea-spending': { table: 'T20600', code: 'DPCERC', calc: 'mom' },
  'bea-gdp-adv': { table: 'T10101', code: 'A191RL', calc: 'value', freq: 'Q' },
  'bea-gdp-2nd': { table: 'T10101', code: 'A191RL', calc: 'value', freq: 'Q' },
  'bea-gdp-3rd': { table: 'T10101', code: 'A191RL', calc: 'value', freq: 'Q' },
};
const LIMIT = { value: 15, mom: 10, yoy: 30 };
const MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];

/** BEA keys are UUIDs; tolerate stray whitespace or punctuation pasted around the secret. */
function cleanKey(k) {
  const m = String(k || '').match(/[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}/);
  return m ? m[0] : '';
}

function summaryToEntries(summary) {
  const s = String(summary || '');
  const hits = matchSummary(s, 'bea');
  if (hits.length) return hits;
  if (/GDP \(Second Estimate\)/i.test(s)) return CATALOG.filter((e) => e.id === 'bea-gdp-2nd' || e.id === 'bea-profits');
  if (/Personal Income and Outlays/i.test(s)) {
    return CATALOG.filter((e) => e.agency === 'bea' && /pce|income|spending/i.test(e.id));
  }
  return [{
    id: 'bea-other', agency: 'bea', country: 'US', importance: 1,
    he: s.replace(/\\,/g, ','), en: s.replace(/\\,/g, ','), aliases: [s],
  }];
}

/** Reference period the release covers, from BEA's own title. Ambiguous titles (two months) -> null. */
function refPeriod(summary) {
  const s = String(summary || '');
  const q = s.match(/\b([1-4])(?:st|nd|rd|th) Quarter (20\d{2})\b/i);
  if (/^GDP \(|^Gross Domestic Product,/i.test(s) && q) return { kind: 'Q', key: `${q[2]}Q${q[1]}`, year: +q[2], q: +q[1] };
  const m = s.match(/^Personal Income and Outlays,\s+([A-Za-z]+)\s+(20\d{2})$/i);
  if (m && MONTHS.includes(m[1].toLowerCase())) {
    const mo = MONTHS.indexOf(m[1].toLowerCase()) + 1;
    return { kind: 'M', key: `${m[2]}M${String(mo).padStart(2, '0')}`, year: +m[2], month: mo };
  }
  return null;
}

function prevKey(key, n = 1) {
  if (/Q/.test(key)) {
    let [y, q] = key.split('Q').map(Number);
    q -= n; while (q <= 0) { q += 4; y -= 1; }
    return `${y}Q${q}`;
  }
  let [y, m] = key.split('M').map(Number);
  m -= n; while (m <= 0) { m += 12; y -= 1; }
  return `${y}M${String(m).padStart(2, '0')}`;
}

function pct1(v) {
  let t = (Math.round(v * 10) / 10).toFixed(1);
  if (t === '-0.0') t = '0.0';
  return `${t}%`;
}

/** series: { 'YYYYMmm' | 'YYYYQn': number }. Returns { value, previous } in percent, or nulls. */
function computeBea(spec, series, key) {
  const at = (k) => (Number.isFinite(series[k]) ? series[k] : null);
  const one = (k) => {
    if (spec.calc === 'value') return at(k);
    if (spec.calc === 'mom') { const a = at(k), b = at(prevKey(k)); return a != null && b ? (a / b - 1) * 100 : null; }
    if (spec.calc === 'yoy') { const a = at(k), b = at(prevKey(k, 12)); return a != null && b ? (a / b - 1) * 100 : null; }
    return null;
  };
  return { value: one(key), previous: one(prevKey(key)) };
}

function plausibleBea(spec, v) {
  return Number.isFinite(v) && Math.abs(v) <= (LIMIT[spec.calc] || 15);
}

function parseTable(json, code) {
  const res = json && json.BEAAPI && json.BEAAPI.Results;
  if (!res || res.Error || !Array.isArray(res.Data)) {
    const e = (res && res.Error) || (json && json.BEAAPI && json.BEAAPI.Error) || {};
    throw new Error(`BEA API error ${e.APIErrorCode || ''} ${e.APIErrorDescription || 'no data'}`.trim());
  }
  const out = {};
  for (const d of res.Data) {
    if (d.SeriesCode !== code) continue;
    const n = +String(d.DataValue).replace(/,/g, '');
    if (Number.isFinite(n)) out[d.TimePeriod] = n;
  }
  return out;
}

function periodLabel(entry, ref) {
  if (ref.kind === 'Q') return { period: `רבעון ${ref.q} · קצב שנתי מותאם (q/q annualized)`, periodEn: `Quarter ${ref.q} · q/q annualized` };
  const p = periodMonthly(`${ref.year}-${String(ref.month).padStart(2, '0')}`, /yy$/.test(entry.id) ? 'שנתי' : 'חודשי');
  return { period: p.he, periodEn: p.en };
}

async function ingest(http, { from, to, lookbackFrom, keys = {}, log = () => {} }) {
  const out = [];
  const skipped = [];
  const dateMin = lookbackFrom || from;
  const releases = [];
  try {
    const text = await http.getText(ICS);
    const events = parseIcs(text);
    for (const ev of events) {
      if (!inRange(ev.date, dateMin, to)) continue;
      const entries = summaryToEntries(ev.summary);
      for (const entry of entries) {
        out.push(candidate(entry, { date: ev.date, time: ev.time, url: 'https://www.bea.gov/news/schedule' }));
      }
      releases.push({ ev, entries });
    }
  } catch (e) {
    log(`BEA calendar skipped: ${e.message}`);
    skipped.push({ source: 'bea-ics', reason: e.message });
    if (e.code === 'HTTP_STOP' || e.code === 'HTTP_BLOCKED') return { candidates: out, skipped };
  }

  const key = cleanKey(keys.BEA_API_KEY);
  if (!key) {
    skipped.push({ source: 'bea-api', reason: keys.BEA_API_KEY ? 'BEA_API_KEY is not a valid BEA UserID' : 'no BEA_API_KEY; schedule rows only', keyNeeded: true });
    return { candidates: out, skipped };
  }

  // Only releases that already happened and carry actuals; fetch each table once.
  const nowIso = new Date().toISOString().slice(0, 10);
  const work = [];
  for (const { ev, entries } of releases) {
    if (ev.date > (to || nowIso)) continue;
    const ref = refPeriod(ev.summary);
    for (const entry of entries) {
      const spec = SERIES[entry.id];
      if (!spec) continue;
      if (!ref || ref.kind !== (spec.freq || 'M')) {
        skipped.push({ source: 'bea-api', series: entry.id, date: ev.date, reason: `reference period not clear from "${ev.summary}"` });
        continue;
      }
      work.push({ ev, entry, spec, ref });
    }
  }
  const tables = {};
  for (const w of work) {
    const tk = `${w.spec.table}|${w.spec.freq || 'M'}|${w.ref.year}`;
    if (!(tk in tables)) {
      if (http.isBlocked()) break;
      try {
        const url = `${API}?UserID=${key}&method=GetData&datasetname=NIPA&TableName=${w.spec.table}&Frequency=${w.spec.freq || 'M'}&Year=${w.ref.year - 1},${w.ref.year}&ResultFormat=JSON`;
        const res = await http.get(url, { accept: 'application/json' });
        tables[tk] = JSON.parse(res.text());
      } catch (e) {
        tables[tk] = { error: e.message };
        log(`BEA ${w.spec.table} skipped: ${e.message}`);
        if (e.code === 'HTTP_STOP' || e.code === 'HTTP_BLOCKED') break;
      }
    }
    const t = tables[tk];
    if (!t) continue;
    let series;
    try {
      if (t.error) throw new Error(t.error);
      series = parseTable(t, w.spec.code);
    } catch (e) {
      skipped.push({ source: 'bea-api', series: w.entry.id, date: w.ev.date, reason: e.message });
      continue;
    }
    const got = computeBea(w.spec, series, w.ref.key);
    if (got.value == null) {
      skipped.push({ source: 'bea-api', series: w.entry.id, date: w.ev.date, reason: `${w.spec.code} ${w.ref.key} not in BEA data yet` });
      continue;
    }
    if (!plausibleBea(w.spec, got.value)) {
      skipped.push({ source: 'bea-api', series: w.entry.id, date: w.ev.date, reason: `guard: ${got.value} outside ±${LIMIT[w.spec.calc]}%` });
      continue;
    }
    const per = periodLabel(w.entry, w.ref);
    out.push(candidate(w.entry, {
      date: w.ev.date, time: w.ev.time,
      url: w.spec.freq === 'Q' ? GDP_URL : PIO_URL,
      period: per.period, periodEn: per.periodEn,
      actual: pct1(got.value),
      previous: got.previous != null && plausibleBea(w.spec, got.previous) ? pct1(got.previous) : undefined,
      meta: { agency: 'bea', series: `${w.spec.table}:${w.spec.code}`, refPeriod: w.ref.key, officialRevision: true },
    }));
  }
  return { candidates: out, skipped };
}

module.exports = { ingest, ICS, cleanKey, refPeriod, computeBea, parseTable, SERIES, prevKey, plausibleBea };
