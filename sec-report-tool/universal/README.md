# universal - reusable SEC issuer discovery/validation core

Isolated, issuer-agnostic core that discovers an issuer's SEC filings, validates
each report document offline-parseable evidence, and links fiscal slots
(FY/Q1-Q4) to validated EDGAR document URLs. Built for the approved all-6315
autonomous report connector pass. No issuer-specific code paths.

## Scope and guarantees

- Official SEC hosts/paths only (www.sec.gov Archives + JSON APIs,
  www.sec.gov/files/company_tickers.json). Identifying User-Agent required.
- Global pacing: at most 1 request/second across the whole runner process via
  an flock-based shared pacer on the local filesystem. This is a
  within-runner, same-filesystem guarantee ONLY. Cross-runner/cross-machine
  mutual exclusion is an external workflow contract owned by the integrator.
- Transport hard-stop on 403/429/redirect/block-page: the stop is persistent
  (survives process restarts via the state file) and can only be cleared by
  `GlobalSecTransport.reset_after_review(review_reference)` after human review.
  5xx responses get bounded exponential backoff; they do not trip the stop.
  An official HTTP 200 whose body exceeds MAX_BODY (50 MiB) is a per-document
  size failure (`document_exceeds_size_budget`), not a persistent access stop.
- Raw HTML/JSON is cached hash-addressed in a runner-temporary cache dir. The
  cache is NOT a resume mechanism: resume is driven by slot-level checkpoints
  in the result document (see CHECKPOINT.md).
- Fail-closed document budget: max_documents_per_issuer (default 90) bounds
  document fetches per issuer per batch and resets on each continuation. If it
  is exhausted mid-scan the row stays pending (reason
  "document_budget_exhausted"), validated slots are withheld from publication
  until the version scan completes, and the checkpoint resumes where it
  stopped. Done-lists prevent any refetch, so the budget never multiplies
  total requests across continuations.
- Amendments: only an explicit Inline-XBRL-tagging-only 8-K/A is accepted as
  non-superseding (decision `non_superseding_tagging_only`); every other
  amendment form (10-K/A, 10-Q/A, other 8-K/A) holds the issuer. An original
  validated URL is never auto-replaced.
- Q4 binding: Item 2.02 8-K -> single ex-99.1 exhibit (link label '99.1' or
  ex-991 filename, same accession directory) -> not preliminary -> own-period
  "quarter ended <date>" sentence -> dated three-month income table whose
  period end matches the issuer's own validated FY end (exact or expected-next
  +/-10d). 10-K never substitutes for Q4. Pre-fetch candidate window: filed
  within 75 days after a known/expected FY end (Q4_PREWINDOW_DAYS).
- Q4 coverage is explicit, never silent. For every validated annual year with
  no linked Q4, unresolved_slots carries exactly one honest indicator when a
  candidate exists: "only preliminary Q4 release found", "q4 candidate found
  but not validated" (fetched, examined, rejected), or "q4 release candidate
  outside 75-day examination window" (an Item 2.02 8-K filed 75-150 days after
  the FY end, never fetched). An issuer with no Item 2.02 8-K in the whole
  150-day band simply has no Q4 release to miss and stays unmarked; a late
  filer beyond 150 days is out of v1 scope by design.
- Slot year = DEI DocumentFiscalYearFocus, never calendar year.
- DEI dates/booleans accepted only via declared ixt transforms
  (date-monthname-day-year-en, datemonthdayyearen, date-month-day-year;
  false via '', ixt:booleanfalse, ixt:fixed-false). Anything else holds.
- `connected` status = every in-scope discovered filing validated this pass.
  It is NOT a claim of complete historical coverage.

## API

    run_batch(inventory, prior, transport, *, as_of, pass_id, generation,
              deadline_seconds=None, max_issuers=None) -> result dict

- inventory: parsed manifest dict {'schema_version':1, 'as_of':..., 'rows':[...]}.
- prior: previous result dict for a sanitized continuation, or None.
- transport: GlobalSecTransport (live) or ReplayTransport (offline evidence).
- Gates checked BEFORE any SEC request: inventory schema, pass_id match,
  generation == prior.generation + 1, inventory_sha256 match, as_of match.
- inventory_sha256 = SHA-256 of canonical(inventory) where canonical() is
  UTF-8 sorted-compact JSON + trailing newline (exported as
  universal.core.canonical). Verified to equal the exact manifest file bytes
  when the file is written in that canonical form.

Result: schema_version, as_of, inventory_sha256, pass_id, batch_id,
generated_at, generation, cursor, processed, transport_attempts,
complete_pass, access_held/access_hold_reason, status_semantics,
continuation_note, summary, rows, checkpoints.

Row: symbol, rank, cik, profile, status, reason, reason_code, reports
{fyYear: {FY|Qn: url}}, ledger [{slot,url,body_sha256,period_end,filing_date,
form,decision}], unresolved_slots, linked_slots.
Statuses: existing_preserved | connected | partial_validated | held |
unsupported | pending. Reason codes: REASON_CODES enum in core.py.

## CLI

    python -m universal.cli --inventory M.json --state state.json \
        --result out.json --as-of YYYY-MM-DD --pass-id P --generation N \
        [--deadline-seconds S] [--max-issuers N] \
        (--live --cache DIR | --replay-cache DIR) [--prior prev.json] \
        [--log LOG] [--reviewed-reset --review-reference REF]

Exit codes: 0 pass complete, 1 incomplete (resume with --prior), 2 fatal or
transport access held (requires reviewed reset before further SEC requests).

## Tests

    python3 -m unittest discover -s universal/tests        # synthetic suite
    UNIVERSAL_REPLAY_ISRG=<dir> UNIVERSAL_REPLAY_NOW=<dir> \
        python3 -m unittest discover -s universal/tests    # + real-corpus replay

46 tests: synthetic issuers (synth.py FakeSEC), transport pacing/hold/cache,
and real retained-corpus replays re-deriving the accepted ISRG (33 slots:
FY2020-FY2025 + all quarters + 2026 Q1-Q3) and NOW (33 slots + one
non_superseding_tagging_only amendment) connections with zero network access.

## Hard boundaries

- No repo/app/workflow/consumer writes. No live SEC requests during build.
- No raw HTML in committed/public artifacts; ledger carries hashes + metadata
  only. Reason text stays runner-local; only REASON_CODES and the ledger
  decision vocabulary may appear in sanitized artifacts.
