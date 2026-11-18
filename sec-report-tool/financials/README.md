# financials – SEC companyfacts for the Finance tab

Public company income-statement figures (revenue, operating income, net
income, D&A → EBITDA, margins, Y/Y, Q/Q) for the app's Finance tab. The
repo never sees portfolio or watchlist data.

* Input: official `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
  and the public ticker map `https://www.sec.gov/files/company_tickers_exchange.json`.
* Output: one compact shard per ticker at `financials/AAPL.json` (and siblings),
  read by `index.html` for the selected company only.
* Fair access: User-Agent `SavageTracker Savtra12@gmail.com`, at most 2
  requests per second. HTTP 403 or 429 stops the run with no retry. HTTP 404
  skips that company.
* Incremental runs use the official EDGAR daily index to refresh only issuers
  that just filed a 10-K / 10-Q / 20-F, plus a resume queue for the first pass.

Run a local sample:

```
python3 sec-report-tool/financials/build_financials.py --only AAPL,MSFT,NVDA
```

The scheduled GitHub Action (`.github/workflows/financials.yml`) is not enabled
until that workflow is pushed.

## 8-K fast layer (`fast_layer.py`, `press_release.py`)

Earnings releases (8-K Item 2.02) arrive days before the 10-Q / 10-K XBRL.
`.github/workflows/financials-fast.yml` (every 30 min on weekdays + a daily
catch-up) finds them in the official EDGAR latest-filings feed / daily index,
reads the GAAP income statement from the EX-99 press release and adds the new
quarter to the shard as `{"f":"8-K","src":"pr",...}`. The app shows it with a
small "מהודעה לעיתונות" note under the period label.

* Fail safe: written only when units, period columns and labels are clear AND
  the release's prior-year column matches the existing XBRL figures (revenue,
  operating income, net income). Non-GAAP / reconciliation tables are ignored.
  EBITDA only when a three-month D&A column also matches XBRL.
* Superseded: `build_financials.py` keeps the press-release record only until
  companyfacts has that period; then the XBRL record replaces it.
* 1 request/second, same fair-access rules as above.

```
python3 sec-report-tool/financials/fast_layer.py --accession 1045810:0001045810-26-000088:2026-11-17
python3 sec-report-tool/financials/test_fast_layer.py
```

## Earnings board (earnings-live)

`fast_layer.py --board-out FILE` also lists every Item 2.02 filing it saw (acceptance time) with the parsed
release figures for `scripts/earnings-board.cjs --live`: revenue (`r`), GAAP diluted EPS (`eps`, accepted only
when net income / EPS reproduces the diluted share count of the verified income statement), and the
company-labelled adjusted / non-GAAP diluted EPS (`adj_eps`, clearly labelled table rows or sentences only;
`non_gaap` tells whether the release mentions non-GAAP EPS at all). `.github/workflows/earnings-live.yml`
runs this every 10 minutes in the US reporting windows (see `scripts/earnings-live.sh`).
