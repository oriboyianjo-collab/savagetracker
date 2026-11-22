'use strict';

const { CATALOG } = require('../catalog.cjs');
const { candidate, inRange } = require('./util.cjs');
const { ymdInZone, hmInZone, IL, etWallToIsrael } = require('../time.cjs');
const { formatPublished } = require('../format.cjs');

const H15 = 'https://www.federalreserve.gov/releases/h15/current/default.htm';
const H15_ALT = 'https://www.federalreserve.gov/releases/h15/';
const H41 = 'https://www.federalreserve.gov/releases/h41/current/';
const H8 = 'https://www.federalreserve.gov/releases/h8/current/default.htm';
const CP = 'https://www.federalreserve.gov/releases/cp/';
const EVENTS_NOV = 'https://www.federalreserve.gov/newsevents/2026-november.htm';
const EVENTS_DEC = 'https://www.federalreserve.gov/newsevents/2026-december.htm';
const FOMC = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm';

function dataAsOf(html) {
  // "Release Date: November 19, 2026" or "Data for November 18, 2026"
  const m = html.match(/Release Date:\s*([A-Z][a-z]+ \d{1,2}, 20\d{2})/i)
    || html.match(/Data as of[^,]{0,20}([A-Z][a-z]+ \d{1,2}, 20\d{2})/i)
    || html.match(/for\s+([A-Z][a-z]+ \d{1,2}, 20\d{2})/i);
  return m ? m[1] : null;
}

const MON = { January:1,February:2,March:3,April:4,May:5,June:6,July:7,August:8,September:9,October:10,November:11,December:12 };

function mdToYmd(s) {
  const m = String(s || '').match(/([A-Z][a-z]+)\s+(\d{1,2}),\s+(20\d{2})/);
  if (!m) return null;
  return `${m[3]}-${String(MON[m[1]]).padStart(2, '0')}-${String(+m[2]).padStart(2, '0')}`;
}

const MON3 = { Jan:1,Feb:2,Mar:3,Apr:4,May:5,Jun:6,Jul:7,Aug:8,Sep:9,Oct:10,Nov:11,Dec:12 };

