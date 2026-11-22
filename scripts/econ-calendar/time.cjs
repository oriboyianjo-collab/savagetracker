'use strict';

const IL = 'Asia/Jerusalem';
const ET = 'America/New_York';

function pad(n) { return String(n).padStart(2, '0'); }

function partsInZone(date, tz) {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  });
  const bag = {};
  for (const p of fmt.formatToParts(date)) if (p.type !== 'literal') bag[p.type] = p.value;
  return bag;
}

function ymdInZone(date, tz) {
  const p = partsInZone(date, tz);
  return `${p.year}-${p.month}-${p.day}`;
}

function hmInZone(date, tz) {
  const p = partsInZone(date, tz);
  return `${p.hour}:${p.minute}`;
}

/** Parse an ET wall time (YYYYMMDD[T]HHMMSS or Date) and return Israel calendar date + HH:MM. */
function etWallToIsrael(year, month, day, hour = 0, minute = 0) {
  // Build a UTC instant that equals the given ET wall time via binary-ish correction.
  let guess = Date.UTC(year, month - 1, day, hour, minute, 0);
  for (let i = 0; i < 4; i++) {
    const p = partsInZone(new Date(guess), ET);
    const want = Date.UTC(year, month - 1, day, hour, minute);
    const got = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute);
    guess += want - got;
  }
  const d = new Date(guess);
  return { date: ymdInZone(d, IL), time: hmInZone(d, IL), instant: d };
}

function icsUtcToIsrael(yyyymmdd, hhmmss) {
  const y = +yyyymmdd.slice(0, 4), m = +yyyymmdd.slice(4, 6), d = +yyyymmdd.slice(6, 8);
  const h = +(hhmmss || '000000').slice(0, 2);
  const min = +(hhmmss || '000000').slice(2, 4);
  const inst = new Date(Date.UTC(y, m - 1, d, h, min, 0));
  return { date: ymdInZone(inst, IL), time: hmInZone(inst, IL), instant: inst };
}

function icsTzToIsrael(tzid, yyyymmdd, hhmmss) {
  const y = +yyyymmdd.slice(0, 4), m = +yyyymmdd.slice(4, 6), d = +yyyymmdd.slice(6, 8);
  const h = +(hhmmss || '000000').slice(0, 2);
  const min = +(hhmmss || '000000').slice(2, 4);
  const tz = /eastern|new_york|america\/new_york|us-eastern/i.test(tzid || '') ? ET : (tzid || ET);
  if (tz === ET) return etWallToIsrael(y, m, d, h, min);
  // Fallback: treat as ET if unknown US economic calendar.
  return etWallToIsrael(y, m, d, h, min);
}

const HE_MONTHS = ['', 'ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר'];
const EN_MONTHS = ['', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

function monthNameHe(n) { return HE_MONTHS[+n] || ''; }
function monthNameEn(n) { return EN_MONTHS[+n] || ''; }

function periodMonthly(yearMonth, kind = 'חודשי') {
  // yearMonth: '2026-10' or {year, month}
  let y, m;
  if (typeof yearMonth === 'string') { y = yearMonth.slice(0, 4); m = +yearMonth.slice(5, 7); }
  else { y = yearMonth.year; m = yearMonth.month; }
  const heM = monthNameHe(m);
  const enM = monthNameEn(m);
  if (kind === 'שנתי') return { he: `${heM} · שנתי`, en: `${enM} · annual` };
  if (kind === 'סופי') return { he: `${heM} · סופי`, en: `${enM} · final` };
  return { he: `${heM} · חודשי`, en: `${enM} · monthly` };
}

function periodQuarter(year, q, extraHe = 'רבעוני', extraEn = 'quarterly') {
  return { he: `רבעון ${q} · ${extraHe}`, en: `Quarter ${q} · ${extraEn}` };
}

function todayIsrael(now = new Date()) {
  return ymdInZone(now, IL);
}

module.exports = {
  IL, ET, pad, partsInZone, ymdInZone, hmInZone, etWallToIsrael, icsUtcToIsrael, icsTzToIsrael,
  monthNameHe, monthNameEn, periodMonthly, periodQuarter, todayIsrael,
};
