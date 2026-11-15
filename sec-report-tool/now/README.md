# ServiceNow report automation

NOW-only addition. It does not import, replace or widen the ISRG parser, transport, workflow or data. Python 3 and Node 18+ are required. No Python packages, account credentials, paid services or new recurring schedule are needed.

## What the automation does

1. Read the official NOW SEC submissions index and every relevant historical submissions page, within fixed budgets.
2. Select native 10-K / 10-Q reports from 2020, plus Q4 earnings 8-K Exhibit 99.1. The initial required history is FY and Q1-Q4 for 2020-2025, plus Q1-Q3 2026. Newly ended future periods remain pending until a filing exists.
3. Check issuer, symbol, filing form, DEI fiscal period/year, declared date transforms, metadata date and own-report cover. Check actual dated numeric income, balance sheet and cash-flow tables. Quarterly cash flows can be YTD, as in the native 10-Q.
4. For Q4, require the first NOW earnings headline to name the same fourth-quarter/full-year year, bind the opening own-quarter-ended date, require a dated three-month income table and check all three statements. Never substitute a 10-K for Q4. Preliminary or unrecognized releases hold publication for review.
5. Review amendments. Only an explicit Inline-XBRL-tagging-only 8-K/A saying it makes no other information update is non-superseding. Other amendments stop publication pending version review. This links native reports; it does not normalize old comparative figures or extract financial values.
6. Run a separate read-only check using the actual cover/headline dates and checked-table hashes against retained HTTP bodies.
7. Write the NOW-specific app index atomically, only after all checks. Empty, incomplete or invalid results never replace the last-good index. Prior validated periods and URLs cannot disappear or change without review.
8. The app's isolated NOW consumer reads that generated index and uses the existing report controls. No period URL is entered by hand. An already-open app needs reload; no background polling is added.

## Run locally

From `sec-report-tool/now/`:

```sh
python3 -m unittest -v
python3 run_now.py --live --as-of 2026-11-15 \
  --cache /tmp/now-edgar-cache \
  --result /tmp/now-result.json \
  --log /tmp/now-run.jsonl \
  --app-output ../../report-links-now.json
python3 verify_now.py --result /tmp/now-result.json --cache /tmp/now-edgar-cache
NOW_CAPTURE_CACHE=/tmp/now-edgar-cache python3 -m unittest -v
```

Without `--live`, the CLI sends no requests. Unit tests are offline. The real-corpus tests are skipped unless `NOW_CAPTURE_CACHE` supplies retained raw responses. A replay is not a fresh HTTP check.

Transport declares `SavageTracker Savtra12@gmail.com`, uses only official NOW SEC routes and waits at least 0.6 seconds between requests. On 403, 429 or a challenge it stops without bypass or retry. The local cache records a persistent stop requiring review. Submissions are refreshed on each execution; immutable document cache entries are hash-checked before reuse. In GitHub, the cache is temporary for this one-off run. A failed access attempt is not grounds to redispatch until the reason has been reviewed.

## Deployment and one-off test

Install the `now/` directory under `sec-report-tool/`. Install `now-edgar-reports.yml` as `.github/workflows/now-edgar-reports.yml`. It has **workflow_dispatch only**, no clock schedule. Its runner generates `report-links-now.json`, verifies it, runs the full raw-corpus tests and commits only that generated file. No prebuilt index is part of the code installation.

Insert `now-consumer-insert.js` immediately after the unique `/* End ISRG retained-data pilot. */` marker inside `index.html`'s existing application script. Do not change the existing ISRG consumer or report-control functions. The insertion only adds NOW data bindings; it adds no new visual controls.

Add `now-edgar-reports` to the existing `.github/workflows/pages-queued.yml` `workflow_run.workflows` allowlist, preserving its existing successful-completion, same-repository and main-branch gates. A GITHUB_TOKEN commit does not itself trigger a separate push workflow. This completion trigger is required for the generated file to deploy without a manual second step. The separate ISRG completion-trigger fix can share the same allowlist edit but is outside these source files.

Run the NOW workflow once. Verify its generated-file commit, automatic Pages completion, served bytes, and actual NOW FY / quarter button destinations, including 2020 and 2026 Q1-Q3. Preserve ISRG and another company's controls. Do not describe the local result alone as a completed app connection.

## Schema

The generated app file has exactly `schema_version`, `symbol`, `cik`, `source_status`, `live_connected`, `as_of`, `reports`, `ledger_summary`. Symbol is NOW, CIK is `0001373715`, and all report URLs are issuer-bound official EDGAR URLs. Each ledger item binds a `slot`, `url` and raw `body_sha256`. The consumer rejects invalid, empty, wrong-issuer, duplicate, unended or ledger-mismatched entries without replacing existing links.

Detailed result files and raw evidence belong outside the repository. They are not application assets.
