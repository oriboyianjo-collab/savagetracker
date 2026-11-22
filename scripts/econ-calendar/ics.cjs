'use strict';

const { icsUtcToIsrael, icsTzToIsrael } = require('./time.cjs');

function unfold(text) {
  return String(text || '').replace(/\r\n/g, '\n').replace(/\n[ \t]/g, '');
}

function parseIcs(text) {
  const src = unfold(text);
  const events = [];
  const blocks = src.split(/BEGIN:VEVENT/i).slice(1);
  for (const raw of blocks) {
    const body = raw.split(/END:VEVENT/i)[0];
    const get = (key) => {
      const re = new RegExp(`^${key}(;[^:]*)?:(.*)$`, 'im');
      const m = body.match(re);
      if (!m) return null;
      return { params: m[1] || '', value: (m[2] || '').replace(/\\n/g, '\n').replace(/\\,/g, ',').trim() };
    };
    const sum = get('SUMMARY');
    const start = get('DTSTART');
    if (!sum || !start) continue;
    const params = start.params || '';
    const val = start.value || '';
    const isUtc = /Z$/.test(val);
    const m = val.match(/^(\d{8})(?:T(\d{6}))?(Z)?$/);
    if (!m) continue;
    const tzid = (params.match(/TZID=([^;]+)/i) || [])[1] || '';
    const dateVal = params.includes('VALUE=DATE') && !m[2];
    let il;
    if (isUtc) il = icsUtcToIsrael(m[1], m[2] || '000000');
    else if (dateVal) {
      // All-day in the listed calendar date: treat as that civil date, time unknown.
      const y = m[1].slice(0, 4), mo = m[1].slice(4, 6), d = m[1].slice(6, 8);
      il = { date: `${y}-${mo}-${d}`, time: '', instant: null };
    } else il = icsTzToIsrael(tzid, m[1], m[2] || '000000');
    const desc = get('DESCRIPTION');
    events.push({
      summary: sum.value,
      description: desc ? desc.value : '',
      date: il.date,
      time: il.time,
      uid: (get('UID') || {}).value || '',
      instant: il.instant || null,
    });
  }
  return events;
}

module.exports = { parseIcs, unfold };