/** H.4.1: "Week ended Nov 18, 2026" or "Wednesday Nov 18, 2026" -> 2026-11-18. */
function weekEndedYmd(html) {
  const text = String(html || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  const m = text.match(/(?:Week ended|Wednesday,?)\s+([A-Z][a-z]{2})[a-z]*\.?\s+(\d{1,2}),\s+(20\d{2})/);
  if (!m || !MON3[m[1]]) return null;
  return `${m[3]}-${String(MON3[m[1]]).padStart(2, '0')}-${String(+m[2]).padStart(2, '0')}`;
}

function heDateShort(ymd) {
  if (!ymd) return '';
  const [y, m, d] = ymd.split('-');
  return `${+d}.${+m}`;
}

async function publishedRelease(http, url, entry, defaultTime, dateMin, to, out, log, labelField) {
  try {
    const html = await http.getText(url);
    const asOf = dataAsOf(html);
    const ymd = mdToYmd(asOf);
    // The *release* date is often the next business day after as-of. If we can't find it, use today Israel if the page is current.
    let rel = ymd;
    const relM = html.match(/Release Date:\s*([A-Z][a-z]+ \d{1,2}, 20\d{2})/i);
    if (relM) rel = mdToYmd(relM[1]);
    if (!rel) return;
    // H.15 is released on date D with data for D or D-1; existing calendar uses the release date.
    if (!inRange(rel, dateMin, to)) return;
    const time = defaultTime;
    let actual = formatPublished(heDateShort(ymd || rel));
    if (entry.id === 'fed-h41') {
      // H.4.1 rows read "פורסם · 11.11": the Wednesday the week's levels refer to, no "נתוני".
      const wk = weekEndedYmd(html);
      if (!wk) return;
      actual = `פורסם · ${heDateShort(wk)}`;
    }
    out.push(candidate(entry, {
      date: rel, time, url,
      actual,
      meta: { agency: 'fed', series: entry.id },
    }));
  } catch (e) {
    log(`Fed ${entry.id} skipped: ${e.message}`);
  }
}

function parseEventsPage(html, monthHint) {
  // Board monthly pages list speeches with times. Structure varies; look for time + name patterns.
  const events = [];
  const text = html.replace(/\r/g, '');
  // e.g. "11:25 a.m. EST" / "2:15 p.m." near a name. This is best-effort.
  const blocks = text.split(/<h[23][^>]*>/i);
  return events; // speeches already in the file for Nov 18-20; new ones added via a looser parse below
}

function parseLooseSpeeches(html, from, to) {
  const out = [];
  // Look for datetime-like "November 19" and times "4:25 p.m."
  // Skip if we can't reliably parse - better no duplicate speeches than junk.
  const stripped = html.replace(/<script[\s\S]*?<\/script>/gi, ' ').replace(/<style[\s\S]*?<\/style>/gi, ' ');
  // Many FRB pages have items like: <strong>November 19, 2026</strong> ... Governor Jefferson ... 9:25 a.m.
  const dayBlocks = stripped.split(/<strong>(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(2026)<\/strong>/i);
  // split keeps delimiters: [pre, mon, day, year, body, mon, day, year, body...]
  for (let i = 1; i + 3 < dayBlocks.length; i += 4) {
    const mon = dayBlocks[i], day = +dayBlocks[i + 1], year = +dayBlocks[i + 2], body = dayBlocks[i + 3];
    const plain = body.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    // Don't invent titles from messy HTML if no obvious speech marker.
    if (!/speech|remarks|discussion|moderat|appears|testimony|panel/i.test(plain)) continue;
  }
  return out;
}

async function ingest(http, { from, to, lookbackFrom, log = () => {} }) {
  const out = [];
  const skipped = [];
  const dateMin = lookbackFrom || from;
  const h15 = CATALOG.find((e) => e.id === 'fed-h15');
  const h41 = CATALOG.find((e) => e.id === 'fed-h41');
  const h8 = CATALOG.find((e) => e.id === 'fed-h8');
  const cp = CATALOG.find((e) => e.id === 'fed-cp');

  await publishedRelease(http, H15, h15, '23:15', dateMin, to, out, log);
  if (http.isBlocked()) return { candidates: out, skipped };
  await publishedRelease(http, H41, h41, '23:30', dateMin, to, out, log);
  if (http.isBlocked()) return { candidates: out, skipped };
  await publishedRelease(http, H8, h8, '23:15', dateMin, to, out, log);
  if (http.isBlocked()) return { candidates: out, skipped };
  await publishedRelease(http, CP, cp, '20:00', dateMin, to, out, log);
  if (http.isBlocked()) return { candidates: out, skipped };

  // FOMC minutes / calendar (titles only + published flag).
  try {
    const html = await http.getText(FOMC);
    const mins = CATALOG.find((e) => e.id === 'fed-fomc-minutes');
    // "Minutes of the October 27-28, 2026 meeting will be released on November 18, 2026"
    const rx = /Minutes of the[^<]{0,80}released on\s+([A-Z][a-z]+ \d{1,2}, 20\d{2})/gi;
    let m;
    while ((m = rx.exec(html))) {
      const ymd = mdToYmd(m[1]);
      if (!ymd || !inRange(ymd, dateMin, to)) continue;
      const il = etWallToIsrael(+ymd.slice(0, 4), +ymd.slice(5, 7), +ymd.slice(8, 10), 14, 0);
      out.push(candidate(mins, {
        date: il.date, time: il.time, url: FOMC,
        actual: 'פורסם',
        meta: { agency: 'fed', series: 'fed-fomc-minutes' },
      }));
    }
  } catch (e) {
    log(`FOMC calendar skipped: ${e.message}`);
    skipped.push({ source: 'fed-fomc', reason: e.message });
  }

  return { candidates: out, skipped };
}

module.exports = { ingest, H15, FOMC, parseLooseSpeeches, weekEndedYmd, publishedRelease };
