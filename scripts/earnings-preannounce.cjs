'use strict';

const MONTHS = {
  january: 1, february: 2, march: 3, april: 4, may: 5, june: 6,
  july: 7, august: 8, september: 9, october: 10, november: 11, december: 12,
  jan: 1, feb: 2, mar: 3, apr: 4, jun: 6, jul: 7, aug: 8, sep: 9, sept: 9,
  oct: 10, nov: 11, dec: 12,
};

function stripHtml(s) {
  return String(s || '')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;|&#160;/gi, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&[a-z]+;|&#\d+;/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function pad2(n) { return String(n).padStart(2, '0'); }

function ymd(y, m, d) {
  if (!y || !m || !d) return null;
  y = +y; m = +m; d = +d;
  if (y < 100) y += 2000;
  if (y < 2020 || y > 2035 || m < 1 || m > 12 || d < 1 || d > 31) return null;
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return null;
  return `${y}-${pad2(m)}-${pad2(d)}`;
}

function parseMonthToken(tok) {
  return MONTHS[String(tok || '').replace(/\./g, '').toLowerCase()] || 0;
}

function parseClockParts(h, m, ap) {
  h = +h;
  m = m == null || m === '' ? 0 : +m;
  if (!Number.isFinite(h) || !Number.isFinite(m) || h < 0 || h > 23 || m < 0 || m > 59) return null;
  const apu = String(ap || '').replace(/\./g, '').toLowerCase();
  if (apu === 'pm' && h < 12) h += 12;
  if (apu === 'am' && h === 12) h = 0;
  if (!apu && h <= 12) return null;
  return { h, m, min: h * 60 + m };
}

function zoneFromText(s) {
  const t = String(s || '');
  if (/\b(?:hong\s*kong|hkt|hk\s*time)\b/i.test(t)) return 'Asia/Hong_Kong';
  if (/\b(?:pacific|p\.?\s*t\.?|pdt|pst)\b/i.test(t)) return 'America/Los_Angeles';
  if (/\b(?:mountain|m\.?\s*t\.?|mdt|mst)\b/i.test(t) && !/paramount/i.test(t)) return 'America/Denver';
  if (/\b(?:central|c\.?\s*t\.?|cdt|cst)\b/i.test(t) && !/central\s+(?:bank|government|park)/i.test(t)) return 'America/Chicago';
  if (/\b(?:london|uk|bst|british)\b/i.test(t)) return 'Europe/London';
  if (/\b(?:eastern|e\.?\s*t\.?|edt|est|u\.?s\.\s*eastern)\b/i.test(t)) return 'America/New_York';
  return null;
}

function instantFromZoned(dateYmd, h, m, tz) {
  const [Y, Mo, D] = dateYmd.split('-').map(Number);
  let ms = Date.UTC(Y, Mo - 1, D, h, m, 0);
  for (let i = 0; i < 4; i++) {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(new Date(ms));
    const g = (ty) => {
      const v = parts.find((x) => x.type === ty);
      return v ? +v.value : NaN;
    };
    let hour = g('hour');
    if (hour === 24) hour = 0;
    const got = Date.UTC(g('year'), g('month') - 1, g('day'), hour, g('minute'));
    const want = Date.UTC(Y, Mo - 1, D, h, m);
    const delta = want - got;
    if (delta === 0) break;
    ms += delta;
  }
  return new Date(ms).toISOString();
}

function ilClockFromZoned(dateYmd, clock, tz, ilClockFn) {
  if (!dateYmd || !clock) return null;
  const iso = instantFromZoned(dateYmd, clock.h, clock.m, tz || 'America/New_York');
  return ilClockFn(iso);
}

const WILL_RELEASE = /\b(?:will|to|is to|plans to|expects to|scheduled to)\s+(?:release|announce|issue|report|publish|furnish|file|make available)\b|\b(?:announces?|announced|sets?|set|schedules?|scheduled)\s+(?:the\s+)?(?:date|timing|schedule|release date)\b|\bearnings\s+(?:release\s+)?(?:date|schedule|timing)\b|\bschedule[sd]?\s+(?:its\s+)?(?:first|second|third|fourth|q[1-4]|fiscal|quarterly|annual|year[- ]end|earnings|financial)\b|\bto\s+hold\s+(?:a\s+)?(?:conference|earnings|investor)\s+call\b|\binvite[sd]?\s+(?:you|investors|the public)\s+to\s+(?:a\s+)?(?:conference|earnings)\s+call\b|\bwill host a (?:conference |earnings |investor )?call\b/i;

const RESULTS_WORD = /\b(?:financial\s+results|earnings\s+results|quarterly\s+results|fiscal\s+(?:year\s+)?results|year[- ]end\s+results|q[1-4]\s+results|(?:first|second|third|fourth)\s+quarter(?:\s+fiscal)?(?:\s+20\d{2})?\s+results|earnings|results)\b/i;

const CALL_HINT = /\b(?:conference call|earnings call|investor call|results call|earnings webcast|live webcast|audio webcast|will host a (?:conference |earnings )?call|to host a (?:conference |earnings )?call)\b/i;

function isAlreadyReleasedResults(t) {
  if (/\b(?:will|to|plans to|expects to|scheduled to)\s+(?:release|announce|issue|report|publish)\b/i.test(t)) return false;
  if (/\b(?:date|timing|schedule) of (?:its )?(?:upcoming )?(?:financial )?results\b/i.test(t)) return false;
  if (/\b(?:reports|reported)\b[\s\S]{0,90}\b(?:financial\s+)?results\b/i.test(t)) return true;
  return false;
}

function isEarningsPreannounce(text) {
  const t = String(text || '');
  if (isAlreadyReleasedResults(t)) return false;
  if (!WILL_RELEASE.test(t)) return false;
  if (!RESULTS_WORD.test(t) && !CALL_HINT.test(t)) return false;
  return true;
}

function detectSession(text) {
  const t = String(text || '');
  const usChunk = (() => {
    const m = t.match(/U\.?S\.?\s*(?:Time|markets?|investors?)[\s\S]{0,280}/i);
    return m ? m[0] : t;
  })();
  const after = /\b(?:after\s+(?:the\s+)?(?:market|u\.?s\.\s+market)\s+clos(?:e|es|ing)|after[- ]hours|after[- ]market|after\s+the\s+close|following\s+(?:the\s+)?(?:market|u\.?s\.\s+market)\s+close)\b/i;
  const before = /\b(?:before\s+(?:the\s+)?(?:market|u\.?s\.\s+market|nasdaq|nyse|hong\s+kong\s+market)?\s*open(?:ing)?|pre[- ]market|prior\s+to\s+(?:the\s+)?(?:market\s+)?open(?:ing)?|before\s+(?:the\s+)?(?:opening|trading hours|open of trading))\b/i;
  if (after.test(usChunk) || after.test(t)) return 'after';
  if (before.test(usChunk) || before.test(t)) return 'before';
  return '';
}

const DATE_MDY = /\b(?:on\s+)?(?:(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s+)?(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b/ig;
const DATE_DMY = /\b(?:on\s+)?(?:(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?,?\s+(20\d{2})\b/ig;

function allDates(text) {
  const out = [];
  const t = String(text || '');
  let m;
  const re1 = new RegExp(DATE_MDY.source, 'ig');
  while ((m = re1.exec(t))) {
    const y = ymd(m[3], parseMonthToken(m[1]), m[2]);
    if (y) out.push({ date: y, index: m.index, end: m.index + m[0].length, raw: m[0] });
  }
  const re2 = new RegExp(DATE_DMY.source, 'ig');
  while ((m = re2.exec(t))) {
    const y = ymd(m[3], parseMonthToken(m[2]), m[1]);
    if (y) out.push({ date: y, index: m.index, end: m.index + m[0].length, raw: m[0] });
  }
  return out;
}

function isPeriodEndDate(text, d) {
  const before = String(text).slice(Math.max(0, d.index - 70), d.index);
  return /\b(?:quarter|period|year|fiscal year|three months|nine months|six months|months?|weeks?)\s+ended(?:\s+on)?\s*$/i.test(before)
    || /\bended\s+(?:on\s+)?$/i.test(before);
}

function isMeetingDate(text, d) {
  const before = String(text).slice(Math.max(0, d.index - 80), d.index);
  return /\b(?:audit committee|committee|board)\s+(?:meeting\s+)?(?:will\s+)?(?:hold a meeting|meets|meeting)\s+on\s*$/i.test(before)
    || /\bwill hold a meeting on\s*$/i.test(before);
}

function preferBoardDate(text, dates) {
  if (!dates.length) return null;
  const t = String(text || '');
  const scored = dates.filter((d) => !isPeriodEndDate(t, d) && !isMeetingDate(t, d));
  const pool = scored.length ? scored : dates;
  const tagged = [];
  for (const d of pool) {
    const after = t.slice(d.end, d.end + 40);
    const before = t.slice(Math.max(0, d.index - 40), d.index);
    if (/^[, ]*(?:U\.?S\.?\s*Time|U\.?S\.?\s*markets?)/i.test(after)
      || /\b(?:Eastern(?:\s+Time)?|New York|Nasdaq|NYSE)\b/i.test(after)
      || /U\.?S\.?\s*Time\s*$/i.test(before)) tagged.push(d.date);
  }
  if (tagged.length) return tagged[0];
  for (const d of pool) {
    const around = t.slice(Math.max(0, d.index - 200), d.end + 40);
    if (/\b(?:will|to)\s+(?:release|announce|issue|report|publish)\b|\bannounc\w+\s+(?:its\s+)?(?:financial\s+)?results\b/i.test(around)) {
      if (/hong\s*kong/i.test(around) && !/U\.?S\./i.test(around)) continue;
      return d.date;
    }
  }
  return pool[0].date;
}

function allTimes(text) {
  const out = [];
  const t = String(text || '');
  let m;
  const re = /(\d{1,2})(?::(\d{2}))?\s*(a\.?\s*m\.?|p\.?\s*m\.?)/ig;
  while ((m = re.exec(t))) {
    const clock = parseClockParts(m[1], m[2], m[3]);
    if (!clock) continue;
    const end = m.index + m[0].length;
    const after = t.slice(end, Math.min(t.length, end + 40));
    const before = t.slice(Math.max(0, m.index - 40), m.index);
    const around = t.slice(Math.max(0, m.index - 80), Math.min(t.length, end + 60));
    const zone = zoneFromText(after) || zoneFromText(before) || zoneFromText(around) || 'America/New_York';
    out.push({ clock, index: m.index, end, around, zone });
  }
  return out;
}

function guessDateNear(text, index, fallback) {
  const dates = allDates(text).filter((d) => !isPeriodEndDate(text, d));
  const pool = dates.length ? dates : allDates(text);
  if (!pool.length) return fallback || null;
  const after = pool.filter((d) => d.index >= index && d.index - index <= 160);
  if (after.length) {
    after.sort((a, b) => a.index - b.index);
    return after[0].date;
  }
  let best = pool[0];
  let bestDist = Math.abs(pool[0].index - index);
  for (const d of pool) {
    const dist = Math.abs(d.index - index);
    if (dist < bestDist) { best = d; bestDist = dist; }
  }
  return best.date;
}

function phraseWindows(text, phraseRe, afterChars) {
  const t = String(text || '');
  const out = [];
  const re = new RegExp(phraseRe.source, phraseRe.flags.includes('g') ? phraseRe.flags : `${phraseRe.flags}g`);
  let m;
  while ((m = re.exec(t))) {
    const start = m.index;
    const end = Math.min(t.length, m.index + m[0].length + (afterChars || 180));
    out.push({ start, end, text: t.slice(start, end), phrase: m[0] });
  }
  return out;
}

function firstTimeIn(windowText, baseIndex) {
  const times = allTimes(windowText);
  if (!times.length) return null;
  const tm = times[0];
  return {
    clock: tm.clock,
    zone: tm.zone,
    index: baseIndex + tm.index,
  };
}

function pickCallTime(text, date, ilClockFn) {
  const windows = phraseWindows(text, CALL_HINT, 200);
  windows.push(...phraseWindows(text, /\b(?:the\s+call|conference|webcast)\s+(?:will\s+)?(?:begin|start|be held|take place)\b/i, 160));
  for (const w of windows) {
    const tm = firstTimeIn(w.text, w.start);
    if (!tm) continue;
    const useDate = guessDateNear(text, tm.index) || date;
    const clock = ilClockFromZoned(useDate, tm.clock, tm.zone, ilClockFn);
    if (clock) return { clock, date: useDate };
  }
  return null;
}

function pickReleaseTime(text, date, call, ilClockFn) {
  const re = /\b(?:press release|news release|earnings release)\b(?:[^.]{0,80}\b(?:at|after|before|approximately))?|\bresults will be (?:released|announced|issued|published|furnished|made available)\b|\bwill be (?:released|issued|published|furnished|made available)\s+(?:at|after|before|approximately)\b/ig;
  const windows = phraseWindows(text, re, 120);
  for (const w of windows) {
    const tm = firstTimeIn(w.text, w.start);
    if (!tm) continue;
    const useDate = guessDateNear(text, tm.index) || date;
    const clock = ilClockFromZoned(useDate, tm.clock, tm.zone, ilClockFn);
    if (!clock) continue;
    if (call && clock === call.clock) continue;
    return { clock, date: useDate };
  }
  return null;
}

function sessionFromReleaseClock(clock) {
  if (!clock) return '';
  if (clock.min >= 16 * 60) return 'after';
  if (clock.min <= 9 * 60 + 30) return 'before';
  return '';
}

function parseEarningsPreannounce(text, ilClockFn) {
  const raw = String(text || '');
  const t = /<[a-z][\s\S]*>/i.test(raw) ? stripHtml(raw) : raw.replace(/\s+/g, ' ').trim();
  if (!t || t.length < 40) return null;
  if (!isEarningsPreannounce(t)) return null;

  const dates = allDates(t);
  const date = preferBoardDate(t, dates);
  let session = detectSession(t);
  const call = pickCallTime(t, date, ilClockFn);
  const release = pickReleaseTime(t, date, call, ilClockFn);
  if (!session && release) session = sessionFromReleaseClock(release.clock && typeof release.clock === 'object' ? release.clock : null);
  // sessionFromReleaseClock needs the raw ET clock, not IL. Re-detect from the first release window time.
  if (!session) {
    const re = /\b(?:press release|news release|earnings release)\b/ig;
    const w = phraseWindows(t, re, 120)[0];
    const tm = w && firstTimeIn(w.text, w.start);
    if (tm) session = sessionFromReleaseClock(tm.clock);
  }

  return {
    isPreannounce: true,
    date: date || null,
    session: session || '',
    releaseTimeIl: release ? release.clock : null,
    callTimeIl: call ? call.clock : null,
    sourceKind: 'issuer-scheduled',
  };
}

function parseCallTimeFromRelease(text, date, ilClockFn) {
  const raw = String(text || '');
  const t = /<[a-z][\s\S]*>/i.test(raw) ? stripHtml(raw) : raw.replace(/\s+/g, ' ').trim();
  if (!t) return null;
  const call = pickCallTime(t, date, ilClockFn);
  return call ? call.clock : null;
}

module.exports = {
  stripHtml,
  parseEarningsPreannounce,
  parseCallTimeFromRelease,
  isEarningsPreannounce,
  detectSession,
  allDates,
  preferBoardDate,
  instantFromZoned,
  zoneFromText,
};
