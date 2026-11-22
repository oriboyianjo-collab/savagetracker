'use strict';

const { parseIcs } = require('../ics.cjs');
const { CATALOG, matchSummary } = require('../catalog.cjs');
const { formatPct, formatPayrolls, formatK, trimNum } = require('../format.cjs');
const { candidate, inRange, yearMonthFromBls, mom, yoy, periodFromYm } = require('./util.cjs');

const ICS = 'https://www.bls.gov/schedule/news_release/bls.ics';
const V1 = 'https://api.bls.gov/publicAPI/v1/timeseries/data/';
const V2 = 'https://api.bls.gov/publicAPI/v2/timeseries/data/';

function neededSeries() {
  const ids = [];
  for (const e of CATALOG) if (e.agency === 'bls' && e.blsSeries) ids.push(e.blsSeries.id);
  return [...new Set(ids)];
}

/**
 * Units: BLS publishes CES payroll levels and JOLTS openings in THOUSANDS (159293 = 159.293M jobs).
 * blsSeries.scale converts the raw series unit to persons before formatting, so a 165 (thousand)
 * monthly change is written as "165K", never "0.2K". Percent / rate series are never scaled.
 */
function scaleOf(entry) {
  const s = +(entry.blsSeries && entry.blsSeries.scale);
  return Number.isFinite(s) && s > 0 ? s : 1;
}

/** BLS prints percents with exactly one decimal ("5.0%", "+0.3%"). */
function pct1(v, signed) {
  let t = (Math.round(v * 10) / 10).toFixed(1);
  if (t === '-0.0') t = '0.0';
  return `${signed && +t > 0 ? '+' : ''}${t}%`;
}

function formatSeriesValue(entry, value) {
  const calc = entry.blsSeries.calc;
  const signed = !!entry.blsSeries.signed || calc === 'mom';
  const v = +value;
  if (!Number.isFinite(v)) return null;
  if (entry.format === 'payrolls') return formatPayrolls(v * scaleOf(entry));
  if (entry.format === 'millions') return `${trimNum((v * scaleOf(entry)) / 1e6, 3)} מיליון`;
  if (entry.format === 'pct-level') return pct1(v, false);
  if (calc === 'level') return String(trimNum(v, 1));
  if (calc === 'net') return formatPayrolls(v * scaleOf(entry));
  return pct1(v, signed);
}

/** Plausibility limits on the computed value (after scaling), so a unit or mapping slip is refused, not written. */
function plausible(entry, value) {
  const v = +value;
  if (!Number.isFinite(v)) return { ok: false, reason: 'not a number' };
  const calc = entry.blsSeries.calc;
  const persons = v * scaleOf(entry);
  if (entry.format === 'payrolls') {
    if (Math.abs(persons) > 5e6) return { ok: false, reason: `payroll change ${persons} outside ±5M` };
    if (persons !== 0 && Math.abs(persons) < 1000) return { ok: false, reason: `payroll change ${persons} below 1K: unit error` };
    return { ok: true };
  }
  if (entry.format === 'millions') {
    if (persons < 1e6 || persons > 3e7) return { ok: false, reason: `level ${persons} outside 1M–30M` };
    return { ok: true };
  }
  if (entry.format === 'pct-level') {
    if (v < 0 || v > 30) return { ok: false, reason: `rate ${v}% outside 0–30%` };
    return { ok: true };
  }
  if (calc === 'mom' && Math.abs(v) > 15) return { ok: false, reason: `monthly change ${v}% outside ±15%` };
  if (calc === 'yoy' && Math.abs(v) > 40) return { ok: false, reason: `12-month change ${v}% outside ±40%` };
  return { ok: true };
}

/** Reference month a release covers: release month minus lag (default 1; JOLTS 2). */
function referenceYm(entry, releaseDate) {
  const lag = +(entry.blsSeries && entry.blsSeries.lag) || 1;
  return decYm(String(releaseDate).slice(0, 7), lag);
}

