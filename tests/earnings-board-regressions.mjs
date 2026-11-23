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
  ok('no estimate: SEC-verified revenue is shown after the release, without beat/miss (Ori 19.11)', eb.applyRevenue(noEst, rv) === true && noEst['הכנסות_בפועל'] === '17.103B' && !('השוואה_הכנסות' in noEst));
  const fnf = { 'סימול': 'FNF', 'תאריך': '2026-11-05' }, mara = { 'סימול': 'MARA', 'תאריך': '2026-11-05' }, xtot = { 'סימול': 'X', 'תאריך': '2026-11-05' };
  ok('no estimate + 10-Q XBRL component tag (FNF escrow fees 603M) -> not shown', eb.applyRevenue(fnf, { r: 603e6, tag: 'RevenueFromContractWithCustomerExcludingAssessedTax', cur: 'USD', label: 'Q3 FY2026' }) === false && !('הכנסות_בפועל' in fnf));
  ok('no estimate + 10-Q XBRL plain Revenues -> shown without beat/miss', eb.applyRevenue(xtot, { r: 2e9, tag: 'Revenues', cur: 'USD', label: 'Q3 FY2026' }) === true && xtot['הכנסות_בפועל'] === '2B' && !('השוואה_הכנסות' in xtot));
  ok('no estimate + press-release figure (prior-year verified), any tag -> shown', eb.applyRevenue(mara, { r: 252e6, pr: true, tag: 'RevenueFromContractWithCustomerExcludingAssessedTax', cur: 'USD', label: 'Q3 FY2026' }) === true && mara['הכנסות_בפועל'] === '252M');
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


