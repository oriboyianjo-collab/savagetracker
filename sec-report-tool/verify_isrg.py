#!/usr/bin/env python3
"""Verify each published ISRG button URL on official SEC hosts, fairly and politely."""
import json, os, re, sys
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
    try:
        todo = _check_payload(app)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    log_path = here / 'logs' / 'isrg-verification.jsonl'
    logger = RunLog(log_path)
    cache = Path('/tmp/isrg-edgar-cache')
    transport = SecTransport(cache, identity=os.environ.get("SEC_UA") or SEC_USER_AGENT, network=True, logger=logger)
    rows = []
    errors = 0
    try:
        for year, period, url in todo:
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

def _check_payload(app):
    """Shape and identity validation of the published index itself. Rejects truthy-empty
    years, malformed keys/periods/URLs, and any URL outside the ISRG EDGAR issuer route."""
    reports = app.get('reports')
    if not isinstance(reports, dict) or not reports:
        raise ValueError('published index has no reports; refusing to accept an empty payload')
    rows = []
    for year, periods in reports.items():
        if not re.fullmatch(r'20\d{2}', str(year)):
            raise ValueError('invalid year key in published index: %r' % (year,))
        if not isinstance(periods, dict) or not periods:
            raise ValueError('empty year entry in published index: %r' % (year,))
        for period, url in periods.items():
            if period not in {'FY', 'Q1', 'Q2', 'Q3', 'Q4'}:
                raise ValueError('invalid period in published index: %r' % (period,))
            if not isinstance(url, str):
                raise ValueError('invalid URL entry in published index for %s %s' % (year, period))
            sec_url(url)
            if not url.startswith('https://www.sec.gov/Archives/edgar/data/1035267/'):
                raise ValueError('published URL outside the ISRG EDGAR issuer route: %s' % url)
            rows.append((str(year), period, url))
    return sorted(rows)

def _matches(body, year, period):
    try:
        text = body.decode('utf-8')
    except UnicodeError:
        return False, 'body is not utf-8'
    if period == 'Q4':
        plain = ' '.join(' '.join(Facts(text).parts).split())
        if 'Intuitive Surgical' not in plain and not re.search(r'Nasdaq:\s*ISRG', plain):
            return False, 'Q4 exhibit issuer not established'
        if re.search(r'\bpreliminary\b', plain[:2000], re.I):
            return False, 'Q4 exhibit is a preliminary release'
        years = {m.group(1) for m in re.finditer(r'quarter\s+ended\s+December\s+31,?\s+(20\d{2})', plain, re.I)}
        if years != {str(year)}:
            return False, 'Q4 exhibit period-end years %s do not bind %s' % (sorted(years), year)
        return True, 'q4_exhibit_text'
    facts = Facts(text)
    try:
        cik = str(int(facts.one('EntityCentralIndexKey'))).zfill(10)
        focus_year = facts.one('DocumentFiscalYearFocus')
        focus_period = facts.one('DocumentFiscalPeriodFocus')
        end = facts.one_date('DocumentPeriodEndDate')
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
