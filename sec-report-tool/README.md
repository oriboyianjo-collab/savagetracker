# ISRG report tool source - inactive

Python source for an Intuitive Surgical (ISRG) report-link prototype. These files are provided for code review. They are not connected to the website, an app import, a server job, or a scheduler. Uploading them does not activate report collection.

## Files

- `pipeline.py`: reads prepared SEC captures, checks issuer and reporting-period identity, saves progress, and builds a candidate report-link index.
- `transport_locked.py`: disabled transport implementation. Its public request method always stops without making a request. The internal test path rejects the default real network opener.
- `test_pipeline.py`: standard-library unit tests using synthetic fixtures and injected fake responses.
- `demo_synthetic.py`: a local synthetic demonstration. Its generated links and documents are test data, not verified filings.

## Local use

Requires Python 3 and its standard library. From this directory:

```sh
python -m unittest -v
python pipeline.py --output /tmp/isrg-held-demo
python demo_synthetic.py --output /tmp/isrg-synthetic-demo
```

The default pipeline run stops with a held result and sends no network request. The synthetic demo uses local fixtures only. An optional `--captures DIR` argument reads an already-prepared local capture manifest; it does not retrieve URLs. Output directories are created locally and are not website data.

## Limits

This version is ISRG-specific, with a fixed default cutoff of 2026-11-15 and a historical period model beginning in 2021. It is not a general all-company connector. A quarter ending does not establish that a report has been published.

The candidate index is not a live connection or a completeness certificate. Missing captures remain unknown. The tool does not extract financial values, change existing report links, publish app data, or promote a candidate to a live index.

Report and amendment recognition is deliberately narrow. Some genuine reports, partial amendments, PDF-only documents, and other formats require review and are held rather than guessed. A Q4 earnings exhibit is not an annual report or a standalone Q4 cash-flow statement.

Capture hashes check consistency with the supplied manifest, not source authenticity, freshness, or completeness. Synthetic fixtures must never be treated as actual SEC evidence. Live transport, current-source validation, broader company support, and app integration are outside this inactive source upload.

These files contain no configured account credentials or contact identity. Do not add credentials, private captures, generated run state, or access details to this directory.
