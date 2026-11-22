'use strict';

const { CATALOG } = require('../catalog.cjs');
const { candidate, inRange } = require('./util.cjs');
const { etWallToIsrael, todayIsrael } = require('../time.cjs');
const { formatOilMmbbl, formatGasBcf } = require('../format.cjs');
const { pdfToText } = require('../pdf.cjs');

const OIL_SCHED = 'https://www.eia.gov/petroleum/supply/weekly/schedule.php';
const OIL_PAGE = 'https://www.eia.gov/petroleum/supply/weekly/';
const OIL_HIGHLIGHTS = 'https://www.eia.gov/petroleum/supply/weekly/pdf/highlights.pdf';
const GAS_SCHED = 'https://ir.eia.gov/ngs/schedule.html';
const GAS_PAGE = 'https://ir.eia.gov/ngs/ngs.html';

function parseScheduleDates(html, from, to) {
  // Look for 2026-11-18 or November 18, 2026 or 11/18/26 around release times 10:30 a.m.
  const events = [];
  const re = /\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+2026\b|\b2026-\d{2}-\d{2}\b|\b\d{1,2}\/\d{1,2}\/26\b/g;
  // Better: YYYY-MM-DD in tables, or "November 18, 2026"
  const mon = { January:1,February:2,March:3,April:4,May:5,June:6,July:7,August:8,September:9,October:10,November:11,December:12 };
  const rx = /(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(2026)/gi;
  let m;
  const seen = new Set();
  while ((m = rx.exec(html))) {
    const il = etWallToIsrael(+m[3], mon[m[1]], +m[2], 10, 30);
    if (seen.has(il.date)) continue;
    seen.add(il.date);
    if (inRange(il.date, from, to)) events.push(il);
  }
  return events;
}

function parseOilChange(html) {
  const text = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  // "Commercial crude oil inventories ... increased by 4.7 million barrels"
  const m = text.match(/crude oil inventories[^.]{0,120}(increased|decreased|fell|rose|were unchanged)\s+(?:by\s+)?([0-9.]+)?\s*million barrels/i);
  if (!m) return null;
  if (/unchanged/i.test(m[1])) return 0;
  const n = m[2] ? parseFloat(m[2]) : null;
  if (n == null) return null;
  return /decreased|fell/i.test(m[1]) ? -n : n;
}

function parseGasChange(html) {
  const text = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  const m = text.match(/(?:net\s+)?(increase|decrease|injection|withdrawal)[^.]{0,40}?([0-9,]+)\s*Bcf/i)
    || text.match(/working gas in storage[^.]{0,80}(increased|decreased)\s+by\s+([0-9,]+)\s*Bcf/i);
  if (!m) return null;
  const n = parseFloat(String(m[2]).replace(/,/g, ''));
  if (/decrease|withdrawal/i.test(m[1])) return -n;
  return n;
}

/** "Released: November 19, 2026 at 10:30 a.m." -> Israel date/time of that release. */
function parseGasReleaseDate(html) {
  const text = String(html || '').replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ');
  const mon = { January:1,February:2,March:3,April:4,May:5,June:6,July:7,August:8,September:9,October:10,November:11,December:12 };
  const m = text.match(/Released:?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})(?:\s+at\s+(\d{1,2}):(\d{2})\s*([ap])\.?m)?/i);
  if (!m) return null;
  let hh = m[4] ? +m[4] : 10, mm = m[5] ? +m[5] : 30;
  if (m[6] && /p/i.test(m[6]) && hh < 12) hh += 12;
  return etWallToIsrael(+m[3], mon[m[1][0].toUpperCase() + m[1].slice(1).toLowerCase()], +m[2], hh, mm);
}

function parseOilReleaseDates(html, from, to) {
  const seen = new Set();
  const out = [];
  const rx = /\/archive\/(20\d{2})\/\1_(\d{2})_(\d{2})\//g;
  let m;
  while ((m = rx.exec(String(html || '')))) {
    const y = +m[1], mo = +m[2], d = +m[3];
    const il = etWallToIsrael(y, mo, d, 10, 30);
    if (seen.has(il.date)) continue;
    seen.add(il.date);
    if (inRange(il.date, from, to)) out.push(il);
  }
  return out;
}

/** Prefer the stocks table, not the often-stale highlights paragraph. */
function parseHighlightsCrudeChange(text) {
  const compact = String(text || '').replace(/[\t ]+/g, ' ');
  const m = compact.match(/Crude Oil\s*\(Excluding SPR\)\d*[^\d\n]{0,20}(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)/i);
  if (!m) return null;
  const current = parseFloat(m[1]);
  const previous = parseFloat(m[2]);
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return null;
  return { current, previous, change: Math.round((current - previous) * 10) / 10 };
}

