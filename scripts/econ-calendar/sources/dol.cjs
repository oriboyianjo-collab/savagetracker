'use strict';

const { pdfToText } = require('../pdf.cjs');
const { CATALOG } = require('../catalog.cjs');
const { candidate, inRange } = require('./util.cjs');
const { etWallToIsrael } = require('../time.cjs');
const { formatClaims } = require('../format.cjs');

const CLAIMS_HTML = 'https://oui.doleta.gov/unemploy/claims.asp';
const CLAIMS_PDF = 'https://www.dol.gov/ui/data.pdf';

function parseClaimsText(text) {
  const t = String(text || '').replace(/\s+/g, ' ');
  const init = t.match(/seasonally adjusted initial claims was\s+([0-9,]+),\s+(?:an?\s+)?(increase|decrease|unchanged)[^.]{0,120}previous week(?:'s)? revised level/i);
  const revised = t.match(/previous week(?:'s)? level was revised\s+(?:up|down)\s+by\s+[0-9,]+\s+from\s+([0-9,]+)\s+to\s+([0-9,]+)/i);
  const cont = t.match(/seasonally adjusted insured unemployment during the week ending[^.]{0,80}was\s+([0-9,]+)/i);
  let contPub = null, contRevTo = null;
  if (cont) {
    const after = t.slice(t.indexOf(cont[0]));
    const r = after.match(/previous week(?:'s)? level was revised\s+(?:up|down)\s+by\s+[0-9,]+\s+from\s+([0-9,]+)\s+to\s+([0-9,]+)/i);
    if (r) { contPub = +r[1].replace(/,/g, ''); contRevTo = +r[2].replace(/,/g, ''); }
  }
  const released = t.match(/(?:EMBARGOED UNTIL|8:30 A\.M\.\s*\(Eastern\))\s+[^,]{0,20},\s*([A-Z][a-z]+ \d{1,2}, 20\d{2})/i)
    || t.match(/Thursday,\s+([A-Z][a-z]+ \d{1,2}, 20\d{2})/i)
    || t.match(/(?:For release|released)[:\s]+(?:Thursday|Wednesday|Friday|Tuesday|Monday)?,?\s*([A-Z][a-z]+ \d{1,2},?\s+20\d{2})/i);
  if (!init && !t.match(/initial claims was\s+([0-9,]+)/i)) return null;
  const currentMatch = init || t.match(/seasonally adjusted initial claims was\s+([0-9,]+)/i);
  const current = currentMatch ? +currentMatch[1].replace(/,/g, '') : null;
  const originallyPublished = revised ? +revised[1].replace(/,/g, '') : null;
  const revisedTo = revised ? +revised[2].replace(/,/g, '') : null;
  return {
    initial: current,
    previousRevised: revisedTo,
    previousPublished: originallyPublished,
    continuing: cont ? +cont[1].replace(/,/g, '') : null,
    continuingPreviousPublished: contPub,
    continuingPreviousRevised: contRevTo,
    releaseText: released ? released[1] : null,
  };
}

function parseClaimsHtml(html) {
  const text = html.replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ');
  return parseClaimsText(text);
}

const MON = { January:1,February:2,March:3,April:4,May:5,June:6,July:7,August:8,September:9,October:10,November:11,December:12 };
function parseMdY(s) {
  const m = String(s || '').match(/([A-Z][a-z]+)\s+(\d{1,2}),?\s+(20\d{2})/);
  if (!m || !MON[m[1]]) return null;
  return { y: +m[3], m: MON[m[1]], d: +m[2] };
}

function shiftIsraelDate(ymd, days) {
  const [y, m, d] = ymd.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  const pad = (n) => String(n).padStart(2, '0');
  return `${dt.getUTCFullYear()}-${pad(dt.getUTCMonth() + 1)}-${pad(dt.getUTCDate())}`;
}

async function ingest(http, { from, to, lookbackFrom, log = () => {} }) {
  const out = [];
  const skipped = [];
  const dateMin = lookbackFrom || from;
  let parsed = null;
  let src = CLAIMS_PDF;
  try {
    const res = await http.get(CLAIMS_PDF, { accept: 'application/pdf' });
    let text = '';
    try { text = pdfToText(res.buf); }
    catch (e) {
      skipped.push({ source: 'dol-pdftotext', reason: `pdftotext unavailable: ${e.message}` });
      log(`DOL claims: pdftotext failed (${e.message})`);
    }
    parsed = text ? parseClaimsText(text) : null;
  } catch (e) {
    log(`DOL claims PDF skipped: ${e.message}`);
    skipped.push({ source: 'dol-pdf', reason: e.message });
    if (e.code === 'HTTP_STOP' || e.code === 'HTTP_BLOCKED') return { candidates: out, skipped };
  }
  if (!parsed || !parsed.initial || !parsed.releaseText) {
    skipped.push({ source: 'dol-claims', reason: 'could not parse official weekly claims release' });
    return { candidates: out, skipped };
  }

  const rel = parseMdY(parsed.releaseText);
  if (!rel) {
    skipped.push({ source: 'dol-claims-date', reason: 'release date not found' });
    return { candidates: out, skipped };
  }
  const il = etWallToIsrael(rel.y, rel.m, rel.d, 8, 30);
  const date = il.date, time = il.time;
  const claims = CATALOG.find((e) => e.id === 'dol-claims');
  const cont = CATALOG.find((e) => e.id === 'dol-claims-cont');
  if (inRange(date, dateMin, to)) {
    out.push(candidate(claims, {
      date, time, url: src, period: 'שבועי', periodEn: 'Weekly',
      actual: formatClaims(parsed.initial),
      previous: parsed.previousRevised ? formatClaims(parsed.previousRevised) : undefined,
      meta: { agency: 'dol', series: 'dol-claims', previousPublished: parsed.previousPublished ? formatClaims(parsed.previousPublished) : undefined },
    }));
    if (parsed.continuing != null) {
      out.push(candidate(cont, {
        date, time, url: src, period: 'שבועי', periodEn: 'Weekly',
        actual: formatClaims(parsed.continuing, { continuing: true }),
        previous: parsed.continuingPreviousRevised ? formatClaims(parsed.continuingPreviousRevised, { continuing: true }) : undefined,
        meta: { agency: 'dol', series: 'dol-claims-cont', previousPublished: parsed.continuingPreviousPublished ? formatClaims(parsed.continuingPreviousPublished, { continuing: true }) : undefined },
      }));
    }
  }
  if (parsed.previousPublished && parsed.previousRevised && parsed.previousPublished !== parsed.previousRevised) {
    const prevDate = shiftIsraelDate(date, -7);
    if (inRange(prevDate, dateMin, to)) {
      out.push(candidate(claims, {
        date: prevDate, time, url: src, period: 'שבועי', periodEn: 'Weekly',
        actual: formatClaims(parsed.previousRevised),
        meta: { agency: 'dol', series: 'dol-claims', previousPublished: formatClaims(parsed.previousPublished) },
      }));
    }
  }
  if (parsed.continuingPreviousPublished && parsed.continuingPreviousRevised
      && parsed.continuingPreviousPublished !== parsed.continuingPreviousRevised) {
    const prevDate = shiftIsraelDate(date, -7);
    if (inRange(prevDate, dateMin, to)) {
      out.push(candidate(cont, {
        date: prevDate, time, url: src, period: 'שבועי', periodEn: 'Weekly',
        actual: formatClaims(parsed.continuingPreviousRevised, { continuing: true }),
        meta: { agency: 'dol', series: 'dol-claims-cont', previousPublished: formatClaims(parsed.continuingPreviousPublished, { continuing: true }) },
      }));
    }
  }
  return { candidates: out, skipped };
}

module.exports = { ingest, parseClaimsHtml, parseClaimsText, shiftIsraelDate, CLAIMS_HTML, CLAIMS_PDF };