// --- live 8-K press release (earnings-live): SEC confirmation + EPS + revenue in one pass ---
{
  const base = () => [
    { 'מזהה': 'r-10', 'חברה': 'Home Depot', 'סימול': 'HD', 'תאריך': '2026-11-17', 'מועד': 'before', 'צפי_EPS': '3.86', 'מטבע_EPS': 'USD', 'בסיס_צפי_EPS': 'Analyst consensus (Alpha Vantage)', 'מקור_צפי_EPS': 'Alpha Vantage EARNINGS_CALENDAR', 'צפי_הכנסות': '42.78B', 'מטבע_צפי_הכנסות': 'USD', 'הערה': 'הערה של אורי', 'הערה_en': "Ori's note" },
    { 'מזהה': 'r-11', 'חברה': 'NVIDIA', 'סימול': 'NVDA', 'תאריך': '2026-11-17', 'מועד': 'after', 'צפי_EPS': '2.49', 'בסיס_צפי_EPS': 'Analyst consensus (Alpha Vantage)', 'צפי_הכנסות': '108.732B', 'מטבע_צפי_הכנסות': 'USD' },
    { 'מזהה': 'r-12', 'חברה': 'Gaap Only', 'סימול': 'GAO', 'תאריך': '2026-11-17', 'צפי_EPS': '0.50', 'צפי_הכנסות': '1B', 'מטבע_צפי_הכנסות': 'USD' },
    { 'מזהה': 'r-13', 'חברה': 'Unclear', 'סימול': 'UNC', 'תאריך': '2026-11-17', 'צפי_EPS': '1.00' },
    { 'מזהה': 'r-14', 'חברה': 'Absurd', 'סימול': 'ABS', 'תאריך': '2026-11-17', 'צפי_EPS': '2.00', 'צפי_הכנסות': '10B', 'מטבע_צפי_הכנסות': 'USD' },
    { 'מזהה': 'r-15', 'חברה': 'Far', 'סימול': 'FAR', 'תאריך': '2026-11-25', 'צפי_EPS': '1.00' },
  ];
  const ciks = { HD: '0000354950', NVDA: '0001045810', GAO: '0000000001', UNC: '0000000002', ABS: '0000000003', FAR: '0000000004' };
  const feed = { filings: [
    { cik: '0000354950', acc: '0000354950-26-000184', form: '8-K', accepted: '2026-11-17T06:18:03-05:00', url: 'https://www.sec.gov/Archives/edgar/data/354950/000035495026000184/hd_exhibit991x11012026.htm', r: 43398000000, eps: 3.72, adj_eps: 3.86, non_gaap: true, slot: 'Q3 FY2026', tag: 'RevenueFromContractWithCustomerExcludingAssessedTax', cur: 'USD' },
    { cik: '0001045810', acc: '0001045810-26-000088', form: '8-K', accepted: '2026-11-17T16:20:51-05:00', url: 'https://www.sec.gov/x/q3fy27pr.htm', r: 115844000000, eps: 2.7, adj_eps: null, non_gaap: true, slot: 'Q3 FY2027', tag: 'Revenues', cur: 'USD' },
    { cik: '0000000001', acc: '0000000001-26-000001', form: '8-K', accepted: '2026-11-17T07:00:00-05:00', r: 1.3e9, eps: 0.55, adj_eps: null, non_gaap: false, slot: 'Q3 FY2026', tag: 'Revenues', cur: 'USD' },
    { cik: '0000000002', acc: '0000000002-26-000001', form: '8-K', accepted: '2026-11-17T07:00:00-05:00', eps: 0.8, adj_eps: null, non_gaap: true },
    { cik: '0000000003', acc: '0000000003-26-000001', form: '8-K', accepted: '2026-11-17T07:00:00-05:00', r: 10.2e9, eps: -7.5, adj_eps: null, non_gaap: false, tag: 'Revenues', cur: 'USD' },
    { cik: '0000000004', acc: '0000000004-26-000001', form: '8-K', accepted: '2026-11-17T07:00:00-05:00', eps: 1.0, non_gaap: false },
  ] };
  const rows = base(); const st = eb.applyLive(rows, feed, { today, cikOf: (s) => ciks[s] });
  const [hd, nv, gao, unc, abs, far] = rows;
  ok('live: SEC confirmation, release time and press-release link', hd['אימות_פרסום_SEC'] === '0000354950-26-000184' && hd.release_time_il === '13:18' && /hd_exhibit991/.test(hd['קישור_לדוח']) && hd['מועד'] === 'before', JSON.stringify(hd));
  ok('live: company-labelled adjusted EPS fills the board against the analyst consensus', hd['בפועל_EPS'] === '3.86' && /Non-GAAP \(adjusted\)/.test(hd['בסיס_בפועל_EPS']) && /hd_exhibit991/.test(hd['מקור_בפועל_EPS']));
  ok('live: revenue within 15% of the estimate is filled', hd['הכנסות_בפועל'] === '43.398B' && /8-K press release/.test(hd['בסיס_בפועל_הכנסות']));
  ok('live: note fields untouched', hd['הערה'] === 'הערה של אורי' && hd['הערה_en'] === "Ori's note");
  ok('live: non-GAAP company without a clearly labelled adjusted EPS -> EPS left blank (never GAAP as a guess)', !('בפועל_EPS' in nv) && nv['הכנסות_בפועל'] === '115.844B');
  ok('live: GAAP diluted EPS when the company reports no non-GAAP EPS', gao['בפועל_EPS'] === '0.55' && /^GAAP diluted EPS/.test(gao['בסיס_בפועל_EPS']));
  ok('live: revenue 30% off the estimate is not filled', !('הכנסות_בפועל' in gao));
  ok('live: unclear basis -> blank', !('בפועל_EPS' in unc));
  ok('live: EPS far from the estimate (sign flip, >3x) is shown anyway (no 100% guard, Ori 19.11); revenue still checked', abs['בפועל_EPS'] === '-7.5' && abs['הכנסות_בפועל'] === '10.2B');
  ok('live: rows outside ±1 day of the filing are not touched', !('אימות_פרסום_SEC' in far) && !('בפועל_EPS' in far));
  ok('live: stats', st.secApplied === 5 && st.epsFilled === 3 && st.revFilled === 3, JSON.stringify(st));
  const again = clone(rows); eb.applyLive(again, feed, { today, cikOf: (s) => ciks[s] });
  ok('live: second pass is a no-op (no churn, no repeat alert)', JSON.stringify(again) === JSON.stringify(rows));
  ok('live: a new actual raises one alert', alertReports(base(), rows, Date.parse('2026-11-17T22:00:00Z')).some((x) => x['מזהה'] === 'r-10'));
  ok('live: press-release EPS is comparable with the consensus (beat/miss % shown)', hd['השוואה_EPS'] === 'כן' && !('הסבר_EPS' in hd));
  ok('live: revenue within 15% is comparable (beat/miss % shown)', hd['השוואה_הכנסות'] === 'כן');
  // EPS sanity guard
  ok('eps: any distance from the estimate accepted', eb.epsPlausible(0.4) && eb.epsPlausible(1.9) && eb.epsPlausible(-3) && eb.epsPlausible(12) && eb.epsPlausible(-0.5));
  ok('eps: non-numbers / per-share figures >= 1000 rejected', !eb.epsPlausible(1500) && !eb.epsPlausible(NaN));
  // the AV street figure may later replace the press-release EPS (same provider as the estimate -> comparable)
  const z = { fiscalDateEnding: '2026-10-31', reportedDate: '2026-11-17', reportedEPS: '3.86', estimatedEPS: '3.86' };
  const hd2 = clone(hd); ok('AV street actual replaces the press-release EPS and enables the comparison', eb.applyAvActual(hd2, z) && hd2['השוואה_EPS'] === 'כן' && /Alpha Vantage/.test(hd2['בסיס_בפועל_EPS']) && !('הסבר_EPS' in hd2));
  const man = { 'בפועל_EPS': '1.00', 'בסיס_בפועל_EPS': 'manual' }; ok('a manual EPS is never replaced', !eb.applyAvActual(man, z) && man['בפועל_EPS'] === '1.00');
  // a filing already on the row (hourly job confirmed it) still gets its figures
  const r2 = base()[0]; r2['אימות_פרסום_SEC'] = '0000354950-26-000184'; eb.applyLive([r2], feed, { today, cikOf: (s) => ciks[s] });
  ok('live: figures fill a row the hourly job already confirmed', r2['בפועל_EPS'] === '3.86');
  const r3 = base()[0]; r3['אימות_פרסום_SEC'] = '0000354950-26-000999'; eb.applyLive([r3], feed, { today, cikOf: (s) => ciks[s] });
  ok('live: a row confirmed with a different filing is not filled from this one', !('בפועל_EPS' in r3));
}


// --- earnings-live window: US trading days 10:00 -> 02:00 Israel time (fixed in Israel time) ---
{
  const { inWindow } = require('../scripts/earnings-live-window.cjs');
  const il = (s) => new Date(s);   // ISO with Israel offset
  ok('window: Wed 08:37 IL is outside', !inWindow(il('2026-11-18T08:37:00+02:00')));
  ok('window: Wed 10:00 IL opens', inWindow(il('2026-11-18T10:00:00+02:00')) && !inWindow(il('2026-11-18T09:59:00+02:00')));
  ok('window: Wed 23:30 and Thu 01:59 IL are inside', inWindow(il('2026-11-18T23:30:00+02:00')) && inWindow(il('2026-11-19T01:59:00+02:00')));
  ok('window: closes at 02:00 IL', !inWindow(il('2026-11-19T02:00:00+02:00')) && !inWindow(il('2026-11-19T05:00:00+02:00')));
  ok('window: Friday night runs until Sat 02:00, Saturday/Sunday daytime off', inWindow(il('2026-11-21T01:30:00+02:00')) && !inWindow(il('2026-11-21T12:00:00+02:00')) && !inWindow(il('2026-11-22T12:00:00+02:00')));
  ok('window: Monday after midnight (Sunday window) is off', !inWindow(il('2026-11-23T01:00:00+02:00')) && inWindow(il('2026-11-23T10:30:00+02:00')));
  ok('window: NYSE holiday (Thanksgiving) skipped, incl. its night', !inWindow(il('2026-11-26T15:00:00+02:00')) && !inWindow(il('2026-11-27T01:00:00+02:00')) && inWindow(il('2026-11-27T10:00:00+02:00')));
  ok('window: Israel summer time handled (10:00 IDT)', inWindow(il('2027-06-02T10:05:00+03:00')) && !inWindow(il('2027-06-02T09:55:00+03:00')) && !inWindow(il('2027-06-03T02:05:00+03:00')));
}


