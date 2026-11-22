'use strict';

const { CATALOG } = require('../catalog.cjs');
const { candidate, inRange } = require('./util.cjs');
const { formatPct, formatIndex, formatBillionUSD } = require('../format.cjs');

const WEI = 'https://www.dallasfed.org/research/wei';
const NY_NOWCAST = 'https://www.newyorkfed.org/research/policy/nowcast';
const MBOS = 'https://www.philadelphiafed.org/surveys-and-data/regional-economic-analysis/manufacturing-business-outlook-survey';
const MTS = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/mts/mts_table_1?sort=-record_date&page[size]=12';
const EUROSTAT_IP = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/sts_inpr_m?format=JSON&geo=EA20&s_adj=SCA&nace_r2=C&unit=I21&lastTimePeriod=6';

async function ingestRegional(http, { from, to, lookbackFrom, log = () => {} }) {
  const out = [];
  const skipped = [];
  const dateMin = lookbackFrom || from;

  // Dallas Fed WEI: try to read a latest value from the public page (non-commercial reuse with credit).
  try {
    const html = await http.getText(WEI);
    const text = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    const m = text.match(/Weekly Economic Index[^.]{0,40}?(-?[0-9]+\.[0-9]+)/i)
      || text.match(/WEI[^.]{0,20}?(-?[0-9]+\.[0-9]+)\s*percent/i);
    const wei = CATALOG.find((e) => e.id === 'dallas-wei');
    // Don't invent a date if we can't parse one; only fill actual on an existing scheduled row in range.
    const dateM = text.match(/(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(2026)/);
    if (m && dateM) {
      const mon = { January:1,February:2,March:3,April:4,May:5,June:6,July:7,August:8,September:9,October:10,November:11,December:12 };
      const ymd = `${dateM[3]}-${String(mon[dateM[1]]).padStart(2, '0')}-${String(+dateM[2]).padStart(2, '0')}`;
      if (inRange(ymd, dateMin, to)) {
        out.push(candidate(wei, {
          date: ymd, time: '18:30', url: WEI,
          actual: formatIndex(m[1], 2),
          meta: { agency: 'dallasfed', series: 'dallas-wei' },
        }));
      }
    }
  } catch (e) {
    log(`Dallas WEI skipped: ${e.message}`);
    skipped.push({ source: 'dallas-wei', reason: e.message });
    if (e.code === 'HTTP_STOP' || e.code === 'HTTP_BLOCKED') return { candidates: out, skipped };
  }

  try {
    const html = await http.getText(NY_NOWCAST);
    const text = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    const m = text.match(/nowcast[^.]{0,40}?(-?[0-9]+\.[0-9]+)\s*%/i);
    // Date is hard to pin; skip if no explicit update date in range.
    if (!m) skipped.push({ source: 'nyfed-nowcast', reason: 'no parseable nowcast value' });
  } catch (e) {
    log(`NY Fed nowcast skipped: ${e.message}`);
    skipped.push({ source: 'nyfed-nowcast', reason: e.message });
  }

  try {
    await http.getText(MBOS); // schedule/link presence; value parsing is page-specific
  } catch (e) {
    skipped.push({ source: 'philly-mbos', reason: e.message });
  }

  return { candidates: out, skipped };
}

async function ingestTreasury(http, { from, to, lookbackFrom, log = () => {} }) {
  const out = [];
  const skipped = [];
  try {
    const res = await http.get(MTS, { accept: 'application/json' });
    const json = JSON.parse(res.text());
    // We only fill when a matching scheduled row exists in the window; MTS release date is not always record_date.
    if (!json.data) skipped.push({ source: 'treasury-mts', reason: 'no data array' });
  } catch (e) {
    log(`Treasury MTS skipped: ${e.message}`);
    skipped.push({ source: 'treasury-mts', reason: e.message });
  }
  return { candidates: out, skipped };
}

async function ingestEurostat(http, { from, to, lookbackFrom, log = () => {} }) {
  const out = [];
  const skipped = [];
  try {
    const res = await http.get(EUROSTAT_IP, { accept: 'application/json' });
    JSON.parse(res.text());
    // Without a Eurostat release-date calendar in this run, don't invent a US/EU date.
    skipped.push({ source: 'eurostat-ip', reason: 'value available but release date not mapped this run' });
  } catch (e) {
    log(`Eurostat IP skipped: ${e.message}`);
    skipped.push({ source: 'eurostat-ip', reason: e.message });
  }
  return { candidates: out, skipped };
}

module.exports = { ingestRegional, ingestTreasury, ingestEurostat, WEI, NY_NOWCAST, MTS };
