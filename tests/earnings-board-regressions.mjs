// Earnings-board updater: calendar mapping, date moves, SEC 8-K matching, revenue/EPS fills, hash, notes untouched,
// and the push-news alert filter. No network, no secrets, no portfolio data.
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const eb = require('../scripts/earnings-board.cjs');
const { alertReports } = require('../scripts/push-news.cjs');
const CL = eb.CL;
let failed = 0;
const ok = (name, cond, detail = '') => { if (!cond) { failed++; console.log('FAIL', name, detail); } else console.log('PASS', name); };
const today = '2026-11-17';
const clone = (x) => JSON.parse(JSON.stringify(x));

// --- calendar mapping: new rows ---
{
  const rows = [{ 'חברה': 'Old Co', 'סימול': 'OLD', 'תאריך': '2026-11-05', 'בפועל_EPS': '1', 'מדד': ['S&P 500'], 'מזהה': 'r-3696' }];
  const cal = eb.parseCsv('symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\nAAA,AAA INC,2026-11-18,2026-09-30,0.34,USD,pre-market\nOLD,OLD CO,2026-11-18,2026-09-30,1.1,USD,post-market\nBBB,"BBB, INC",2026-11-19,2026-10-31,,USD,\nOLD,OLD CO,2027-02-10,2026-12-31,1.3,USD,post-market\nZZZ,ZZZ,2026-11-10,2026-09-30,1,USD,');
  const st = eb.applyCalendar(rows, cal, { today, names: { AAA: 'Triple A Inc.' } });
  const a = rows.find((r) => r['סימול'] === 'AAA'), b = rows.find((r) => r['סימול'] === 'BBB'), o2 = rows.find((r) => r['סימול'] === 'OLD' && r['תאריך'] === '2027-02-10');
  ok('new rows continue the r-NNNN sequence', a['מזהה'] === 'r-3697' && b['מזהה'] === 'r-3698' && o2['מזהה'] === 'r-3699', JSON.stringify(rows.map((r) => r['מזהה'])));
  ok('mapping: name, date, timing, estimate, currency', a['חברה'] === 'Triple A Inc.' && a['תאריך'] === '2026-11-18' && a['מועד'] === 'before' && a['צפי_EPS'] === '0.34' && a['מטבע_EPS'] === 'USD' && a['רבעון_מסתיים'] === '2026-09-30');
  ok('quoted CSV name and missing estimate/timing stay absent', b['חברה'] === 'BBB, INC' && !('צפי_EPS' in b) && !('מועד' in b));
  ok('no index key unless the symbol already had one (ETF fallback stays on)', !('מדד' in a) && JSON.stringify(o2['מדד']) === '["S&P 500"]');
  ok('already-reported quarter is not re-added; next quarter is', st.skippedReported === 1 && rows.filter((r) => r['סימול'] === 'OLD').length === 2);
  ok('past calendar dates are not added', !rows.some((r) => r['סימול'] === 'ZZZ'));
  ok('no note fields on new rows', rows.every((r) => !('הערה' in r) && !('הערה_en' in r)));
}