// --- Form 6-K (foreign issuers): confirmation + link + same-day time only, never numbers, never a date move ---
{
  const mk = () => [
    { 'מזהה': 'r-20', 'סימול': 'PONY', 'תאריך': '2026-11-18', 'מועד': 'before', 'הערה': 'n' },
    { 'מזהה': 'r-21', 'סימול': 'HAFN', 'תאריך': '2026-11-18', 'מועד': 'before', 'צפי_EPS': '0.20' },
  ];
  const ciks = { PONY: '0001969302', HAFN: '0001815779' };
  const feed = { filings: [
    { cik: '0001969302', acc: '0001104659-26-200001', form: '6-K', results: true, accepted: '2026-11-18T05:31:00-05:00', url: 'https://www.sec.gov/Archives/edgar/data/1969302/x/ex99-1.htm', eps: 9, r: 1e9 },
    { cik: '0001815779', acc: '0001140361-26-200002', form: '6-K', results: false, accepted: '2026-11-18T06:00:00-05:00' },
    { cik: '0001815779', acc: '0001140361-26-200003', form: '6-K', results: true, accepted: '2026-11-19T07:00:00-05:00', url: 'https://www.sec.gov/y.htm' },
  ] };
  const rows = mk(); eb.applyLive(rows, feed, { today: '2026-11-18', cikOf: (s) => ciks[s] });
  const [pony, hafn] = rows;
  ok('6-K results release: confirmation, link and same-day time', pony['אימות_פרסום_SEC'] === '0001104659-26-200001' && /ex99-1/.test(pony['קישור_לדוח']) && pony.release_time_il === '12:31' && pony.release_time_basis === 'sec-6k-acceptance');
  ok('6-K: no numbers from the release, note untouched', !('בפועל_EPS' in pony) && !('הכנסות_בפועל' in pony) && pony['הערה'] === 'n');
  ok('6-K that is not a results release is ignored; a next-day 6-K confirms without moving the date or time', hafn['אימות_פרסום_SEC'] === '0001140361-26-200003' && hafn['תאריך'] === '2026-11-18' && !('release_time_il' in hafn) && !('בפועל_EPS' in hafn));
}


// --- DIS: verified press-release total revenue without a revenue estimate; adjusted EPS "excluding certain items" ---
{
  const dis = { 'מזהה': 'r-3702', 'סימול': 'DIS', 'תאריך': '2026-11-17', 'מועד': 'before', 'צפי_EPS': '1.67', 'בסיס_צפי_EPS': 'Analyst consensus (Alpha Vantage)', 'אימות_פרסום_SEC': '0001744489-26-000065', 'הערה': 'x' };
  const f = { cik: '0001744489', acc: '0001744489-26-000065', form: '8-K', accepted: '2026-11-17T06:30:00-05:00', url: 'https://www.sec.gov/z.htm', r: 25947e6, eps: 1.51, adj_eps: 1.77, non_gaap: true, tag: 'Revenues', cur: 'USD', slot: 'Q4 FY2026' };
  const rows = [dis]; eb.applyLive(rows, { filings: [f] }, { today: '2026-11-18', cikOf: () => '0001744489' });
  ok('DIS: EPS 1.77 and revenue 25.947B filled, note untouched', dis['בפועל_EPS'] === '1.77' && dis['הכנסות_בפועל'] === '25.947B' && dis['הערה'] === 'x', JSON.stringify(dis));
  const bank = { 'סימול': 'BNK', 'תאריך': '2026-11-17', 'אימות_פרסום_SEC': 'a-1' };
  eb.applyLive([bank], { filings: [{ cik: '1', acc: 'a-1', form: '8-K', accepted: '2026-11-17T07:00:00-05:00', r: 5e9, tag: 'RevenuesNetOfInterestExpense' }] }, { today: '2026-11-18', cikOf: () => '1' });
  ok('no estimate + non-total revenue tag -> verified revenue shown without beat/miss (Ori 19.11)', bank['הכנסות_בפועל'] === '5B' && !('השוואה_הכנסות' in bank), JSON.stringify(bank));
}

