'use strict';

const { valuesEquivalent, normalizeValue } = require('./format.cjs');

const AUTOMATION = 'savage-econ-calendar';

/** Fields the job may never write or change. */
const NEVER = new Set([
  'הערה', 'הערה_en', 'צפי', 'צפי_en', 'מקור_צפי', 'היסטוריית_צפי',
]);

const REVISABLE = new Set(['בפועל', 'בפועל_en', 'קודם', 'קודם_en']);

function isEmpty(v) {
  return v == null || v === '';
}

function canon(s) {
  return String(s || '')
    .toLowerCase()
    .replace(/[“”״"׳'`,.]/g, '')
    .replace(/[–—]/g, '-')
    .replace(/\s+/g, ' ')
    .trim();
}

function nextId(rows) {
  let max = 0;
  for (const r of rows) {
    const m = String(r['מזהה'] || '').match(/^c-(\d+)$/i);
    if (m) max = Math.max(max, +m[1]);
  }
  return 'c-' + String(max + 1).padStart(4, '0');
}

function nameKeys(row, extra) {
  const out = new Set();
  for (const v of [row['אירוע'], row['אירוע_en'], ...(extra || [])]) {
    const c = canon(v);
    if (c) out.add(c);
  }
  return out;
}

function findRow(rows, candidate) {
  if (candidate['מזהה']) {
    const hit = rows.find((r) => r['מזהה'] === candidate['מזהה']);
    if (hit) return hit;
  }
  const names = nameKeys(candidate, candidate._aliases);
  if (!candidate['תאריך'] || !candidate['מדינה'] || !names.size) return null;
  return rows.find((r) => (
    r['תאריך'] === candidate['תאריך']
    && r['מדינה'] === candidate['מדינה']
    && [...nameKeys(r)].some((n) => names.has(n))
  )) || null;
}

function autoSlot(row, field) {
  const root = row['אוטומציה'];
  if (!root || typeof root !== 'object') return null;
  const slot = root[field];
  return slot && typeof slot === 'object' ? slot : null;
}

/**
 * Official revisions may update בפועל/קודם when:
 *  - the field is empty, or
 *  - this automation previously wrote it from the same official agency, or
 *  - the current text equals the originally published official value now being revised
 *    (covers a human/other bot who typed that first official print).
 * Never revises צפי or notes. Never overwrites a different human-entered value.
 */
function mayWrite(row, field, newValue, meta = {}) {
  if (NEVER.has(field)) return { ok: false, reason: 'protected' };
  if (isEmpty(newValue)) return { ok: false, reason: 'empty-incoming' };
  const cur = row[field];
  if (isEmpty(cur)) return { ok: true, reason: 'fill' };
  if (valuesEquivalent(cur, newValue)) return { ok: false, reason: 'unchanged' };
  if (!REVISABLE.has(field)) return { ok: false, reason: 'nonempty' };

  const slot = autoSlot(row, field);
  const sameAgency = slot && slot.by === AUTOMATION && (!meta.agency || slot.agency === meta.agency);
  if (sameAgency) return { ok: true, reason: 'revise-ours' };

  // Ori's rule "תעדכן לנתון המתוקן": an agency that only publishes the latest (revised) vintage, e.g. BLS,
  // may replace the stored print for the exact reference month. Only numeric-over-numeric (a stored note
  // like "3.7% (ספטמבר)" or "N/A" is left alone); the source has already applied its plausibility guards.
  if (meta.officialRevision && normalizeValue(cur).startsWith('N:') && normalizeValue(newValue).startsWith('N:')) {
    return { ok: true, reason: 'revise-official-latest' };
  }

  const originals = [meta.previousPublished, slot && slot.first, slot && slot.last]
    .filter((v) => !isEmpty(v));
  if (originals.some((v) => valuesEquivalent(cur, v))) return { ok: true, reason: 'revise-official-original' };

  return { ok: false, reason: 'human-or-other' };
}

function setAuto(row, field, meta, value, when, kind, from) {
  if (!row['אוטומציה'] || typeof row['אוטומציה'] !== 'object') row['אוטומציה'] = {};
  const prev = row['אוטומציה'][field] || {};
  const firstVal = prev.first || ((kind === 'revise-official-original' || kind === 'revise-official-latest') && !isEmpty(from) ? from : value);
  const rec = {
    by: AUTOMATION,
    agency: meta.agency || prev.agency || '',
    series: meta.series || prev.series || '',
    first: firstVal,
    last: value,
    first_at: prev.first_at || when,
  };
  if (String(kind).startsWith('revise')) rec.revised_at = when;
  else rec.filled_at = when;
  if (meta.url) rec.url = meta.url;
  row['אוטומציה'][field] = rec;
}

function appendHistory(row, field, from, to, when, reason) {
  if (isEmpty(from)) return;
  const key = 'היסטוריית_נתונים';
  if (isEmpty(row[key])) row[key] = [];
  if (!Array.isArray(row[key])) return; // don't overwrite a non-array human value
  row[key].push({ field, from, to, at: when, reason });
}

/**
 * Apply a list of candidate event patches onto calendar rows.
 * Each candidate is a partial calendar row plus optional _aliases, _meta, _sourceUrl.
 */
function applyCandidates(rows, candidates, { now = new Date(), addFrom = null } = {}) {
  const when = now.toISOString().slice(0, 10);
  const stats = {
    added: 0, filled: 0, revised: 0, skipped: 0, protected: 0, unchanged: 0, human: 0,
    changes: [],
  };
  const list = rows.slice();

  for (const cand of candidates) {
    if (!cand || !cand['תאריך'] || !cand['מדינה'] || !cand['אירוע']) {
      stats.skipped++;
      continue;
    }
    let row = findRow(list, cand);
    if (!row) {
      if (addFrom && cand['תאריך'] < addFrom) { stats.skipped++; continue; }
      row = newRowFrom(cand, nextId(list));
      list.push(row);
      stats.added++;
      stats.changes.push({ action: 'add', id: row['מזהה'], date: row['תאריך'], event: row['אירוע'] });
    }

    const meta = cand._meta || {};
    const sourceUrl = cand._sourceUrl || cand['מקור'] || meta.url;

    for (const [field, value] of Object.entries(cand)) {
      if (field.startsWith('_')) continue;
      if (field === 'מזהה') continue;
      const prevPub = field === 'קודם' || field === 'קודם_en'
        ? (meta.previousPublished ?? meta.previousPublishedPrevious)
        : (meta.previousPublishedActual ?? (field === 'בפועל' || field === 'בפועל_en' ? meta.previousPublished : undefined));
      const { ok, reason } = mayWrite(row, field, value, {
        agency: meta.agency,
        previousPublished: prevPub,
        officialRevision: !!meta.officialRevision,
      });
      if (!ok) {
        if (reason === 'protected') stats.protected++;
        else if (reason === 'unchanged') stats.unchanged++;
        else if (reason === 'human-or-other') {
          stats.human++;
          stats.changes.push({ action: 'human-skip', id: row['מזהה'], field, from: row[field], to: value, event: row['אירוע'], date: row['תאריך'], reason });
        }
        else stats.skipped++;
        continue;
      }
      const from = row[field];
      row[field] = value;
      if (reason === 'fill') {
        stats.filled++;
        stats.changes.push({ action: 'fill', id: row['מזהה'], field, to: value, event: row['אירוע'], date: row['תאריך'] });
      } else {
        stats.revised++;
        appendHistory(row, field, from, value, when, reason);
        stats.changes.push({ action: 'revise', id: row['מזהה'], field, from, to: value, event: row['אירוע'], date: row['תאריך'], reason });
      }
      if (REVISABLE.has(field)) {
        setAuto(row, field, { ...meta, url: sourceUrl }, value, when, reason, from);
        if (field === 'בפועל' && sourceUrl && isEmpty(row['מקור_בפועל'])) row['מקור_בפועל'] = sourceUrl;
        if (field === 'קודם' && sourceUrl && isEmpty(row['מקור_קודם'])) row['מקור_קודם'] = sourceUrl;
      }
    }

    if (sourceUrl && isEmpty(row['מקור'])) row['מקור'] = sourceUrl;
    if (cand['קישור'] && isEmpty(row['קישור'])) row['קישור'] = cand['קישור'];
  }

  return { rows: list, stats };
}

function newRowFrom(cand, id) {
  const row = { 'מזהה': id };
  for (const [k, v] of Object.entries(cand)) {
    if (k.startsWith('_')) continue;
    if (NEVER.has(k)) continue;
    if (isEmpty(v)) continue;
    row[k] = v;
  }
  if (!row['חשיבות']) row['חשיבות'] = 1;
  return row;
}

function stringifyCalendar(rows) {
  // Match existing calendar.json: compact JSON, no trailing newline.
  return JSON.stringify(rows);
}

module.exports = {
  AUTOMATION, NEVER, REVISABLE, isEmpty, canon, nextId, findRow, mayWrite,
  applyCandidates, newRowFrom, stringifyCalendar, nameKeys,
};
