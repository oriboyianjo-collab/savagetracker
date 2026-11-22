// Official economic calendar updater: merge guards, revisions, formatting, parsers.
// No network, no secrets, no portfolio data.
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const merge = require('../scripts/econ-calendar/merge.cjs');
const format = require('../scripts/econ-calendar/format.cjs');
const ics = require('../scripts/econ-calendar/ics.cjs');
const time = require('../scripts/econ-calendar/time.cjs');
const census = require('../scripts/econ-calendar/sources/census.cjs');
const dol = require('../scripts/econ-calendar/sources/dol.cjs');
const eia = require('../scripts/econ-calendar/sources/eia.cjs');
const bls = require('../scripts/econ-calendar/sources/bls.cjs');

let failed = 0;
const ok = (name, cond, detail = '') => {
  if (!cond) { failed++; console.log('FAIL', name, detail); }
  else console.log('PASS', name);
};

// --- format ---
ok('claims 194000 -> 194K', format.formatClaims(194000) === '194K');
  ok('claims 200000 -> 200K, not 2K', format.formatClaims(200000) === '200K');
  ok('payrolls 150000 -> 150K', format.formatPayrolls(150000) === '150K');
  ok('trimNum keeps trailing zeros on integers', format.trimNum(200, 0) === '200' && format.trimNum(4.70, 1) === '4.7');
ok('continuing 1718000 -> 1.718M', format.formatClaims(1718000, { continuing: true }) === '1.718M');
ok('payrolls 165000 -> 165K', format.formatPayrolls(165000) === '165K');
ok('pct 0.3', format.formatPct(0.3) === '0.3%');
ok('oil +4.7', format.formatOilMmbbl(4.7) === '+4.7 מיליון חביות');
ok('gas +61', format.formatGasBcf(61) === '+61 מיליארד רגל מעוקבת');
ok('194K equals 194,000', format.valuesEquivalent('194K', '194,000'));
ok('200K != 191K', format.valuesEquivalent('200K', '191K') === false);
ok('+0.2% equals 0.2%', format.valuesEquivalent('+0.2%', '0.2%'));

// --- time: 8:30 ET winter -> 15:30 Israel ---
{
  const il = time.etWallToIsrael(2026, 11, 19, 8, 30);
  ok('8:30 ET Nov 19 2026 is 15:30 Israel', il.date === '2026-11-19' && il.time === '15:30', JSON.stringify(il));
  const utc = time.icsUtcToIsrael('20261125', '133000');
  ok('BEA 13:30Z is 15:30 Israel', utc.date === '2026-11-25' && utc.time === '15:30', JSON.stringify(utc));
}

// --- ICS ---
{
  const evs = ics.parseIcs(`BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;TZID=US-Eastern:20261118T083000
SUMMARY:New Residential Construction
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE-TIME:20261125T133000Z
SUMMARY:Personal Income and Outlays\\, October 2026
END:VEVENT
END:VCALENDAR`);
  ok('ICS parses two events', evs.length === 2);
  ok('ICS ET 8:30 -> 15:30 IL', evs[0].date === '2026-11-18' && evs[0].time === '15:30', JSON.stringify(evs[0]));
  ok('ICS UTC 13:30 -> 15:30 IL', evs[1].date === '2026-11-25' && evs[1].time === '15:30', JSON.stringify(evs[1]));
}

// --- merge: never write notes or forecasts ---
{
  const rows = [{
    'מזהה': 'c-0001', 'תאריך': '2026-11-19', 'מדינה': 'US',
    'אירוע': 'תביעות אבטלה שבועיות', 'אירוע_en': 'Weekly jobless claims',
    'צפי': '194K', 'הערה': 'הערה של אורי', 'הערה_en': "Ori's note",
    'קודם': '200K',
  }];
  const { rows: next, stats } = merge.applyCandidates(rows, [{
    'תאריך': '2026-11-19', 'מדינה': 'US',
    'אירוע': 'תביעות אבטלה שבועיות', 'אירוע_en': 'Weekly jobless claims',
    'צפי': '999K', 'הערה': 'אין לגעת', 'בפועל': '210K', 'קודם': '191K',
    _meta: { agency: 'dol', previousPublished: '200K' },
  }]);
  const r = next[0];
  ok('fills empty actual', r['בפועל'] === '210K' && stats.filled >= 1);
  ok('revises previous official print typed by the other bot (200K -> 191K)', r['קודם'] === '191K' && stats.revised >= 1, JSON.stringify({ prev: r['קודם'], stats }));
  ok('does not write or overwrite צפי', r['צפי'] === '194K');
  ok('does not write or overwrite הערה', r['הערה'] === 'הערה של אורי' && r['הערה_en'] === "Ori's note");
  ok('new rows never include forecast or notes', !('צפי' in merge.newRowFrom({ 'תאריך': '2026-11-26', 'מדינה': 'US', 'אירוע': 'X', 'צפי': '1', 'הערה': 'n' }, 'c-0002')));
}

