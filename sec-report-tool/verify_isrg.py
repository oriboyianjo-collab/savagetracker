#!/usr/bin/env python3
"""Verify each published ISRG button URL on official SEC hosts, fairly and politely."""
import json, os, sys
from pathlib import Path

from common import AccessHeld, body_excerpt, sec_url
from pipeline import Facts, RunLog
from transport_locked import SEC_USER_AGENT, SecTransport

PERIOD_END = {'FY': '12-31', 'Q1': '03-31', 'Q2': '06-30', 'Q3': '09-30'}

def main():
    here = Path(__file__).resolve().parent
    repo = here.parent
    app = json.loads((repo / 'report-links-pilot.json').read_text())
    if app.get('source_status') != 'edgar_live' or not app.get('live_connected'):
        print('published index is not an EDGAR live index', file=sys.stderr)
        sys.exit(2)
    log_path = here / 'logs' / 'isrg-verification.jsonl'
    logger = RunLog(log_path)
    cache = Path('/tmp/isrg-edgar-cache')
    transport = SecTransport(cache, identity=os.environ.get("SEC_UA") or SEC_USER_AGENT, network=True, logger=logger)
    rows = []
    errors = 0
    try:
        for year, periods in sorted(app.get('reports') or {}).items():
            for period, url in sorted(periods.items()):
                sec_url(url)
                logger.event(event='verify_start', year=year, period=period, url=url)
                body, ev = transport.get(url)
                ok, reason = _matches(body, year, period)
                rows.append({'year': year, 'period': period, 'url': url, 'http_status': ev.get('status'), 'ok': ok, 'reason': reason})
                logger.event(event='verify_result', year=year, period=period, url=url, http_status=ev.get('status'), ok=ok, reason=reason)
                if not ok:
                    errors += 1
    except AccessHeld as e:
        logger.event(event='verify_stopped', reason=str(e))
        logger.close()
        print('verification stopped under fair-access rules:', e, file=sys.stderr)
        sys.exit(2)
    dest = here / 'logs' / 'isrg-verification.json'
    dest.write_text(json.dumps({'ok': errors == 0, 'checked': len(rows), 'failed': errors, 'rows': rows}, indent=2) + '\n')
    logger.event(event='verify_done', checked=len(rows), failed=errors)
    logger.close()
    print(json.dumps({'ok': errors == 0, 'checked': len(rows), 'failed': errors}, indent=2))
    sys.exit(0 if errors == 0 else 2)

def _matches(body, year, period):
    try:
        text = body.decode('utf-8')
    except UnicodeError:
        return False, 'body is not utf-8'
    if period == 'Q4':
        if 'Intuitive Surgical' not in text:
            return False, 'Q4 exhibit does not name Intuitive Surgical'
        if f'December 31, {year}' not in text and f'December 31 {year}' not in text:
            return False, 'Q4 exhibit period end not found'
        return True, 'q4_exhibit_text'
    facts = Facts(text)
    try:
        cik = str(int(facts.one('EntityCentralIndexKey'))).zfill(10)
        focus_year = facts.one('DocumentFiscalYearFocus')
        focus_period = facts.one('DocumentFiscalPeriodFocus')
        end = facts.one('DocumentPeriodEndDate')
    except ValueError as e:
        return False, 'DEI facts missing: ' + str(e)
    if cik != '0001035267':
        return False, 'CIK mismatch'
    if focus_year != str(year) or focus_period != period:
        return False, f'DEI period mismatch {focus_year} {focus_period}'
    if end != f'{year}-{PERIOD_END[period]}':
        return False, f'period end mismatch {end}'
    return True, 'dei_period_identity'

if __name__ == '__main__':
    main()
