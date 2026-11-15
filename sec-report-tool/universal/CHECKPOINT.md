# Checkpoint schema (sanitized continuation state)

`result.checkpoints` is the durable resume mechanism. It lets a later batch of
the SAME pass resume an interrupted issuer without refetching validated slots,
and without relying on the runner-temporary raw cache. Only the vocabulary
below may appear in checkpoints; it is safe to commit/transfer as part of the
sanitized result.

## Shape

    checkpoints: {
      "<symbol>": {
        "cik":       "0001035267",              // zero-padded 10-digit string
        "profile":   "domestic" | "foreign_annual",
        "fy_ends":   [["2020-12-31", 2020], ...],  // validated ANNUAL (FY) period
                                                   // ends only, [iso_date, fy_year]
                                                   // pairs sorted by date
        "ledger":    [ <checkpoint ledger entry>, ... ],  // 8 keys, see below
        "errors":    [ <error object>, ... ],    // objects, NOT strings; see below
        "unresolved":[ {"slot": "2020-Q4"|"2020-?", "reason": "<runner-local text>"} ... ],
        "regular_done": ["0001035267-21-000012", ...],  // accession numbers
        "q4_done":      ["0001035267-22-000021", ...],  // fetched-and-examined only
        "amend_done":   ["0001035267-23-000099", ...],
        "preliminary_q4": [2024, ...],             // fy years whose only Q4
                                                   // candidate was preliminary
        "rejected_q4":   [2023, ...]               // fy years with an examined Q4
                                                   // candidate that did not validate
      }, ...
    }

## Allowed keys (closed set)

cik, profile, fy_ends, ledger, errors, unresolved, regular_done, q4_done,
amend_done, preliminary_q4, rejected_q4. Any other key is a contract violation.

## Checkpoint ledger entry (8 keys)

    {"slot": "2023-Q4" | "2023-FY" | "2023-Q1" | null,
     "url": "https://www.sec.gov/Archives/edgar/data/<cik>/<accession-nodash>/<doc>",
     "body_sha256": "<64 hex>",
     "period_end": "YYYY-MM-DD",
     "filing_date": "YYYY-MM-DD",
     "form": "10-K" | "10-Q" | "20-F" | "40-F" | "8-K" | "8-K/A",
     "decision": "qualified" | "qualified_q4_earnings_exhibit" |
                 "non_superseding_tagging_only",
     "accession": "0001035267-23-000099"}

The public row.ledger projection drops "accession" (7 keys only). The checkpoint
form retains it so resume can dedupe and audit without any refetch.

slot is null exactly for non_superseding_tagging_only amendments. Such entries
are preserved verbatim in checkpoints and re-projected into every later
result's row.ledger, but are excluded from reports and linked_slots; their
accession in amend_done guarantees they are never refetched.

## Error objects (not strings)

    {"accession": "0001035267-21-000012",   // present when tied to one filing
     "form": "10-Q",                        // present on per-document failures
     "reason": "<runner-local free text>"}

"reason" is free text for the runner log. The core NEVER parses error or
unresolved reason strings: resume decisions use only structured fields
(accession dedupe, presence/count). A sanitizer may replace reason text with
codes without affecting resume, provided identity/progress fields (accession,
form, the done-lists, ledger, fy_ends) are preserved.

## Example

    "checkpoints": {
      "NOW": {
        "cik": "0001373715",
        "profile": "domestic",
        "fy_ends": [["2020-12-31", 2020], ["2021-12-31", 2021]],
        "ledger": [
          {"slot": "2021-Q4",
           "url": "https://www.sec.gov/Archives/edgar/data/1373715/000137371522000010/erq4fy21.htm",
           "body_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
           "period_end": "2021-12-31",
           "filing_date": "2022-01-27",
           "form": "8-K",
           "decision": "qualified_q4_earnings_exhibit",
           "accession": "0001373715-22-000010"}
        ],
        "errors": [{"accession": "0001373715-21-000009", "form": "10-Q",
                    "reason": "missing dated numeric balance statement"}],
        "unresolved": [],
        "regular_done": ["0001373715-21-000006"],
        "q4_done": ["0001373715-22-000010"],
        "amend_done": [],
        "preliminary_q4": [],
        "rejected_q4": []
      }
    }

## Resume rules enforced by the core

- Continuation requires the same pass_id and inventory_sha256 and
  generation == prior.generation + 1; all gates are checked before any SEC
  request.
- Final-status rows (including held) carry forward verbatim and are never
  refetched.
- Accessions in regular_done/q4_done/amend_done are never refetched; validated
  slots are rehydrated from checkpoint ledger entries.
- fy_ends is restored from the checkpoint so Q4 binding after resume uses the
  same issuer-validated annual ends.
- progress = newly final rows + checkpoint ledger growth. Refetching URLs is
  not progress; transport_attempts counts requests only.
- Fail-closed on budget: when the per-issuer document budget
  (max_documents_per_issuer, default 90, per issuer PER BATCH) is exhausted
  mid-scan, the row stays pending with reason "document_budget_exhausted", its
  slots do NOT publish (unscanned regulars/amendments could supersede or
  conflict with validated URLs), and the checkpoint resumes the scan in the
  next batch. The budget resets each continuation; done-lists guarantee only
  not-yet-examined documents are fetched, so the cross-batch total is bounded
  by the issuer's actual document count.
