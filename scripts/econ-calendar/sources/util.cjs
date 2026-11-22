'use strict';

const { periodMonthly } = require('../time.cjs');

function candidate(entry, opts) {
  const c = {
    'תאריך': opts.date,
    'מדינה': entry.country || 'US',
    'אירוע': entry.he,
    'אירוע_en': entry.en,
    'חשיבות': entry.importance || 1,
    _aliases: [entry.en, entry.he, ...(entry.aliases || [])],
    _meta: { agency: entry.agency, series: entry.id, ...(opts.meta || {}) },
  };
  if (opts.time) c['שעה'] = opts.time;
  if (opts.period) c['תקופה'] = opts.period;
  if (opts.periodEn) c['תקופה_en'] = opts.periodEn;
  if (opts.url) {
    c['מקור'] = opts.url;
    c._sourceUrl = opts.url;
    if (opts.link !== false) c['קישור'] = opts.link || opts.url;
  }
  if (!entry.private) {
    if (opts.actual != null && opts.actual !== '') c['בפועל'] = opts.actual;
    if (opts.previous != null && opts.previous !== '') c['קודם'] = opts.previous;
  }
  return c;
}

function inRange(date, from, to) {
  if (!date) return false;
  if (from && date < from) return false;
  if (to && date > to) return false;
  return true;
}

function yearMonthFromBls(obs) {
  // obs.year + obs.period M01..M12
  const p = String(obs.period || '');
  const m = p.match(/^M(\d{2})$/);
  if (!m) return null;
  return `${obs.year}-${m[1]}`;
}

function mom(curr, prev) {
  if (!prev || +prev === 0) return null;
  return ((+curr - +prev) / +prev) * 100;
}

function yoy(curr, yearAgo) {
  if (!yearAgo || +yearAgo === 0) return null;
  return ((+curr - +yearAgo) / +yearAgo) * 100;
}

function periodFromYm(ym, kind) {
  if (!ym) return {};
  const p = periodMonthly(ym, kind === 'שנתי' ? 'שנתי' : 'חודשי');
  return { period: p.he, periodEn: p.en };
}

module.exports = { candidate, inRange, yearMonthFromBls, mom, yoy, periodFromYm };
