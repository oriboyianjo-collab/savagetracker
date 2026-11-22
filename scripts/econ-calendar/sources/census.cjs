'use strict';

const { CATALOG, matchSummary } = require('../catalog.cjs');
const { candidate, inRange, periodFromYm } = require('./util.cjs');
const { etWallToIsrael } = require('../time.cjs');
const { formatPct, formatHomesSaar, formatBillionUSD } = require('../format.cjs');

const LIST = 'https://www.census.gov/economic-indicators/calendar-listview-2026.html';
const STARTS_HTML = 'https://www.census.gov/construction/nrc/current/index.html';
const STARTS_PDF = 'https://www.census.gov/construction/nrc/pdf/newresconst.pdf';

const MONTHS = {
  January: 1, February: 2, March: 3, April: 4, May: 5, June: 6,
  July: 7, August: 8, September: 9, October: 10, November: 11, December: 12,
};

function parseTime(s) {
  // "8:30 AM" or "10:00 AM"
  const m = String(s || '').trim().match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
  if (!m) return { hour: 8, minute: 30 };
  let h = +m[1];
  const min = +m[2];
  const ap = m[3].toUpperCase();
  if (ap === 'PM' && h !== 12) h += 12;
  if (ap === 'AM' && h === 12) h = 0;
  return { hour: h, minute: min };
}

function parseList(html) {
  const events = [];
  const rows = html.split(/<tr[^>]*>/i).slice(1);
  for (const raw of rows) {
    const rec = raw.split(/<\/tr>/i)[0];
    const text = rec.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&ndash;/g, '-').replace(/\s+/g, ' ').trim();
    const m = text.match(/^(.*)\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})\s+(\d{1,2}:\d{2}\s*(?:AM|PM))\s+(.+)$/i);
    if (!m) continue;
    const title = m[1].trim();
    const mon = MONTHS[m[2]];
    const day = +m[3];
    const year = +m[4];
    const tm = parseTime(m[5]);
    const il = etWallToIsrael(year, mon, day, tm.hour, tm.minute);
    // period text is leftover, e.g. "October 2026 A2026..."
    const per = (m[6] || '').match(/(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})/i);
    const periodYm = per ? `${per[2]}-${String(MONTHS[per[1]]).padStart(2, '0')}` : null;
    events.push({ title, date: il.date, time: il.time, periodYm });
  }
  return events;
}

function entriesFor(title) {
  const hits = matchSummary(title, 'census');
  if (hits.length) return hits;
  return CATALOG.filter((e) => e.agency === 'census' && (e.aliases || []).some((a) => title.startsWith(a) || a.startsWith(title.slice(0, 40))));
}

async function ingest(http, { from, to, lookbackFrom, keys = {}, log = () => {} }) {
  const out = [];
  const skipped = [];
  const dateMin = lookbackFrom || from;
  let events = [];
  try {
    const html = await http.getText(LIST);
    events = parseList(html);
    for (const ev of events) {
      if (!inRange(ev.date, dateMin, to)) continue;
      const ents = entriesFor(ev.title);
      if (!ents.length) {
        skipped.push({ source: 'census-uncatalogued', reason: ev.title, date: ev.date });
        continue;
      }
      for (const entry of ents) {
        const per = ev.periodYm ? periodFromYm(ev.periodYm, entry.period) : {};
        out.push(candidate(entry, { date: ev.date, time: ev.time, url: LIST, period: per.period, periodEn: per.periodEn }));
      }
    }
  } catch (e) {
    log(`Census calendar skipped: ${e.message}`);
    skipped.push({ source: 'census-list', reason: e.message });
    if (e.code === 'HTTP_STOP' || e.code === 'HTTP_BLOCKED') return { candidates: out, skipped };
  }

  // Housing starts: official current page (keyless).
  try {
    const html = await http.getText(STARTS_HTML);
    const starts = parseHousingStarts(html);
    if (starts) {
      // Latest release that already happened (schedule rows may look ahead).
      const today = require('../time.cjs').todayIsrael();
      const ev = events.filter((e) => /New Residential Construction/i.test(e.title) && inRange(e.date, dateMin, to) && e.date <= today)
        .sort((a, b) => b.date.localeCompare(a.date))[0];
      const entry = CATALOG.find((c) => c.id === 'census-housing-starts');
      if (entry && ev) {
        const per = ev.periodYm ? periodFromYm(ev.periodYm) : {};
        out.push(candidate(entry, {
          date: ev.date, time: ev.time, url: STARTS_HTML,
          period: per.period, periodEn: per.periodEn,
          actual: starts.actual, previous: starts.previous,
          meta: { agency: 'census', series: 'housing-starts', previousPublished: starts.previousPublished },
        }));
      }
    }
  } catch (e) {
    log(`Census housing starts actuals skipped: ${e.message}`);
    skipped.push({ source: 'census-starts', reason: e.message });
  }

  if (!keys.CENSUS_API_KEY) {
    skipped.push({ source: 'census-api', reason: 'no CENSUS_API_KEY; using public pages only', keyNeeded: false });
  }
  return { candidates: out, skipped };
}

function parseHousingStarts(html) {
  // Look for seasonally adjusted annual rate figures, e.g. "1,352,000" or "Housing Starts ... 1,331,000".
  const text = html.replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ');
  // Common Census phrasing: "Privately‐owned housing starts in October were at a seasonally adjusted annual rate of 1,xxx,000. This is x.x percent (±x.x percent) above/below the revised September estimate of 1,xxx,000."
  const cur = text.match(/housing starts[^.]*?(?:annual rate of|rate of)\s+([0-9,]{3,})/i);
  const prev = text.match(/revised\s+\w+\s+estimate of\s+([0-9,]{3,})/i)
    || text.match(/(?:September|October|November|December|January|February|March|April|May|June|July|August)\s+estimate of\s+([0-9,]{3,})/i)
    || text.match(/previous (?:month|estimate)[^0-9]{0,40}([0-9,]{3,})/i);
  if (cur) {
    return {
      actual: formatHomesSaar(+cur[1].replace(/,/g, '')),
      previous: prev ? formatHomesSaar(+prev[1].replace(/,/g, '')) : undefined,
    };
  }
  const m2 = text.match(/Starts[^.]{0,40}?([0-9]\.[0-9]{1,3})\s*million/i);
  if (m2) return { actual: `${m2[1]} מיליון` };
  return null;
}

module.exports = { ingest, parseList, parseHousingStarts, LIST };
