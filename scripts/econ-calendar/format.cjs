'use strict';

function trimNum(n, digits) {
  if (!Number.isFinite(+n)) return null;
  let s = (+n).toFixed(digits);
  // Only strip trailing zeros after a decimal point. "200" must stay "200", not "2".
  if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, '');
  return s || '0';
}

function formatPct(n, { signed = false, digits = 1 } = {}) {
  const v = +n;
  if (!Number.isFinite(v)) return null;
  const t = trimNum(v, digits);
  const sign = signed && v > 0 ? '+' : '';
  return `${sign}${t}%`;
}

function formatK(n, { signed = false, digits = 3 } = {}) {
  const v = +n;
  if (!Number.isFinite(v)) return null;
  const sign = signed && v > 0 ? '+' : (v < 0 ? '-' : '');
  const abs = Math.abs(v);
  if (abs >= 1e6) return `${sign}${trimNum(abs / 1e6, 3)}M`;
  if (abs >= 1000 || (abs >= 100 && Number.isInteger(abs / 1000 * 10) === false && abs % 1 === 0 && abs >= 1000)) {
    // 194000 -> 194K; 1718e3 continuing claims sometimes 1.718M already handled
  }
  if (abs >= 1000) return `${sign}${trimNum(abs / 1000, abs % 1000 === 0 ? 0 : 2)}K`;
  return `${sign}${trimNum(abs, digits)}`;
}

/** Weekly claims: 194K; continuing: 1.718M */
function formatClaims(n, { continuing = false } = {}) {
  const v = +n;
  if (!Number.isFinite(v)) return null;
  if (continuing || Math.abs(v) >= 1e6) return `${trimNum(Math.abs(v) / 1e6, 3)}M`;
  return `${trimNum(v / 1000, v % 1000 === 0 ? 0 : 2)}K`.replace(/\.00K$/, 'K');
}

function formatPayrolls(n) {
  const v = +n;
  if (!Number.isFinite(v)) return null;
  // Existing file mixes "165K" and "+29K". Prefer signed only when negative or when clearly a change; default 165K.
  if (v < 0) return `-${trimNum(Math.abs(v) / 1000, 0)}K`;
  return `${trimNum(v / 1000, Math.abs(v) % 1000 === 0 ? 0 : 1)}K`;
}

function formatBillionUSD(n, { signed = true, digits = 1 } = {}) {
  const v = +n;
  if (!Number.isFinite(v)) return null;
  const sign = v < 0 ? '-' : (signed && v > 0 ? '' : '');
  // Trade balance uses "-134.9 מיליארד דולר"
  return `${v < 0 ? '-' : ''}${trimNum(Math.abs(v), digits)} מיליארד דולר`;
}

function formatMillionUSD(n, { digits = 1 } = {}) {
  const v = +n;
  if (!Number.isFinite(v)) return null;
  return `${v < 0 ? '-' : ''}${trimNum(Math.abs(v), digits)} מיליון דולר`;
}

function formatOilMmbbl(change) {
  const v = +change;
  if (!Number.isFinite(v)) return null;
  const sign = v > 0 ? '+' : (v < 0 ? '-' : '');
  return `${sign}${trimNum(Math.abs(v), 1)} מיליון חביות`;
}

function formatGasBcf(change) {
  const v = +change;
  if (!Number.isFinite(v)) return null;
  const sign = v > 0 ? '+' : (v < 0 ? '-' : '');
  return `${sign}${trimNum(Math.abs(v), 0)} מיליארד רגל מעוקבת`;
}

function formatIndex(n, digits = 1) {
  const v = +n;
  if (!Number.isFinite(v)) return null;
  return trimNum(v, digits);
}

function formatPublished(dateOrLabel) {
  if (!dateOrLabel) return 'פורסם';
  return `פורסם · נתוני ${dateOrLabel}`;
}

function formatHomesSaar(n) {
  // 676K or 3.75 מיליון
  const v = +n;
  if (!Number.isFinite(v)) return null;
  if (Math.abs(v) >= 1e6) return `${trimNum(v / 1e6, 3)} מיליון`;
  return formatK(v);
}

/** Normalize a display value for equality (194K vs 194,000 vs 194 אלף). */
function normalizeValue(s) {
  if (s == null) return '';
  let t = String(s).trim();
  if (!t) return '';
  t = t.replace(/[–—]/g, '-').replace(/,/g, '').replace(/\s+/g, ' ');
  t = t.replace(/אלף/g, 'K').replace(/מיליון חביות/g, 'MMBBL').replace(/מיליארד רגל מעוקבת/g, 'BCF');
  t = t.replace(/מיליארד דולר/g, 'BUSD').replace(/מיליון דולר/g, 'MUSD').replace(/מיליון/g, 'M');
  t = t.replace(/%/g, 'PCT');
  const m = t.match(/^([+-])?\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Z]+)?$/i);
  if (m) {
    const sign = m[1] === '-' ? -1 : 1;
    let n = sign * parseFloat(m[2]);
    const u = (m[3] || '').toUpperCase();
    if (u === 'K') n *= 1e3;
    else if (u === 'M') n *= 1e6;
    else if (u === 'B' || u === 'BUSD') n *= 1e9;
    else if (u === 'MUSD') n *= 1e6;
    else if (u === 'MMBBL') n *= 1; // already millions
    else if (u === 'BCF') n *= 1;
    else if (u === 'PCT') n *= 1;
    return `N:${n}`;
  }
  return t.toLowerCase();
}

function valuesEquivalent(a, b) {
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  if (String(a).trim() === String(b).trim()) return true;
  const na = normalizeValue(a), nb = normalizeValue(b);
  if (na && na === nb) return true;
  if (na.startsWith('N:') && nb.startsWith('N:')) {
    const x = +na.slice(2), y = +nb.slice(2);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return false;
    const scale = Math.max(1, Math.abs(x), Math.abs(y));
    return Math.abs(x - y) <= scale * 1e-6 + 1e-6;
  }
  return false;
}

module.exports = {
  trimNum, formatPct, formatK, formatClaims, formatPayrolls, formatBillionUSD, formatMillionUSD,
  formatOilMmbbl, formatGasBcf, formatIndex, formatPublished, formatHomesSaar,
  normalizeValue, valuesEquivalent,
};
