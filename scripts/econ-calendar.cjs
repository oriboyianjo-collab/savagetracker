'use strict';

/**
 * Official economic calendar updater for calendar.json.
 * Legal official sources only. Never writes צפי or הערה / הערה_en.
 * Official revisions may update בפועל/קודם when this job (or the original official print) is the source.
 * Keys (optional): BLS_API_KEY, BEA_API_KEY, CENSUS_API_KEY, EIA_API_KEY — missing keys skip that API, not the job.
 */

const fs = require('fs');
const path = require('path');
const { createHttp } = require('./econ-calendar/http.cjs');
const { todayIsrael } = require('./econ-calendar/time.cjs');
const { applyCandidates, stringifyCalendar } = require('./econ-calendar/merge.cjs');
const bls = require('./econ-calendar/sources/bls.cjs');
const bea = require('./econ-calendar/sources/bea.cjs');
const census = require('./econ-calendar/sources/census.cjs');
const dol = require('./econ-calendar/sources/dol.cjs');
const eia = require('./econ-calendar/sources/eia.cjs');
const fed = require('./econ-calendar/sources/fed.cjs');
const other = require('./econ-calendar/sources/other.cjs');

function parseArgs(argv) {
  const a = { dryRun: false, from: null, to: null, lookback: 14, file: 'calendar.json', out: null, commit: false };
  for (let i = 0; i < argv.length; i++) {
    const x = argv[i];
    if (x === '--dry-run') a.dryRun = true;
    else if (x === '--commit') a.commit = true;
    else if (x === '--from') a.from = argv[++i];
    else if (x === '--to') a.to = argv[++i];
    else if (x === '--lookback') a.lookback = +argv[++i];
    else if (x === '--file') a.file = argv[++i];
    else if (x === '--out') a.out = argv[++i];
    else if (x === '--report') a.report = argv[++i];
    else if (x === '--full') a.full = true;
    else if (x === '--light') a.full = false;
  }
  return a;
}

function shiftDate(ymd, days) {
  const [y, m, d] = ymd.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  const p = (n) => String(n).padStart(2, '0');
  return `${dt.getUTCFullYear()}-${p(dt.getUTCMonth() + 1)}-${p(dt.getUTCDate())}`;
}

function keysFromEnv() {
  return {
    BLS_API_KEY: process.env.BLS_API_KEY || process.env.BLS_KEY || '',
    BEA_API_KEY: process.env.BEA_API_KEY || process.env.BEA_USER_ID || '',
    CENSUS_API_KEY: process.env.CENSUS_API_KEY || '',
    EIA_API_KEY: process.env.EIA_API_KEY || '',
  };
}

async function collect(http, opts, log) {
  const skipped = [];
  const candidates = [];
  const runners = [
    ['bls', bls.ingest],
    ['bea', bea.ingest],
    ['census', census.ingest],
    ['dol', dol.ingest],
    ['eia', eia.ingest],
    ['fed', fed.ingest],
    ['regional-fed', other.ingestRegional],
    ['treasury', other.ingestTreasury],
    ['eurostat', other.ingestEurostat],
  ];
  for (const [name, fn] of runners) {
    if (http.isBlocked()) {
      skipped.push({ source: name, reason: 'stopped after HTTP 403/429' });
      continue;
    }
    try {
      const r = await fn(http, opts);
      candidates.push(...(r.candidates || []));
      skipped.push(...(r.skipped || []));
    } catch (e) {
      log(`${name} failed: ${e.message}`);
      skipped.push({ source: name, reason: e.message, stop: e.code === 'HTTP_STOP' || e.code === 'HTTP_BLOCKED' });
      if (e.code === 'HTTP_STOP' || e.code === 'HTTP_BLOCKED') break;
    }
  }
  return { candidates, skipped };
}

function summarize(stats, skipped, keys) {
  return {
    added: stats.added,
    filled: stats.filled,
    revised: stats.revised,
    humanSkipped: stats.human,
    protected: stats.protected,
    unchanged: stats.unchanged,
    changes: stats.changes,
    skipped,
    keys: {
      BLS_API_KEY: keys.BLS_API_KEY ? 'present' : 'missing (v1 keyless used)',
      BEA_API_KEY: keys.BEA_API_KEY ? 'present' : 'missing (schedule only)',
      CENSUS_API_KEY: keys.CENSUS_API_KEY ? 'present' : 'missing (public pages used)',
      EIA_API_KEY: keys.EIA_API_KEY ? 'present' : 'missing (public pages used)',
    },
  };
}

async function run(argv = process.argv.slice(2), io = {}) {
  const args = parseArgs(argv);
  const log = io.log || ((m) => console.error(m));
  const now = io.now || new Date();
  const today = todayIsrael(now);
  const to = args.to || today;
  const from = args.from || today;
  const lookbackFrom = shiftDate(from, -Math.abs(args.lookback || 14));
  const file = path.resolve(args.file);
  const raw = fs.readFileSync(file, 'utf8');
  const rows = JSON.parse(raw);
  const keys = keysFromEnv();
  const http = io.http || createHttp();
  const full = args.full || process.env.ECON_FULL === '1';
  const { candidates, skipped } = await collect(http, { from, to, lookbackFrom, keys, log, now, full }, log);
  const { rows: next, stats } = applyCandidates(rows, candidates, { now, addFrom: from });
  const report = summarize(stats, skipped, keys);
  report.from = from;
  report.to = to;
  report.lookbackFrom = lookbackFrom;
  report.dryRun = !!args.dryRun;
  report.requests = (http.log || []).map((r) => ({ url: r.url, status: r.status, bytes: r.bytes }));
  const outPath = args.out || (args.dryRun ? file.replace(/\.json$/, '.preview.json') : file);
  if (args.dryRun) {
    fs.writeFileSync(outPath, stringifyCalendar(next));
    report.out = outPath;
  } else if (stats.added || stats.filled || stats.revised) {
    fs.writeFileSync(outPath, stringifyCalendar(next));
    report.out = outPath;
    report.wrote = true;
  } else {
    report.out = file;
    report.wrote = false;
  }
  if (args.report) fs.writeFileSync(args.report, JSON.stringify(report, null, 2));
  return { rows: next, report, args };
}

if (require.main === module) {
  run().then(({ report }) => {
    console.log(JSON.stringify({
      added: report.added,
      filled: report.filled,
      revised: report.revised,
      humanSkipped: report.humanSkipped,
      protected: report.protected,
      out: report.out,
      keys: report.keys,
      skipped: report.skipped,
      changes: report.changes,
    }, null, 2));
  }).catch((e) => {
    console.error(e.stack || e);
    process.exit(1);
  });
}

module.exports = { run, parseArgs, shiftDate, collect, keysFromEnv };
