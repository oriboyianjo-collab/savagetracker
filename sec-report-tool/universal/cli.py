"""CLI wrapper for the universal connector core. Owns all atomic persistence.

No network without --live. Offline runs use --replay-cache of retained captures.

  python3 -m universal.cli --inventory inventory.json --state DIR --result out.json \
      --as-of 2026-11-15 --pass-id universe-20261115-6315-v1 --generation 1 \
      [--deadline-seconds 540] [--max-issuers 40] [--live --cache DIR | --replay-cache DIR ...] \
      [--log run.jsonl] [--prior PATH]

Resume: the CLI reads <state>/last-result.json as prior unless --prior is given.
Continuation gates (inventory hash, as_of, pass_id, generation) fail BEFORE any SEC
request. Exit codes: 0 complete_pass true; 1 incomplete/pending (normal batch end);
2 fatal or persistent access hold.
"""
import argparse
import copy
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from .core import run_batch, AccessHeld
from .replay import ReplayTransport


def _atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    os.replace(tmp, path)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory', required=True)
    p.add_argument('--state', required=True, help='CLI-owned state directory')
    p.add_argument('--result', required=True)
    p.add_argument('--as-of', required=True, help='fixed pass cutoff; identical across continuations')
    p.add_argument('--pass-id', help='stable pass id; must match prior on continuations')
    p.add_argument('--generation', type=int, help='controller generation; must match prior when both set')
    p.add_argument('--deadline-seconds', type=float, default=None)
    p.add_argument('--max-issuers', type=int, default=None)
    p.add_argument('--max-pages', type=int, default=8)
    p.add_argument('--max-documents-per-issuer', type=int, default=90)
    p.add_argument('--live', action='store_true', help='opt-in real SEC requests via GlobalSecTransport')
    p.add_argument('--cache', help='raw response cache dir for --live')
    p.add_argument('--replay-cache', action='append', help='retained capture dir (repeatable); offline')
    p.add_argument('--prior', help='explicit prior result path; default <state>/last-result.json')
    p.add_argument('--log', help='JSONL event log path')
    p.add_argument('--reviewed-reset', action='store_true',
                   help='clear a persistent transport stop; requires --review-reference')
    p.add_argument('--review-reference', help='owner/source review id recorded with a stop reset')
    a = p.parse_args(argv)
    if not a.live and not a.replay_cache:
        p.error('no network without --live; supply --replay-cache for an offline run')
    date.fromisoformat(a.as_of)  # validation

    state = Path(a.state)
    state.mkdir(parents=True, exist_ok=True)
    log_fh = None
    if a.log:
        Path(a.log).parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(a.log, 'a', encoding='utf-8')

    def logger(**kw):
        rec = {'ts': datetime.now(timezone.utc).isoformat(), **kw}
        line = json.dumps(rec, ensure_ascii=False, default=str)
        if log_fh:
            log_fh.write(line + '\n')
            log_fh.flush()

    if a.live:
        from .transport import GlobalSecTransport
        transport = GlobalSecTransport(a.cache or str(state / 'cache'), str(state), network=True, logger=logger)
    else:
        transport = ReplayTransport(a.replay_cache)

    if a.reviewed_reset:
        if not a.live:
            p.error('--reviewed-reset applies to a live transport state only')
        transport.reset_after_review(a.review_reference)
        logger(event='reviewed_reset', reference=a.review_reference)
        print(json.dumps({'stop_cleared': True, 'review_reference': a.review_reference}))
        if log_fh:
            log_fh.close()
        return 0

    inventory = json.loads(Path(a.inventory).read_text())
    prior_path = Path(a.prior) if a.prior else state / 'last-result.json'
    prior = json.loads(prior_path.read_text()) if prior_path.exists() else None
    pass_id = a.pass_id or (prior or {}).get('pass_id')

    try:
        result = run_batch(inventory, prior, transport, as_of=a.as_of,
                           deadline_seconds=a.deadline_seconds, max_issuers=a.max_issuers,
                           pass_id=pass_id, generation=a.generation,
                           max_pages=a.max_pages,
                           max_documents_per_issuer=a.max_documents_per_issuer,
                           logger=logger)
    except (AccessHeld, ValueError) as e:
        logger(event='run_failed', reason=str(e))
        if log_fh:
            log_fh.close()
        print(str(e), file=sys.stderr)
        return 2

    _atomic(a.result, result)
    _atomic(state / 'last-result.json', result)
    if result.get('pass_id'):
        _atomic(state / 'pass_id', {'pass_id': result['pass_id'], 'as_of': a.as_of})
    logger(event='batch_done', summary=result['summary'], complete=result['complete_pass'],
           access_held=result['access_held'], cursor=result['cursor'])
    if log_fh:
        log_fh.close()
    print(json.dumps({'complete_pass': result['complete_pass'], 'summary': result['summary'],
                      'cursor': result['cursor'], 'access_held': result['access_held'],
                      'pass_id': result['pass_id'], 'batch_id': result['batch_id']}, indent=2))
    return 0 if result['complete_pass'] else (2 if result['access_held'] else 1)


if __name__ == '__main__':
    sys.exit(main())
