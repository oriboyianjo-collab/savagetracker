#!/usr/bin/env node
// earnings-live window, fixed in Israel time (Ori's choice): every US trading day from 10:00 Israel time until 02:00
// Israel time the following night. The trading day is the Israel date on which the window opened (Mon-Fri, not an NYSE
// full-day holiday). CLI: exit 0 inside the window, 1 outside.
'use strict';
// NYSE full-day closures (update yearly).
const US_HOLIDAYS = new Set([
  '2026-11-26', '2026-12-25',
  '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24',
]);
const START_MIN = 10 * 60, END_MIN = 2 * 60;
function ilParts(d) {
  const p = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jerusalem', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(d);
  const g = (t) => p.find((x) => x.type === t).value;
  return { date: `${g('year')}-${g('month')}-${g('day')}`, min: +g('hour') * 60 + +g('minute') };
}
const tradingDay = (ymd) => { const wd = new Date(ymd + 'T12:00:00Z').getUTCDay(); return wd >= 1 && wd <= 5 && !US_HOLIDAYS.has(ymd); };
const prevDay = (ymd) => new Date(Date.parse(ymd + 'T12:00:00Z') - 864e5).toISOString().slice(0, 10);
function inWindow(d = new Date()) {
  const { date, min } = ilParts(d);
  if (min >= START_MIN) return tradingDay(date);
  if (min < END_MIN) return tradingDay(prevDay(date));
  return false;
}
module.exports = { inWindow, tradingDay, US_HOLIDAYS };
if (require.main === module) process.exit(inWindow(process.argv[2] ? new Date(process.argv[2]) : new Date()) ? 0 : 1);