// --- date move + estimate update ---
{
  const rows = [{ 'חברה': 'Mover', 'סימול': 'MOV', 'תאריך': '2026-11-20', 'מועד': 'after', 'צפי_EPS': '1', 'מקור_צפי_EPS': 'Alpha Vantage EARNINGS_CALENDAR', 'רבעון_מסתיים': '2026-10-31', 'מזהה': 'r-0001', 'הערה': 'הערה של אורי', 'הערה_en': "Ori's note" },
    { 'חברה': 'Manual', 'סימול': 'MAN', 'תאריך': '2026-11-19', 'צפי_EPS': '2', 'מקור_צפי_EPS': 'https://example.invalid', 'מזהה': 'r-0002' }];
  const cal = eb.parseCsv('symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\nMOV,MOVER,2026-11-18,2026-10-31,1.05,USD,pre-market\nMAN,MANUAL,2026-11-19,2026-09-30,2.5,USD,post-market');
  const st = eb.applyCalendar(rows, cal, { today });
  const m = rows[0];
  ok('date move updates תאריך and keeps the original', m['תאריך'] === '2026-11-18' && m['תאריך_מקורי'] === '2026-11-20' && m['שינוי_מועד'] === 'advanced' && st.moved === 1);
  ok('date history records both dates', Array.isArray(m['היסטוריית_מועד']) && m['היסטוריית_מועד'][0].scheduled_date === '2026-11-20' && m['היסטוריית_מועד'][1].date === '2026-11-18');
  ok('timing and AV estimate updated', m['מועד'] === 'before' && m['צפי_EPS'] === '1.05');
  ok('note untouched by calendar', m['הערה'] === 'הערה של אורי' && m['הערה_en'] === "Ori's note");
  ok('manual (non-AV) estimate is not overwritten', rows[1]['צפי_EPS'] === '2' && rows[1]['מועד'] === 'after');
  const again = eb.applyCalendar(rows, cal, { today });
  ok('second identical pull changes nothing', again.moved === 0 && again.estimate === 0 && again.added === 0 && again.timing === 0);
}

{
  const rows = [{ 'חברה': 'Late', 'סימול': 'LAT', 'תאריך': '2026-11-11', 'צפי_EPS': '1', 'מזהה': 'r-0005' }];
  const st = eb.applyCalendar(rows, eb.parseCsv('symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\nLAT,LATE,2026-11-18,2026-09-30,1,USD,'), { today });
  ok('past rows are never moved or duplicated', rows.length === 1 && rows[0]['תאריך'] === '2026-11-11' && st.skippedPast === 1);
}

// --- SEC 8-K Item 2.02 ---
{
  const recent = { form: ['8-K', '10-Q', '8-K', '8-K'], items: ['2.02,9.01', '', '5.07', '2.02,9.01'], acceptanceDateTime: ['2026-11-17T21:20:00.000Z', '2026-11-17T21:30:00.000Z', '2026-11-16T13:00:00.000Z', '2026-08-26T20:20:00.000Z'], accessionNumber: ['0001045810-26-000100', 'x', 'y', 'z'], primaryDocument: ['a.htm', '', '', ''] };
  const hit = eb.find202(recent, '2026-11-17');
  ok('finds the 8-K Item 2.02 around the board date', hit && hit.acc === '0001045810-26-000100' && hit.et.date === '2026-11-17');
  ok('ignores old quarters / other items', eb.find202(recent, '2026-11-25') === null);
  const row = { 'סימול': 'NVDA', 'תאריך': '2026-11-17', 'מזהה': 'r-1' };
  eb.applySec(row, hit, { today, cik: '0001045810', link: 'https://www.sec.gov/Archives/edgar/data/1045810/000104581026000100/ex99.htm' });
  ok('release time in Israel, after close, link', row.release_time_il === '23:20' && row['מועד'] === 'after' && row.release_time_approx === true && row.release_time_basis === 'sec-8k-item-2.02-acceptance' && /ex99\.htm$/.test(row['קישור_לדוח']) && row['אימות_פרסום_SEC'] === hit.acc);
  const early = { 'סימול': 'NVDA', 'תאריך': '2026-11-18', 'מועד': 'before', 'מזהה': 'r-2' };
  eb.applySec(early, hit, { today, cik: '1045810' });
  ok('release a day earlier than scheduled moves the date', early['תאריך'] === '2026-11-17' && early['תאריך_מקורי'] === '2026-11-18' && early['מועד'] === 'after');
  const issuer = { 'סימול': 'X', 'תאריך': '2026-11-17', 'release_time_il': '14:00', 'release_time_basis': 'issuer-confirmed', 'מועד': 'before', 'קישור_לדוח': 'https://issuer.invalid/pr' };
  eb.applySec(issuer, hit, { today, cik: '1' });
  ok('issuer-confirmed time and existing link are kept', issuer.release_time_il === '14:00' && issuer['מועד'] === 'before' && issuer['קישור_לדוח'] === 'https://issuer.invalid/pr');
}

