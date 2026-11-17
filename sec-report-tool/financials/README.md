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