async function ingest(http, { from, to, lookbackFrom, keys = {}, log = () => {} }) {
  const out = [];
  const skipped = [];
  const dateMin = lookbackFrom || from;
  const crude = CATALOG.find((e) => e.id === 'eia-crude');
  const gas = CATALOG.find((e) => e.id === 'eia-gas');

  try {
    const html = await http.getText(OIL_SCHED);
    const dates = parseScheduleDates(html, dateMin, to);
    for (const d of dates) out.push(candidate(crude, { date: d.date, time: d.time, url: OIL_SCHED, period: 'שבועי', periodEn: 'Weekly' }));
  } catch (e) {
    log(`EIA oil schedule skipped: ${e.message}`);
    skipped.push({ source: 'eia-oil-sched', reason: e.message });
    if (e.code === 'HTTP_STOP' || e.code === 'HTTP_BLOCKED') return { candidates: out, skipped };
  }
  try {
    const html = await http.getText(OIL_PAGE);
    const dates = parseOilReleaseDates(html, dateMin, to);
    for (const d of dates) out.push(candidate(crude, { date: d.date, time: d.time, url: OIL_PAGE, period: 'שבועי', periodEn: 'Weekly' }));
    let ch = parseOilChange(html);
    let src = OIL_PAGE;
    if (ch == null) {
      try {
        const pdf = await http.get(OIL_HIGHLIGHTS, { accept: 'application/pdf' });
        const text = pdfToText(pdf.buf);
        const parsed = parseHighlightsCrudeChange(text);
        if (parsed) { ch = parsed.change; src = OIL_HIGHLIGHTS; }
      } catch (e) {
        log(`EIA oil highlights PDF skipped: ${e.message}`);
        skipped.push({ source: 'eia-oil-highlights', reason: e.message });
        if (e.code === 'HTTP_STOP' || e.code === 'HTTP_BLOCKED') return { candidates: out, skipped };
      }
    }
    if (ch != null) {
      const today = todayIsrael();
      const oilCands = out.filter((c) => c['אירוע'] === crude.he && c['תאריך'] <= today);
      const ev = oilCands.sort((a, b) => b['תאריך'].localeCompare(a['תאריך']))[0];
      if (ev) {
        out.push(candidate(crude, {
          date: ev['תאריך'], time: ev['שעה'], url: src, period: 'שבועי', periodEn: 'Weekly',
          actual: formatOilMmbbl(ch),
          meta: { agency: 'eia', series: 'eia-crude' },
        }));
      }
    }
  } catch (e) {
    log(`EIA oil actuals skipped: ${e.message}`);
    skipped.push({ source: 'eia-oil', reason: e.message });
    if (e.code === 'HTTP_STOP' || e.code === 'HTTP_BLOCKED') return { candidates: out, skipped };
  }

  try {
    const html = await http.getText(GAS_SCHED);
    const dates = parseScheduleDates(html, dateMin, to);
    for (const d of dates) out.push(candidate(gas, { date: d.date, time: d.time || '17:30', url: GAS_SCHED, period: 'שבועי', periodEn: 'Weekly' }));
  } catch (e) {
    log(`EIA gas schedule skipped: ${e.message}`);
    skipped.push({ source: 'eia-gas-sched', reason: e.message });
  }
  try {
    const html = await http.getText(GAS_PAGE);
    const ch = parseGasChange(html);
    // Attach the figure to the row of the date the report says it was released, never to "the latest
    // schedule date" (the EIA schedule page lists only holiday-shifted dates, e.g. Nov 13 and Nov 25).
    const rel = parseGasReleaseDate(html);
    if (ch != null && !rel) skipped.push({ source: 'eia-gas', reason: 'release date not found on report page; value not written' });
    if (ch != null && rel && !inRange(rel.date, dateMin, to)) skipped.push({ source: 'eia-gas', reason: `report released ${rel.date} outside window` });
    if (ch != null && rel && inRange(rel.date, dateMin, to)) {
      const ev = { 'תאריך': rel.date, 'שעה': rel.time };
      {
        out.push(candidate(gas, {
          date: ev['תאריך'], time: ev['שעה'], url: GAS_PAGE, period: 'שבועי', periodEn: 'Weekly',
          actual: formatGasBcf(ch),
          meta: { agency: 'eia', series: 'eia-gas' },
        }));
      }
    }
  } catch (e) {
    log(`EIA gas actuals skipped: ${e.message}`);
    skipped.push({ source: 'eia-gas', reason: e.message });
  }

  if (!keys.EIA_API_KEY) {
    skipped.push({ source: 'eia-api', reason: 'no EIA_API_KEY; using official HTML (keyless)', keyNeeded: false });
  }
  return { candidates: out, skipped };
}

module.exports = { ingest, parseOilChange, parseGasChange, parseGasReleaseDate, parseScheduleDates, parseOilReleaseDates, parseHighlightsCrudeChange, OIL_HIGHLIGHTS };