// --- 18.11.2026 before-open reporters (real filings): EPS no longer depends on the revenue check; revenue verified through
//     net income only (r_nv) needs an estimate within 15%; 6-K results releases never carry numbers ---
{
  const T = '2026-11-18';
  const tjx = { 'סימול': 'TJX', 'תאריך': T, 'מועד': 'before', 'צפי_EPS': '1.33', 'צפי_הכנסות': '15.855B', 'הערה': 'keep' };
  const brbr = { 'סימול': 'BRBR', 'תאריך': T, 'מועד': 'before', 'צפי_EPS': '0.21' };
  const jjsf = { 'סימול': 'JJSF', 'תאריך': T, 'מועד': 'before', 'צפי_EPS': '1.21' };
  const tgt = { 'סימול': 'TGT', 'תאריך': T, 'מועד': 'before', 'צפי_EPS': '2.04' };
  const low = { 'סימול': 'LOW', 'תאריך': T, 'מועד': 'before', 'צפי_EPS': '2.86', 'צפי_הכנסות': '22.36B' };
  const iccm = { 'סימול': 'ICCM', 'תאריך': T, 'מועד': 'before', 'צפי_EPS': '-0.83', 'הערה_en': 'mine' };
  const kndi = { 'סימול': 'KNDI', 'תאריך': T, 'מועד': 'before' };
  const ciks = { TJX: '0000109198', BRBR: '0001772016', JJSF: '0000785956', TGT: '0000027419', LOW: '0000060667', ICCM: '0001584371', KNDI: '0001720250' };
  const u = 'https://www.sec.gov/Archives/edgar/data/1/x/ex99.htm';
  const feed = { filings: [
    { cik: ciks.TJX, acc: '0000109198-26-000058', form: '8-K', accepted: '2026-11-18T09:19:28-05:00', url: u, r: 15952e6, eps: 1.39, adj_eps: 1.34, non_gaap: true, r_nv: true, tag: 'SalesRevenueNet', cur: 'USD', slot: 'Q3 FY2027' },
    { cik: ciks.BRBR, acc: '0001628280-26-074645', form: '8-K', accepted: '2026-11-18T07:01:41-05:00', url: u, r: 692e6, eps: 0.31, adj_eps: 0.22, non_gaap: true, r_nv: true, tag: 'Revenues', cur: 'USD', slot: 'Q4 FY2026' },
    { cik: ciks.JJSF, acc: '0001437749-26-037473', form: '8-K', accepted: '2026-11-18T07:02:00-05:00', url: u, e: '2026-09-26', adj_eps: 1.39, non_gaap: true, eps_only: true, cur: 'USD' },
    { cik: ciks.TGT, acc: '0000027419-26-000051', form: '8-K', accepted: '2026-11-18T06:46:59-05:00', url: u, r: 27067e6, eps: 2.65, adj_eps: 2.65, non_gaap: true, r_nv: false, tag: 'RevenueFromContractWithCustomerExcludingAssessedTax', cur: 'USD', slot: 'Q3 FY2026' },
    { cik: ciks.LOW, acc: '0000060667-26-000126', form: '8-K', accepted: '2026-11-18T08:45:11-05:00', url: u, r: 22756e6, eps: 2.98, adj_eps: 3.1, non_gaap: true, r_nv: false, tag: 'RevenueFromContractWithCustomerExcludingAssessedTax', cur: 'USD', slot: 'Q3 FY2026' },
    { cik: ciks.ICCM, acc: '0001213900-26-121630', form: '6-K', results: true, accepted: '2026-11-18T08:45:01-05:00', url: u },
    { cik: ciks.KNDI, acc: '0001213900-26-121585', form: '6-K', results: true, accepted: '2026-11-18T07:00:01-05:00', url: 'https://www.sec.gov/Archives/edgar/data/1720250/x/ea0312570-6k_kandi.htm' },
  ] };
  const rows = [tjx, brbr, jjsf, tgt, low, iccm, kndi];
  const st = eb.applyLive(rows, feed, { today: T, cikOf: (s) => ciks[s] });
  ok('TJX: adjusted EPS 1.34 + revenue 15.952B (net-income verified, within 15% of 15.855B) with beat/miss, note untouched',
    tjx['בפועל_EPS'] === '1.34' && tjx['השוואה_EPS'] === 'כן' && tjx['הכנסות_בפועל'] === '15.952B' && tjx['השוואה_הכנסות'] === 'כן' && /net income verified/.test(tjx['בסיס_בפועל_הכנסות']) && tjx['הערה'] === 'keep', JSON.stringify(tjx));
  ok('BRBR: EPS 0.22; net-income-verified revenue 692M shown without an estimate (no beat/miss)', brbr['בפועל_EPS'] === '0.22' && brbr['הכנסות_בפועל'] === '692M' && !('השוואה_הכנסות' in brbr), JSON.stringify(brbr));
  ok('JJSF: EPS-only record (GAAP check failed) fills adjusted EPS 1.39 with beat/miss, no revenue', jjsf['בפועל_EPS'] === '1.39' && jjsf['השוואה_EPS'] === 'כן' && !('הכנסות_בפועל' in jjsf), JSON.stringify(jjsf));
  ok('TGT: EPS 2.65 and revenue 27.067B without an estimate (no beat/miss)', tgt['בפועל_EPS'] === '2.65' && tgt['הכנסות_בפועל'] === '27.067B' && !('השוואה_הכנסות' in tgt), JSON.stringify(tgt));
  ok('LOW: EPS 3.1 and revenue 22.756B (not the 100% column) with beat/miss', low['בפועל_EPS'] === '3.1' && low['הכנסות_בפועל'] === '22.756B' && low['השוואה_הכנסות'] === 'כן', JSON.stringify(low));
  ok('ICCM / KNDI 6-K: confirmation, link and time only, never numbers; note untouched',
    iccm['אימות_פרסום_SEC'] === '0001213900-26-121630' && kndi['אימות_פרסום_SEC'] === '0001213900-26-121585' && /kandi/.test(kndi['קישור_לדוח']) && kndi.release_time_il === '14:00'
    && !('בפועל_EPS' in iccm) && !('בפועל_EPS' in kndi) && !('הכנסות_בפועל' in kndi) && iccm['הערה_en'] === 'mine' && !('הערה' in kndi), JSON.stringify([iccm, kndi]));
  ok('stats: 7 confirmations, 5 EPS, 4 revenue', st.secApplied === 7 && st.epsFilled === 5 && st.revFilled === 4, JSON.stringify(st));
  const wild = { 'סימול': 'JJSF', 'תאריך': T, 'צפי_EPS': '1.21' };
  eb.applyLive([wild], { filings: [{ ...feed.filings[2], adj_eps: 4.9 }] }, { today: T, cikOf: () => ciks.JJSF });
  ok('EPS-only record far from the estimate is shown (4.9 vs 1.21, no 100% guard)', wild['בפועל_EPS'] === '4.9' && wild['השוואה_EPS'] === 'כן');
  const far = { 'סימול': 'TJX', 'תאריך': T, 'צפי_EPS': '1.33', 'צפי_הכנסות': '12B' };
  eb.applyLive([far], { filings: [feed.filings[0]] }, { today: T, cikOf: () => ciks.TJX });
  ok('net-income-verified revenue 33% off the estimate is rejected', !('הכנסות_בפועל' in far) && far['בפועל_EPS'] === '1.34');
}