// --- merge: do not overwrite a different human value ---
{
  const rows = [{
    'מזהה': 'c-0003', 'תאריך': '2026-11-12', 'מדינה': 'US',
    'אירוע': 'תביעות אבטלה שבועיות', 'בפועל': '180K',
  }];
  const { rows: next, stats } = merge.applyCandidates(rows, [{
    'תאריך': '2026-11-12', 'מדינה': 'US', 'אירוע': 'תביעות אבטלה שבועיות',
    'בפועל': '191K', _meta: { agency: 'dol', previousPublished: '200K' },
  }]);
  ok('leaves a different human actual alone', next[0]['בפועל'] === '180K' && stats.human >= 1 && stats.revised === 0, JSON.stringify(stats));
  ok('records the human skip in changes', (stats.changes || []).some((c) => c.action === 'human-skip' && c.from === '180K' && c.to === '191K'));
}

{
  const rows = [{
    'מזהה': 'c-0060', 'תאריך': '2026-11-05', 'מדינה': 'US',
    'אירוע': 'תביעות אבטלה שבועיות', 'בפועל': '189K', 'צפי': '197K',
    'הערה': 'שבוע שהסתיים ב-31.10.2026',
  }];
  const { rows: next, stats } = merge.applyCandidates(rows, [{
    'תאריך': '2026-11-05', 'מדינה': 'US', 'אירוע': 'תביעות אבטלה שבועיות',
    'בפועל': '191K', _meta: { agency: 'dol', previousPublished: '189K' },
  }]);
  const slot = next[0]['אוטומציה']['בפועל'];
  ok('revises other-bot official print 189K -> 191K', next[0]['בפועל'] === '191K' && stats.revised === 1, JSON.stringify(stats));
  ok('stores the first official print, not the revision, in אוטומציה', slot.first === '189K' && slot.last === '191K', JSON.stringify(slot));
  ok('leaves צפי and הערה untouched on official revision', next[0]['צפי'] === '197K' && next[0]['הערה'] === 'שבוע שהסתיים ב-31.10.2026');
}

// --- merge: automation can revise its own official figure ---
{
  const rows = [{
    'מזהה': 'c-0004', 'תאריך': '2026-11-12', 'מדינה': 'US',
    'אירוע': 'תביעות אבטלה שבועיות', 'בפועל': '200K',
    'אוטומציה': { 'בפועל': { by: merge.AUTOMATION, agency: 'dol', first: '200K', last: '200K' } },
  }];
  const { rows: next, stats } = merge.applyCandidates(rows, [{
    'תאריך': '2026-11-12', 'מדינה': 'US', 'אירוע': 'תביעות אבטלה שבועיות',
    'בפועל': '191K', _meta: { agency: 'dol' },
  }]);
  ok('revises our own official actual', next[0]['בפועל'] === '191K' && stats.revised === 1, JSON.stringify(next[0]));
  ok('keeps first published official value in אוטומציה', next[0]['אוטומציה']['בפועל'].first === '200K' && next[0]['אוטומציה']['בפועל'].last === '191K');
  ok('records revision history without touching notes', Array.isArray(next[0]['היסטוריית_נתונים']) && next[0]['היסטוריית_נתונים'][0].from === '200K' && !('הערה' in next[0]));
}

// --- IDs and matching ---
{
  const rows = [{ 'מזהה': 'c-0205', 'תאריך': '2026-11-18', 'מדינה': 'US', 'אירוע': 'בנייה למגורים חדשה - התחלות בנייה והיתרים', 'אירוע_en': 'New residential construction - housing starts and permits' }];
  ok('next id continues the sequence', merge.nextId(rows) === 'c-0206');
  const { rows: next, stats } = merge.applyCandidates(rows, [{
    'תאריך': '2026-11-18', 'מדינה': 'US',
    'אירוע': 'בנייה למגורים חדשה - התחלות בנייה והיתרים',
    'אירוע_en': 'New residential construction - housing starts and permits',
    'בפועל': '1.35 מיליון',
    _aliases: ['New Residential Construction (Building Permits, Housing Starts, and Housing Completions)'],
    _meta: { agency: 'census' },
  }]);
  ok('matches existing row by date+country+name, no duplicate', next.length === 1 && next[0]['מזהה'] === 'c-0205' && next[0]['בפועל'] === '1.35 מיליון' && stats.added === 0);
  const add = merge.applyCandidates(next, [{
    'תאריך': '2026-11-25', 'מדינה': 'US', 'אירוע': 'הזמנות למוצרי בני קיימא (כולל תחבורה)',
    'אירוע_en': 'Durable goods orders (incl. transportation)', 'שעה': '15:30', 'חשיבות': 2,
    _meta: { agency: 'census' },
  }]);
  ok('new official event gets c-0206', add.rows.length === 2 && add.rows[1]['מזהה'] === 'c-0206' && add.stats.added === 1);
  ok('new row has no צפי or הערה', !('צפי' in add.rows[1]) && !('הערה' in add.rows[1]));
}

