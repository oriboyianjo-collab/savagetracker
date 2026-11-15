# ISRG EDGAR report tool

This tool fills Intuitive Surgical (ISRG) annual and quarterly report buttons from official SEC EDGAR filings, starting with reports published for periods from 2020 onward. It is ISRG-only. Expanding it to other companies needs a separate decision.

## Legal / fair-access compliance

The live run follows the SEC's EDGAR fair-access policy:

- Policy: https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- Internet Security Policy: no more than 10 requests per second in total, across all machines.

This client:

- Sends a declared User-Agent on every request: `SavageTracker oriboyianjo@users.noreply.github.com`
- Uses only official endpoints: `https://data.sec.gov/submissions/...` and `https://www.sec.gov/Archives/edgar/data/1035267/...`
- Waits at least 0.6 seconds between requests (~1.6/s), well under the 10/s maximum
- Downloads only the submissions index and the primary document (or Q4 Exhibit 99.1) needed to map a period
- Does not use unofficial mirrors, proxies, IP rotation, or a disguised browser User-Agent
- On HTTP 403, stops immediately, writes a log, and does not retry or circumvent the block
- On HTTP 429 or a transient 5xx, backs off politely a limited number of times, then stops and logs; it does not keep requesting while blocked

A detailed JSONL log of each request, status, mapping decision, and error is written under `logs/`. Logs contain no secrets.

Live HTTP uses the same official Node `fetch` pattern as the existing `fundamentals` job (`sec_fetch.cjs`): declared User-Agent, official hosts only, no retries inside the helper, and no proxies or disguised clients.


## Local use

Requires Python 3 and its standard library. From this directory:

```sh
python3 -m unittest -v
python3 pipeline.py --output /tmp/isrg-held-demo
python3 demo_synthetic.py --output /tmp/isrg-synthetic-demo
```

The default pipeline run does not use the network. A live authorized run (ISRG only):

```sh
python3 pipeline.py --output state/isrg --live --clear-stale-hold \
  --as-of "$(date +%F)" \
  --log logs/isrg-run.jsonl \
  --app-output ../report-links-pilot.json \
  --cache /tmp/isrg-edgar-cache
```

Document bodies are cached outside the repository. Pipeline progress (`pipeline-state.json`) and the app index (`report-links-pilot.json`) are what get committed.

## How filings map to buttons

ISRG's fiscal year is the calendar year.

- FY = Form 10-K for the year ended 31 December
- Q1 / Q2 / Q3 = Form 10-Q for the quarters ended 31 March, 30 June, 30 September
- Q4 = Exhibit 99.1 of the earnings Form 8-K (Item 2.02), not the annual report

The app reads `report-links-pilot.json` and places each URL on the matching year and period button. A scheduled GitHub Actions workflow (`isrg-edgar-reports`) re-runs this for ISRG on weekdays and commits only when the published index changes.

## Limits

This version is ISRG-specific. A quarter ending does not mean a report has been published; missing periods stay empty until a validated filing exists. Amendments that are not an explicit full restatement keep the original report on the button and are noted in the log. The tool does not extract financial values or change other companies' links.