// --- card source label: analysts vs company, for EPS and revenue (v329) ---
{
  const fs = require('fs');
  const path = require('path');
  const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  const en = fs.readFileSync(path.join(root, 'i18n-en.js'), 'utf8');
  const sw = fs.readFileSync(path.join(root, 'sw.js'), 'utf8');
  const m = html.match(/const srcOf = b0=>\{[\s\S]*?return ''; \};/);
  ok('srcOf is defined on the earnings card', !!m);
  const srcOf = new Function('I18n', m[0] + '; return srcOf;')({ p: (_id, d) => d });
  ok('analyst consensus -> אנליסטים', srcOf('Analyst consensus (Alpha Vantage)') === 'אנליסטים');
  ok('AV revenue consensus -> אנליסטים', srcOf('Analyst consensus (Alpha Vantage), total revenue') === 'אנליסטים');
  ok('company guidance range -> חברה', srcOf('Company guidance, Q3 2026 revenue range') === 'חברה');
  ok('dated company guidance EPS -> חברה', srcOf('Company guidance, Q3 2026 Non-GAAP diluted EPS range') === 'חברה');
  ok('unknown or accounting-only basis has no source label', srcOf('') === '' && srcOf('מתואם') === '' && srcOf('FFO') === '' && srcOf('GAAP') === '' && srcOf('לא ידוע') === '');
  ok('analyst text that mentions not company guidance stays analysts', srcOf('Analyst consensus from dated preview; not company guidance') === 'אנליסטים');
  ok('explicit not-guidance without analyst has no label', srcOf('third party estimate, not company guidance') === '');
  ok('estimate line appends mid-dot source; estimate-only uses a small tag; beat/miss % stays after the estimate',
    html.includes('const srcS = src ? ` · ${esc(src)}` : \'\';')
    && html.includes('${eb(est)}${srcS}</small>${tg}${cm.ok')
    && html.includes('srcOf(r.epsEstB)') && html.includes('srcOf(r.revEstB)')
    && html.includes('<small class="rb">${esc(src)}</small>')
    && html.includes('sp(x, ap)') && html.includes('rngB(rr, est, act)'));
  ok('English i18n labels are Analysts and Company', en.includes('"ui-1334":"Analysts"') && en.includes('"ui-1335":"Company"'));
  ok('sw cache bumped to v330 or later', +((sw.match(/const CACHE = 'portfolio-shell-v(\d+)'/)||[])[1]||0) >= 330);
}