/**
 * Compute the value for a reference month (targetYm). When targetYm is omitted the newest
 * observation is used. Neighbours are looked up by calendar month, never by array position,
 * so a gap in the series (e.g. a month BLS never published) cannot shift values onto the wrong month.
 */
function compute(entry, seriesObs, targetYm) {
  const calc = entry.blsSeries.calc;
  if (!seriesObs || !seriesObs.length) return null;
  // BLS marks months it never published (e.g. Oct 2025 CPI, shutdown) with "-": treat as missing, not as a number.
  const at = (ym) => seriesObs.find((o) => yearMonthFromBls(o) === ym && o.value !== '' && Number.isFinite(+o.value));
  const ym = targetYm || yearMonthFromBls(seriesObs[0]);
  const cur = at(ym);
  if (!cur) return null;
  const prevYm = decYm(ym, 1);
  const prev = at(prevYm);
  if (calc === 'level') {
    return { value: +cur.value, previous: prev ? +prev.value : null, ym };
  }
  if (calc === 'net') {
    const older = at(decYm(ym, 2));
    return {
      value: prev ? +cur.value - +prev.value : null,
      previous: prev && older ? +prev.value - +older.value : null,
      ym,
    };
  }
  if (calc === 'mom') {
    const older = at(decYm(ym, 2));
    return {
      value: prev ? mom(cur.value, prev.value) : null,
      previous: prev && older ? mom(prev.value, older.value) : null,
      ym,
    };
  }
  if (calc === 'yoy') {
    const yearAgo = at(decYm(ym, 12));
    const prevYearAgo = prev && at(decYm(prevYm, 12));
    return {
      value: yearAgo ? yoy(cur.value, yearAgo.value) : null,
      previous: prev && prevYearAgo ? yoy(prev.value, prevYearAgo.value) : null,
      ym,
    };
  }
  return null;
}

function decYm(ym, months) {
  if (!ym) return null;
  let y = +ym.slice(0, 4), m = +ym.slice(5, 7) - months;
  while (m <= 0) { m += 12; y -= 1; }
  return `${y}-${String(m).padStart(2, '0')}`;
}