// --- actuals ---
{
  const shard = { cik: '0000000001', cur: 'USD', tags: { r: 'Revenues' }, p: { '2026': { Q3: { f: '10-Q', d: '2026-11-18', e: '2026-09-30', a: '0000000001-26-000001', r: 17103000000 }, Q2: { f: '10-Q', d: '2026-08-01', e: '2026-06-30', a: 'q2', r: 1 } } } };
  const rv = eb.shardRevenue(shard, '2026-11-17');
  ok('shard revenue picks the quarter filed around the release', rv && rv.r === 17103000000 && rv.label === 'Q3 FY2026');
  const noEst = { 'סימול': 'A', 'תאריך': '2026-11-17' };
  ok('no revenue fill without a comparable estimate', eb.applyRevenue(noEst, rv) === false && !('הכנסות_בפועל' in noEst));
  const far = { 'סימול': 'A', 'תאריך': '2026-11-17', 'צפי_הכנסות': '30B' };
  ok('no revenue fill when far from the estimate (component tag)', eb.applyRevenue(far, rv) === false);
  const avRow = { 'סימול': 'A', 'תאריך': '2026-11-17', 'צפי_הכנסות': '16.9B', 'מטבע_צפי_הכנסות': 'USD', 'בסיס_צפי_הכנסות': 'Analyst consensus (Alpha Vantage), total revenue' };
  ok('revenue fill: value, currency, basis, comparable', eb.applyRevenue(avRow, rv) && avRow['הכנסות_בפועל'] === '17.103B' && avRow['מטבע_הכנסות'] === 'USD' && /^GAAP total revenue/.test(avRow['בסיס_בפועל_הכנסות']) && avRow['השוואה_הכנסות'] === 'כן');
  const earn = { quarterlyEarnings: [{ fiscalDateEnding: '2026-09-30', reportedDate: '2026-11-17', reportedEPS: '2.95', estimatedEPS: '2.88' }] };
  const r1 = { 'סימול': 'I', 'תאריך': '2026-11-17', 'צפי_EPS': '2.9', 'מקור_צפי_EPS': 'Alpha Vantage EARNINGS_CALENDAR', 'רבעון_מסתיים': '2026-09-30' };
  eb.applyAvActual(r1, eb.avQuarter(earn, '2026-11-17', '2026-09-30'));
  ok('AV actual aligns the AV estimate and marks comparable', r1['בפועל_EPS'] === '2.95' && r1['צפי_EPS'] === '2.88' && r1['השוואה_EPS'] === 'כן' && r1['השוואה_EPS_en'] === 'Yes');
  const r2 = { 'סימול': 'I', 'תאריך': '2026-11-17', 'צפי_EPS': '2.5', 'מקור_צפי_EPS': 'https://nasdaq.invalid' };
  eb.applyAvActual(r2, eb.avQuarter(earn, '2026-11-17'));
  ok('different-source estimate: no comparison, fixed bilingual reason', r2['השוואה_EPS'] === 'לא' && r2['צפי_EPS'] === '2.5' && r2['הסבר_EPS'] && r2['הסבר_EPS_en']);
  const r3 = { 'סימול': 'I', 'תאריך': '2026-11-17' };
  ok('reportedEPS None is not filled', eb.applyAvActual(r3, { reportedEPS: 'None', reportedDate: '2026-11-17' }) === false && !('בפועל_EPS' in r3));
  const est = { estimates: [{ date: '2026-10-31', horizon: 'fiscal quarter', revenue_estimate_average: '108731903900.00', revenue_estimate_analyst_count: '40' }] };
  const r4 = { 'סימול': 'N', 'תאריך': '2026-11-18' };
  ok('revenue estimate mapped from fiscal quarter', eb.applyRevEstimate(r4, est, '2026-10-31') && r4['צפי_הכנסות'] === '108.732B' && r4['מטבע_צפי_הכנסות'] === 'USD');
}