// --- 19.11.2026 gaps (Nov 18 after-close): no 100% EPS guard, actuals without estimates, EPS wording ---
{
  const T = '2026-11-18';
  const mk = (sym, extra) => Object.assign({ 'סימול': sym, 'תאריך': T, 'מועד': 'after' }, extra);
  const panw = mk('PANW', { 'צפי_EPS': '0.52', 'צפי_הכנסות': '3.308B', 'הערה': 'n' });
  const wwd = mk('WWD', { 'צפי_EPS': '2.5' });
  const uti = mk('UTI', { 'צפי_EPS': '0.33' });
  const snex = mk('SNEX', { 'צפי_EPS': '0.86' });
  const noest = mk('NOE', {});
  const ciks = { PANW: '0001327567', WWD: '0000108312', UTI: '0001261654', SNEX: '0000913760', NOE: '0000000099' };
  const u = 'https://www.sec.gov/Archives/edgar/data/1/x/ex99.htm';
  const tg = 'RevenueFromContractWithCustomerExcludingAssessedTax';
  const feed = { filings: [
    { cik: ciks.PANW, acc: '0001327567-26-000030', form: '8-K', accepted: '2026-11-18T16:37:00-05:00', url: u, r: 3445e6, eps: 0.57, adj_eps: 1.05, non_gaap: true, r_nv: false, tag: tg, cur: 'USD', slot: 'Q1 FY2027' },
    { cik: ciks.WWD, acc: '0001171843-26-007561', form: '8-K', accepted: '2026-11-18T16:00:00-05:00', url: u, r: 1160198000, eps: 2.74, adj_eps: 2.83, non_gaap: true, r_nv: false, tag: tg, cur: 'USD', slot: 'Q4 FY2026' },
    { cik: ciks.UTI, acc: '0001261654-26-000021', form: '8-K', accepted: '2026-11-18T16:07:00-05:00', url: u, r: 235883000, eps: 0.32, adj_eps: null, non_gaap: false, r_nv: false, tag: tg, cur: 'USD', slot: 'Q4 FY2026' },
    { cik: ciks.SNEX, acc: '0000913760-26-000044', form: '8-K', accepted: '2026-11-18T16:25:00-05:00', url: u, r: 37459500000, eps: null, adj_eps: null, non_gaap: true, r_nv: true, tag: tg, cur: 'USD', slot: 'Q4 FY2026' },
    { cik: ciks.NOE, acc: '0000000099-26-000001', form: '8-K', accepted: '2026-11-18T16:05:00-05:00', url: u, r: 50e6, eps: -0.12, adj_eps: null, non_gaap: false, r_nv: false, tag: 'Revenues', cur: 'USD', slot: 'Q3 FY2026' },
  ] };
  const rows = [panw, wwd, uti, snex, noest];
  eb.applyLive(rows, feed, { today: T, cikOf: (s) => ciks[s] });
  ok('PANW: adjusted EPS 1.05 vs 0.52 shown with beat/miss (102% off, no guard); revenue 3.445B within 15%; note untouched',
    panw['בפועל_EPS'] === '1.05' && panw['השוואה_EPS'] === 'כן' && panw['הכנסות_בפועל'] === '3.445B' && panw['השוואה_הכנסות'] === 'כן' && panw['הערה'] === 'n', JSON.stringify(panw));
  ok('WWD: adjusted EPS 2.83 (summary-table layout) + revenue 1.16B without an estimate', wwd['בפועל_EPS'] === '2.83' && wwd['הכנסות_בפועל'] === '1.16B' && !('השוואה_הכנסות' in wwd), JSON.stringify(wwd));
  ok('UTI: no non-GAAP EPS (only adjusted EBITDA) -> verified GAAP EPS 0.32 vs 0.33 + revenue 235.883M', uti['בפועל_EPS'] === '0.32' && /^GAAP diluted EPS/.test(uti['בסיס_בפועל_EPS']) && uti['השוואה_EPS'] === 'כן' && uti['הכנסות_בפועל'] === '235.883M', JSON.stringify(uti));
  ok('SNEX: no EPS in the release -> EPS blank; net-income-verified revenue shown', !('בפועל_EPS' in snex) && snex['הכנסות_בפועל'] === '37.459B', JSON.stringify(snex));
  ok('no estimates at all: actual EPS and revenue shown, no beat/miss', noest['בפועל_EPS'] === '-0.12' && noest['הכנסות_בפועל'] === '50M' && !('השוואה_EPS' in noest) && !('השוואה_הכנסות' in noest), JSON.stringify(noest));
  const again = clone(rows); eb.applyLive(again, feed, { today: T, cikOf: (s) => ciks[s] });
  ok('second pass is a no-op', JSON.stringify(again) === JSON.stringify(rows));
  // a revenue estimate arriving later turns on the beat/miss for a revenue shown without one
  const tgt = mk('TGT', { 'צפי_EPS': '2.04' });
  eb.applyLive([tgt], { filings: [{ cik: '0000027419', acc: 'a-27419', form: '8-K', accepted: '2026-11-18T06:46:59-05:00', url: u, r: 27067e6, eps: 2.65, adj_eps: 2.65, non_gaap: true, tag: tg, cur: 'USD', slot: 'Q3 FY2026' }] }, { today: T, cikOf: () => '0000027419' });
  ok('TGT revenue shown first without an estimate', tgt['הכנסות_בפועל'] === '27.067B' && !('השוואה_הכנסות' in tgt));
  tgt['רבעון_מסתיים'] = '2026-10-31';
  const est = { estimates: [{ horizon: 'fiscal quarter', date: '2026-10-31', revenue_estimate_average: '26800000000', revenue_estimate_analyst_count: '25' }] };
  ok('a later revenue estimate is accepted for a reported row', eb.applyRevEstimate(tgt, est, '2026-10-31') && tgt['צפי_הכנסות'] === '26.8B');
}

// --- Alpha Vantage at 14:00 / 02:00 Israel (Ori 19.11.2026): slots, backup crons, shared New York-day quota ---
{
  const { check } = require('../scripts/av-slot.cjs');
  const { execFileSync } = require('child_process');
  const c = (cron, iso) => check(cron, new Date(iso)).ok;
  ok('winter crons: 12:00 UTC = 14:00 Israel, 00:00 UTC = 02:00 Israel', c('0 12 * * *', '2026-11-19T12:03:00Z') && c('0 0 * * *', '2026-11-20T00:05:00Z'));
  ok('winter: the summer crons (13:00 / 01:00 Israel) skip Alpha Vantage', !c('0 11 * * *', '2026-11-19T11:02:00Z') && !c('0 23 * * *', '2026-11-19T23:01:00Z'));
  ok('summer crons: 11:00 UTC = 14:00 Israel, 23:00 UTC = 02:00 Israel; winter ones skip', c('0 11 * * *', '2026-07-01T11:04:00Z') && c('0 23 * * *', '2026-07-02T00:20:00Z') && !c('0 12 * * *', '2026-07-01T12:04:00Z') && !c('0 0 * * *', '2026-07-02T00:20:00Z'));
  ok('a scheduled run more than 90 minutes late skips Alpha Vantage', !c('0 12 * * *', '2026-11-19T14:00:00Z') && !c('0 0 * * *', '2026-11-20T03:00:00Z') && c('0 12 * * *', '2026-11-19T13:30:00Z'));
  const slot = (h) => { try { return execFileSync('bash', ['-c', 'eval "$(grep "^av_slot()" scripts/earnings-live.sh)"; av_slot ' + h], { encoding: 'utf8' }).trim(); } catch (e) { return ''; } };
  ok('earnings-live dispatches only in the 14:00 and 02:00 Israel hours', slot(14) === '14' && slot(2) === '02' && ['7', '19', '13', '15', '1', '3', '0'].every((h) => slot(h) === ''));
  // 14:00 Israel = 07:00 ET (winter), 02:00 Israel = 19:00 ET of the same New York date: one counter, 12 + 12 <= 25
  ok('the 14:00 Israel run (morning ET) keeps 12 calls for the 02:00 run; the 02:00 run (evening ET) keeps none',
    eb.avReserve('2026-11-19T12:00:00Z') === 12 && eb.avReserve('2026-11-20T00:00:00Z') === 0 && eb.avReserve('2026-07-01T11:00:00Z') === 12 && eb.avReserve('2026-07-01T23:00:00Z') === 0);
  const day = (used, reserve) => eb.avClient('k', { avCalls: { '2026-11-19': used } }, '2026-11-19', reserve).left();
  ok('quota: fresh New York day -> 12 at 14:00 and 12 at 02:00', day(0, 12) === 12 && day(12, 0) === 12 && day(13, 0) === 12 && day(24, 0) === 1);
  ok('quota: a morning run after 11 calls already used gets only 2 (the evening run keeps its 12)', day(11, 12) === 2 && day(14, 12) === 0);
  ok('quota: the counter is per New York date', eb.avClient('k', { avCalls: { '2026-11-18': 25 } }, '2026-11-19', 0).left() === 12);
}