// --- parsers ---
{
  const html = `Privately-owned housing starts in October were at a seasonally adjusted annual rate of 1,331,000. This is 2.0 percent below the revised September estimate of 1,358,000.`;
  const p = census.parseHousingStarts(`<p>${html}</p>`);
  ok('housing starts parser', p && p.actual === '1.331 מיליון' && p.previous === '1.358 מיליון', JSON.stringify(p));
}
{
  const html = `For release: Thursday, November 19, 2026. In the week ending November 14, the advance figure for seasonally adjusted initial claims was 220,000, a decrease of 10,000 from the previous week's revised level of 230,000. The previous week's level was revised up by 2,000 from 228,000 to 230,000. The advance seasonally adjusted insured unemployment rate during the week ending November 7 was 1.2 percent, and continued claims was 1,697,000.`;
  const p = dol.parseClaimsHtml(`<html>${html}</html>`);
  ok('claims parser current and revision', p && p.initial === 220000 && p.previousRevised === 230000 && p.previousPublished === 228000, JSON.stringify(p));
  ok('claims release date parsed', p && p.releaseText.includes('November 19, 2026'));
}
{
  const pdf = `TRANSMISSION OF MATERIALS IN THIS RELEASE IS EMBARGOED UNTIL 8:30 A.M. (Eastern) Thursday, November 12, 2026
In the week ending November 7, the advance figure for seasonally adjusted initial claims was 200,000, an increase of 9,000 from the previous week's revised level. The previous week's level was revised up by 2,000 from 189,000 to 191,000.
The advance number for seasonally adjusted insured unemployment during the week ending October 31 was 1,697,000, a decrease of 20,000 from the previous week's revised level. The previous week's level was revised down by 1,000 from 1,718,000 to 1,717,000.`;
  const p = dol.parseClaimsText(pdf);
  ok('DOL official PDF text: 200K and 189K->191K revision', p && p.initial === 200000 && p.previousPublished === 189000 && p.previousRevised === 191000 && p.releaseText.includes('November 12, 2026'), JSON.stringify(p));
  ok('DOL official PDF text: continuing 1,718,000 -> 1,717,000', p && p.continuing === 1697000 && p.continuingPreviousPublished === 1718000 && p.continuingPreviousRevised === 1717000, JSON.stringify(p));
}
{
  const ch = eia.parseOilChange('<p>Commercial crude oil inventories (excluding those in the Strategic Petroleum Reserve) increased by 4.7 million barrels from the previous week.</p>');
  ok('oil change parser', ch === 4.7, String(ch));
  const highlights = `Commercial crude oil inventories (excluding the Strategic Petroleum Reserve) decreased 0.6 million barrels to 423.4 million barrels, 1% above the five-year average.
Stocks (Million Barrels)
                                                 11/13/26        11/6/26        11/14/25
Crude Oil (Excluding SPR)2                             417.8           414.4             424.2
Motor Gasoline3                                        215.9           210.8             207.4`;
  const parsed = eia.parseHighlightsCrudeChange(highlights);
  ok('oil highlights table wins over stale prose', parsed && parsed.change === 3.4 && parsed.current === 417.8, JSON.stringify(parsed));
  ok('oil archive release dates', eia.parseOilReleaseDates('/petroleum/supply/weekly/archive/2026/2026_11_18/wpsr_2026_11_18.php', '2026-11-18', '2026-11-30').some((d) => d.date === '2026-11-18' && d.time === '17:30'));
  const gas = eia.parseGasChange('<p>Working gas in storage increased by 61 Bcf compared with the previous week.</p>');
  ok('gas change parser', gas === 61, String(gas));
}


