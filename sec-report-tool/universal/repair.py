"""Reopen unresolved issuers for one more pass of the universal connector.

No network. The live runner, its User-Agent, its 1 request/second pacer and its
403/429 stop are unchanged. This only selects who is pending again:

- partial_validated rows that still have unresolved slots
- NO_VALIDATED_REPORTS rows whose profile is domestic (they have SEC 10-K/10-Q
  filings). Foreign annual holds are left alone.

Connected rows, identity holds and security-class holds are not reopened.
Already-qualified URLs are not deleted here; publication keeps last-good links
while a reopened issuer is still pending.
"""
import argparse
import json
from pathlib import Path

try:
    from .resume_shards import dehydrate, hydrate
    from .publication import atomic
except ImportError:
    from resume_shards import dehydrate, hydrate
    from publication import atomic


def is_affected(row):
    if not isinstance(row, dict):
        return False
    if row.get('status') == 'partial_validated' and row.get('unresolved_slots'):
        return True
    return row.get('reason_code') == 'NO_VALIDATED_REPORTS' and row.get('profile') == 'domestic'


def reopen_rows(rows):
    """Return (rows, reopened_symbols). Final rows that are not affected pass through."""
    out = []
    opened = []
    for row in rows:
        if not is_affected(row):
            out.append(row)
            continue
        opened.append(row.get('symbol'))
        nxt = dict(row)
        nxt['status'] = 'pending'
        nxt['reason_code'] = 'PENDING_NOT_ATTEMPTED'
        nxt['reports'] = {}
        nxt['ledger'] = []
        nxt['unresolved_slots'] = []
        nxt['linked_slots'] = 0
        nxt.pop('reason', None)
        out.append(nxt)
    return out, opened


def apply(resume_path, directory, control_path):
    resume_path = Path(resume_path)
    directory = Path(directory)
    control_path = Path(control_path)
    result = hydrate(json.loads(resume_path.read_text()), directory)
    result['rows'], opened = reopen_rows(result['rows'])
    for sym in opened:
        result.get('checkpoints', {}).pop(sym, None)
    manifest = dehydrate(result, directory)
    atomic(resume_path, manifest)
    control = json.loads(control_path.read_text())
    processed = sum(r.get('status') != 'pending' for r in result['rows'])
    control['complete'] = False
    control['stopped'] = False
    control['stop_code'] = None
    control['processed'] = processed
    control['logical_progress'] = processed * 100000
    atomic(control_path, control)
    return {'reopened': len(opened), 'processed': processed, 'pending': len(opened)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--resume', required=True)
    p.add_argument('--directory', required=True)
    p.add_argument('--control', required=True)
    a = p.parse_args()
    print(json.dumps(apply(a.resume, a.directory, a.control), sort_keys=True))