// --- issuer pre-announcements + investor call time (never used as the release clock) ---
{
  const tcom = 'Trip.com Group Limited today announced that it will announce its unaudited financial results for the quarter ended September 30, 2026, on Tuesday, December 1, 2026, U.S. Time, after the market closes. The Company will hold a conference call at 7:00 PM U.S. Eastern Time on December 1, 2026 (or 8:00 AM Hong Kong Time on December 2, 2026) following the announcement. In Hong Kong, the Company will announce the results on Wednesday, December 2, 2026, before the Hong Kong market opens.';
  const p = eb.parseEarningsPreannounce(tcom);
  ok('TCOM pre-announce: US date 1 Dec, after the close, no release clock, call 02:00 Israel',
    p && p.date === '2026-12-01' && p.session === 'after' && !p.releaseTimeIl && p.callTimeIl === '02:00', JSON.stringify(p));
  const row = { 'סימול': 'TCOM', 'תאריך': '2026-11-23', 'הערה': 'keep-me', 'הערה_en': 'keep-en', 'מזהה': 'r-1' };
  ok('TCOM date is corrected and the note is left alone',
    eb.applyPreannounce(row, p, { today: '2026-11-23', source: 'https://www.sec.gov/Archives/edgar/data/1269238/000119312526467690/d77175dex992.htm' })
    && row['תאריך'] === '2026-12-01' && row['תאריך_מקורי'] === '2026-11-23' && row['מועד'] === 'after'
    && !row.release_time_il && row.call_time_il === '02:00' && row.release_time_basis !== 'issuer-scheduled'
    && row.call_time_basis === 'issuer-scheduled' && row['הערה'] === 'keep-me' && row['הערה_en'] === 'keep-en');

  const exactTxt = 'Acme Corp will release its third quarter fiscal 2026 financial results in a press release at 4:05 p.m. Eastern Time on Tuesday, November 24, 2026. The company will host a conference call at 5:00 p.m. Eastern Time on the same day.';
  const ex = eb.parseEarningsPreannounce(exactTxt);
  ok('exact press-release clock is 23:05 Israel; call is 00:00 and is not used as the release time',
    ex && ex.date === '2026-11-24' && ex.session === 'after' && ex.releaseTimeIl === '23:05' && ex.callTimeIl === '00:00', JSON.stringify(ex));
  const acme = { 'סימול': 'ACME', 'תאריך': '2026-11-24', 'הערה': 'n' };
  eb.applyPreannounce(acme, ex, { today: '2026-11-23', source: 'https://www.sec.gov/ex99.htm' });
  ok('exact clock stored as issuer-scheduled, call stored separately, note untouched',
    acme.release_time_il === '23:05' && acme.release_time_basis === 'issuer-scheduled' && acme.release_time_approx === false
    && acme.call_time_il === '00:00' && acme['הערה'] === 'n' && acme['מועד'] === 'after');

  const onlyCall = 'Beta Inc announced the date of its fourth quarter and fiscal year 2026 earnings release. The company will report financial results after the market closes on Thursday, December 3, 2026, and will host a conference call at 8:30 a.m. Eastern Time on Friday, December 4, 2026.';
  const oc = eb.parseEarningsPreannounce(onlyCall);
  ok('call time is not promoted to a release clock when the filing only gives a call time',
    oc && oc.date === '2026-12-03' && oc.session === 'after' && !oc.releaseTimeIl && oc.callTimeIl === '15:30', JSON.stringify(oc));

  const divi = 'On November 4, 2026, the Board of Directors of Hewlett Packard Enterprise Company approved declaring a cash dividend of $0.1425 per share on the company\'s common stock. The dividend will be paid on January 2, 2027.';
  ok('a non-earnings 7.01 (dividend) is ignored', eb.parseEarningsPreannounce(divi) === null);

  const resultsPr = 'For immediate release. Gamma Inc reports third quarter 2026 financial results. Revenue was $1.2 billion. The company will host a conference call at 8:00 a.m. Eastern Time today, November 20, 2026.';
  ok('a results press release is not treated as a pre-announcement', eb.parseEarningsPreannounce(resultsPr) === null);
  ok('but the same 2.02 / 6-K release can still yield an investor-call clock', eb.parseCallTimeFromRelease(resultsPr, '2026-11-20') === '15:00');

  const trap = 'Delta Co will host a conference call to discuss its third quarter 2026 financial results at 4:30 p.m. Eastern Time on Wednesday, November 25, 2026. The press release will be issued at the start of the call.';
  const tr = eb.parseEarningsPreannounce(trap);
  ok('a call time is never stored as the release clock, even if the release is "at the start of the call"',
    tr && tr.callTimeIl === '23:30' && !tr.releaseTimeIl, JSON.stringify(tr));

  // 2.02 acceptance replaces an issuer-scheduled clock, keeps the call and issuer-confirmed protection
  const sched = { 'סימול': 'ACME', 'תאריך': '2026-11-24', 'release_time_il': '23:05', 'release_time_basis': 'issuer-scheduled', 'מועד': 'after', 'call_time_il': '00:00', 'הערה': 'n', 'מזהה': 'r-2' };
  const hit = { acc: '0000000000-26-000001', iso: '2026-11-24T16:12:00-05:00', et: { date: '2026-11-24', min: 16 * 60 + 12 }, dd: 0, form: '8-K' };
  // etParts would normally build this; applySec uses hit.et and ilClock(hit.iso)
  eb.applySec(sched, hit, { today: '2026-11-24', cik: '1', link: 'https://www.sec.gov/ex99.htm' });
  ok('2.02 acceptance replaces an issuer-scheduled clock and keeps the call and the note',
    sched.release_time_basis === 'sec-8k-item-2.02-acceptance' && sched.release_time_il !== '23:05'
    && sched.call_time_il === '00:00' && sched['הערה'] === 'n', JSON.stringify({ t: sched.release_time_il, b: sched.release_time_basis, c: sched.call_time_il }));

  const confirmed = { 'סימול': 'X', 'תאריך': '2026-11-24', 'release_time_il': '14:00', 'release_time_basis': 'issuer-confirmed', 'מועד': 'before', 'קישור_לדוח': 'https://issuer.invalid/pr', 'call_time_il': '16:00', 'הערה': 'n' };
  eb.applySec(confirmed, hit, { today: '2026-11-24', cik: '1' });
  ok('issuer-confirmed release time stays protected; call and note stay',
    confirmed.release_time_il === '14:00' && confirmed['מועד'] === 'before' && confirmed.call_time_il === '16:00' && confirmed['הערה'] === 'n');

  const recent = {
    form: ['8-K', '8-K', '6-K', '10-Q'],
    items: ['7.01,9.01', '2.02,9.01', '', ''],
    accessionNumber: ['a-701', 'a-202', 'a-6k', 'a-10q'],
    acceptanceDateTime: ['2026-11-19T09:00:00-05:00', '2026-11-20T16:20:00-05:00', '2026-11-19T08:00:00-05:00', '2026-11-01T08:00:00-05:00'],
    filingDate: ['2026-11-19', '2026-11-20', '2026-11-19', '2026-11-01'],
    primaryDocument: ['d8k.htm', 'd202.htm', 'd6k.htm', 'd10q.htm'],
  };
  const pre = eb.findPreannounceFilings(recent, '2026-11-23');
  ok('pre-announce scan keeps 7.01 and 6-K and skips Item 2.02',
    pre.map((x) => x.acc).join(',') === 'a-701,a-6k', JSON.stringify(pre));
}
  ok('resolveCik reads TCOM from the stored report-links map without throwing',
    String(eb.resolveCik('TCOM') || '').replace(/^0+/, '') === '1269238');
  ok('resolveCik for an unknown symbol returns null, not a throw', eb.resolveCik('__NOT_A_TICKER__') === null);



