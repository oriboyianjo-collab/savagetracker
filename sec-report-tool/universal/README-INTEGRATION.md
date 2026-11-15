# Finite automatic EDGAR report pass

Candidate integration. Do not deploy or dispatch until combined core qualification and independent review pass.

## Scope

Frozen inventory: 6,315 exact app symbols, hash `4c9fdc1ad463bddf2fdfabcfa78bd5d35ef3dee05cfea3c89c0441c5bb7a46a6`. Cutoff: 2026-11-15. Existing company connections are in scope for verified per-slot EDGAR replacement. If no report qualifies, the original link remains. No financial values, unrelated data, or UI layout changes.

39 inventory holds remain: two explicit exclusions, 15 reserved pending scope clarification, and 22 other pre-existing holds. The core additionally holds 461 name-classified securities (143 warrants, 132 debt notes, 77 rights, 62 preferred securities, 47 units). These conservative name rules can hold legitimate partnership units. The 500 held rows are accounted for, not certified source failures. At most 5,815 symbols proceed to issuer discovery; this is not a promise of 5,815 connections.

The existing ISRG workflow stays disabled. Universal, NOW, and fundamentals share `sec-edgar-shared` with `cancel-in-progress: false` and `queue: max`. Existing NOW/fundamentals scripts and clock triggers remain unchanged. This serializes these repository workflows, not SEC traffic from other clients.

## Files

- `report-links-all.json`: small current symbol-to-digest manifest.
- `report-links-all/SYMBOL.SHA256.json`: validated current company report slots and evidence hashes. Browser loads only a selected/visible symbol, verifies its hash and scope, and merges slots over the old map.
- `report-status-all.json`: full inventory accounting, fixed public reason codes, and summary.
- `report-pass-control.json`: fixed pass identity, expected next generation, stop/completion flags.
- `report-pass-resume.json` and `report-pass-state/`: hash-bound sanitized resume data. Not loaded by the app.

Raw filing bodies, free-form parser diagnostics, and raw execution logs are not committed or uploaded. Local temporary core results are projected into the public whitelist before commit.

## Pre-install review

1. Back up the current app and its existing report assets at a known committed revision. Keep a working rollback route.
2. Review exact consumer insertion plus five data-only lookups. Confirm the existing static report map is byte-identical.
3. Run core and integration offline tests, two-generation CLI rehearsal, interruption/version-scan replay, persistent access-stop replay, and sanitized cross-runner resume round-trip.
4. Review the exact workflow diff and generated-file allowlist. Confirm self-dispatch permission and the new workflow's inclusion in the existing Pages completion allowlist.
5. Inspect the actual report controls at mobile and desktop sizes, selected-year retention, no-report fallback, wrong-hash rejection, and both ISRG/NOW loader arrival orders.
6. Check no legacy source-using workflow is already running outside the shared concurrency group.

## Launch and completion

Initial dispatch uses fixed pass ID `universe-20261115-6315-replace-v1`, generation `0`. Preflight rejects a stale, duplicate, stopped, or complete pass before any SEC requests. Every successful generated-output commit advances one generation. Continuation is dispatched only after that commit reaches main. A crash before the commit restarts from the last committed generation and resume shards.

No automatic access reset is permitted. SEC denial, challenge, or rate-limit state stops continuation and remains stopped. Unexpected failure and no logical progress do not produce an unbounded retry loop. The pass has a finite batch cap. Explicit unsupported/held rows remain accounted for rather than becoming guessed connections.

A button link is not a completion claim by itself. Record the actual first source-run start, generated-output commit, successful Pages deployment, and live report-button evidence. Inspect the actual run about five minutes after it starts. Report discovered coverage and held/unsupported outcomes separately from full 6,315-symbol inventory accounting.

## Scale evidence

Synthetic only: 6,315 symbols x 33 slots yielded a 655,387-byte app manifest, approximately 75.3 MB total report shards, and a largest selected-company shard of 11,939 bytes. Estimated sanitized row state before checkpoints was 74.7 MB; resume state therefore uses small per-symbol files, not a single large Git blob. These figures are not actual SEC coverage or live throughput.

## Coverage limits

Status reports explicitly say `historical_coverage_verified: false`. A `connected` row certifies only the filings the connector discovered and validated. The 75-day Q4 prefetch window omits later releases; rejected non-preliminary candidates may not appear in unresolved counts. Status rows list available slots, Q4 missing alongside validated domestic annuals, unresolved counts, and unsupported foreign quarters. No missing slot is filled with an inferred URL.
