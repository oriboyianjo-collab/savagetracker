'use strict';

/**
 * Weekly / daily official releases added ahead of time (schedule rows only, never actuals):
 *  - DOL UI weekly claims (initial + continuing): Thursday 8:30 ET; exceptions from DOL's own list.
 *  - Fed H.15 (business days 4:15 pm ET, not on holidays), H.4.1 (Thursday 4:30 pm ET, next business
 *    day if a federal holiday), H.8 (Friday 4:15 pm ET, Thursday if Friday is a federal holiday).
 *    Rules quoted from each release's official "Release Dates" page.
 *  - EIA Weekly Petroleum Status Report (Wednesday 10:30 ET) and Natural Gas Storage Report
 *    (Thursday 10:30 ET), with holiday exceptions (date + time) from EIA's own schedule pages.
 * Federal holidays follow 5 U.S.C. 6103 (observed Saturday -> Friday, Sunday -> Monday).
 */

const { CATALOG } = require('../catalog.cjs');
const { candidate, inRange } = require('./util.cjs');
const { etWallToIsrael } = require('../time.cjs');

const DOL_SCHED = 'https://oui.doleta.gov/unemploy/claims_arch.asp';
const OIL_SCHED = 'https://www.eia.gov/petroleum/supply/weekly/schedule.php';
const GAS_SCHED = 'https://ir.eia.gov/ngs/schedule.html';
const H15 = 'https://www.federalreserve.gov/releases/h15/';
const H41 = 'https://www.federalreserve.gov/releases/h41/';
const H8 = 'https://www.federalreserve.gov/releases/h8/';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const p2 = (n) => String(n).padStart(2, '0');
const ymd = (d) => `${d.getUTCFullYear()}-${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())}`;
const utc = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d)); };
const addDays = (s, n) => { const d = utc(s); d.setUTCDate(d.getUTCDate() + n); return ymd(d); };
const dow = (s) => utc(s).getUTCDay(); // 0 Sun .. 6 Sat

function nthWeekday(y, m, wd, n) { // n = 1..4, or -1 for last
  if (n > 0) {
    const first = new Date(Date.UTC(y, m - 1, 1));
    const d = 1 + ((wd - first.getUTCDay() + 7) % 7) + (n - 1) * 7;
    return `${y}-${p2(m)}-${p2(d)}`;
  }
  const last = new Date(Date.UTC(y, m, 0));
  const d = last.getUTCDate() - ((last.getUTCDay() - wd + 7) % 7);
  return `${y}-${p2(m)}-${p2(d)}`;
}

/** Federal holidays (observed) for a year. saturdayToFriday=false for the Fed, which stays open that Friday. */
function federalHolidays(y, { saturdayToFriday = true } = {}) {
  const fixed = [`${y}-01-01`, `${y}-06-19`, `${y}-07-04`, `${y}-11-11`, `${y}-12-25`];
  const out = new Set([
    nthWeekday(y, 1, 1, 3), nthWeekday(y, 2, 1, 3), nthWeekday(y, 5, 1, -1), nthWeekday(y, 9, 1, 1),
    nthWeekday(y, 10, 1, 2), nthWeekday(y, 11, 4, 4),
  ]);
  for (const f of fixed) {
    const w = dow(f);
    if (w === 6) { if (saturdayToFriday) out.add(addDays(f, -1)); }
    else if (w === 0) out.add(addDays(f, 1));
    else out.add(f);
  }
  // New Year's Day of next year observed on Dec 31 when Jan 1 is a Saturday.
  if (saturdayToFriday && dow(`${y + 1}-01-01`) === 6) out.add(`${y}-12-31`);
  return out;
}

function isHoliday(s, opts) {
  const y = +s.slice(0, 4);
  return federalHolidays(y, opts).has(s) || federalHolidays(y + 1, opts).has(s);
}
const isBusinessDay = (s, opts) => dow(s) !== 0 && dow(s) !== 6 && !isHoliday(s, opts);

function datesBetween(a, b) {
  const out = [];
  for (let d = a; d <= b; d = addDays(d, 1)) out.push(d);
  return out;
}

const weekKey = (s) => addDays(s, -((dow(s) + 6) % 7)); // Monday of that week

function text(html) {
  return String(html || '').replace(/<[^>]+>/g, ' ').replace(/&nbsp;|&#160;/gi, ' ').replace(/\s+/g, ' ');
}

/** "November 25, 2026 Wednesday 12:00 p.m." (EIA) -> [{ date, hour, minute }] */
function parseEiaExceptions(html) {
  const t = text(html);
  const rx = /(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})(?:\s*-\s*\(Updated\))?\s+(Monday|Tuesday|Wednesday|Thursday|Friday)\s+(\d{1,2}):(\d{2})\s*([ap])\.?\s*m\.?/gi;
  const out = [];
  let m;
  while ((m = rx.exec(t))) {
    let h = +m[5];
    if (/p/i.test(m[7]) && h < 12) h += 12;
    if (/a/i.test(m[7]) && h === 12) h = 0;
    const mo = MONTHS.findIndex((x) => x.toLowerCase() === m[1].toLowerCase()) + 1;
    out.push({ date: `${m[3]}-${p2(mo)}-${p2(+m[2])}`, hour: h, minute: +m[6] });
  }
  return out;
}