async function fetchSeries(http, ids, key) {
  const end = new Date().getUTCFullYear();
  const start = end - 2;
  const body = { seriesid: ids, startyear: String(start), endyear: String(end) };
  const url = key ? V2 : V1;
  if (key) body.registrationkey = key;
  const res = await http.get(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const json = JSON.parse(res.text());
  if (json.status && json.status !== 'REQUEST_SUCCEEDED') {
    throw new Error(`BLS API: ${json.status} ${(json.message || []).join('; ')}`);
  }
  const map = {};
  for (const s of (json.Results && json.Results.series) || []) {
    const obs = (s.data || []).slice().sort((a, b) => {
      const ya = `${a.year}-${a.period}`, yb = `${b.year}-${b.period}`;
      return yb.localeCompare(ya);
    });
    map[s.seriesID] = obs;
  }
  return map;
}

async function ingest(http, { from, to, lookbackFrom, keys = {}, log = () => {}, full = true, now = new Date() }) {
  const out = [];
  const skipped = [];
  let icsEvents = [];
  try {
    const text = await http.getText(ICS);
    icsEvents = require('../ics.cjs').parseIcs(text);
  } catch (e) {
    log(`BLS calendar skipped: ${e.message}`);
    skipped.push({ source: 'bls-ics', reason: e.message });
    if (e.code === 'HTTP_STOP' || e.code === 'HTTP_BLOCKED') return { candidates: out, skipped };
  }

  const dateMin = lookbackFrom || from;
  for (const ev of icsEvents) {
    if (!inRange(ev.date, dateMin, to)) continue;
    const matches = matchSummary(ev.summary, 'bls');
    const entries = matches.length ? matches : [];
    // If no catalog match, still add a generic official BLS schedule row (English title + Hebrew fallback = English)
    if (!entries.length) {
      out.push({
        'תאריך': ev.date,
        'שעה': ev.time,
        'מדינה': 'US',
        'אירוע': ev.summary,
        'אירוע_en': ev.summary,
        'חשיבות': 1,
        'מקור': ICS,
        _sourceUrl: ICS,
        _aliases: [ev.summary],
        _meta: { agency: 'bls', series: 'bls-other' },
      });
      continue;
    }
    for (const entry of entries) {
      const kind = entry.period === 'שנתי' ? 'שנתי' : 'חודשי';
      out.push(candidate(entry, { date: ev.date, time: ev.time, url: ICS }));
    }
  }

  // Actuals via API (v1 keyless, v2 if key). Skip gracefully on failure.
  const ids = neededSeries();
  if (!ids.length) return { candidates: out, skipped };
  // Keyless BLS API allows ~25 queries a day, and the release window runs every 15 minutes. Query only
  // on a full (daily / manual) run, or within 3 hours after a BLS release that carries actuals.
  if (!full && !keys.BLS_API_KEY) {
    const summaries = new Set(CATALOG.filter((e) => e.agency === 'bls' && e.blsSeries).map((e) => e.blsSummary));
    const t = (now instanceof Date ? now : new Date()).getTime();
    const recent = icsEvents.some((ev) => summaries.has(ev.summary) && ev.instant
      && t >= ev.instant.getTime() - 5 * 60e3 && t <= ev.instant.getTime() + 3 * 3600e3);
    if (!recent) {
      skipped.push({ source: 'bls-api', reason: 'no BLS release in the last 3 hours (quota saver; daily run covers revisions)' });
      return { candidates: out, skipped };
    }
  }
  let map;
  try {
    map = await fetchSeries(http, ids, keys.BLS_API_KEY);
  } catch (e) {
    log(`BLS time series skipped: ${e.message}`);
    skipped.push({ source: 'bls-api', reason: e.message, keyNeeded: /registration|unauth|key/i.test(e.message) && !keys.BLS_API_KEY });
    return { candidates: out, skipped };
  }

  // Attach numbers to candidates that already have dates, and also to recent rows via release-date matching later (merge).
  // We don't always know the exact release date for a vintage from the series alone; we join by blsSummary date.
  const bySummaryDate = new Map();
  for (const ev of icsEvents) {
    if (!inRange(ev.date, dateMin, to)) continue;
    if (!bySummaryDate.has(ev.summary)) bySummaryDate.set(ev.summary, []);
    bySummaryDate.get(ev.summary).push(ev);
  }
  for (const entry of CATALOG) {
    if (entry.agency !== 'bls' || !entry.blsSeries) continue;
    const obs = map[entry.blsSeries.id] || [];
    const releases = (bySummaryDate.get(entry.blsSummary) || []).filter((r) => inRange(r.date, dateMin, to));
    for (const ev of releases) {
      // Each release only gets the month it covers. No match -> nothing written (never the newest month by default).
      const targetYm = referenceYm(entry, ev.date);
      const got = compute(entry, obs, targetYm);
      if (!got || got.value == null) {
        skipped.push({ source: 'bls-api', series: entry.id, date: ev.date, reason: `${entry.blsSeries.id}: ${targetYm} value not computable (month or comparison month missing in BLS data)` });
        continue;
      }
      const chk = plausible(entry, got.value);
      if (!chk.ok) {
        skipped.push({ source: 'bls-api', series: entry.id, date: ev.date, reason: `guard: ${chk.reason}` });
        continue;
      }
      const per = periodFromYm(got.ym, entry.period);
      const actual = formatSeriesValue(entry, got.value);
      const prevOk = got.previous != null && plausible(entry, got.previous).ok;
      const previous = prevOk ? formatSeriesValue(entry, got.previous) : undefined;
      const url = entry.blsRelease || 'https://www.bls.gov/';
      out.push(candidate(entry, {
        date: ev.date, time: ev.time, url,
        period: per.period, periodEn: per.periodEn,
        actual, previous,
        meta: { agency: 'bls', series: entry.blsSeries.id, refMonth: got.ym, officialRevision: true },
      }));
    }
  }
  return { candidates: out, skipped };
}

module.exports = { ingest, compute, formatSeriesValue, neededSeries, plausible, referenceYm, scaleOf };