// --- BLS: units, series-to-row mapping, reference month (regression for NFP "0.2K" over 165K) ---
const fed = require('../scripts/econ-calendar/sources/fed.cjs');
const { CATALOG } = require('../scripts/econ-calendar/catalog.cjs');
// Official BLS API values (vintage Nov 22, 2026), trimmed. CES payrolls and JOLTS are in thousands.
const BLS_FIXTURE = {"CES0000000001":[["2026M10","159293"],["2026M09","159128"],["2026M08","159068"],["2026M07","158882"],["2026M06","158892"],["2026M05","158861"],["2026M04","158798"],["2026M03","158650"],["2026M02","158436"],["2026M01","158592"],["2025M12","158432"],["2025M11","158449"],["2025M10","158408"],["2025M09","158548"],["2025M08","158472"]],"LNS14000000":[["2026M10","4.1"],["2026M09","4.2"],["2026M08","4.1"],["2026M07","4.1"],["2026M06","4.2"],["2026M05","4.3"],["2026M04","4.3"],["2026M03","4.3"],["2026M02","4.4"],["2026M01","4.3"],["2025M12","4.4"],["2025M11","4.5"],["2025M10","-"],["2025M09","4.4"],["2025M08","4.3"]],"CES0500000003":[["2026M10","38.00"],["2026M09","37.86"],["2026M08","37.76"],["2026M07","37.64"],["2026M06","37.59"],["2026M05","37.49"],["2026M04","37.41"],["2026M03","37.35"],["2026M02","37.27"],["2026M01","37.15"],["2025M12","37.02"],["2025M11","37.00"],["2025M10","36.85"],["2025M09","36.70"],["2025M08","36.62"]],"CUSR0000SA0":[["2026M10","337.476"],["2026M09","336.298"],["2026M08","334.131"],["2026M07","332.813"],["2026M06","332.568"],["2026M05","333.979"],["2026M04","332.407"],["2026M03","330.293"],["2026M02","327.460"],["2026M01","326.588"],["2025M12","326.031"],["2025M11","325.063"],["2025M10","-"],["2025M09","324.245"],["2025M08","323.291"]],"CUUR0000SA0":[["2026M10","337.511"],["2026M09","336.940"],["2026M08","334.980"],["2026M07","333.918"],["2026M06","333.952"],["2026M05","335.123"],["2026M04","333.020"],["2026M03","330.213"],["2026M02","326.785"],["2026M01","325.252"],["2025M12","324.054"],["2025M11","324.122"],["2025M10","-"],["2025M09","324.800"],["2025M08","323.976"]],"CUSR0000SA0L1E":[["2026M10","339.900"],["2026M09","338.896"],["2026M08","337.765"],["2026M07","336.789"],["2026M06","336.065"],["2026M05","336.121"],["2026M04","335.423"],["2026M03","334.165"],["2026M02","333.512"],["2026M01","332.793"],["2025M12","331.814"],["2025M11","331.043"],["2025M10","-"],["2025M09","330.418"],["2025M08","329.700"]],"CUUR0000SA0L1E":[["2026M10","339.921"],["2026M09","339.287"],["2026M08","338.041"],["2026M07","337.133"],["2026M06","336.882"],["2026M05","336.846"],["2026M04","335.803"],["2026M03","334.391"],["2026M02","333.242"],["2026M01","331.950"],["2025M12","330.506"],["2025M11","330.425"],["2025M10","-"],["2025M09","330.804"],["2025M08","329.970"]],"WPSFD4":[["2026M10","160.254"],["2026M09","159.699"],["2026M08","157.482"],["2026M07","156.834"],["2026M06","156.675"],["2026M05","156.874"],["2026M04","156.061"],["2026M03","154.393"],["2026M02","153.204"],["2026M01","152.468"],["2025M12","151.592"],["2025M11","151.054"],["2025M10","150.439"],["2025M09","150.245"],["2025M08","149.327"]],"WPUFD4":[["2026M10","160.248"],["2026M09","159.535"],["2026M08","157.673"],["2026M07","157.205"],["2026M06","157.149"],["2026M05","157.219"],["2026M04","156.443"],["2026M03","154.675"],["2026M02","153.156"],["2026M01","152.145"],["2025M12","150.773"],["2025M11","150.580"],["2025M10","150.439"],["2025M09","150.100"],["2025M08","149.466"]],"WPSFD49104":[["2026M10","156.740"],["2026M09","156.230"],["2026M08","154.960"],["2026M07","154.664"],["2026M06","154.236"],["2026M05","153.577"],["2026M04","153.594"],["2026M03","152.471"],["2026M02","152.033"],["2026M01","151.600"],["2025M12","150.350"],["2025M11","149.594"],["2025M10","149.219"],["2025M09","148.767"],["2025M08","148.001"]],"WPUFD49104":[["2026M10","156.893"],["2026M09","155.986"],["2026M08","154.865"],["2026M07","154.666"],["2026M06","154.432"],["2026M05","153.717"],["2026M04","153.840"],["2026M03","152.744"],["2026M02","152.114"],["2026M01","151.542"],["2025M12","149.936"],["2025M11","149.275"],["2025M10","149.356"],["2025M09","148.542"],["2025M08","147.912"]],"JTS000000000000000JOL":[["2026M09","7523"],["2026M08","7190"],["2026M07","7335"],["2026M06","7182"],["2026M05","7537"],["2026M04","7585"],["2026M03","6887"],["2026M02","6922"],["2026M01","7240"],["2025M12","6550"],["2025M11","6846"],["2025M10","7170"],["2025M09","7169"],["2025M08","6919"]],"EIUIR":[["2026M10","153.8"],["2026M09","152.2"],["2026M08","150.6"],["2026M07","149.8"],["2026M06","150.3"],["2026M05","150.7"],["2026M04","148.1"],["2026M03","144.8"],["2026M02","143.5"],["2026M01","142.1"],["2025M12","141.4"],["2025M11","141.2"],["2025M09","140.8"],["2025M08","141.0"]],"EIUIQ":[["2026M10","172.9"],["2026M09","171.0"],["2026M08","167.0"],["2026M07","165.2"],["2026M06","167.5"],["2026M05","168.8"],["2026M04","166.8"],["2026M03","161.1"],["2026M02","158.4"],["2026M01","155.4"],["2025M12","154.6"],["2025M11","153.7"],["2025M09","153.0"],["2025M08","153.0"]]};
const blsObs = (id) => (BLS_FIXTURE[id] || []).map(([yp, value]) => ({ year: yp.slice(0, 4), period: yp.slice(4), value }));
const cat = (id) => CATALOG.find((e) => e.id === id);
{
  const want = {
    // id: [release date, actual, previous] as BLS published (previous = latest revised vintage)
    'bls-nfp': ['2026-11-06', '165K', '60K'],
    'bls-unemp': ['2026-11-06', '4.1%', '4.2%'],
    'bls-ahe-mm': ['2026-11-06', '+0.4%', '+0.3%'],
    'bls-ahe-yy': ['2026-11-06', '3.1%', '3.2%'],
    'bls-cpi-mm': ['2026-11-10', '+0.4%', '+0.6%'],
    'bls-cpi-core-mm': ['2026-11-10', '+0.3%', '+0.3%'],
    'bls-ppi-mm': ['2026-11-13', '+0.3%', '+1.4%'],
    'bls-ppi-yy': ['2026-11-13', '6.5%', '6.3%'],
    'bls-ppi-core-mm': ['2026-11-13', '+0.3%', '+0.8%'],
    'bls-ppi-core-yy': ['2026-11-13', '5.0%', '5.0%'],
    'bls-jolts': ['2026-11-03', '7.523 מיליון', '7.19 מיליון'],
    'bls-import-mm': ['2026-11-17', '+1.1%', '+1.1%'],
    'bls-export-mm': ['2026-11-17', '+1.1%', '+2.4%'],
  };
  for (const [id, [date, actual, previous]] of Object.entries(want)) {
    const e = cat(id);
    const got = bls.compute(e, blsObs(e.blsSeries.id), bls.referenceYm(e, date));
    const a = got && bls.formatSeriesValue(e, got.value);
    const p = got && got.previous != null ? bls.formatSeriesValue(e, got.previous) : null;
    ok(`BLS ${id} ${date}: ${actual} / prev ${previous}`, a === actual && p === previous, JSON.stringify({ a, p, got }));
  }
  ok('NFP is never formatted as 0.2K (CES is thousands)', bls.formatSeriesValue(cat('bls-nfp'), 165) === '165K' && bls.formatSeriesValue(cat('bls-nfp'), -12) === '-12K');
  ok('NFP guard refuses an unscaled sub-1K change', bls.plausible({ ...cat('bls-nfp'), blsSeries: { ...cat('bls-nfp').blsSeries, scale: 1 } }, 165).ok === false);
  ok('percent series are never scaled as payrolls', bls.scaleOf(cat('bls-ahe-mm')) === 1 && bls.scaleOf(cat('bls-unemp')) === 1 && bls.scaleOf(cat('bls-cpi-mm')) === 1);
  ok('rate guard refuses 41%', bls.plausible(cat('bls-unemp'), 41).ok === false);
  ok('JOLTS reference month is two months back', bls.referenceYm(cat('bls-jolts'), '2026-11-03') === '2026-09');
  ok('CPI reference month is one month back', bls.referenceYm(cat('bls-cpi-mm'), '2026-11-10') === '2026-10');
  ok('PPI 12-month uses NSA series', cat('bls-ppi-yy').blsSeries.id === 'WPUFD4' && cat('bls-ppi-core-yy').blsSeries.id === 'WPUFD49104');
  const cpiYy = bls.compute(cat('bls-cpi-yy'), blsObs('CUUR0000SA0'), '2026-10');
  ok('CPI y/y with unpublished Oct 2025 ("-") gives no value, not NaN', cpiYy && cpiYy.value === null && bls.formatSeriesValue(cat('bls-cpi-yy'), cpiYy.previous) === '3.7%', JSON.stringify(cpiYy));
  const gap = bls.compute(cat('bls-nfp'), blsObs('CES0000000001'), '2026-12');
  ok('missing reference month writes nothing (no fallback to newest month)', gap === null);
  for (const e of CATALOG.filter((x) => x.agency === 'bls' && x.blsSeries)) {
    ok(`catalog ${e.id} has release URL and period`, /^https:\/\/www\.bls\.gov\/news\.release\//.test(e.blsRelease || '') && !!e.period);
  }
}
// End-to-end BLS ingest with fake HTTP (ICS + API) and merge onto rows shaped like calendar.json.
{
  const icsText = ['BEGIN:VCALENDAR',
    'BEGIN:VEVENT', 'DTSTART;TZID=US-Eastern:20261103T100000', 'SUMMARY:Job Openings and Labor Turnover Survey', 'END:VEVENT',
    'BEGIN:VEVENT', 'DTSTART;TZID=US-Eastern:20261106T083000', 'SUMMARY:Employment Situation', 'END:VEVENT',
    'BEGIN:VEVENT', 'DTSTART;TZID=US-Eastern:20261110T083000', 'SUMMARY:Consumer Price Index', 'END:VEVENT',
    'END:VCALENDAR'].join('\r\n');
  const api = { status: 'REQUEST_SUCCEEDED', Results: { series: Object.keys(BLS_FIXTURE).map((id) => ({ seriesID: id, data: blsObs(id) })) } };
  const http = {
    isBlocked: () => null, log: [],
    getText: async () => icsText,
    get: async () => ({ text: () => JSON.stringify(api) }),
  };
  const { candidates } = await bls.ingest(http, { from: '2026-11-22', to: '2026-11-22', lookbackFrom: '2026-11-01' });
  let apiCalls = 0;
  const http2 = { ...http, get: async () => { apiCalls++; return { text: () => JSON.stringify(api) }; } };
  const light = await bls.ingest(http2, { from: '2026-11-22', to: '2026-11-22', lookbackFrom: '2026-11-01', full: false, now: new Date('2026-11-22T18:00:00Z') });
  ok('light run with no recent BLS release skips the keyless API (quota)', apiCalls === 0 && light.skipped.some((x) => /quota/.test(x.reason)));
  await bls.ingest(http2, { from: '2026-11-10', to: '2026-11-10', lookbackFrom: '2026-11-01', full: false, now: new Date('2026-11-10T14:00:00Z') });
  ok('light run 30 min after CPI release queries the API', apiCalls === 1);
  const nfp = candidates.filter((c) => c._meta.series === 'CES0000000001');
  ok('ingest: one NFP actual candidate, Oct, 165K / 60K', nfp.length === 1 && nfp[0]['בפועל'] === '165K' && nfp[0]['קודם'] === '60K' && nfp[0]['תאריך'] === '2026-11-06' && nfp[0]['תקופה'] === 'אוקטובר · חודשי', JSON.stringify(nfp));
  const ahe = candidates.find((c) => c._meta.series === 'CES0500000003' && c['אירוע_en'].includes('monthly') && c['בפועל']);
  ok('ingest: AHE % goes to the AHE row, not payrolls', ahe && ahe['אירוע'] === 'שכר שעתי ממוצע - חודשי' && ahe['בפועל'] === '+0.4%', JSON.stringify(ahe));
  ok('ingest: no candidate writes K units onto a % row or % onto NFP',
    candidates.every((c) => !c['בפועל'] || (c['אירוע'] === 'דוח תעסוקה - שכר לא-חקלאי' ? /K$/.test(c['בפועל']) : !/K$/.test(c['בפועל']))));
  const jolts = candidates.find((c) => c._meta.series === 'JTS000000000000000JOL');
  ok('ingest: JOLTS Nov 3 release -> September 7.523 מיליון', jolts && jolts['בפועל'] === '7.523 מיליון' && jolts['תקופה'] === 'ספטמבר · חודשי', JSON.stringify(jolts));
  ok('ingest: no candidate carries צפי or הערה', candidates.every((c) => !('צפי' in c) && !('הערה' in c) && !('הערה_en' in c)));
  const rows = [
    { 'מזהה': 'c-0067', 'תאריך': '2026-11-06', 'מדינה': 'US', 'אירוע': 'דוח תעסוקה - שכר לא-חקלאי', 'אירוע_en': 'Employment report - nonfarm payrolls', 'בפועל': '165K', 'קודם': '+29K', 'צפי': '63K–65K', 'הערה': 'n' },
    { 'מזהה': 'c-0068', 'תאריך': '2026-11-06', 'מדינה': 'US', 'אירוע': 'שיעור האבטלה', 'אירוע_en': 'Unemployment rate', 'בפועל': '4.1%', 'קודם': '4.2%' },
    { 'מזהה': 'c-0090', 'תאריך': '2026-11-10', 'מדינה': 'US', 'אירוע': 'מדד המחירים לצרכן - חודשי', 'אירוע_en': 'Consumer price index - monthly', 'בפועל': '0.4%', 'קודם': '0.6%' },
  ];
  const { rows: next, stats } = merge.applyCandidates(rows, candidates, { addFrom: '2026-11-22' });
  ok('merge: NFP 165K unchanged (no 0.2K attempt)', next[0]['בפועל'] === '165K' && !stats.changes.some((c) => c.id === 'c-0067' && c.field === 'בפועל'), JSON.stringify(stats.changes.filter((c) => c.id === 'c-0067')));
  ok('merge: BLS revision replaces stored prior +29K -> 60K (Ori: update to revised value)', next[0]['קודם'] === '60K' && stats.changes.some((c) => c.id === 'c-0067' && c.field === 'קודם' && c.action === 'revise' && c.reason === 'revise-official-latest'), JSON.stringify(stats.changes.filter((c) => c.id === 'c-0067')));
  ok('merge: BLS revision keeps the first print in אוטומציה and history', next[0]['אוטומציה']['קודם'].first === '+29K' && next[0]['אוטומציה']['קודם'].last === '60K' && next[0]['היסטוריית_נתונים'].some((h) => h.from === '+29K' && h.to === '60K'), JSON.stringify(next[0]['אוטומציה']));
  ok('merge: unemployment and CPI equal official values (unchanged)', next[1]['בפועל'] === '4.1%' && next[2]['בפועל'] === '0.4%' && !stats.changes.some((c) => ['c-0068', 'c-0090'].includes(c.id) && c.field === 'בפועל'));
  ok('merge: NFP צפי/הערה untouched', next[0]['צפי'] === '63K–65K' && next[0]['הערה'] === 'n');
}
// Official-latest revisions: numeric only, never a note-like value, never notes/forecasts, not for non-BLS sources.
{
  const base = { 'תאריך': '2026-12-10', 'מדינה': 'US', 'אירוע': 'מדד המחירים לצרכן - שנתי' };
  const rows = [{ 'מזהה': 'c-0174', ...base, 'קודם': '3.7% (ספטמבר)', 'צפי': '3.0%', 'הערה': 'n' }];
  const r1 = merge.applyCandidates(rows, [{ ...base, 'קודם': '3.6%', 'צפי': '9%', _meta: { agency: 'bls', officialRevision: true } }]);
  ok('official revision does not overwrite a non-numeric stored note-like value', r1.rows[0]['קודם'] === '3.7% (ספטמבר)' && r1.stats.human === 1);
  ok('official revision never writes צפי/הערה', r1.rows[0]['צפי'] === '3.0%' && r1.rows[0]['הערה'] === 'n');
  const rows2 = [{ 'מזהה': 'c-0001', ...base, 'קודם': '3.7%' }];
  const r2 = merge.applyCandidates(rows2, [{ ...base, 'קודם': '3.6%', _meta: { agency: 'census' } }]);
  ok('without officialRevision a different stored value is still protected', r2.rows[0]['קודם'] === '3.7%' && r2.stats.human === 1);
  const r3 = merge.applyCandidates(rows2.map((r) => ({ ...r })), [{ ...base, 'קודם': '3.6%', _meta: { agency: 'bls', officialRevision: true } }]);
  ok('BLS officialRevision replaces numeric 3.7% -> 3.6%', r3.rows[0]['קודם'] === '3.6%' && r3.stats.revised === 1);
}
// H.4.1 label matches existing rows ("פורסם · 11.11", Wednesday of the week, no "נתוני").
{
  const html = '<div>Release Date:\n    November 12, 2026\n</div><th>Wednesday<br>Nov 11, 2026</th><td>Week ended<br>Nov 11, 2026</td>';
  ok('H.4.1 week-ended date parsed', fed.weekEndedYmd(html) === '2026-11-11');
  const out = [];
  await fed.publishedRelease({ getText: async () => html }, 'https://www.federalreserve.gov/releases/h41/current/', cat('fed-h41'), '23:30', '2026-11-01', '2026-11-22', out, () => {});
  ok('H.4.1 candidate matches c-0117 wording', out.length === 1 && out[0]['תאריך'] === '2026-11-12' && out[0]['בפועל'] === 'פורסם · 11.11', JSON.stringify(out));
  const rows = [{ 'מזהה': 'c-0117', 'תאריך': '2026-11-12', 'מדינה': 'US', 'אירוע': 'מאזן הפד וגורמי יתרות (H.4.1)', 'בפועל': 'פורסם · 11.11' }];
  const { stats } = merge.applyCandidates(rows, out);
  ok('H.4.1 c-0117 no longer a human-skip', stats.human === 0 && stats.unchanged >= 1, JSON.stringify(stats));
}

// EIA gas: value goes to the row of the report's own release date, not the last holiday-schedule date.
{
  const html = '<p>Released: &nbsp;November 19, 2026 at 10:30 a.m.</p><p>Working gas in storage was 3,882 Bcf as of Friday, November 13, 2026. This represents a net increase of 20 Bcf from the previous week.</p>';
  const rel = eia.parseGasReleaseDate(html);
  ok('EIA gas release date -> 2026-11-19 17:30 Israel', rel && rel.date === '2026-11-19' && rel.time === '17:30', JSON.stringify(rel));
  ok('EIA gas change +20', eia.parseGasChange(html) === 20);
}
// BEA actuals (official NIPA API values, vintage Nov 22 2026, trimmed) vs rows c-0015..c-0023 of Oct 29.
{
  const bea = require('../scripts/econ-calendar/sources/bea.cjs');
  const BEA_FIXTURE = {"DPCERGM":{"2025M08":0.3,"2025M09":0.3,"2026M07":0.1,"2026M08":0.3,"2026M09":0.5},"DPCCRGM":{"2025M08":0.2,"2025M09":0.2,"2026M07":0.1,"2026M08":0.3,"2026M09":0.3},"DPCERG":{"2025M08":127.229,"2025M09":127.601,"2026M07":131.187,"2026M08":131.611,"2026M09":132.257},"DPCCRG":{"2025M08":126.646,"2025M09":126.94,"2026M07":130.148,"2026M08":130.489,"2026M09":130.902},"A065RC":{"2025M08":26495067,"2025M09":26604910,"2026M07":27570024,"2026M08":27653372,"2026M09":27707845},"DPCERC":{"2025M08":21029464,"2025M09":21126488,"2026M07":22146038,"2026M08":22339658,"2026M09":22452780},"A191RL":{"2026Q2":2.2,"2026Q3":3.4}};
  ok('BEA key cleaner strips a pasted trailing dot', bea.cleanKey('12345678-ABCD-4ef0-9a9a-0123456789ab.') === '12345678-ABCD-4ef0-9a9a-0123456789ab' && bea.cleanKey('nope') === '');
  ok('BEA ref period monthly', JSON.stringify(bea.refPeriod('Personal Income and Outlays, September 2026')) === JSON.stringify({ kind: 'M', key: '2026M09', year: 2026, month: 9 }));
  ok('BEA ref period two months -> null', bea.refPeriod('Personal Income and Outlays, October and November 2025') === null);
  ok('BEA ref period GDP advance / second / third', bea.refPeriod('GDP (Advance Estimate), 3rd Quarter 2026').key === '2026Q3' && bea.refPeriod('GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026').key === '2026Q3' && bea.refPeriod('GDP (Third Estimate), Industries, Corporate Profits, State GDP, and State Personal Income, 3rd Quarter 2026').key === '2026Q3');
  const want = {
    'bea-pce-mm': ['2026M09', 0.5, 0.3], 'bea-pce-core-mm': ['2026M09', 0.3, 0.3],
    'bea-pce-yy': ['2026M09', 3.6, 3.4], 'bea-pce-core-yy': ['2026M09', 3.1, 3.0],
    'bea-income': ['2026M09', 0.2, 0.3], 'bea-spending': ['2026M09', 0.5, 0.9],
    'bea-gdp-adv': ['2026Q3', 3.4, 2.2],
  };
  for (const [id, [key, a, p]] of Object.entries(want)) {
    const spec = bea.SERIES[id];
    const got = bea.computeBea(spec, BEA_FIXTURE[spec.code], key);
    const r1 = (x) => Math.round(x * 10) / 10;
    ok(`BEA ${id} ${key}: ${a}% / prev ${p}%`, got.value != null && r1(got.value) === a && r1(got.previous) === p, JSON.stringify(got));
  }
  ok('BEA guard refuses 25% m/m', bea.plausibleBea(bea.SERIES['bea-income'], 25) === false);
  ok('BEA table error surfaces as a message, not a crash', (() => { try { bea.parseTable({ BEAAPI: { Results: { Error: { APIErrorCode: '1', APIErrorDescription: 'Invalid' } } } }, 'X'); return false; } catch (e) { return /Invalid/.test(e.message); } })());
  const { redact } = require('../scripts/econ-calendar/http.cjs');
  ok('API keys are redacted from logged URLs', redact('https://apps.bea.gov/api/data?UserID=SECRET&method=GetData') === 'https://apps.bea.gov/api/data?UserID=***&method=GetData' && redact('https://x/?api_key=S&a=1') === 'https://x/?api_key=***&a=1');
}
// Look-ahead: schedule rows for future releases never get actuals (GDP 2nd estimate must not inherit the advance value).
{
  const bea = require('../scripts/econ-calendar/sources/bea.cjs');
  const ics2 = ['BEGIN:VCALENDAR', 'BEGIN:VEVENT', 'DTSTART:20261125T133000Z', 'SUMMARY:GDP (Second Estimate) and Corporate Profits\\, 3rd Quarter 2026', 'END:VEVENT',
    'BEGIN:VEVENT', 'DTSTART:20261029T123000Z', 'SUMMARY:GDP (Advance Estimate)\\, 3rd Quarter 2026', 'END:VEVENT',
    'BEGIN:VEVENT', 'DTSTART:20261202T133000Z', 'SUMMARY:GDP by County and Personal Income by County\\, 2025', 'END:VEVENT', 'END:VCALENDAR'].join('\r\n');
  const table = { BEAAPI: { Results: { Data: [{ SeriesCode: 'A191RL', TimePeriod: '2026Q3', DataValue: '3.4' }, { SeriesCode: 'A191RL', TimePeriod: '2026Q2', DataValue: '2.2' }] } } };
  const http = { isBlocked: () => null, getText: async () => ics2, get: async () => ({ text: () => JSON.stringify(table) }) };
  const r = await bea.ingest(http, { from: '2026-11-22', to: '2026-12-05', lookbackFrom: '2026-10-25', keys: { BEA_API_KEY: '12345678-abcd-4ef0-9a9a-0123456789ab' }, now: new Date('2026-11-22T19:00:00Z') });
  const second = r.candidates.filter((c) => c['אירוע'] === 'תמ"ג ריאלי (הערכה שנייה)');
  ok('future GDP 2nd estimate row is scheduled without an actual', second.length >= 1 && second.every((c) => !('בפועל' in c) && !('קודם' in c)), JSON.stringify(second));
  const adv = r.candidates.find((c) => c['אירוע'] === 'תמ"ג ריאלי (הערכה ראשונה)' && c['בפועל']);
  ok('past GDP advance row gets 3.4% / 2.2%', adv && adv['בפועל'] === '3.4%' && adv['קודם'] === '2.2%', JSON.stringify(adv));
  ok('uncatalogued BEA release is not added as an English-only row', !r.candidates.some((c) => /County/.test(c['אירוע'])) && r.skipped.some((x) => x.source === 'bea-uncatalogued'));
  ok('BLS released(): future release is not released yet', bls.released({ date: '2026-12-04', instant: new Date('2026-12-04T13:30:00Z') }, new Date('2026-11-22T19:00:00Z')) === false && bls.released({ date: '2026-11-06', instant: new Date('2026-11-06T13:30:00Z') }, new Date('2026-11-22T19:00:00Z')) === true);
}
// --- compact JSON style ---
{
  const s = merge.stringifyCalendar([{ 'מזהה': 'c-0001', 'תאריך': '2026-11-19' }]);
  ok('compact JSON, no trailing newline', s === '[{"מזהה":"c-0001","תאריך":"2026-11-19"}]');
}

if (failed) {
  console.log(`\n${failed} failed`);
  process.exit(1);
}
console.log('\nAll econ-calendar regressions passed');