// --- hash: English stays on after an automatic change, stale stays stale ---
{
  const r = { 'חברה': 'Hash Co', 'סימול': 'HSH', 'תאריך': '2026-11-18', 'מזהה': 'r-9' };
  await eb.sealRow(r, true);
  ok('new row is English-ready', (await CL.readiness('reports', r)).ready);
  r['צפי_EPS'] = '1.2'; ok('a change makes the old hash stale', !(await CL.hashMatches('reports', r)));
  await eb.sealRow(r, true); ok('re-seal restores readiness', (await CL.readiness('reports', r)).ready);
  const stale = { ...clone(r), _translation: { en: { source_hash: 'old', schema_version: 1 } } };
  await eb.sealRow(stale, false); ok('stale translation is not re-certified', stale._translation.en.source_hash === 'old');
  const bil = { ...clone(r), 'השוואה_EPS': 'לא', 'הסבר_EPS': 'הצפי והתוצאה ממקורות שונים; לא חושבה הפתעה.', 'הסבר_EPS_en': 'Estimate and actual come from different sources; no surprise was calculated.', 'בסיס_בפועל_EPS': 'Adjusted EPS, street basis (Alpha Vantage)' };
  await eb.sealRow(bil, true); ok('bilingual explanation pair keeps English ready', (await CL.readiness('reports', bil)).ready);
}

// --- push-news alert filter ---
{
  const now = Date.parse('2026-11-17T12:00:00Z');
  const base = [
    { 'מזהה': 'r-1', 'סימול': 'AAPL', 'תאריך': '2026-11-17', 'צפי_EPS': '1' },
    { 'מזהה': 'r-2', 'סימול': 'MSFT', 'תאריך': '2026-11-25', 'צפי_EPS': '1' },
    { 'מזהה': 'r-3', 'סימול': 'NVDA', 'תאריך': '2026-11-10', 'בפועל_EPS': '1', 'הערה': 'x' },
    { 'מזהה': 'r-4', 'סימול': 'TSLA', 'תאריך': '2026-11-20', 'צפי_EPS': '1' },
    { 'מזהה': 'r-5', 'סימול': 'IBM', 'תאריך': '2026-11-05', 'צפי_הכנסות': '1B' },
  ];
  const next = clone(base);
  next[0]['בפועל_EPS'] = '1.1';                 // new result today -> alert
  next[1]['צפי_EPS'] = '1.05';                  // estimate tweak -> no
  next[2]['הערה'] = 'y';                        // note edit of an old published row -> no
  next[3]['תאריך'] = '2026-11-18';              // moved to tomorrow -> alert (earnings tomorrow)
  next[4]['הכנסות_בפועל'] = '1.01B';            // backfill of an old row -> no (outside detect window)
  next.push({ 'מזהה': 'r-6', 'סימול': 'AMZN', 'תאריך': '2026-12-01', 'צפי_EPS': '1' });   // far-future new row -> no
  next.push({ 'מזהה': 'r-7', 'סימול': 'META', 'תאריך': '2026-11-18', 'צפי_EPS': '1' });   // brand-new calendar row for tomorrow -> no (no flood on first fill)
  const sent = alertReports(base, next, now).map((x) => x['מזהה']);
  ok('only alert-worthy rows are queued', JSON.stringify(sent.sort()) === JSON.stringify(['r-1', 'r-4']), JSON.stringify(sent));
  ok('unchanged board queues nothing', alertReports(base, clone(base), now).length === 0);
  const many = Array.from({ length: 300 }, (_, i) => ({ 'מזהה': 'n-' + i, 'סימול': 'S' + i, 'תאריך': '2026-11-17', 'בפועל_EPS': '1' }));
  ok('flood is capped', alertReports([], many, now).length === 120);
}

if (failed) { console.log(failed + ' failed'); process.exit(1); }
console.log('all earnings-board checks passed');
