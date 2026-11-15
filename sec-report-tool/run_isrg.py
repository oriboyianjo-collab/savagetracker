#!/usr/bin/env python3
"""Authorized ISRG live runner. Import pipeline as a module; do not execute it as __main__."""
import argparse, json, sys
from datetime import date
from pathlib import Path

from common import SYMBOL, AccessHeld
from pipeline import Pipeline, RunLog
from transport_locked import SEC_USER_AGENT, SecTransport

def main():
    here = Path(__file__).resolve().parent
    repo = here.parent
    p = argparse.ArgumentParser()
    p.add_argument('--output', default=str(here / 'state' / 'isrg'))
    p.add_argument('--as-of', default=date.today().isoformat())
    p.add_argument('--log', required=True)
    p.add_argument('--app-output', default=str(repo / 'report-links-pilot.json'))
    p.add_argument('--cache', default=str(Path('/tmp') / 'isrg-edgar-cache'))
    p.add_argument('--clear-stale-hold', action='store_true')
    a = p.parse_args()
    logger = RunLog(a.log)
    transport = SecTransport(a.cache, identity=SEC_USER_AGENT, network=True, logger=logger)
    logger.event(event='live_transport_ready', user_agent=SEC_USER_AGENT, cache=a.cache)
    pipe = Pipeline(a.output, a.as_of, transport, logger=logger, live=True)
    try:
        result = pipe.run(clear_stale_hold=a.clear_stale_hold)
    except AccessHeld as e:
        result = {'status': 'held', 'reason': str(e), 'live_connected': False, 'last_good_unchanged': True}
        logger.event(event='run_held', reason=str(e))
    if result.get('status') == 'live' and result.get('result'):
        pipe.publish_app(a.app_output, result['result'])
        mapping = here / 'logs' / 'isrg-mapping.md'
        _write_mapping(mapping, result['result'])
        logger.event(event='mapping_written', path=str(mapping))
    buttons = ((result.get('result') or {}).get('buttons') or {}).get(SYMBOL, {})
    summary = {k: v for k, v in result.items() if k != 'result'}
    summary['links'] = sum(len(x) for x in buttons.values())
    print(json.dumps(summary, indent=2, default=str))
    logger.close()
    sys.exit(0 if result.get('status') == 'live' else 2)

def _write_mapping(path, result):
    lines = [
        '# ISRG EDGAR button mapping',
        '',
        f"as_of: {result.get('as_of')}",
        f"source: {result.get('provenance_kind')}",
        '',
        '| Year | Period | Status | URL |',
        '| --- | --- | --- | --- |',
    ]
    buttons = (result.get('buttons') or {}).get(SYMBOL, {})
    for row in result.get('ledger') or []:
        url = (buttons.get(str(row['year'])) or {}).get(row['period'], '')
        lines.append(f"| {row['year']} | {row['period']} | {row['status']} | {url} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n')

if __name__ == '__main__':
    main()