// --- pre-announce date must be today or later; repair undoes stale moves ---
{

  const stale = { 'סימול': 'CRM', 'תאריך': '2026-12-02', 'הערה': 'keep', 'מזהה': 'r-9' };
  const staleParsed = { isPreannounce: true, date: '2026-10-20', session: 'after', releaseTimeIl: null, callTimeIl: '23:00' };
  ok('a past "results on" date is not applied to an upcoming row, and the note stays',
    eb.applyPreannounce(stale, staleParsed, { today: '2026-11-23', source: 'https://www.sec.gov/old.htm' }) === false
    && stale['תאריך'] === '2026-12-02' && !stale.call_time_il && stale['הערה'] === 'keep');

  const twinA = { 'סימול': 'VMAR', 'תאריך': '2026-11-27', 'מזהה': 'r-10' };
  const twinB = { 'סימול': 'VMAR', 'תאריך': '2027-01-12', 'מזהה': 'r-11' };
  const vmarP = { isPreannounce: true, date: '2026-12-05', session: 'after', releaseTimeIl: null, callTimeIl: '16:00' };
  ok('a future issuer date is still applied',
    eb.applyPreannounce(twinA, vmarP, { today: '2026-11-23', source: 'https://www.sec.gov/x.htm' }) === true
    && twinA['תאריך'] === '2026-12-05' && twinA.call_time_il === '16:00');
  ok('applying to one row does not by itself change a later row of the same symbol',
    twinB['תאריך'] === '2027-01-12' && !twinB.call_time_il);

  const bad = { 'סימול': 'ADBE', 'תאריך': '2026-09-02', 'תאריך_מקורי': '2026-12-09', 'הערה': 'n',
    'היסטוריית_מועד': [
      { scheduled_date: '2026-12-09', basis: 'Previous board date', preserved_on: '2026-11-23' },
      { date: '2026-09-02', basis: 'Issuer scheduled earnings release (SEC 8-K/6-K pre-announcement)', source: 'https://www.sec.gov/x.htm', verified_on: '2026-11-23' },
    ],
    call_time_il: '15:00', call_time_basis: 'issuer-scheduled', call_time_verified_date: '2026-11-23' };
  const keep = { 'סימול': 'TCOM', 'תאריך': '2026-12-01', 'תאריך_מקורי': '2026-11-23', 'call_time_il': '02:00',
    call_time_basis: 'issuer-scheduled', call_time_verified_date: '2026-11-23',
    'היסטוריית_מועד': [
      { scheduled_date: '2026-11-23', basis: 'Previous board date', preserved_on: '2026-11-23' },
      { date: '2026-12-01', basis: 'Issuer scheduled earnings release (SEC 8-K/6-K pre-announcement)', source: 'https://www.sec.gov/t.htm', verified_on: '2026-11-23' },
    ] };
  ok('repair restores a past pre-announce date and drops its call time',
    eb.revertInvalidPreannounceDates([bad, keep], '2026-11-23') === 1
    && bad['תאריך'] === '2026-12-09' && !bad['תאריך_מקורי'] && !bad.call_time_il && bad['הערה'] === 'n'
    && keep['תאריך'] === '2026-12-01' && keep.call_time_il === '02:00');
}


if (failed) { console.log(failed + ' failed'); process.exit(1); }
console.log('all earnings-board checks passed');