/** "Wednesday, November 25, 2026 8:30 AM EST" (DOL) -> [{ date, hour, minute }] */
function parseDolExceptions(html) {
  const t = text(html);
  const rx = /(Monday|Tuesday|Wednesday|Thursday|Friday),\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})\s+(\d{1,2}):(\d{2})\s*([AP])M/gi;
  const out = [];
  let m;
  while ((m = rx.exec(t))) {
    let h = +m[5];
    if (/P/i.test(m[7]) && h < 12) h += 12;
    const mo = MONTHS.findIndex((x) => x.toLowerCase() === m[2].toLowerCase()) + 1;
    out.push({ date: `${m[4]}-${p2(mo)}-${p2(+m[3])}`, hour: h, minute: +m[6] });
  }
  return out;
}

/**
 * Weekly release dates in [from, to]: the default weekday at the default time, except weeks with an
 * official exception (the exception replaces that week's release) and default days that are federal
 * holidays without a listed exception (skipped rather than guessed).
 */
function weeklyDates({ from, to, weekday, hour, minute, exceptions = [] }) {
  const exWeeks = new Set(exceptions.map((e) => weekKey(e.date)));
  const out = [];
  for (const d of datesBetween(from, to)) {
    if (dow(d) === weekday && !exWeeks.has(weekKey(d)) && !isHoliday(d)) out.push({ date: d, hour, minute });
  }
  for (const e of exceptions) if (inRange(e.date, from, to)) out.push(e);
  return out.sort((a, b) => a.date.localeCompare(b.date));
}

/** Fed rules from the official release pages. */
function fedDates(kind, from, to) {
  const fedOpts = { saturdayToFriday: false };
  const out = [];
  if (kind === 'h15') {
    for (const d of datesBetween(from, to)) if (isBusinessDay(d, fedOpts)) out.push({ date: d, hour: 16, minute: 15 });
  } else if (kind === 'h41') {
    // Thursday; next business day when Thursday is a federal holiday.
    for (const d of datesBetween(addDays(from, -7), to)) {
      if (dow(d) !== 4) continue;
      let r = d;
      while (!isBusinessDay(r, fedOpts)) r = addDays(r, 1);
      if (inRange(r, from, to)) out.push({ date: r, hour: 16, minute: 30 });
    }
  } else if (kind === 'h8') {
    // Friday; Thursday when Friday is a federal holiday.
    for (const d of datesBetween(from, addDays(to, 1))) {
      if (dow(d) !== 5) continue;
      const r = isHoliday(d, fedOpts) ? addDays(d, -1) : d;
      if (inRange(r, from, to)) out.push({ date: r, hour: 16, minute: 15 });
    }
  }
  return out;
}

function pushRows(out, entry, dates, url, period) {
  for (const d of dates) {
    const [y, m, dd] = d.date.split('-').map(Number);
    const il = etWallToIsrael(y, m, dd, d.hour, d.minute);
    out.push(candidate(entry, {
      date: il.date, time: il.time, url, period: period.he, periodEn: period.en,
      meta: { agency: entry.agency, series: entry.id, scheduleTime: true },
    }));
  }
}

const WEEKLY = { he: 'שבועי', en: 'Weekly' };
const DAILY = { he: 'יומי', en: 'Daily' };

async function ingest(http, { from, to, log = () => {} }) {
  const out = [];
  const skipped = [];
  const byId = (id) => CATALOG.find((e) => e.id === id);
  if (!from || !to) return { candidates: out, skipped };
  // Only upcoming rows (today onward); past weekly rows are left to each source's actuals.
  const page = async (url, name) => {
    try { return await http.getText(url); }
    catch (e) {
      skipped.push({ source: `weekly-${name}`, reason: e.message });
      log(`weekly ${name} schedule skipped: ${e.message}`);
      if (e.code === 'HTTP_STOP' || e.code === 'HTTP_BLOCKED') throw e;
      return null;
    }
  };

  // DOL claims
  const dolHtml = await page(DOL_SCHED, 'dol');
  if (dolHtml != null) {
    const ex = parseDolExceptions(dolHtml);
    if (!/Publication Schedule/i.test(text(dolHtml))) skipped.push({ source: 'weekly-dol', reason: 'schedule text not found; rows not added' });
    else {
      const dates = weeklyDates({ from, to, weekday: 4, hour: 8, minute: 30, exceptions: ex });
      pushRows(out, byId('dol-claims'), dates, DOL_SCHED, WEEKLY);
      pushRows(out, byId('dol-claims-cont'), dates, DOL_SCHED, WEEKLY);
    }
  }

  // EIA petroleum (Wednesday) and natural gas (Thursday)
  const oilHtml = await page(OIL_SCHED, 'eia-oil');
  if (oilHtml != null) pushRows(out, byId('eia-crude'), weeklyDates({ from, to, weekday: 3, hour: 10, minute: 30, exceptions: parseEiaExceptions(oilHtml) }), OIL_SCHED, WEEKLY);
  const gasHtml = await page(GAS_SCHED, 'eia-gas');
  if (gasHtml != null) pushRows(out, byId('eia-gas'), weeklyDates({ from, to, weekday: 4, hour: 10, minute: 30, exceptions: parseEiaExceptions(gasHtml) }), GAS_SCHED, WEEKLY);

  // Fed (rules are fixed on the official release pages; no fetch needed)
  pushRows(out, byId('fed-h15'), fedDates('h15', from, to), H15, DAILY);
  pushRows(out, byId('fed-h41'), fedDates('h41', from, to), H41, WEEKLY);
  pushRows(out, byId('fed-h8'), fedDates('h8', from, to), H8, WEEKLY);

  return { candidates: out, skipped };
}

module.exports = { ingest, federalHolidays, isHoliday, weeklyDates, fedDates, parseEiaExceptions, parseDolExceptions, DOL_SCHED, OIL_SCHED, GAS_SCHED };
